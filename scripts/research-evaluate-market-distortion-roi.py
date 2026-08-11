#!/usr/bin/env python3
import argparse, collections, importlib.util, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COURSES = {'ライト': 2000, 'スタンダード': 5000, 'プレミアム': 10000}
LOCAL_WEIGHTS = (0.50, 0.75)
RISK_GAMMAS = (0.0, 0.50)
TRAIN_CAPS = (2000, 5000)
VALUE_ODDS_EDGES = (3, 5, 8, 12, 20, 35, 60, 100, 180, 300, 600, 1200)
MIN_N = 100
BIN_PRIOR = 2000.0
KEY_PRIOR = 600.0
PRIOR_ROI = 0.80
TOP_COMPONENTS = 8
MARKET_SINGLES = ('odds','mrank','minpop','maxpop','popsum','favcnt','distort')
MARKET_PAIRS = (
    ('odds','distort'),('mrank','distort'),('minpop','distort'),('maxpop','distort'),
    ('popsum','distort'),('bestform','distort'),('bestspeed','distort'),
    ('surface','distort'),('rclass','distort'),('odds','bestform'),('mrank','bestform'),
)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cmod = load(ROOT / 'scripts/research-continuous-walkforward-demand.py', 'market_dist_continuous')
gen = load(ROOT / 'scripts/generate-final-live-bets.py', 'market_dist_live')
smod = cmod.smod
dmod = cmod.dmod


