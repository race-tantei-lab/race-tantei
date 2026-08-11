#!/usr/bin/env python3
import argparse,collections,itertools,json,math
from pathlib import Path

BET_SPECS={
 'win':('単勝',1,True),
 'umaren':('馬連',2,False),
 'wide':('ワイド',2,False),
 'umatan':('馬単',2,True),
 'trio':('3連複',3,False),
 'trifecta':('3連単',3,True),
}
COURSES={'light':2000,'standard':5000,'premium':10000}
ODDS_EDGES=[2,3,5,7,10,15,20,30,50,75,100,150,300,500,800,1200,2000]
ODDS_MID=[1.4,2.45,3.9,5.9,8.4,12.2,17.3,24.5,38.7,61.2,86.6,122.5,212.1,387.3,632.5,979.8,1549.2,2500.0]
CONFIGS=[
 ('ability_b035','ability',0.35),
 ('ability_b070','ability',0.70),
 ('ability_b105','ability',1.05),
 ('gap_b050','gap',0.50),
 ('gap_b100','gap',1.00),
]


def norm_combo(bt,horses):
    if bt in ('umaren','wide','trio'):
        horses=tuple(sorted(horses))
    return '-'.join(str(x) for x in horses)


def odds_value(v):
    if isinstance(v,list):
        vals=[float(x) for x in v if x is not None]
        return sum(vals)/len(vals) if vals else None
    return float(v) if v is not None else None


def bsearch(edges,x):
    i=0
    while i<len(edges) and x>=edges[i]:i+=1
    return i


def allocate(odds_list,budget):
    U=budget//100;n=len(odds_list);cap=max(1,int(math.floor(U*.35+1e-12)))
    if n<3 or n>10 or n*cap<U:raise RuntimeError(f'INVALID_ALLOCATION:{n}:{U}:{cap}')
    bins=[bsearch(ODDS_EDGES,o) for o in odds_list]
    units=[1]*n;rem=U-n
    weights=[min(1.0,(100.0/ODDS_MID[b])**1.5) for b in bins];tw=sum(weights)
    targets=[U*w/tw for w in weights]
    while rem>0:
        elig=[i for i in range(n) if units[i]<cap]
        if not elig:raise RuntimeError('ALLOCATION_FAILED')
        elig.sort(key=lambda i:(-(targets[i]-units[i]),-weights[i],ODDS_MID[bins[i]],i))
        units[elig[0]]+=1;rem-=1
    if max(units)>cap or sum(units)!=U:raise RuntimeError('ALLOCATION_GATE_FAILED')
    return units


def zscores(rows,key):
    vals=[float(r[key]) for r in rows];m=sum(vals)/len(vals);v=sum((x-m)**2 for x in vals)/max(1,len(vals));s=math.sqrt(v)
    if s<1e-12:return {int(r['horseNo']):0.0 for r in rows}
    return {int(r['horseNo']):(float(r[key])-m)/s for r in rows}


def fair_weights(pred_rows,win_odds,mode,beta):
    active=[r for r in pred_rows if int(r['horseNo']) in win_odds]
    if len(active)<3:return None
    za=zscores(active,'abilityScore');zm=zscores(active,'marketScore')
    raw={}
    for r in active:
        h=int(r['horseNo']);q=1.0/max(1.01,float(win_odds[h]))
        signal=za[h] if mode=='ability' else za[h]-zm[h]
        raw[h]=q*math.exp(max(-4.0,min(4.0,beta*signal)))
    total=sum(raw.values())
    return {h:v/total for h,v in raw.items()} if total>0 else None


def ordered2(w,a,b):
    return w[a]*w[b]/max(1e-15,1.0-w[a])


def ordered3(w,a,b,c):
    return w[a]*(w[b]/max(1e-15,1.0-w[a]))*(w[c]/max(1e-15,1.0-w[a]-w[b]))


def ticket_prob(bt,horses,w):
    if bt=='win':return w[horses[0]]
    if bt=='umatan':return ordered2(w,*horses)
    if bt=='umaren':
        a,b=horses;return ordered2(w,a,b)+ordered2(w,b,a)
    if bt=='trifecta':return ordered3(w,*horses)
    if bt=='trio':
        a,b,c=horses
        return sum(ordered3(w,*p) for p in itertools.permutations((a,b,c),3))
    a,b=horses;out=0.0
    for c in w:
        if c in (a,b):continue
        out+=ordered3(w,a,b,c)+ordered3(w,a,c,b)+ordered3(w,b,a,c)+ordered3(w,b,c,a)+ordered3(w,c,a,b)+ordered3(w,c,b,a)
    return out


