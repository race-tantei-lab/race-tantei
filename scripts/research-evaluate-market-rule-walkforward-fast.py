#!/usr/bin/env python3
import argparse, collections, importlib.util, json, math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COURSES={'ライト':2000,'スタンダード':5000,'プレミアム':10000}
CAPS=(2000,5000)
MIN_NS=(100,300)
ZS=(0.0,0.75,1.5)
AGGS=('top1','top3')
PRIOR_N=500.0
PRIOR_ROI=0.80
TOP_RULES=3


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

cmod=load(ROOT/'scripts/research-continuous-walkforward-demand.py','fast_rulewf_continuous')
dist=load(ROOT/'scripts/research-evaluate-market-distortion-roi.py','fast_rulewf_distortion')
gen=dist.gen;smod=dist.smod;dmod=dist.dmod
VARIANTS=[(cap,n,z,agg) for cap in CAPS for n in MIN_NS for z in ZS for agg in AGGS]


def period(date):
    y=int(date[:4])
    if date<='2018-12-31':return '2016-08-10..2018'
    if y<=2021:return '2019..2021'
    if y<=2024:return '2022..2024'
    return '2025..2026-08-09'


def init_stat():return {'races':0,'tickets':0,'hitRaces':0,'stakeYen':0,'returnYen':0}
def add(st,stake,ret,n,hit):
    st['races']+=1;st['tickets']+=n;st['hitRaces']+=int(hit);st['stakeYen']+=stake;st['returnYen']+=ret

def fin(st):
    x=dict(st);x['profitYen']=st['returnYen']-st['stakeYen'];x['roiPct']=round(100*st['returnYen']/st['stakeYen'],4) if st['stakeYen'] else None;x['hitRacePct']=round(100*st['hitRaces']/st['races'],4) if st['races'] else None;return x


