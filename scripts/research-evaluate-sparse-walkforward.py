#!/usr/bin/env python3
import argparse,collections,importlib.util,itertools,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
COURSES={'ライト':2000,'スタンダード':5000,'プレミアム':10000}
UNORDERED={'馬連','ワイド','3連複'}

def load(path,name):
    s=importlib.util.spec_from_file_location(name,path)
    if s is None or s.loader is None: raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def midpoint(v):
    if v is None:return None
    if isinstance(v,(list,tuple)):
        xs=[]
        for x in v:
            try:xs.append(float(x))
            except:pass
        return sum(xs)/len(xs) if xs else None
    try:return float(v)
    except:return None

def init_stat():return {'races':0,'tickets':0,'hitRaces':0,'stakeYen':0,'returnYen':0}
def add(st,stake,ret,n,hit):st['races']+=1;st['tickets']+=n;st['hitRaces']+=int(hit);st['stakeYen']+=stake;st['returnYen']+=ret
def fin(st):
    x=dict(st);x['profitYen']=st['returnYen']-st['stakeYen'];x['roiPct']=round(100*st['returnYen']/st['stakeYen'],4) if st['stakeYen'] else None;x['hitRacePct']=round(100*st['hitRaces']/st['races'],4) if st['races'] else None;return x

def period(date):
    y=int(date[:4])
    if date<='2018-12-31':return '2016-08-10..2018'
    if y<=2021:return '2019..2021'
    if y<=2024:return '2022..2024'
    return '2025..2026-08-09'

def load_odds(path):
    out={};files=sorted(Path(path).glob('research-sparse-odds-*.jsonl'))
    for p in files:
        with p.open(encoding='utf-8') as fh:
            for line in fh:
                if not line.strip():continue
                r=json.loads(line);rid=str(r['raceId'])
                if rid in out:raise RuntimeError(f'DUPLICATE_ODDS:{rid}')
                out[rid]=r
    return out,files

def rule_groups(rules):
    d=collections.defaultdict(list)
    for r in rules:d[int(r['conditions'][0][1])].append(r)
    return d

def match(rule,vals):return all(vals.get(a)==v for a,v in rule['conditions'])

def build_tickets(pmod,dmod,smod,gen,state,bundle,odds_row,rules):
    race=bundle['race'];rid=str(race['raceId']);official=odds_row.get('officialOdds') or {};win=official.get('win') or {}
    allowed={int(h) for h,v in win.items() if midpoint(v) is not None and midpoint(v)>1}
    runners=[r for r in bundle.get('runners',[]) if (r.get('runnerStatus') or 'active')=='active' and int(r.get('horseNo') or 0) in allowed]
    runners.sort(key=lambda r:int(r.get('horseNo') or 0))
    if len(runners)<3:raise RuntimeError(f'BETTING_FIELD_TOO_SMALL:{rid}:{len(runners)}')
    feats={int(r['horseNo']):dmod.feature_tuple(pmod,state,rid,r) for r in runners}
    ranked=sorted(feats,key=lambda h:smod.strength(feats[h],h),reverse=True)[:smod.TOP_HORSES]
    base=smod.base_vals(pmod,race,len(runners));rb=rule_groups(rules);tickets=[]
    for bt,(k,market,jp,ordered) in smod.BET_SPECS.items():
        if len(ranked)<k or not rb.get(bt):continue
        market_rows=official.get(market) or {};seq=itertools.permutations(ranked,k) if ordered else itertools.combinations(ranked,k)
        for horses in seq:
            combo='-'.join(str(x) for x in (tuple(sorted(horses)) if not ordered else horses));odd=midpoint(market_rows.get(combo))
            if odd is None or odd<=1:continue
            vals=smod.combo_vals(base,bt,[feats[h] for h in horses]);best=0.0
            for rule in rb[bt]:
                if match(rule,vals):best=max(best,float(rule['newScore']))
            if best>0:tickets.append({'bet':bt,'betType':jp,'horses':list(horses),'combo':combo,'odds':float(odd),'oddsBin':gen.bsearch(gen.ODDS_EDGES,float(odd)),'full':best,'pre':best})
    return gen.select_tickets(tickets)