def candidate_horses(w,pred_rows):
    # Fair-probability leaders plus model-vs-market disagreement outsiders.
    base=[h for h,_ in sorted(w.items(),key=lambda kv:(-kv[1],kv[0]))[:6]]
    za=zscores([r for r in pred_rows if int(r['horseNo']) in w],'abilityScore')
    zm=zscores([r for r in pred_rows if int(r['horseNo']) in w],'marketScore')
    gap=sorted(w,key=lambda h:(-(za[h]-zm[h]),h))[:2]
    out=[]
    for h in base+gap:
        if h not in out:out.append(h)
    return out[:8]


def build_tickets(w,pred_rows,official):
    pool=candidate_horses(w,pred_rows);tickets=[]
    for bt,(jp,k,ordered) in BET_SPECS.items():
        market=official.get(bt,{})
        if len(pool)<k:continue
        seq=itertools.permutations(pool,k) if ordered else itertools.combinations(pool,k)
        for hs in seq:
            combo=norm_combo(bt,hs);ov=odds_value(market.get(combo))
            if ov is None or ov<=1.0:continue
            p=ticket_prob(bt,hs,w);ev=p*ov
            tickets.append({'bt':bt,'betType':jp,'horses':list(hs),'combo':combo,'odds':ov,'prob':p,'ev':ev})
    tickets.sort(key=lambda t:(-t['ev'],-t['prob'],t['odds'],t['bt'],t['combo']))
    if len(tickets)<3:return None
    # Exactly three tickets for the first diagnostic: minimize forced dilution while satisfying >=2 bet types.
    chosen=[tickets[0]];types={tickets[0]['bt']}
    second=next((t for t in tickets[1:] if t['bt'] not in types),None)
    if second is None:return None
    chosen.append(second);types.add(second['bt'])
    used={(t['bt'],t['combo']) for t in chosen}
    third=next((t for t in tickets if (t['bt'],t['combo']) not in used),None)
    if third is None:return None
    chosen.append(third)
    chosen.sort(key=lambda t:(-t['ev'],-t['prob'],t['bt'],t['combo']))
    if len({t['bt'] for t in chosen})<2:raise RuntimeError('SECOND_BET_TYPE_GATE_FAILED')
    return chosen


def payout_index(bundle):
    out={}
    for p in bundle.get('payouts',[]):
        bt=str(p.get('betType') or '');combo=str(p.get('combination') or '');pay=p.get('payoutYen')
        if bt and combo and pay is not None:out[(bt,combo)]=int(pay)
    return out