def load_odds(path):
    out={}
    for p in sorted(Path(path).glob('research-continuous-market-odds-20*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if not line.strip():continue
            r=json.loads(line);rid=str(r['raceId'])
            if rid in out:raise RuntimeError(f'DUPLICATE_ODDS:{rid}')
            out[rid]=r
    return out

# One shared record per rule: [n, sum_cap2000, sq_cap2000, sum_cap5000, sq_cap5000].
def stat_record():return [0.0,0.0,0.0,0.0,0.0]
def update_record(s,x2,x5):
    s[0]+=1.0;s[1]+=x2;s[2]+=x2*x2;s[3]+=x5;s[4]+=x5*x5

def baseline_key(t):return (t['bt'],t['vals']['odds'])

def cap_stats(record,cap):
    if cap==2000:return record[0],record[1],record[2]
    return record[0],record[3],record[4]

def base_mean(record,cap):
    if not record or record[0]<=0:return PRIOR_ROI
    n,s,_=cap_stats(record,cap)
    return (s+PRIOR_N*PRIOR_ROI)/(n+PRIOR_N)

def insert_top3(arr,value):
    if len(arr)<3:
        arr.append(value);arr.sort(reverse=True);return
    if value>arr[-1]:
        arr[-1]=value;arr.sort(reverse=True)


def ticket_scores(t,rule_stats,base_stats):
    keys=list(dist.extended_keys(t))
    bases={cap:base_mean(base_stats.get(baseline_key(t)),cap) for cap in CAPS}
    top={(cap,n,z):[] for cap in CAPS for n in MIN_NS for z in ZS}
    for key in keys:
        rec=rule_stats.get(key)
        if not rec or rec[0]<MIN_NS[0]:continue
        n=rec[0]
        for cap in CAPS:
            _,s,ss=cap_stats(rec,cap)
            bm=bases[cap]
            mean=(s+PRIOR_N*bm)/(n+PRIOR_N)
            raw=s/n if n else bm
            var=max(0.0,ss/n-raw*raw) if n>1 else 0.0
            se=math.sqrt(var/max(1.0,n+PRIOR_N))
            for min_n in MIN_NS:
                if n<min_n:continue
                for z in ZS:insert_top3(top[(cap,min_n,z)],mean-z*se)
    scores={}
    for cap in CAPS:
        for min_n in MIN_NS:
            for z in ZS:
                vals=top[(cap,min_n,z)]
                top1=vals[0] if vals else bases[cap]
                top3=sum(vals[:TOP_RULES])/len(vals[:TOP_RULES]) if vals else bases[cap]
                scores[(cap,min_n,z,'top1')]=top1
                scores[(cap,min_n,z,'top3')]=top3
    return scores,keys


def select(rows,scores):
    ranked=[{**t,'ruleScore':s} for t,s in zip(rows,scores)]
    ranked.sort(key=lambda x:(-x['ruleScore'],x['odds'],x['bt'],x['combo']))
    if len(ranked)<3:raise RuntimeError(f'TOO_FEW_CANDIDATES:{len(ranked)}')
    mx=ranked[0]['ruleScore'];chosen=[t for t in ranked if t['ruleScore']>=mx*0.92-1e-12][:10]
    if len(chosen)<3:chosen=list(ranked[:3])
    types={t['bt'] for t in chosen};keys={(t['bt'],t['combo']) for t in chosen}
    if len(types)<2:
        alt=next((t for t in ranked if t['bt'] not in types and (t['bt'],t['combo']) not in keys),None)
        if alt is None:raise RuntimeError('NO_SECOND_BET_TYPE')
        if len(chosen)<10:chosen.append(alt)
        else:chosen[-1]=alt
    chosen.sort(key=lambda x:(-x['ruleScore'],x['odds'],x['bt'],x['combo']))
    if not(3<=len(chosen)<=10) or len({t['bt'] for t in chosen})<2:raise RuntimeError('FINAL_TICKET_GATE_FAILED')
    return chosen


def settle(chosen,budget,pays):
    units=gen.allocate([t['oddsBin'] for t in chosen],budget//100)
    if sum(units)*100!=budget:raise RuntimeError('BUDGET_INVALID')
    return sum(u*int(pays.get((t['betType'],t['combo']),0) or 0) for t,u in zip(chosen,units))


def concentration(rows,total):
    r=sorted(rows,key=lambda x:x['returnYen'],reverse=True)
    def pct(n):return round(100*sum(x['returnYen'] for x in r[:n])/total,4) if total else 0.0
    return {'largestRaceReturnYen':r[0]['returnYen'] if r else 0,'largestRaceId':r[0]['raceId'] if r else None,'top1ReturnSharePct':pct(1),'top5ReturnSharePct':pct(5),'top10ReturnSharePct':pct(10),'top25ReturnSharePct':pct(25)}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--corpus',required=True);ap.add_argument('--demand',required=True);ap.add_argument('--odds-dir',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    demand={}
    for line in (ROOT/a.demand).read_text(encoding='utf-8').splitlines():
        if line.strip():
            r=json.loads(line);demand[str(r['raceId'])]=r
    if len(demand)!=14410:raise RuntimeError(f'DEMAND_COUNT_INVALID:{len(demand)}')
    odds=load_odds(ROOT/a.odds_dir);missing=sorted(set(demand)-set(odds));seen=set()
    overall={(v,c):init_stat() for v in VARIANTS for c in COURSES};yearly={(v,c):collections.defaultdict(init_stat) for v in VARIANTS for c in COURSES};periods={(v,c):collections.defaultdict(init_stat) for v in VARIANTS for c in COURSES};returns={(v,c):[] for v in VARIANTS for c in COURSES};errors={v:[] for v in VARIANTS}
    rule_stats=collections.defaultdict(stat_record);base_stats=collections.defaultdict(stat_record)
    state={'horse_hist':collections.defaultdict(lambda:collections.deque(maxlen=3)),'horse_starts':collections.Counter(),'jstats':collections.defaultdict(lambda:[0,0]),'tstats':collections.defaultdict(lambda:[0,0])}
    cur=None;day=[]

    def process(date,bundles):
        prepared=[]
        for b in bundles:
            rid=str(b['race']['raceId'])
            if rid not in demand:continue
            seen.add(rid)
            if rid not in odds:continue
            active={int(x) for x in (odds[rid].get('horses') or [])}
            source=dict(b);source['runners']=[r for r in b.get('runners',[]) if int(r['horseNo']) in active]
            raw=cmod.candidate_rows(state,source)
            raw=[t for t in raw if all(int(h) in active for h in t['horses'])]
            try:enriched=dist.enrich_candidates(raw,odds[rid])
            except Exception as e:
                err={'raceId':rid,'raceDate':date,'error':f'{type(e).__name__}:{e}'}
                for v in VARIANTS:errors[v].append(err)
                continue
            pays=smod.payout_index(b)
            score_rows={v:[] for v in VARIANTS};learning=[]
            for t in enriched:
                scores,keys=ticket_scores(t,rule_stats,base_stats)
                learning.append((t,keys))
                for v in VARIANTS:score_rows[v].append(scores[v])
            prepared.append((rid,learning,pays))
            for v in VARIANTS:
                try:
                    chosen=select(enriched,score_rows[v])
                    for c,budget in COURSES.items():
                        ret=settle(chosen,budget,pays);add(overall[(v,c)],budget,ret,len(chosen),ret>0);add(yearly[(v,c)][date[:4]],budget,ret,len(chosen),ret>0);add(periods[(v,c)][period(date)],budget,ret,len(chosen),ret>0);returns[(v,c)].append({'raceId':rid,'returnYen':ret})
                except Exception as e:errors[v].append({'raceId':rid,'raceDate':date,'error':f'{type(e).__name__}:{e}'})
        # Update rule statistics only after the whole date has been scored.
        for rid,learning,pays in prepared:
            for t,keys in learning:
                pay=int(pays.get((t['betType'],t['combo']),0) or 0)
                x2=min(pay,2000)/100.0;x5=min(pay,5000)/100.0
                update_record(base_stats[baseline_key(t)],x2,x5)
                for key in keys:update_record(rule_stats[key],x2,x5)
        dmod.update_state_for_date(state,bundles)

    with (ROOT/a.corpus).open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():continue
            b=json.loads(line);date=str(b['race'].get('raceDate') or '')
            if cur is None:cur=date
            if date!=cur:process(cur,day);day=[];cur=date
            day.append(b)
    if cur:process(cur,day)
    unseen=sorted(set(demand)-seen);rv={}
    for v in VARIANTS:
        cap,min_n,z,agg=v;name=f'cap{cap}-n{min_n}-z{z:.2f}-{agg}';err_ids={e['raceId'] for e in errors[v]};courses={}
        for c in COURSES:
            x=fin(overall[(v,c)]);x['byYear']={y:fin(s) for y,s in sorted(yearly[(v,c)].items())};x['byPeriod']={p:fin(s) for p,s in periods[(v,c)].items()};x['returnConcentration']=concentration(returns[(v,c)],overall[(v,c)]['returnYen']);courses[c]=x
        complete=not missing and not unseen and not err_ids
        rv[name]={'trainingCap':cap,'minRuleN':min_n,'lcbZ':z,'aggregation':agg,'evaluatedRaces':courses['ライト']['races'],'evaluationErrorCount':len(errors[v]),'evaluationErrors':errors[v][:100],'courses':courses,'completeOddsAndEvaluation':complete,'allThreeAtLeast200Pct':complete and all((courses[c]['roiPct'] or 0)>=200 for c in COURSES)}
    ranking=sorted(rv,key=lambda k:(rv[k]['completeOddsAndEvaluation'],min(rv[k]['courses'][c]['roiPct'] or 0 for c in COURSES),sum(rv[k]['courses'][c]['roiPct'] or 0 for c in COURSES)),reverse=True)
    out={'purpose':'research_only_dynamic_market_rule_walk_forward_fast_equivalent','evaluationStart':'2016-08-10','evaluationEnd':'2026-08-09','selectedDemandRaces':len(demand),'oddsRaces':len(odds),'missingOddsRaceCount':len(missing),'missingDemandRacesInCorpus':unseen,'raceSelectionFrozenBeforeOdds':True,'activeRunnersRerankedBeforeTicketGeneration':True,'sameDayResultsUsedForTicketRule':False,'productionRulesReused':False,'trainingReturnCapped':True,'calculationSharedAcrossVariants':True,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False,'variants':rv,'ranking':ranking,'bestVariant':ranking[0] if ranking else None}
    p=ROOT/a.out;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    b=out['bestVariant'];print(json.dumps({'best':b,'roi':{c:rv[b]['courses'][c]['roiPct'] for c in COURSES} if b else None,'errors':rv[b]['evaluationErrorCount'] if b else None},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
