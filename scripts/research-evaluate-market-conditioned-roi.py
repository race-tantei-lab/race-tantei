#!/usr/bin/env python3
import argparse,collections,importlib.util,json,math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COURSES={'ライト':2000,'スタンダード':5000,'プレミアム':10000}
MARKET_WEIGHTS=(0.25,0.50,0.75,1.00)
RISK_GAMMAS=(0.0,0.25,0.50)
MARKET_MIN_N=100.0
MARKET_PRIOR_N=1000.0
MARKET_PRIOR_ROI=0.80
TOP_MARKET_COMPONENTS=6


def load(path,name):
    s=importlib.util.spec_from_file_location(name,path)
    if s is None or s.loader is None:raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

base=load(ROOT/'scripts/research-evaluate-continuous-market-value.py','market_base_roi')
cmod=base.cmod;smod=base.smod;dmod=base.dmod;gen=base.gen


def rank_bucket(rank,total):
    q=rank/max(1,total)
    if q<=0.01:return 0
    if q<=0.03:return 1
    if q<=0.05:return 2
    if q<=0.10:return 3
    if q<=0.20:return 4
    if q<=0.40:return 5
    return 6


def enrich_market_context(prepared,odds_row):
    official=odds_row.get('officialOdds') or {};rank_maps={};totals={}
    for market,values in official.items():
        xs=[]
        for combo,value in (values or {}).items():
            odd=base.midpoint(value)
            if odd is not None and odd>=1.0:xs.append((odd,str(combo)))
        xs.sort(key=lambda x:(x[0],x[1]));rank_maps[market]={combo:i+1 for i,(_,combo) in enumerate(xs)};totals[market]=len(xs)
    out=[]
    for t in prepared:
        rank=rank_maps.get(t['market'],{}).get(t['combo'])
        if rank is None:raise RuntimeError(f'MARKET_RANK_MISSING:{t["market"]}:{t["combo"]}')
        x=dict(t);x['marketRank']=rank;x['marketRankBucket']=rank_bucket(rank,totals[t['market']]);out.append(x)
    return out


def market_keys(t):
    v=t['vals'];bt=t['bt'];ob=t['oddsBin'];rb=t['marketRankBucket']
    yield (bt,('oddsBin',),(ob,))
    yield (bt,('marketRankBucket',),(rb,))
    yield (bt,('oddsBin','marketRankBucket'),(ob,rb))
    for name in ('bestform','bestspeed','bestj','bestt','expcnt','top3lastsum'):
        if name in v:yield (bt,('oddsBin',name),(ob,v[name]))


def predicted_market_roi(t,stats,bet_stats):
    bn,bret=bet_stats.get(t['bt'],(0.0,0.0));bmean=(bret+MARKET_PRIOR_N*100*MARKET_PRIOR_ROI)/(100*(bn+MARKET_PRIOR_N))
    comps=[]
    for key in market_keys(t):
        n,ret=stats.get(key,(0.0,0.0))
        if n<MARKET_MIN_N:continue
        mean=(ret+MARKET_PRIOR_N*100*bmean)/(100*(n+MARKET_PRIOR_N))
        rel=n/(n+MARKET_PRIOR_N);complexity=1.0 if len(key[1])==1 else 0.94
        comps.append((mean,rel*complexity,n))
    if not comps:return bmean
    comps.sort(key=lambda x:(x[0],x[1],x[2]),reverse=True);top=comps[:TOP_MARKET_COMPONENTS];w=sum(x[1] for x in top)
    local=sum(x[0]*x[1] for x in top)/w if w else bmean
    return 0.25*bmean+0.75*local