def robust(rows,budget):
    total_stake=sum(r['stakeYen'] for r in rows);total_return=sum(r['returnYen'] for r in rows)
    ordered=sorted(rows,key=lambda r:(-r['returnYen'],r['raceId']))
    def cut(n):
        n=min(n,len(ordered));rm=ordered[:n];stake=total_stake-sum(r['stakeYen'] for r in rm);ret=total_return-sum(r['returnYen'] for r in rm)
        return round(100*ret/stake,4) if stake else None
    n1=max(1,math.ceil(len(rows)*.01))
    return {
      'races':len(rows),'stakeYen':total_stake,'returnYen':total_return,
      'roiPct':round(100*total_return/total_stake,4) if total_stake else None,
      'top50ExcludedRoiPct':cut(50),'top100ExcludedRoiPct':cut(100),'top1PctExcludedRaceCount':n1,'top1PctExcludedRoiPct':cut(n1),
      'top50ReturnSharePct':round(100*sum(r['returnYen'] for r in ordered[:50])/total_return,4) if total_return else 0.0,
      'hardGateTop50AtLeast200':bool(len(rows)>=50 and cut(50)>=200.0),
    }


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--predictions-dir',required=True);ap.add_argument('--odds-dir',required=True);ap.add_argument('--history',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    preds=collections.defaultdict(list)
    for p in sorted(Path(a.predictions_dir).glob('runner-ranker-20*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r=json.loads(line);preds[str(r['raceId'])].append(r)
    if len(preds)!=14410:raise RuntimeError(f'PREDICTION_RACE_COUNT_INVALID:{len(preds)}')
    odds={}
    for p in sorted(Path(a.odds_dir).glob('research-continuous-market-odds-20*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r=json.loads(line);rid=str(r['raceId'])
                if rid in preds:odds[rid]=r
    if len(odds)!=14410:raise RuntimeError(f'ODDS_RACE_COUNT_INVALID:{len(odds)}')
    hist={}
    with Path(a.history).open(encoding='utf-8') as fh:
        for line in fh:
            if line.strip():
                b=json.loads(line);rid=str(b['race']['raceId'])
                if rid in preds:hist[rid]=b
    if len(hist)!=14410:raise RuntimeError(f'HISTORY_RACE_COUNT_INVALID:{len(hist)}')

    race_results={cfg:collections.defaultdict(list) for cfg,_,_ in CONFIGS};errors=[]
    for idx,rid in enumerate(sorted(preds,key=lambda x:(str(odds[x]['raceDate']),str(odds[x]['venue']),int(odds[x]['raceNo']))),1):
        o=odds[rid];pr=preds[rid];winraw=o['officialOdds'].get('win',{})
        win={int(h):odds_value(v) for h,v in winraw.items() if odds_value(v) is not None}
        pays=payout_index(hist[rid])
        for cfg,mode,beta in CONFIGS:
            w=fair_weights(pr,win,mode,beta)
            if not w:
                errors.append({'raceId':rid,'config':cfg,'reason':'FAIR_WEIGHT_FAILED'});continue
            chosen=build_tickets(w,pr,o['officialOdds'])
            if not chosen:
                errors.append({'raceId':rid,'config':cfg,'reason':'TICKET_SELECTION_FAILED'});continue
            for course,budget in COURSES.items():
                units=allocate([t['odds'] for t in chosen],budget);ret=0
                for t,u in zip(chosen,units):ret+=u*pays.get((t['betType'],t['combo']),0)
                race_results[cfg][course].append({'raceId':rid,'raceDate':o['raceDate'],'venue':o['venue'],'raceNo':o['raceNo'],'stakeYen':budget,'returnYen':ret,'tickets':[{'betType':t['betType'],'combo':t['combo'],'odds':round(t['odds'],4),'prob':round(t['prob'],8),'ev':round(t['ev'],6),'stakeYen':u*100} for t,u in zip(chosen,units)]})
        if idx%2000==0:print(json.dumps({'processed':idx,'errors':len(errors)},ensure_ascii=False),flush=True)
    if errors:raise RuntimeError(f'EVALUATION_ERRORS:{len(errors)}:{errors[:5]}')

    summary={'purpose':'research_only_runner_ml_market_fixed_config_screen','selectedRaces':14410,'historicalFinalOddsUsed':True,'prestartTimingValidationPerformed':False,'targetRaceResultUsedForPrediction':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False,'completionHardGate':{'allCoursesTop50ExcludedRoiPctAtLeast':200.0,'top50ExcludedRequired':True},'configs':{}}
    for cfg,mode,beta in CONFIGS:
        c={'mode':mode,'beta':beta,'courses':{},'byYear':{},'byPeriod':{}}
        for course,budget in COURSES.items():c['courses'][course]=robust(race_results[cfg][course],budget)
        years=sorted({r['raceDate'][:4] for r in race_results[cfg]['standard']})
        for y in years:
            c['byYear'][y]={course:robust([r for r in race_results[cfg][course] if r['raceDate'].startswith(y)],budget) for course,budget in COURSES.items()}
        periods={'2016-2018':('2016','2018'),'2019-2021':('2019','2021'),'2022-2024':('2022','2024'),'2025-2026':('2025','2026')}
        for name,(lo,hi) in periods.items():
            c['byPeriod'][name]={course:robust([r for r in race_results[cfg][course] if lo<=r['raceDate'][:4]<=hi],budget) for course,budget in COURSES.items()}
        c['passesCompletionHardGate']=all(c['courses'][course]['hardGateTop50AtLeast200'] for course in COURSES)
        summary['configs'][cfg]=c
    Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'selectedRaces':14410,'configs':{k:{c:v['courses'][c]['roiPct'] for c in COURSES}|{'top50':{c:v['courses'][c]['top50ExcludedRoiPct'] for c in COURSES},'pass':v['passesCompletionHardGate']} for k,v in summary['configs'].items()}},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