def settle(gen,chosen,budget,payouts):
    units=gen.allocate([t['oddsBin'] for t in chosen],budget//100);ret=0;rows=[]
    for t,u in zip(chosen,units):
        stake=u*100;pay=payouts.get((t['betType'],t['combo']),0);tr=u*pay;ret+=tr;rows.append({'betType':t['betType'],'combination':t['combo'],'stakeYen':stake,'returnYen':tr,'historicalFinalOdds':t['odds']})
    if sum(x['stakeYen'] for x in rows)!=budget:raise RuntimeError(f'BUDGET_INVALID:{budget}')
    return ret,rows

def concentration(rows,total):
    r=sorted(rows,key=lambda x:x['returnYen'],reverse=True)
    def pct(n):return round(100*sum(x['returnYen'] for x in r[:n])/total,4) if total else 0.0
    return {'largestRaceReturnYen':r[0]['returnYen'] if r else 0,'largestRaceId':r[0]['raceId'] if r else None,'top1ReturnSharePct':pct(1),'top5ReturnSharePct':pct(5),'top10ReturnSharePct':pct(10),'top25ReturnSharePct':pct(25)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--corpus',required=True);ap.add_argument('--demand',required=True);ap.add_argument('--rules',required=True);ap.add_argument('--odds-dir',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    pmod=load(ROOT/'scripts/generate-final-preday-selection.py','swf_bins');dmod=load(ROOT/'scripts/research-ten-year-canonical-demand.py','swf_hist');smod=load(ROOT/'scripts/research-sparse-walkforward-demand.py','swf_sparse');gen=load(ROOT/'scripts/generate-final-live-bets.py','swf_gen')
    demand={}
    with (ROOT/a.demand).open(encoding='utf-8') as fh:
        for line in fh:
            if line.strip():
                r=json.loads(line);demand[str(r['raceId'])]=r
    folds={x['fold']:x['rules'] for x in json.loads((ROOT/a.rules).read_text(encoding='utf-8')) if x['startDate']>='2016-08-10'}
    odds,files=load_odds(ROOT/a.odds_dir);missing=sorted(set(demand)-set(odds));seen=set();errors=[];records=[]
    state={'horse_hist':collections.defaultdict(lambda:collections.deque(maxlen=3)),'horse_starts':collections.Counter(),'jstats':collections.defaultdict(lambda:[0,0]),'tstats':collections.defaultdict(lambda:[0,0])}
    overall={c:init_stat() for c in COURSES};yearly={c:collections.defaultdict(init_stat) for c in COURSES};periods={c:collections.defaultdict(init_stat) for c in COURSES};returns={c:[] for c in COURSES}
    cur=None;day=[]
    def process(date,bundles):
        for b in bundles:
            race=b['race'];rid=str(race['raceId'])
            if rid not in demand:continue
            seen.add(rid)
            if rid not in odds:continue
            dr=demand[rid];rules=folds.get(str(dr.get('fold')))
            if not rules:
                errors.append({'raceId':rid,'raceDate':date,'error':f"FOLD_RULES_MISSING:{dr.get('fold')}"});continue
            try:
                chosen=build_tickets(pmod,dmod,smod,gen,state,b,odds[rid],rules);pays=smod.payout_index(b);rec={'raceId':rid,'raceDate':date,'venue':race.get('venue'),'raceNo':race.get('raceNo'),'fold':dr.get('fold'),'courses':{}}
                for c,budget in COURSES.items():
                    ret,tix=settle(gen,chosen,budget,pays);add(overall[c],budget,ret,len(tix),ret>0);add(yearly[c][date[:4]],budget,ret,len(tix),ret>0);add(periods[c][period(date)],budget,ret,len(tix),ret>0);returns[c].append({'raceId':rid,'returnYen':ret});rec['courses'][c]={'stakeYen':budget,'returnYen':ret,'tickets':tix}
                records.append(rec)
            except Exception as e:errors.append({'raceId':rid,'raceDate':date,'venue':race.get('venue'),'raceNo':race.get('raceNo'),'error':f'{type(e).__name__}:{e}'})
        dmod.update_state_for_date(state,bundles)
    with (ROOT/a.corpus).open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():continue
            b=json.loads(line);date=str(b['race'].get('raceDate') or '')
            if cur is None:cur=date
            if date!=cur:process(cur,day);day=[];cur=date
            day.append(b)
    if cur:process(cur,day)
    courses={}
    for c in COURSES:
        x=fin(overall[c]);x['byYear']={y:fin(s) for y,s in sorted(yearly[c].items())};x['byPeriod']={p:fin(s) for p,s in periods[c].items()};x['returnConcentration']=concentration(returns[c],overall[c]['returnYen']);courses[c]=x
    result={'purpose':'research_only_sparse_walk_forward_exact_final_odds_evaluation','evaluationStart':'2016-08-10','evaluationEnd':'2026-08-09','selectedDemandRaces':len(demand),'oddsRaces':len(odds),'missingOddsRaceCount':len(missing),'missingOddsRaceIds':missing,'missingDemandRacesInCorpus':sorted(set(demand)-seen),'evaluationErrorCount':len(errors),'evaluationErrors':errors,'evaluatedRaces':len(records),'courses':courses,'allThreeObservedAtLeast200Pct':all((courses[c]['roiPct'] or 0)>=200 for c in COURSES),'historicalFinalOddsUsed':True,'prestartTimingValidationPerformed':False,'targetDayResultsUsedForSelection':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    out=ROOT/a.out;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'selected':len(demand),'odds':len(odds),'missing':len(missing),'errors':len(errors),'evaluated':len(records),'roi':{c:courses[c]['roiPct'] for c in COURSES},'all200':result['allThreeObservedAtLeast200Pct']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
