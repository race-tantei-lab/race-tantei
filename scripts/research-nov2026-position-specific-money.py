#!/usr/bin/env python3
"""Genuinely NEW JRA six-market financial forecaster:

Train three independent chronological 56-feature LightGBM positional finish
models (first, second, third) on historical runner form, NOT just win odds.
Construct position-specific, conditional ordered joint finish distributions;
derive every market's EXACT payable-event probability, then multiply with an
independently trained actual-yen conditional payout forecast. Choose only via
actual monetary ROI; freeze out-of-time 2025H2 and 2026 Jan-Mar.

All 1,461,364 eligible ticket combinations independently generated, never old
model-selected candidates. Historical final win quote != official T-15
combination quote; third-party result mirror not JRA official-reconciled.
Research only, reject unless all robust200 gates hold.
"""
from __future__ import annotations
from collections import defaultdict
from itertools import product,permutations
from pathlib import Path
import json,math,sys,time,importlib.util
import numpy as np
from lightgbm import LGBMClassifier

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis-results/nov2026-position-specific-sixmarket-cash.json'
ANGLES=((0.,0.),(.25,.25),(.45,.75),(.7,1.),(1.,1.),(.35,1.),(.8,.5))
PAY_POWERS=(.7,1.)
SEED=20261108

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if spec is None or not spec.loader:raise RuntimeError('MISSING_RESEARCH_SOURCE')
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod

def paid_position_labels(archive,metadata,offsets):
    hist=load('scripts/postaug-support-chronological-56feature-validation.py',
              'positional_historic_replay')
    cal=hist.load_public_archive()
    days=hist.load_bundles(cal)
    result={}
    for date,rows in days.items():
        for b in rows:
            result[b['race']['raceId']]={
               int(z['horseNo']):z['finishPosition'] for z in b['results']}
    second=np.zeros(int(offsets[-1]),dtype=np.int8)
    third=np.zeros(int(offsets[-1]),dtype=np.int8)
    pos1=np.zeros(int(offsets[-1]),dtype=np.int8)
    for i,m in enumerate(metadata):
        b=result.get(m['raceId'])
        if b is None:raise RuntimeError('HISTORICAL_FINISH_ORDER_MISSING')
        a=int(offsets[i])
        for j,n in enumerate(m['horseNos']):
            pos=b.get(n)
            try:v=int(pos)
            except(TypeError,ValueError):v=-1
            pos1[a+j]=int(v==1)
            second[a+j]=int(v==2)
            third[a+j]=int(v==3)
    if pos1.sum()<30000 or second.sum()<30000 or third.sum()<30000:
        raise RuntimeError('THREE_FINISH_POSITIONS_LABEL_COVERAGE')
    return pos1,second,third

def position_forecasts(X,labels,metadata,offsets,train_through):
    year=np.asarray([int(x['date'][:4]) for x in metadata],dtype=np.int16)
    individual_year=np.repeat(year,np.diff(offsets))
    train=(individual_year>=2018)&(individual_year<=train_through)
    if int(train.sum())<100000:raise RuntimeError('NOT_ENOUGH_CHRONOLOGICAL_HORSE_TRAINING')
    forecasts=[]
    model_audits=[]
    for position,y in enumerate(labels,start=1):
        cfg=dict(objective='binary',n_estimators=240,
            learning_rate=.035,num_leaves=23,min_child_samples=145,
            reg_lambda=27.,reg_alpha=1.8,colsample_bytree=.82,
            random_state=SEED+position,n_jobs=2,verbosity=-1)
        model=LGBMClassifier(**cfg)
        model.fit(X[train],y[train])
        forecast=np.clip(model.predict_proba(X)[:,1],1e-7,1.)
        forecasts.append(forecast)
        model_audits.append({'position':position,
             'sample':int(train.sum()),'positive':int(y[train].sum())})
    return forecasts,{'trainingThrough':train_through,
        'positionTraining':model_audits}

