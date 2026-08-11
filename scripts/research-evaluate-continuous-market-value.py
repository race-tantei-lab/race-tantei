#!/usr/bin/env python3
import argparse,collections,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COURSES={'ライト':2000,'スタンダード':5000,'プレミアム':10000}
LOCAL_WEIGHTS=(0.25,0.50,0.75)
RISK_GAMMAS=(0.0,0.25,0.50,0.75)
MIN_N=500
KEY_PRIOR=2000.0
TOP_COMPONENTS=8


def load(path,name):
    s=importlib.util.spec_from_file_location(name,path)
    if s is None or s.loader is None: raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

cmod=load(ROOT/'scripts/research-continuous-walkforward-demand.py','market_continuous')
gen=load(ROOT/'scripts/generate-final-live-bets.py','market_live')
smod=cmod.smod; dmod=cmod.dmod


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
    x=dict(st);x['profitYen']=st['returnYen']-st['stakeYen']
    x['roiPct']=round(100*st['returnYen']/st['stakeYen'],4) if st['stakeYen'] else None
    x['hitRacePct']=round(100*st['hitRaces']/st['races'],4) if st['races'] else None
    return x


def load_odds(path):
    out={};files=sorted(Path(path).glob('research-continuous-market-odds-20*.jsonl'))
    for p in files:
        for line in p.read_text().splitlines():
            if not line.strip():continue
            r=json.loads(line);rid=str(r['raceId'])
            if rid in out:raise RuntimeError(f'DUPLICATE_ODDS:{rid}')
            out[rid]=r
    return out,files


def probability_parts(ticket,key_stats,bet_stats):
    bt=ticket['bt'];bn,bh=bet_stats.get(bt,(0.0,0.0))
    base=(bh+1.0)/(bn+2.0)
    comps=[]
    for key in smod.candidate_keys(bt,ticket['vals']):
        n,h=key_stats.get(key,(0.0,0.0))
        if n<MIN_N:continue
        p=(h+KEY_PRIOR*base)/(n+KEY_PRIOR)
        reliability=n/(n+KEY_PRIOR)
        complexity=1.0 if len(key[1])==1 else 0.92
        comps.append((p,reliability*complexity,n))
    if not comps:return base,base
    comps.sort(key=lambda x:(x[0],x[1],x[2]),reverse=True)
    top=comps[:TOP_COMPONENTS];w=sum(x[1] for x in top)
    local=sum(x[0]*x[1] for x in top)/w if w else base
    return base,local


def prepare_market_candidates(rows,odds_row,key_stats,bet_stats):
    official=odds_row.get('officialOdds') or {};out=[];missing=[]
    for t in rows:
        market_rows=official.get(t['market']) or {}
        odd=midpoint(market_rows.get(t['combo']))
        if odd is None or odd<1.0:
            missing.append(f"{t['market']}:{t['combo']}")
            continue
        base,local=probability_parts(t,key_stats,bet_stats)
        out.append({**t,'odds':odd,'baseProb':base,'localProb':local,'oddsBin':gen.bsearch(gen.ODDS_EDGES,odd)})
    if missing:
        raise RuntimeError(f'CANDIDATE_ODDS_INCOMPLETE:{len(missing)}:{missing[:12]}')
    return out


def score_variant(prepared,local_weight,risk_gamma):
    out=[]
    for t in prepared:
        p=(1.0-local_weight)*t['baseProb']+local_weight*t['localProb']
        ev=p*t['odds']
        score=ev*((10.0/max(1.0,t['odds']))**risk_gamma)
        out.append({**t,'pHat':p,'ev':ev,'marketScore':score})
    out.sort(key=lambda x:(-x['marketScore'],-x['ev'],x['odds'],x['bt'],x['combo']))
    return out


def select_tickets(rows):
    if len(rows)<3:raise RuntimeError(f'TOO_FEW_ODDS_CANDIDATES:{len(rows)}')
    mx=rows[0]['marketScore'];chosen=[t for t in rows if t['marketScore']>=mx*0.85-1e-12][:10]
    if len(chosen)<3:chosen=list(rows[:3])
    keys={(t['bt'],t['combo']) for t in chosen};types={t['bt'] for t in chosen}
    if len(types)<2:
        alt=next((t for t in rows if t['bt'] not in types and (t['bt'],t['combo']) not in keys),None)
        if alt is None:raise RuntimeError('NO_SECOND_BET_TYPE')
        if len(chosen)<10:chosen.append(alt)
        else:chosen[-1]=alt
    chosen.sort(key=lambda x:(-x['marketScore'],-x['ev'],x['odds'],x['bt'],x['combo']))
    if not (3<=len(chosen)<=10) or len({t['bt'] for t in chosen})<2:raise RuntimeError('FINAL_TICKET_GATE_FAILED')
    return chosen