def midpoint(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        xs = []
        for x in v:
            try:
                xs.append(float(x))
            except Exception:
                pass
        return sum(xs) / len(xs) if xs else None
    try:
        return float(v)
    except Exception:
        return None


def value_bin(odd):
    i = 0
    while i < len(VALUE_ODDS_EDGES) and odd >= VALUE_ODDS_EDGES[i]:
        i += 1
    return i


def period(date):
    y = int(date[:4])
    if date <= '2018-12-31': return '2016-08-10..2018'
    if y <= 2021: return '2019..2021'
    if y <= 2024: return '2022..2024'
    return '2025..2026-08-09'


def init_stat(): return {'races':0,'tickets':0,'hitRaces':0,'stakeYen':0,'returnYen':0}
def add(st,stake,ret,n,hit):
    st['races']+=1; st['tickets']+=n; st['hitRaces']+=int(hit); st['stakeYen']+=stake; st['returnYen']+=ret

def fin(st):
    x=dict(st); x['profitYen']=st['returnYen']-st['stakeYen']
    x['roiPct']=round(100*st['returnYen']/st['stakeYen'],4) if st['stakeYen'] else None
    x['hitRacePct']=round(100*st['hitRaces']/st['races'],4) if st['races'] else None
    return x


def load_odds(path):
    out={}
    for p in sorted(Path(path).glob('research-continuous-market-odds-20*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if not line.strip(): continue
            r=json.loads(line); rid=str(r['raceId'])
            if rid in out: raise RuntimeError(f'DUPLICATE_ODDS:{rid}')
            out[rid]=r
    return out


def mean_roi(n,ret,prior_n,prior_roi):
    return (ret+prior_n*100.0*prior_roi)/(100.0*(n+prior_n))


def extended_keys(ticket):
    bt=ticket['bt']; v=ticket['vals']
    yielded=set()
    for key in smod.candidate_keys(bt,v):
        yielded.add(key); yield key
    for a in MARKET_SINGLES:
        key=(bt,(a,),(v[a],))
        if key not in yielded:
            yielded.add(key); yield key
    for a,b in MARKET_PAIRS:
        key=(bt,(a,b),(v[a],v[b]))
        if key not in yielded:
            yielded.add(key); yield key


def value_key(ticket, obin, key):
    bt,axes,vals=key
    return (bt,obin,axes,vals)


def market_context(odds_row):
    official=odds_row.get('officialOdds') or {}
    horses=sorted(int(x) for x in (odds_row.get('horses') or []))
    if len(horses)<3: raise RuntimeError(f'ODDS_HORSES_INVALID:{horses}')
    winmap=official.get('win') or {}
    win=[]
    for h in horses:
        odd=midpoint(winmap.get(str(h)))
        if odd is None or odd<=1.0: raise RuntimeError(f'WIN_ODDS_INCOMPLETE:{h}')
        win.append(odd)
    raw=[1.0/x for x in win]; total=sum(raw); weights=[x/total for x in raw]
    pop_order=sorted(range(len(horses)),key=lambda i:(win[i],horses[i]))
    pop=[0]*len(horses)
    for rank,i in enumerate(pop_order,1): pop[i]=rank
    pos={h:i for i,h in enumerate(horses)}
    ranks={}
    for market,omap in official.items():
        rows=[]
        if not isinstance(omap,dict): continue
        for combo,val in omap.items():
            odd=midpoint(val)
            if odd is not None and odd>1.0: rows.append((odd,str(combo)))
        rows.sort(key=lambda x:(x[0],x[1]))
        ranks[market]={combo:rank for rank,(_,combo) in enumerate(rows,1)}
    return official,horses,pos,pop,weights,ranks


def enrich_candidates(rows,odds_row):
    official,horses,pos,pop,weights,ranks=market_context(odds_row)
    out=[]; missing=[]
    for t in rows:
        odd=midpoint((official.get(t['market']) or {}).get(t['combo']))
        if odd is None or odd<1.0:
            missing.append(f"{t['market']}:{t['combo']}"); continue
        if any(int(h) not in pos for h in t['horses']):
            raise RuntimeError(f'CANDIDATE_HORSE_NOT_IN_ODDS:{t["combo"]}')
        pp=tuple(pos[int(h)] for h in t['horses'])
        mp=gen.market_prob(pp,t['market'],weights)
        assumed=gen.PAYOUT_RATIO[t['market']]/max(mp,1e-15)
        ratio=odd/assumed
        pops=[pop[pos[int(h)]] for h in t['horses']]
        mrank=(ranks.get(t['market']) or {}).get(t['combo'])
        if mrank is None:
            missing.append(f"rank:{t['market']}:{t['combo']}"); continue
        vals=dict(t['vals'])
        vals.update({
            'odds':gen.bsearch(gen.ODDS_EDGES,odd),
            'mrank':gen.market_rank_bin(mrank),
            'minpop':gen.minpop_bin(min(pops)),
            'maxpop':gen.maxpop_bin(max(pops)),
            'popsum':gen.popsum_bin(sum(pops)),
            'favcnt':min(3,sum(1 for p in pops if p<=1)),
            'distort':gen.bsearch(gen.DISTORT_EDGES,ratio),
        })
        out.append({**t,'vals':vals,'odds':odd,'valueBin':value_bin(odd),
                    'oddsBin':vals['odds'],'marketRank':mrank,'distortRatio':ratio})
    if missing: raise RuntimeError(f'CANDIDATE_ODDS_INCOMPLETE:{len(missing)}:{missing[:12]}')
    return out


def parts(ticket,cap,bin_stats,key_stats):
    obin=ticket['valueBin']
    bn,bret=bin_stats[cap].get((ticket['bt'],obin),(0.0,0.0))
    base=mean_roi(bn,bret,BIN_PRIOR,PRIOR_ROI)
    comps=[]
    for key in extended_keys(ticket):
        n,ret=key_stats[cap].get(value_key(ticket,obin,key),(0.0,0.0))
        if n<MIN_N: continue
        local=mean_roi(n,ret,KEY_PRIOR,base)
        reliability=n/(n+KEY_PRIOR)
        complexity=1.0 if len(key[1])==1 else 0.90
        comps.append((local,reliability*complexity,n))
    if not comps: return base,base
    comps.sort(key=lambda x:(x[0],x[1],x[2]),reverse=True)
    top=comps[:TOP_COMPONENTS]; w=sum(x[1] for x in top)
    local=sum(x[0]*x[1] for x in top)/w if w else base
    return base,local


def score(prepared,cap,lw,gamma,bin_stats,key_stats):
    out=[]
    for t in prepared:
        base,local=parts(t,cap,bin_stats,key_stats)
        pred=(1.0-lw)*base+lw*local
        s=pred*((10.0/max(1.0,t['odds']))**gamma)
        out.append({**t,'predictedRoi':pred,'marketScore':s})
    out.sort(key=lambda x:(-x['marketScore'],-x['predictedRoi'],x['odds'],x['bt'],x['combo']))
    return out


def select_tickets(rows):
    if len(rows)<3: raise RuntimeError(f'TOO_FEW_ODDS_CANDIDATES:{len(rows)}')
    mx=rows[0]['marketScore']; chosen=[t for t in rows if t['marketScore']>=mx*.85-1e-12][:10]
    if len(chosen)<3: chosen=list(rows[:3])
    keys={(t['bt'],t['combo']) for t in chosen}; types={t['bt'] for t in chosen}
    if len(types)<2:
        alt=next((t for t in rows if t['bt'] not in types and (t['bt'],t['combo']) not in keys),None)
        if alt is None: raise RuntimeError('NO_SECOND_BET_TYPE')
        if len(chosen)<10: chosen.append(alt)
        else: chosen[-1]=alt
    chosen.sort(key=lambda x:(-x['marketScore'],-x['predictedRoi'],x['odds'],x['bt'],x['combo']))
    if not(3<=len(chosen)<=10) or len({t['bt'] for t in chosen})<2: raise RuntimeError('FINAL_TICKET_GATE_FAILED')
    return chosen


def settle(chosen,budget,payouts):
    units=gen.allocate([t['oddsBin'] for t in chosen],budget//100)
    if sum(units)*100!=budget: raise RuntimeError(f'BUDGET_INVALID:{budget}')
    return sum(u*int(payouts.get((t['betType'],t['combo']),0) or 0) for t,u in zip(chosen,units))


def concentration(rows,total):
    r=sorted(rows,key=lambda x:x['returnYen'],reverse=True)
    def pct(n): return round(100*sum(x['returnYen'] for x in r[:n])/total,4) if total else 0.0
    return {'largestRaceReturnYen':r[0]['returnYen'] if r else 0,'largestRaceId':r[0]['raceId'] if r else None,
            'top1ReturnSharePct':pct(1),'top5ReturnSharePct':pct(5),'top10ReturnSharePct':pct(10),'top25ReturnSharePct':pct(25)}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--corpus',required=True); ap.add_argument('--demand',required=True); ap.add_argument('--odds-dir',required=True); ap.add_argument('--out',required=True); a=ap.parse_args()
    demand={}
    for line in (ROOT/a.demand).read_text(encoding='utf-8').splitlines():
        if line.strip():
            r=json.loads(line); demand[str(r['raceId'])]=r
    if len(demand)!=14410: raise RuntimeError(f'DEMAND_COUNT_INVALID:{len(demand)}')
    odds=load_odds(ROOT/a.odds_dir); missing=sorted(set(demand)-set(odds)); seen=set()
    variants=[(cap,lw,g) for cap in TRAIN_CAPS for lw in LOCAL_WEIGHTS for g in RISK_GAMMAS]
    overall={(cap,lw,g,c):init_stat() for cap,lw,g in variants for c in COURSES}
    yearly={(cap,lw,g,c):collections.defaultdict(init_stat) for cap,lw,g in variants for c in COURSES}
    periods={(cap,lw,g,c):collections.defaultdict(init_stat) for cap,lw,g in variants for c in COURSES}
    returns={(cap,lw,g,c):[] for cap,lw,g in variants for c in COURSES}
    errors={(cap,lw,g):[] for cap,lw,g in variants}
    bin_stats={cap:collections.defaultdict(lambda:[0.0,0.0]) for cap in TRAIN_CAPS}
    key_stats={cap:collections.defaultdict(lambda:[0.0,0.0]) for cap in TRAIN_CAPS}
    state={'horse_hist':collections.defaultdict(lambda:collections.deque(maxlen=3)),'horse_starts':collections.Counter(),'jstats':collections.defaultdict(lambda:[0,0]),'tstats':collections.defaultdict(lambda:[0,0])}
    cur=None; day=[]

    def process(date,bundles):
        generated={str(b['race']['raceId']):cmod.candidate_rows(state,b) for b in bundles}
        learning=[]
        for b in bundles:
            race=b['race']; rid=str(race['raceId'])
            if rid not in demand: continue
            seen.add(rid)
            if rid not in odds: continue
            pays=smod.payout_index(b)
            try: enriched=enrich_candidates(generated[rid],odds[rid])
            except Exception as e:
                err={'raceId':rid,'raceDate':date,'venue':race.get('venue'),'raceNo':race.get('raceNo'),'error':f'{type(e).__name__}:{e}'}
                for v in variants: errors[v].append(err)
                continue
            learning.append((enriched,pays))
            for cap,lw,g in variants:
                try:
                    chosen=select_tickets(score(enriched,cap,lw,g,bin_stats,key_stats))
                    for c,budget in COURSES.items():
                        ret=settle(chosen,budget,pays); add(overall[(cap,lw,g,c)],budget,ret,len(chosen),ret>0); add(yearly[(cap,lw,g,c)][date[:4]],budget,ret,len(chosen),ret>0); add(periods[(cap,lw,g,c)][period(date)],budget,ret,len(chosen),ret>0); returns[(cap,lw,g,c)].append({'raceId':rid,'returnYen':ret})
                except Exception as e:
                    errors[(cap,lw,g)].append({'raceId':rid,'raceDate':date,'venue':race.get('venue'),'raceNo':race.get('raceNo'),'error':f'{type(e).__name__}:{e}'})
        # Market-value learning occurs only after all selected races on the date were scored.
        for enriched,pays in learning:
            for t in enriched:
                actual=int(pays.get((t['betType'],t['combo']),0) or 0)
                for cap in TRAIN_CAPS:
                    observed=min(actual,cap); bk=(t['bt'],t['valueBin'])
                    bin_stats[cap][bk][0]+=1; bin_stats[cap][bk][1]+=observed
                    for key in extended_keys(t):
                        kk=value_key(t,t['valueBin'],key); key_stats[cap][kk][0]+=1; key_stats[cap][kk][1]+=observed
        dmod.update_state_for_date(state,bundles)

    with (ROOT/a.corpus).open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip(): continue
            b=json.loads(line); date=str(b['race'].get('raceDate') or '')
            if cur is None: cur=date
            if date!=cur: process(cur,day); day=[]; cur=date
            day.append(b)
    if cur: process(cur,day)

    unseen=sorted(set(demand)-seen); results={}
    for cap,lw,g in variants:
        name=f'cap{cap}-lw{lw:.2f}-g{g:.2f}'; err_ids={e['raceId'] for e in errors[(cap,lw,g)]}; courses={}
        for c in COURSES:
            x=fin(overall[(cap,lw,g,c)]); x['byYear']={y:fin(s) for y,s in sorted(yearly[(cap,lw,g,c)].items())}; x['byPeriod']={p:fin(s) for p,s in periods[(cap,lw,g,c)].items()}; x['returnConcentration']=concentration(returns[(cap,lw,g,c)],overall[(cap,lw,g,c)]['returnYen']); courses[c]=x
        complete=not missing and not unseen and not err_ids
        results[name]={'trainingReturnCapYenPer100':cap,'localWeight':lw,'riskGamma':g,'evaluatedRaces':courses['ライト']['races'],'evaluationErrorCount':len(errors[(cap,lw,g)]),'evaluationErrors':errors[(cap,lw,g)][:200],'courses':courses,'completeOddsAndEvaluation':complete,'allThreeAtLeast200Pct':complete and all((courses[c]['roiPct'] or 0)>=200 for c in COURSES)}
    ranked=sorted(results,key=lambda k:(results[k]['completeOddsAndEvaluation'],min(results[k]['courses'][c]['roiPct'] or 0 for c in COURSES),sum(results[k]['courses'][c]['roiPct'] or 0 for c in COURSES)),reverse=True)
    result={'purpose':'research_only_market_distortion_roi_walk_forward','evaluationStart':'2016-08-10','evaluationEnd':'2026-08-09','selectedDemandRaces':len(demand),'oddsRaces':len(odds),'missingOddsRaceCount':len(missing),'missingOddsRaceIds':missing,'missingDemandRacesInCorpus':unseen,'candidateOddsCompletenessRequired':True,'marketFeatureFormulaMatchesProductionLiveGenerator':True,'productionRulesReused':False,'raceSelectionFrozenBeforeOdds':True,'targetDayResultsUsedForRaceSelection':False,'sameDayResultsUsedForTicketValue':False,'marketValueTrainingUsesPriorSelectedRacesOnly':True,'historicalFinalOddsUsed':True,'prestartTimingValidationPerformed':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False,'variants':results,'ranking':ranked,'bestVariant':ranked[0] if ranked else None}
    out=ROOT/a.out; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    b=result['bestVariant']; print(json.dumps({'selected':len(demand),'odds':len(odds),'missing':len(missing),'best':b,'bestRoi':{c:results[b]['courses'][c]['roiPct'] for c in COURSES} if b else None,'bestErrors':results[b]['evaluationErrorCount'] if b else None,'all200':results[b]['allThreeAtLeast200Pct'] if b else False},ensure_ascii=False),flush=True)

if __name__=='__main__': main()