def core_probability_matrices(win,second,third):
    if not (len(win)==len(second)==len(third)) or len(win)<6:
        raise RuntimeError('INVALID_JOINT_FINISH_FIELD')
    w=np.maximum(win,1e-9)/np.sum(win)
    s=np.maximum(second,1e-9)/np.sum(second)
    t=np.maximum(third,1e-9)/np.sum(third)
    n=len(w)
    pair=w[:,None]*s[None,:]/np.maximum(1.-s[:,None],1e-7)
    np.fill_diagonal(pair,0.)
    denominator=np.maximum(1.-t[:,None]-t[None,:],1e-7)
    triple=pair[:,:,None]*t[None,None,:]/denominator[:,:,None]
    j=np.arange(n)
    triple[j,:,:]=np.where(np.arange(n)[None,:,None]==j[:,None,None],0.,triple[j,:,:])
    # Explicitly exclude repeating an already selected horse in finish order.
    triple[j,j,:]=0.
    triple[j,:,j]=0.
    triple[:,j,j]=0.
    # Each finish position adds up to one over all valid permutations.
    if not .999<np.sum(triple)<1.001:
        raise RuntimeError('THREE_POSITION_PROBABILITY_NOT_NORMALIZED:'+str(np.sum(triple)))
    p12=triple.sum(axis=2)
    p13=triple.sum(axis=1)
    p23=triple.sum(axis=0)
    wide=p12+p12.T+p13+p13.T+p23+p23.T
    exact12=p12+p12.T
    return w,p12,exact12,triple,wide

def distribute_cash_events(races,ids,tickets,lookup,meta,offsets,forecasts,angles):
    # Derive exact six-market paid probabilities for all independently
    # enumerated combo tickets from three individual finish-ordinal predictors.
    out=np.zeros(len(ids),dtype=np.float32)
    joined=0;out_of_state=0
    aw,ap=angles
    for rid,r in enumerate(races):
        a=int(np.searchsorted(ids,rid,'left'))
        b=int(np.searchsorted(ids,rid,'right'))
        if b-a!=206:raise RuntimeError('SIX_MARKET_ENUMERATION_INCOMPLETE')
        nos=[h[0] for h in r['horses']]
        market=np.asarray([1./h[1] for h in r['horses']],dtype=np.float64)
        market/=market.sum()
        idx=lookup.get(r['id'])
        if idx is None:
            w=s=t=market
            out_of_state+=1
        else:
            joined+=1
            start=int(offsets[idx])
            hist_ids=meta[idx]['horseNos']
            orig={int(h):i for i,h in enumerate(hist_ids)}
            signals=[]
            for f in forecasts:
                src=f[start:start+len(hist_ids)]
                values=[src[orig[h]] if h in orig else 1./r['horses'][i][1]
                      for i,h in enumerate(nos)]
                vals=np.asarray(values,dtype=np.float64)
                signals.append(vals/vals.sum())
            w=np.maximum(market,1e-9)**(1.-aw)*np.maximum(signals[0],1e-9)**aw
            s=np.maximum(market,1e-9)**(1.-ap)*np.maximum(signals[1],1e-9)**ap
            t=np.maximum(market,1e-9)**(1.-ap)*np.maximum(signals[2],1e-9)**ap
        w,p12,pquin,p123,pwide=core_probability_matrices(w,s,t)
        ix={num:j for j,num in enumerate(nos)}
        for j in range(a,b):
            market_name,comb=tickets[j]
            c=[ix[k] for k in comb]
            if market_name=='単勝':p=w[c[0]]
            elif market_name=='ワイド':p=pwide[c[0],c[1]]
            elif market_name=='馬連':p=pquin[c[0],c[1]]
            elif market_name=='馬単':p=p12[c[0],c[1]]
            elif market_name=='3連複':
                p=sum(p123[u,v,z] for u,v,z in permutations(c))
            elif market_name=='3連単':
                p=p123[c[0],c[1],c[2]]
            else:raise RuntimeError('UNKNOWN_JRA_BET_TYPE')
            out[j]=p
    if joined<len(races)*.75:raise RuntimeError('NOT_ENOUGH_PRE_RESULT_RUNNER_FORM')
    return out,{'joined':joined,'fallbackMarketOnly':out_of_state}

def selftest():
    w=np.asarray([.5,.25,.13,.06,.04,.02])
    a,b,c,d,e=core_probability_matrices(w,w,w)
    assert abs(a.sum()-1)<1e-10
    assert abs(sum(d[i,j,k] for i in range(6) for j in range(6)
                   for k in range(6))-1)<1e-8
    assert abs(np.sum(np.triu(c,1))-1.)<1e-8
    assert .999<sum(e[i,j] for i in range(6) for j in range(i+1,6))/3.<1.001
    print('THREE_FINISHER_EXACT_SIX_JRA_MARKET_CASH_PROBABILITY_OK',flush=True)