def settle(chosen,budget,payouts):
    units=gen.allocate([t['oddsBin'] for t in chosen],budget//100);ret=0;rows=[]
    for t,u in zip(chosen,units):
        stake=u*100;pay=int(payouts.get((t['betType'],t['combo']),0) or 0);tr=u*pay;ret+=tr
        rows.append({'betType':t['betType'],'combination':t['combo'],'stakeYen':stake,'returnYen':tr,'historicalFinalOdds':t['odds'],'estimatedHitProbability':round(t['pHat'],8),'estimatedValue':round(t['ev'],6),'marketScore':round(t['marketScore'],6)})
    if sum(x['stakeYen'] for x in rows)!=budget:raise RuntimeError(f'BUDGET_INVALID:{budget}')
    return ret,rows


def concentration(rows,total):
    r=sorted(rows,key=lambda x:x['returnYen'],reverse=True)
    def pct(n):return round(100*sum(x['returnYen'] for x in r[:n])/total,4) if total else 0.0
    return {'largestRaceReturnYen':r[0]['returnYen'] if r else 0,'largestRaceId':r[0]['raceId'] if r else None,'top1ReturnSharePct':pct(1),'top5ReturnSharePct':pct(5),'top10ReturnSharePct':pct(10),'top25ReturnSharePct':pct(25)}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--corpus',required=True);ap.add_argument('--demand',required=True);ap.add_argument('--odds-dir',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    demand={}
    for line in (ROOT/a.demand).read_text().splitlines():
        if line.strip():
            r=json.loads(line);demand[str(r['raceId'])]=r
    if len(demand)!=14410:raise RuntimeError(f'DEMAND_COUNT_INVALID:{len(demand)}')
    odds,files=load_odds(ROOT/a.odds_dir);missing=sorted(set(demand)-set(odds));seen=set()
    variants=[(lw,g) for lw in LOCAL_WEIGHTS for g in RISK_GAMMAS]
    overall={(lw,g,c):init_stat() for lw,g in variants for c in COURSES}
    yearly={(lw,g,c):collections.defaultdict(init_stat) for lw,g in variants for c in COURSES}
    periods={(lw,g,c):collections.defaultdict(init_stat) for lw,g in variants for c in COURSES}
    returns={(lw,g,c):[] for lw,g in variants for c in COURSES}
    bet_returns={(lw,g):collections.defaultdict(lambda:[0,0,0]) for lw,g in variants}
    rank_returns={(lw,g):collections.defaultdict(lambda:[0,0]) for lw,g in variants}
    errors={(lw,g):[] for lw,g in variants}
    key_stats=collections.defaultdict(lambda:[0.0,0.0]);bet_stats=collections.defaultdict(lambda:[0.0,0.0])
    state={'horse_hist':collections.defaultdict(lambda:collections.deque(maxlen=3)),'horse_starts':collections.Counter(),'jstats':collections.defaultdict(lambda:[0,0]),'tstats':collections.defaultdict(lambda:[0,0])}
    cur=None;day=[]

    def process(date,bundles):
        # State is intentionally frozen for the entire date. Generate every race's pre-result candidates once.
        generated={}
        for b in bundles:
            rid=str(b['race']['raceId']);generated[rid]=cmod.candidate_rows(state,b)

        # Evaluate selected races before any same-day result is incorporated into the probability model.
        for b in bundles:
            race=b['race'];rid=str(race['raceId'])
            if rid not in demand:continue
            seen.add(rid)
            if rid not in odds:continue
            pays=smod.payout_index(b)
            try:
                prepared=prepare_market_candidates(generated[rid],odds[rid],key_stats,bet_stats)
            except Exception as e:
                err={'raceId':rid,'raceDate':date,'venue':race.get('venue'),'raceNo':race.get('raceNo'),'error':f'{type(e).__name__}:{e}'}
                for variant in variants:errors[variant].append(err)
                continue
            for lw,g in variants:
                try:
                    chosen=select_tickets(score_variant(prepared,lw,g))
                    for rank,t in enumerate(chosen,1):
                        pay=int(pays.get((t['betType'],t['combo']),0) or 0)
                        br=bet_returns[(lw,g)][t['betType']];br[0]+=1;br[1]+=pay;br[2]+=int(pay>0)
                        rr=rank_returns[(lw,g)][rank];rr[0]+=1;rr[1]+=pay
                    for c,budget in COURSES.items():
                        ret,tix=settle(chosen,budget,pays);add(overall[(lw,g,c)],budget,ret,len(tix),ret>0);add(yearly[(lw,g,c)][date[:4]],budget,ret,len(tix),ret>0);add(periods[(lw,g,c)][period(date)],budget,ret,len(tix),ret>0);returns[(lw,g,c)].append({'raceId':rid,'returnYen':ret})
                except Exception as e:
                    errors[(lw,g)].append({'raceId':rid,'raceDate':date,'venue':race.get('venue'),'raceNo':race.get('raceNo'),'error':f'{type(e).__name__}:{e}'})

        # Only after the full date is frozen/evaluated do its outcomes update historical statistics and runner state.
        for b in bundles:
            rid=str(b['race']['raceId']);pays=smod.payout_index(b)
            for t in generated[rid]:
                hit=1.0 if int(pays.get((t['betType'],t['combo']),0) or 0)>0 else 0.0
                bet_stats[t['bt']][0]+=1.0;bet_stats[t['bt']][1]+=hit
                for key in smod.candidate_keys(t['bt'],t['vals']):
                    key_stats[key][0]+=1.0;key_stats[key][1]+=hit
        dmod.update_state_for_date(state,bundles)

    with (ROOT/a.corpus).open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():continue
            b=json.loads(line);date=str(b['race'].get('raceDate') or '')
            if cur is None:cur=date
            if date!=cur:process(cur,day);day=[];cur=date
            day.append(b)
    if cur:process(cur,day)

    results={}
    for lw,g in variants:
        key=f'lw{lw:.2f}-g{g:.2f}';courses={};err_ids={e['raceId'] for e in errors[(lw,g)]}
        for c in COURSES:
            x=fin(overall[(lw,g,c)]);x['byYear']={y:fin(s) for y,s in sorted(yearly[(lw,g,c)].items())};x['byPeriod']={p:fin(s) for p,s in periods[(lw,g,c)].items()};x['returnConcentration']=concentration(returns[(lw,g,c)],overall[(lw,g,c)]['returnYen']);courses[c]=x
        br={smod.BET_SPECS[bt][2]:{'tickets':v[0],'returnYenPer100Stake':round(v[1]/v[0],4) if v[0] else None,'hitPct':round(100*v[2]/v[0],4) if v[0] else None} for bt,v in sorted(bet_returns[(lw,g)].items())}
        rr={str(rank):{'tickets':v[0],'roiPct':round(100*v[1]/(100*v[0]),4) if v[0] else None} for rank,v in sorted(rank_returns[(lw,g)].items())}
        complete=(not missing and not err_ids and not(set(demand)-seen))
        results[key]={'localWeight':lw,'riskGamma':g,'evaluationErrorCount':len(errors[(lw,g)]),'evaluationErrors':errors[(lw,g)][:200],'evaluatedRaces':courses['ライト']['races'],'courses':courses,'betTypeDiagnostics':br,'selectionRankDiagnostics':rr,'completeOddsAndEvaluation':complete,'allThreeAtLeast200Pct':complete and all((courses[c]['roiPct'] or 0)>=200 for c in COURSES)}
    ranked=sorted(results,key=lambda k:(results[k]['completeOddsAndEvaluation'],min(results[k]['courses'][c]['roiPct'] or 0 for c in COURSES),sum(results[k]['courses'][c]['roiPct'] or 0 for c in COURSES)),reverse=True)
    result={'purpose':'research_only_two_stage_market_value_walk_forward','evaluationStart':'2016-08-10','evaluationEnd':'2026-08-09','selectedDemandRaces':len(demand),'oddsRaces':len(odds),'missingOddsRaceCount':len(missing),'missingOddsRaceIds':missing,'missingDemandRacesInCorpus':sorted(set(demand)-seen),'candidateOddsCompletenessRequired':True,'sharedCandidateComputationAcrossVariants':True,'variants':results,'ranking':ranked,'bestVariant':ranked[0] if ranked else None,'historicalFinalOddsUsed':True,'prestartTimingValidationPerformed':False,'raceSelectionFrozenBeforeOdds':True,'targetDayResultsUsedForRaceSelection':False,'sameDayResultsUsedForTicketProbability':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    out=ROOT/a.out;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    best=result['bestVariant'];print(json.dumps({'selected':len(demand),'odds':len(odds),'missing':len(missing),'best':best,'bestRoi':{c:results[best]['courses'][c]['roiPct'] for c in COURSES} if best else None,'bestErrors':results[best]['evaluationErrorCount'] if best else None,'all200':results[best]['allThreeAtLeast200Pct'] if best else False},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