def score_variant(prepared,market_stats,market_bet_stats,market_weight,risk_gamma):
    out=[]
    for t in prepared:
        raw_p=0.5*t['baseProb']+0.5*t['localProb'];raw_ev=raw_p*t['odds'];hist=predicted_market_roi(t,market_stats,market_bet_stats)
        score=(1.0-market_weight)*raw_ev+market_weight*hist
        score*=((10.0/max(1.0,t['odds']))**risk_gamma)
        out.append({**t,'pHat':raw_p,'ev':raw_ev,'historicalMarketRoi':hist,'marketScore':score})
    out.sort(key=lambda x:(-x['marketScore'],-x['historicalMarketRoi'],-x['ev'],x['odds'],x['bt'],x['combo']))
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--corpus',required=True);ap.add_argument('--demand',required=True);ap.add_argument('--odds-dir',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    demand={}
    for line in (ROOT/a.demand).read_text().splitlines():
        if line.strip():
            r=json.loads(line);demand[str(r['raceId'])]=r
    if len(demand)!=14410:raise RuntimeError(f'DEMAND_COUNT_INVALID:{len(demand)}')
    odds,_=base.load_odds(ROOT/a.odds_dir);missing=sorted(set(demand)-set(odds));seen=set();variants=[(w,g) for w in MARKET_WEIGHTS for g in RISK_GAMMAS]
    overall={(w,g,c):base.init_stat() for w,g in variants for c in COURSES};yearly={(w,g,c):collections.defaultdict(base.init_stat) for w,g in variants for c in COURSES};returns={(w,g,c):[] for w,g in variants for c in COURSES};errors={(w,g):[] for w,g in variants}
    key_stats=collections.defaultdict(lambda:[0.0,0.0]);bet_stats=collections.defaultdict(lambda:[0.0,0.0]);market_stats=collections.defaultdict(lambda:[0.0,0.0]);market_bet_stats=collections.defaultdict(lambda:[0.0,0.0])
    state={'horse_hist':collections.defaultdict(lambda:collections.deque(maxlen=3)),'horse_starts':collections.Counter(),'jstats':collections.defaultdict(lambda:[0,0]),'tstats':collections.defaultdict(lambda:[0,0])};cur=None;day=[]

    def process(date,bundles):
        generated={str(b['race']['raceId']):cmod.candidate_rows(state,b) for b in bundles};prepared_by_rid={}
        for b in bundles:
            race=b['race'];rid=str(race['raceId'])
            if rid not in demand:continue
            seen.add(rid)
            if rid not in odds:continue
            try:prepared_by_rid[rid]=enrich_market_context(base.prepare_market_candidates(generated[rid],odds[rid],key_stats,bet_stats),odds[rid])
            except Exception as e:
                err={'raceId':rid,'raceDate':date,'error':f'{type(e).__name__}:{e}'}
                for v in variants:errors[v].append(err)
                continue
            pays=smod.payout_index(b)
            for w,g in variants:
                try:
                    chosen=base.select_tickets(score_variant(prepared_by_rid[rid],market_stats,market_bet_stats,w,g))
                    for c,budget in COURSES.items():
                        ret,_=base.settle(chosen,budget,pays);base.add(overall[(w,g,c)],budget,ret,len(chosen),ret>0);base.add(yearly[(w,g,c)][date[:4]],budget,ret,len(chosen),ret>0);returns[(w,g,c)].append({'raceId':rid,'returnYen':ret})
                except Exception as e:errors[(w,g)].append({'raceId':rid,'raceDate':date,'error':f'{type(e).__name__}:{e}'})
        # Update probability stats from all races only after date freeze.
        for b in bundles:
            rid=str(b['race']['raceId']);pays=smod.payout_index(b)
            for t in generated[rid]:
                hit=1.0 if int(pays.get((t['betType'],t['combo']),0) or 0)>0 else 0.0
                bet_stats[t['bt']][0]+=1;bet_stats[t['bt']][1]+=hit
                for key in smod.candidate_keys(t['bt'],t['vals']):key_stats[key][0]+=1;key_stats[key][1]+=hit
        # Update market-conditioned ROI only from previously frozen selected races with official odds.
        for b in bundles:
            rid=str(b['race']['raceId']);pays=smod.payout_index(b)
            for t in prepared_by_rid.get(rid,[]):
                ret=float(int(pays.get((t['betType'],t['combo']),0) or 0));market_bet_stats[t['bt']][0]+=1;market_bet_stats[t['bt']][1]+=ret
                for key in market_keys(t):market_stats[key][0]+=1;market_stats[key][1]+=ret
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
    for w,g in variants:
        key=f'mw{w:.2f}-g{g:.2f}';courses={};err_ids={e['raceId'] for e in errors[(w,g)]}
        for c in COURSES:
            x=base.fin(overall[(w,g,c)]);x['byYear']={y:base.fin(s) for y,s in sorted(yearly[(w,g,c)].items())};x['returnConcentration']=base.concentration(returns[(w,g,c)],overall[(w,g,c)]['returnYen']);courses[c]=x
        complete=(not missing and not err_ids and not(set(demand)-seen));results[key]={'marketWeight':w,'riskGamma':g,'evaluatedRaces':courses['ライト']['races'],'evaluationErrorCount':len(errors[(w,g)]),'evaluationErrors':errors[(w,g)][:200],'courses':courses,'completeOddsAndEvaluation':complete,'allThreeAtLeast200Pct':complete and all((courses[c]['roiPct'] or 0)>=200 for c in COURSES)}
    ranked=sorted(results,key=lambda k:(results[k]['completeOddsAndEvaluation'],min(results[k]['courses'][c]['roiPct'] or 0 for c in COURSES),sum(results[k]['courses'][c]['roiPct'] or 0 for c in COURSES)),reverse=True);best=ranked[0]
    result={'purpose':'research_only_market_conditioned_roi_walk_forward','selectedDemandRaces':len(demand),'oddsRaces':len(odds),'missingOddsRaceCount':len(missing),'missingOddsRaceIds':missing,'marketStatsUpdatedOnlyAfterDateFreeze':True,'marketStatsUseSelectedPastRacesOnly':True,'variants':results,'ranking':ranked,'bestVariant':best,'historicalFinalOddsUsed':True,'prestartTimingValidationPerformed':False,'raceSelectionFrozenBeforeOdds':True,'sameDayResultsUsedForTicketProbability':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    out=ROOT/a.out;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'best':best,'evaluated':results[best]['evaluatedRaces'],'errors':results[best]['evaluationErrorCount'],'roi':{c:results[best]['courses'][c]['roiPct'] for c in COURSES}},ensure_ascii=False))

if __name__=='__main__':main()