def main():
    if '--self-test' in sys.argv:selftest();return
    started=time.monotonic();selftest()
    base=load('scripts/research-nov2026-sixmarket-real-paid-cash.py','pos_cash_source')
    form=load('scripts/research-nov2026-56feature-sixmarket-pl-money.py',
              'pos_cash_form')
    races,audit=base.read_pinned_csv()
    X,cash,ids,types,tickets,weights=base.build_actual_payout_rows(races)
    names=form.read_source_horse_names()
    horse_X,horse_win,offsets,meta,names_archive,dropped=form.historical_horse_features()
    lookup=form.join_pre_result_races_by_horse_identity(
        races,meta,names_archive,names)
    labels=paid_position_labels(horse_X,meta,offsets)
    amount2024,prov24=form.fit_paid_amount(X,cash,types,ids,races,2024)
    forecasts2024,position_train_2024=position_forecasts(
        horse_X,labels,meta,offsets,2024)
    score_bank={}
    probe=[]
    for angles in ANGLES:
        event,coverage=distribute_cash_events(
            races,ids,tickets,lookup,meta,offsets,forecasts2024,angles)
        probe.append({'angles':angles,'coverage':coverage})
        for power in PAY_POWERS:
            money_score=event*np.power(amount2024,power)
            score_bank[(angles,power)]=form.by_race_market_best(
                races,ids,types,cash,tickets,money_score)
    policy=None;count=0;eligible=0
    for (angles,power),pred in score_bank.items():
        for pair,overlap in product((-1,)+tuple(range(15)),(0.,.3)):
            rows,missing,days=form.settle(
                races,pred,('202501','202507'),pair,overlap)
            metrics=form.accounting(rows,missing,days)
            count+=1
            if metrics['races']<500 or metrics['paidRacePct']<20 or missing:continue
            eligible+=1
            rank=(int(metrics['numericallyPass200']),
                 metrics['roiNoLargestRacePct'],metrics['roiPct'])
            if policy is None or rank>policy[0]:
                policy=(rank,angles,power,pair,overlap,metrics)
    if policy is None:raise RuntimeError('NO_ELIGIBLE_FINANCIAL_POLICY')
    _,angles,power,pair,overlap,h1=policy
    print('THREE_POSITION_FINANCIAL_2025H1',json.dumps({
      'selected':{'angles':angles,'payoutExponent':power,
                  'pairIndex':pair,'overlapPenalty':overlap},
      '2025H1':h1,'tested':count,'eligible':eligible},
      ensure_ascii=False),flush=True)
    rows,missing,days=form.settle(
        races,score_bank[(angles,power)],('202507','202601'),pair,overlap)
    h2=form.accounting(rows,missing,days)
    print('THREE_POSITION_FINANCIAL_2025H2',json.dumps(h2,ensure_ascii=False),flush=True)
    forecasts2025,position_train_2025=position_forecasts(
        horse_X,labels,meta,offsets,2025)
    amount2025,prov25=form.fit_paid_amount(X,cash,types,ids,races,2025)
    event26,coverage26=distribute_cash_events(
        races,ids,tickets,lookup,meta,offsets,forecasts2025,angles)
    score26=event26*np.power(amount2025,power)
    bets26=form.by_race_market_best(races,ids,types,cash,tickets,score26)
    rows,missing,days=form.settle(races,bets26,
                                  ('202601','202604'),pair,overlap)
    h26=form.accounting(rows,missing,days)
    print('THREE_POSITION_FINANCIAL_2026',json.dumps(h26,ensure_ascii=False),flush=True)
    result={
      'financialPrediction':'three distinct first/second/third position models, sequential finish probabilities for six markets, actual paid amount learner',
      'thirdPartyPayoutMirrorNotReconciledOfficial':True,
      'historicalPricesAreFinalWinNotT15Combination':True,
      'oldModelSelectedTicketUniverseUsed':False,
      'independentlyGeneratedTickets':len(cash),
      '2024PositionalTraining':position_train_2024,
      '2024CashPayoutTraining':prov24,
      'selectedBy2025H1':{'angles':angles,'payoutExponent':power,
          'pairIndex':pair,'overlapPenalty':overlap},
      '2025H1':h1,'2025H2':h2,
      '2025RefittedPosition':position_train_2025,
      '2025RefittedPayout':prov25,
      '2026':h26,
      '2025H1SearchCount':count,'eligible':eligible,
      'passedRobust200BothHoldouts':bool(
            h2['numericallyPass200'] and h26['numericallyPass200']),
      'researchOnly':True,'productionDeployed':False,
      'runtimeSeconds':round(time.monotonic()-started,2)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('THREE_POSITION_REAL_MONEY_RESULT_WRITTEN',OUT,flush=True)

if __name__=='__main__':main()
