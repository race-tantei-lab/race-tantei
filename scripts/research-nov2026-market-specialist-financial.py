#!/usr/bin/env python3
"""Six market-specific monetary prediction engines (NOT odds-picking rules).

Fit independently generated historical JRA-ticket outcomes with a different
actual-yen return model for each of the SIX distinct market types, in addition
to separate event / conditional paid-yen models. Optimize only robust cash ROI
using 2025H1; freeze ticket policy and validate 2025H2, then 2026 Jan-Mar after
refitting models on 2024+2025. Exactly two distinct market types, 5 races/day/
venue, unchanged ¥2000 per race. Pre-race 56-feature historical form for each
candidate; no previously-selected tickets. Third-party JRA payout mirror and
final win odds are NOT fully authenticated official T-15 quotes.
Never deploy this research directly to production.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass,asdict
from itertools import combinations,product
from pathlib import Path
import importlib.util,json,math,os,time,sys
import numpy as np
from lightgbm import LGBMRegressor,LGBMClassifier

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis-results/nov2026-independent-market-specialists-cash.json'
PAIRS=tuple(combinations(range(6),2))
MARKETS=('単勝','ワイド','馬連','馬単','3連複','3連単')
SEED=20261108

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError('DEPENDENCY_NOT_FOUND:'+path)
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj

def training_data():
    source=load('scripts/research-nov2026-sixmarket-real-paid-cash.py','market_specialist_payout')
    form=load('scripts/research-nov2026-56feature-sixmarket-pl-money.py','market_specialist_form')
    feat=load('scripts/research-nov2026-form-aware-sixmarket-cash.py','market_specialist_features')
    races,audit=source.read_pinned_csv()
    X,y,ids,markets,tickets,_=source.build_actual_payout_rows(races)
    source_names=form.read_source_horse_names()
    hx,labels,offsets,meta,names,missing=form.historical_horse_features()
    idx=form.join_pre_result_races_by_horse_identity(races,meta,names,source_names)
    full=feat.enrich_with_chronological_runner_forms(races,X,ids,tickets,meta,offsets,idx,hx)
    return races,full,y,ids,markets,tickets,audit

def specialists(X,y,ids,types,races,cutoff):
    years=np.asarray([int(races[int(i)]['month'][:4]) for i in ids],dtype=np.int16)
    train=(years>=2024)&(years<=cutoff)
    predictions={key:np.zeros(len(y),dtype=np.float32)
       for key in ('direct','trimmed','hurdle','conservative','upside')}
    aud=[]
    for m in range(6):
        train_m=train&(types==m)
        all_m=(types==m)
        good=train_m&(y>0)
        if train_m.sum()<1000 or good.sum()<150:
            raise RuntimeError('NO_MARKET_MONEY_TRAIN_DATA_'+MARKETS[m])
        yy=y[train_m].astype(np.float64)/100.
        cap=float(np.quantile(y[good]/100.,.975))
        base=dict(n_estimators=180,num_leaves=15,learning_rate=.035,
              min_child_samples=85,reg_lambda=24.,reg_alpha=2.,
              colsample_bytree=.82,random_state=SEED,n_jobs=2,verbosity=-1)
        direct=LGBMRegressor(objective='tweedie',tweedie_variance_power=1.35,**base)
        capped=LGBMRegressor(objective='tweedie',tweedie_variance_power=1.35,**base)
        classifier=LGBMClassifier(objective='binary',**base)
        positive=LGBMRegressor(objective='huber',alpha=.8,
              **{**base,'min_child_samples':45,'n_estimators':130})
        direct.fit(X[train_m],yy)
        capped.fit(X[train_m],np.minimum(yy,cap))
        classifier.fit(X[train_m],(yy>0).astype(np.int8))
        positive.fit(X[good],np.log(y[good].astype(np.float64)/100.))
        raw=np.clip(direct.predict(X[all_m]),1e-7,10000.)
        trim=np.clip(capped.predict(X[all_m]),1e-7,10000.)
        p=np.clip(classifier.predict_proba(X[all_m])[:,1],1e-8,1)
        amount=np.exp(positive.predict(X[all_m]))
        # Use TRAIN-ONLY estimated payout dispersion to counter truncation.
        ratios=(y[good]/100.)/np.exp(positive.predict(X[good]))
        smear=float(np.clip(np.mean(np.minimum(ratios,8)),1.,5.))
        pay=np.clip(p*amount*smear,1e-7,10000.)
        predictions['direct'][all_m]=raw
        predictions['trimmed'][all_m]=trim
        predictions['hurdle'][all_m]=pay
        predictions['conservative'][all_m]=np.minimum(raw,pay)
        predictions['upside'][all_m]=.7*raw+.3*pay
        aud.append({'market':MARKETS[m],'trainTickets':int(train_m.sum()),
                    'paidTickets':int(good.sum()),'trainingPayCap':cap,
                    'conditionalSmear':smear})
    return predictions,aud

def variants():
    return list(product(
        ('direct','trimmed','hurdle','conservative','upside'),
        (.65,1.,1.35),
        (0.,.15,.4)))

def candidate_rank(values,variantspec):
    mode,temperature,tail=variantspec
    arr=values[mode].astype(np.float64)
    # These are financial yield forecasts, not horse probabilities.
    # Temperature is market-specific convex/concave money response.
    result=np.power(np.maximum(arr,1e-7),temperature)
    if tail:result/=1+tail*np.maximum(0,np.log1p(arr/10.))
    return result.astype(np.float32)

def per_race_best(races,ids,types,tickets,y,values):
    out=[]
    for rid in range(len(races)):
        a=int(np.searchsorted(ids,rid,'left'))
        b=int(np.searchsorted(ids,rid,'right'))
        ss=values[a:b]
        tt=types[a:b]
        picks=[]
        for m in range(6):
            local=np.flatnonzero(tt==m)
            if not len(local):raise RuntimeError('MISSING_ALL_SIX_MARKETS')
            j=a+int(local[np.argmax(ss[local])])
            picks.append((float(values[j]),int(y[j]),tuple(tickets[j][1])))
        out.append(picks)
    return out

def choose(pair_market,pair_id,overlap):
    pairs=PAIRS if pair_id<0 else (PAIRS[pair_id],)
    best=None
    for a,b in pairs:
        x,z=pair_market[a],pair_market[b]
        shared=len(set(x[2]).intersection(z[2]))
        expected=(x[0]+z[0])*(1-overlap*shared/3.)
        choice=(expected,-a,-b,a,b,x[1],z[1])
        if best is None or choice[:3]>best[:3]:best=choice
    return best

def settle(races,best,period,pair,overlap):
    days=defaultdict(list)
    for i,r in enumerate(races):
        if not period[0]<=r['month']<period[1]:continue
        rate,_,__,m1,m2,paid1,paid2=choose(best[i],pair,overlap)
        days[r['day']].append((rate,r['id'],r['month'],m1,m2,paid1,paid2))
    rows=[];incomplete=0
    for rs in days.values():
        if len(rs)<5:incomplete+=1;continue
        rs.sort(key=lambda t:(-t[0],t[1]))
        rows.extend(rs[:5])
    return rows,incomplete,len(days)

def audit(rows,missing,days):
    paid=np.asarray([(r[5]+r[6])*10 for r in rows],dtype=np.float64)
    n=len(rows);stake=n*2000
    gross=float(paid.sum())
    largest_ticket=float(max((p*10 for r in rows for p in (r[5],r[6])),default=0))
    largest_race=float(max(paid,default=0))
    hit=sum(p>0 for p in paid)
    def pct(a,d):return round(100*a/d,5) if d else None
    by_month=defaultdict(lambda:[0,0,0])
    for r,amount in zip(rows,paid):
        stat=by_month[r[2]]
        stat[0]+=1;stat[1]+=amount;stat[2]+=int(amount>0)
    return {'races':n,'stakeYen':stake,'payoutYen':int(gross),
      'profitYen':int(gross-stake),'roiPct':pct(gross,stake),
      'trimLargestTicketRoiPct':pct(gross-largest_ticket,stake),
      'trimLargestRaceRoiPct':pct(gross-largest_race,stake),
      'hitRacePct':pct(hit,n),'incompleteVenueDays':missing,
      'totalVenueDays':days,
      'byMonth':{k:{'races':v[0],'roiPct':pct(v[1],v[0]*2000),
        'hitRacePct':pct(v[2],v[0])} for k,v in sorted(by_month.items())},
      'robust200Pass':bool(n>=100 and missing==0 and hit/n>=.2
        and gross>=2*stake and gross-largest_ticket>=2*stake and
        gross-largest_race>=2*stake)}

def main():
    if '--self-test' in sys.argv:
        assert len(PAIRS)==15
        rows=[(0,'r','202501',0,1,250,0)]*5
        assert audit(rows,0,1)['roiPct']==125.
        print('SIX_JRA_MARKET_DIRECT_FINANCIAL_MODEL_SELFTEST_OK')
        return
    if any(os.getenv(x) for x in ('CLOUDFLARE_API_TOKEN','CLOUDFLARE_D1_DATABASE_ID')):
        raise RuntimeError('NO_LIVE_PRODUCTION_SECRETS_ALLOWED')
    begin=time.monotonic()
    races,X,y,ids,types,tickets,source_audit=training_data()
    print('MARKET_SPECIALIST_CANDIDATE_UNIVERSE',json.dumps(
       {'races':len(races),'independentTickets':len(y),'paidTickets':int(np.sum(y>0)),
        'sixMarkets':list(MARKETS)},ensure_ascii=False),flush=True)
    preds24,fit24=specialists(X,y,ids,types,races,2024)
    eligible=0;searched=0;selected=None
    for variant in variants():
        predicted=candidate_rank(preds24,variant)
        candidates=per_race_best(races,ids,types,tickets,y,predicted)
        for pair,overlap in product((-1,)+tuple(range(15)),(0.,.35)):
            records,bad,days=settle(races,candidates,('202501','202507'),pair,overlap)
            m=audit(records,bad,days)
            searched+=1
            if m['races']<500 or m['hitRacePct']<20 or bad:continue
            eligible+=1
            key=(int(m['robust200Pass']),m['trimLargestRaceRoiPct'],m['roiPct'])
            if selected is None or key>selected[0]:
                selected=(key,variant,pair,overlap,m)
    if selected is None:raise RuntimeError('NO_VALID_FIVE_RACE_TWO_MARKET_CASH_MODEL')
    _,variant,pair,overlap,h1=selected
    print('MARKET_SPECIALIST_2025H1_SELECTED',json.dumps(
       {'selectedModel':variant,'pair':pair,'overlap':overlap,
        'evaluated':searched,'eligible':eligible,'money':h1},ensure_ascii=False),flush=True)
    candidates=per_race_best(races,ids,types,tickets,y,candidate_rank(preds24,variant))
    records,bad,days=settle(races,candidates,('202507','202601'),pair,overlap)
    h2=audit(records,bad,days)
    print('MARKET_SPECIALIST_2025H2_FROZEN',json.dumps(h2,ensure_ascii=False),flush=True)
    preds25,fit25=specialists(X,y,ids,types,races,2025)
    candidates=per_race_best(races,ids,types,tickets,y,candidate_rank(preds25,variant))
    records,bad,days=settle(races,candidates,('202601','202604'),pair,overlap)
    yy26=audit(records,bad,days)
    print('MARKET_SPECIALIST_2026_FROZEN',json.dumps(yy26,ensure_ascii=False),flush=True)
    report={'financialPredictionAlgorithm':'six independent market-specific direct Tweedie cash-returns, six event/conditional cash heads, train-only market-specific payout-tail bias correction',
       'sourceAudit':source_audit,'marketTraining2024':fit24,
       'evaluatedCandidateModels':searched,'eligibleWith20PctHitAndCoverage':eligible,
       'chosenFinancialPrediction':variant,'pair':pair,'overlap':overlap,
       '2025H1Selection':h1,'2025H2Holdout':h2,
       'marketRefit2024And2025':fit25,'2026JanMarHoldout':yy26,
       'bothHoldoutsRobust200':bool(h2['robust200Pass'] and yy26['robust200Pass']),
       'historicalSourceThirdPartyNotOfficialAudited':True,
       'finalWinOddsNotT15OfficialCombinationQuotes':True,
       '2026AlreadyInspectedInPreviousExperiments':True,
       'noProductionWrites':True,'promoteToProduction':False,
       'seconds':round(time.monotonic()-begin,2)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('MARKET_SPECIALIST_PAID_MONEY_RESEARCH_RESULT',str(OUT),flush=True)

if __name__=='__main__':main()
