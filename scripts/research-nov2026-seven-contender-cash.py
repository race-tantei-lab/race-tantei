#!/usr/bin/env python3
"""Unseen-before-purchase seven-contender multi-market financial forecaster.

Change core predicted outcome, NOT just bet thresholds: widen from top six
to SEVEN priced contenders and directly learn the true yen payout distribution
over all six market combinations using both uncapped Tweedie and a distinct
paid-event + conditional-pay model. Select only by cash ROI on 2025H1, freeze
and test 2025H2 and 2026; no past race-tantei preselected bets.
This research archive has FINAL win quotes not verified official T-15 prices.
"""
from __future__ import annotations
from collections import defaultdict
from itertools import combinations,product
from pathlib import Path
import importlib.util,json,sys,time,math
import numpy as np
from lightgbm import LGBMRegressor,LGBMClassifier

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis-results/nov2026-expanded-seven-market-cash.json'
MARKETS=('単勝','ワイド','馬連','馬単','3連複','3連単')
PAIRS=tuple(combinations(range(6),2))
SEED=20261108
N_PER=7+21+21+42+35+210

def module(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError('SOURCE_FILE_MISSING')
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m
    spec.loader.exec_module(m)
    return m

def load():
    base=module('scripts/research-nov2026-sixmarket-real-paid-cash.py','expanded_candidate_jra_cash')
    base.TOP_HORSES=7
    races,audit=base.read_pinned_csv()
    X,y,ids,types,tickets,weights=base.build_actual_payout_rows(races)
    assert len(tickets)==len(y)==len(ids)==len(types)
    if len(y)!=len(races)*N_PER:
        raise RuntimeError('NOT_SEVEN_RUNNERS_ALL_SIX_MARKET_ENUMERATION')
    return races,X,y,ids,types,tickets,weights,audit

def fit_financial(X,y,ids,types,weights,races,cutoff):
    years=np.asarray([int(races[int(i)]['month'][:4]) for i in ids],dtype=np.int16)
    train=(years>=2024)&(years<=cutoff)
    paid=train&(y>0)
    if int(paid.sum())<10000:raise RuntimeError('NOT_ENOUGH_OBSERVED_CASH_PAYOUTS')
    x=X[train]
    z=y[train].astype(np.float64)/100.
    wt=weights[train]
    opts=dict(n_estimators=160,num_leaves=15,learning_rate=.038,
       min_child_samples=220,colsample_bytree=.8,reg_alpha=2.,
       reg_lambda=24.,random_state=SEED,n_jobs=2,verbosity=-1)
    gross=LGBMRegressor(objective='tweedie',tweedie_variance_power=1.35,**opts)
    cap=LGBMRegressor(objective='tweedie',tweedie_variance_power=1.35,**opts)
    event=LGBMClassifier(objective='binary',**opts)
    positive=LGBMRegressor(objective='huber',alpha=.85,
       **{**opts,'n_estimators':130,'min_child_samples':55})
    cap_by_type=np.asarray([np.quantile((y[paid&(types==m)]/100.),.98)
                  for m in range(6)],dtype=np.float64)
    gross.fit(x,z,sample_weight=wt)
    cap.fit(x,np.minimum(z,cap_by_type[types[train]]),sample_weight=wt)
    event.fit(x,(z>0).astype(np.int8),sample_weight=wt)
    positive.fit(X[paid],np.log(y[paid]/100.),
                 sample_weight=weights[paid])
    # Forecast ONLY future years, never evaluate the in-sample trend.
    future=(years>cutoff)
    target_x=X[future]
    if not len(target_x):raise RuntimeError('MISSING_FORWARD_FINANCIAL_TEST')
    direct=np.clip(gross.predict(target_x),1e-6,10000.)
    tail=np.clip(cap.predict(target_x),1e-6,10000.)
    prob=np.clip(event.predict_proba(target_x)[:,1],1e-9,1.)
    logpaid=positive.predict(target_x)
    ratios=(y[paid]/100.)/np.maximum(np.exp(positive.predict(X[paid])),1e-4)
    smears=np.asarray([
        float(np.clip(np.mean(np.minimum(ratios[types[paid]==m],8.)),1.,5.))
        for m in range(6)],dtype=np.float64)
    hurdle=np.clip(prob*np.exp(logpaid)*smears[types[future]],1e-6,10000.)
    out={key:np.zeros(len(y),dtype=np.float32)
         for key in ('direct','tail','hurdle','balanced','upside')}
    for k,p in {
        'direct':direct,'tail':tail,'hurdle':hurdle,
        'balanced':.5*tail+.5*hurdle,
        'upside':.6*direct+.4*hurdle}.items():out[k][future]=p.astype(np.float32)
    return out,{'yearsUpTo':cutoff,'trainingTickets':int(train.sum()),
        'paidTickets':int(paid.sum()),
        'trainOnlyPayoutCaps':dict(zip(MARKETS,cap_by_type.tolist())),
        'trainOnlyHurdleSmear':dict(zip(MARKETS,smears.tolist()))}

def rank(scores,variant):
    head,power,risk=variant
    r=np.maximum(scores[head].astype(np.float64),1e-8)
    v=np.power(r,power)/(1.+risk*np.log1p(r))
    return v.astype(np.float32)

def each_market(races,ids,types,tickets,y,forecast,period):
    by_race={}
    for rid,r in enumerate(races):
        if not period[0]<=r['month']<period[1]:continue
        a=int(np.searchsorted(ids,rid,'left'));b=int(np.searchsorted(ids,rid,'right'))
        if b-a!=N_PER:raise RuntimeError('BAD_RACE_CANDIDATE_ENUMERATION')
        opts=[]
        for m in range(6):
            candidates=np.flatnonzero(types[a:b]==m)
            j=a+int(candidates[np.argmax(forecast[a:b][candidates])])
            opts.append((float(forecast[j]),int(y[j]),tuple(tickets[j][1])))
        by_race[rid]=opts
    return by_race

def choose(opts,pair,overlap):
    pairs=PAIRS if pair<0 else (PAIRS[pair],)
    best=None
    for a,b in pairs:
        qa,qb=opts[a],opts[b]
        score=(qa[0]+qb[0])*(1.-overlap*len(set(qa[2]).intersection(qb[2]))/3.)
        c=(score,-a,-b,a,b,qa[1],qb[1])
        if best is None or c[:3]>best[:3]:best=c
    return best

def settle(races,betset,pair,overlap):
    day=defaultdict(list)
    for rid,opts in betset.items():
        q,_,__,a,b,p1,p2=choose(opts,pair,overlap)
        r=races[rid]
        day[r['day']].append((q,r['id'],r['month'],a,b,p1,p2))
    rows=[];missing=0
    for d,choices in day.items():
        if len(choices)<5:missing+=1;continue
        choices.sort(key=lambda x:(-x[0],x[1]))
        rows.extend(choices[:5])
    return rows,missing,len(day)

def audit(rows,missing,days):
    stake=len(rows)*2000
    pays=[(r[5]+r[6])*10 for r in rows]
    ret=sum(pays)
    large=max((p*10 for r in rows for p in (r[5],r[6])),default=0)
    large_race=max(pays,default=0)
    hit=sum(p>0 for p in pays)
    p=lambda val,den:round(100*val/den,5) if den else None
    stats=defaultdict(lambda:[0,0,0])
    for rec,val in zip(rows,pays):
        a=stats[rec[2]];a[0]+=1;a[1]+=val;a[2]+=int(val>0)
    return {'races':len(rows),'stakeYen':stake,'paidYen':ret,
        'profitYen':ret-stake,'roiPct':p(ret,stake),
        'trimLargestTicketRoiPct':p(ret-large,stake),
        'trimLargestRaceRoiPct':p(ret-large_race,stake),
        'hitRacePct':p(hit,len(rows)),
        'venueDays':days,'incompleteVenueDays':missing,
        'byMonth':{k:{'races':s[0],'roiPct':p(s[1],s[0]*2000),
              'hitRacePct':p(s[2],s[0])} for k,s in sorted(stats.items())},
        'passesRobust200':bool(stake and len(rows)>=100 and missing==0
          and hit/len(rows)>=.2 and ret>=2*stake and ret-large>=2*stake
          and ret-large_race>=2*stake)}

def main():
    if '--self-test' in sys.argv:
        assert len(PAIRS)==15 and N_PER==336
        assert audit([(1.,'x','202501',0,1,200,200)]*5,0,1)['roiPct']==200.
        print('SEVEN_CONTENDERS_SIX_MARKET_CASH_TEST_OK',flush=True);return
    started=time.monotonic()
    races,X,y,ids,types,tickets,weights,a=load()
    print('SEVEN_RUNNERS_NEW_FINANCIAL_UNIVERSE',json.dumps({
        'races':len(races),'independentBetChoices':len(y),
        'paidChoices':int((y>0).sum()),
        'topPricedHorses':7,'sixMarkets':True},ensure_ascii=False),flush=True)
    scores,train24=fit_financial(X,y,ids,types,weights,races,2024)
    h1=('202501','202507');h2=('202507','202601')
    best=None;tested=0;eligible=0
    for variant in product(
          ('direct','tail','hurdle','balanced','upside'),
          (.7,1.,1.3),(0.,.2)):
        pred=rank(scores,variant)
        b_h1=each_market(races,ids,types,tickets,y,pred,h1)
        for pair,overlap in product((-1,)+tuple(range(15)),(0.,.3)):
            rows,miss,days=settle(races,b_h1,pair,overlap)
            m=audit(rows,miss,days);tested+=1
            if m['races']<500 or m['hitRacePct']<20 or miss:continue
            eligible+=1
            key=(int(m['passesRobust200']),m['trimLargestRaceRoiPct'],m['roiPct'])
            if best is None or key>best[0]:best=(key,variant,pair,overlap,m)
    if not best:raise RuntimeError('NO_H1_200_SEARCH_POLICY_VALID')
    _,variant,pair,overlap,h1val=best
    print('SEVEN_RUNNERS_2025H1_SELECT',json.dumps({
         'chosenForecast':variant,'pair':pair,'overlap':overlap,
         'policiesTried':tested,'eligible':eligible,
         'money':h1val},ensure_ascii=False),flush=True)
    pred=rank(scores,variant)
    b_h2=each_market(races,ids,types,tickets,y,pred,h2)
    rows,miss,days=settle(races,b_h2,pair,overlap)
    h2val=audit(rows,miss,days)
    print('SEVEN_RUNNERS_2025H2_MONEY',json.dumps(h2val,ensure_ascii=False),flush=True)
    scores26,train25=fit_financial(X,y,ids,types,weights,races,2025)
    pred=rank(scores26,variant)
    b26=each_market(races,ids,types,tickets,y,pred,('202601','202604'))
    rows,miss,days=settle(races,b26,pair,overlap)
    v26=audit(rows,miss,days)
    print('SEVEN_RUNNERS_2026_MONEY',json.dumps(v26,ensure_ascii=False),flush=True)
    output={'newPrediction':'seven contenders x six ticket markets; direct yen Tweedie, 98th capped money, money event x paid yen model, blended cash models',
        'sourceRaces':len(races),'independentTickets':len(y),
        'training2024':train24,'selected2025H1':{
          'variant':variant,'pair':pair,'overlap':overlap,'metrics':h1val},
        'searched':tested,'validWithHit20':eligible,
        'holdout2025H2':h2val,'training2025Refit':train25,
        'test2026JanMar':v26,'passedRobust200BothHoldouts':bool(
           h2val['passesRobust200'] and v26['passesRobust200']),
        'thirdPartyPayoutNotOfficialReconciled':True,
        'finalWinOddsNotT15OfficialCombinationQuotes':True,
        '2026PreviouslyInspected':True,
        'productionDeployment':False,'adopted':False,
        'seconds':round(time.monotonic()-started,2)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('SEVEN_RUNNERS_FINANCIAL_RESULT_WRITTEN',str(OUT),flush=True)

if __name__=='__main__':main()
