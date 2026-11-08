#!/usr/bin/env python3
"""Research-only NEW two-stage model predicting independent paid yen per bet.
2024 train; 2025 H1 select return policy; 2025 H2 validate; 2024-25
refit; 2026 Jan-Mar evaluate. No historical race-tantei picks, no D1 or live.
Final single-win quotes are NOT official T-15 combination odds and cannot
substitute them in production. Actual payout source is a third-party mirror.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from dataclasses import asdict,dataclass
from itertools import combinations,product
import importlib.util,json,sys,time
from pathlib import Path
import numpy as np
from lightgbm import LGBMClassifier,LGBMRegressor

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'scripts/research-nov2026-sixmarket-real-paid-cash.py'
OUT=ROOT/'analysis-results/nov2026-independent-sixmarket-hurdle-money.json'
MARKETS=('単勝','ワイド','馬連','馬単','3連複','3連単')
PAIRS=tuple(combinations(range(6),2))
BUDGET_PER_RACE=2000
FIVE_PER_DAY=5
SEED=20261108

@dataclass(frozen=True)
class Policy:
    cash_mode:str
    risk:float
    probability_exponent:float
    overlap_penalty:float
    pair:str

def base_module():
    spec=importlib.util.spec_from_file_location('sixmarket_paid_source',BASE)
    if not spec or not spec.loader:raise RuntimeError('MISSING_PINNED_SIX_MARKET_SOURCE')
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod

def fit_hurdle(X,y,market,years,train_years):
    train=np.isin(years,train_years)
    positive=train & (y>0)
    if positive.sum()<2000:raise RuntimeError('INSUFFICIENT_PAID_TICKETS')
    common=dict(n_estimators=100,learning_rate=.045,num_leaves=15,
                min_child_samples=200,reg_alpha=2.,reg_lambda=50.,
                colsample_bytree=.85,random_state=SEED,n_jobs=2,verbosity=-1)
    event=LGBMClassifier(objective='binary',**common)
    event.fit(X[train],(y[train]>0).astype('int8'))
    amount=LGBMRegressor(objective='regression',
          **{**common,'min_child_samples':55,'reg_lambda':30.})
    caps=[]
    for m in range(6):
        vals=y[positive & (market==m)]
        if len(vals)<50:raise RuntimeError('INSUFFICIENT_MARKET_PAID_EVENTS:'+MARKETS[m])
        caps.append(float(np.quantile(vals,.975)))
    capped=np.minimum(y[positive].astype('float64'),
                      np.asarray(caps)[market[positive]])
    amount.fit(X[positive],np.log(capped))
    p=np.clip(event.predict_proba(X)[:,1],1e-8,1.-1e-8)
    cond=np.clip(np.exp(amount.predict(X)),100.,1e7)
    # Compensation for asymmetric payout tails, fitted ONLY on training years.
    smear=[];prior=[]
    for m in range(6):
        hit=positive & (market==m)
        ratio=np.mean(np.minimum(y[hit]/np.maximum(cond[hit],100.),5.))
        smear.append(float(np.clip(ratio,1.,2.5)))
        prior.append(float(np.mean(y[train & (market==m)])))
    gross=p*cond*np.asarray(smear)[market]
    return {'p':p.astype('float32'),'conditional':cond.astype('float32'),
            'cash':gross.astype('float32'),
            'shrunken_cash':(.85*gross+.15*np.asarray(prior)[market]).astype('float32'),
            'audit':{'trainYears':list(train_years),'tickets':int(train.sum()),
                'paidTickets':int(positive.sum()),
                'smear':dict(zip(MARKETS,smear)),'cap975':dict(zip(MARKETS,caps))}}

def variants():
    return list(product(('cash','shrunken_cash'),(0.,.3,.6),(0.,.25)))

def best_each_market(races,ids,y,tickets,market,forecast,variant):
    name,risk,power=variant
    p=forecast['p']
    # Only an internal proxy of cash returns, NOT a real quotation for a bet.
    score=(forecast[name]*np.power(np.maximum(p,1e-8),power)/
           (1.+risk*np.log1p(forecast['conditional']/1000.)))
    result=[]
    for rid,r in enumerate(races):
        a=int(np.searchsorted(ids,rid,'left'))
        b=int(np.searchsorted(ids,rid,'right'))
        local=score[a:b]
        local_types=market[a:b]
        picks=[]
        for m in range(6):
            possible=np.flatnonzero(local_types==m)
            if not len(possible):raise ValueError('SIX_MARKETS_NOT_ENUMERATED')
            i=int(possible[np.argmax(local[possible])])+a
            picks.append((float(score[i]),int(y[i]),tuple(tickets[i][1])))
        result.append(picks)
    return result

def best_pair(six,penalty,pair):
    options=PAIRS if pair=='any' else (PAIRS[int(pair)],)
    best=None
    for a,b in options:
        s1,y1,h1=six[a];s2,y2,h2=six[b]
        shared=len(set(h1).intersection(h2))
        rank=(s1+s2)*(1.-penalty*shared/3.)
        cand=(rank,-a,-b,a,b,y1,y2)
        if best is None or cand[:3]>best[:3]:best=cand
    return best

def select(races,by_race,policy,start,end):
    day=defaultdict(list)
    for i,r in enumerate(races):
        if not start<=r['month']<end:continue
        val,_,__,a,b,paid_a,paid_b=best_pair(by_race[i],
                  policy.overlap_penalty,policy.pair)
        day[r['day']].append((val,r['id'],r['month'],r['venue'],a,b,paid_a,paid_b))
    rows=[];incomplete=[]
    for k,items in sorted(day.items()):
        if len(items)<FIVE_PER_DAY:
            incomplete.append({'venueDay':k,'racesAvailable':len(items)})
            continue
        items.sort(key=lambda t:(-t[0],t[1]))
        rows.extend(items[:FIVE_PER_DAY])
    return rows,incomplete,len(day)

def accounting(rows,incomplete,days):
    races=len(rows)
    stake=races*BUDGET_PER_RACE
    returns=[(r[6]+r[7])*10 for r in rows]
    payouts=sum(returns)
    max_ticket=max((p*10 for r in rows for p in (r[6],r[7])),default=0)
    max_race=max(returns,default=0)
    hits=sum(x>0 for x in returns)
    months=defaultdict(lambda:[0,0,0])
    markets=defaultdict(lambda:[0,0])
    for r,pay in zip(rows,returns):
        mon=months[r[2]];mon[0]+=1;mon[1]+=pay;mon[2]+=int(pay>0)
        for m,v in ((r[4],r[6]),(r[5],r[7])):
            mt=markets[MARKETS[m]];mt[0]+=1;mt[1]+=v*10
    def pct(n,d):return round(100*n/d,5) if d else None
    return {'races':races,'venueDaysWithFiveRaces':races//5,
        'venueDaysInSource':days,'incompleteVenueDayCount':len(incomplete),
        'incompleteVenueDayExamples':incomplete[:10],
        'stakeYen':stake,'payoutYen':payouts,'profitYen':payouts-stake,
        'roiPct':pct(payouts,stake),
        'trimLargestTicketRoiPct':pct(payouts-max_ticket,stake),
        'trimLargestRaceRoiPct':pct(payouts-max_race,stake),
        'hitRacePct':pct(hits,races),
        'byMonth':{k:{'races':v[0],'roiPct':pct(v[1],v[0]*2000),
                      'hitRacePct':pct(v[2],v[0])} for k,v in sorted(months.items())},
        'byMarket':{k:{'tickets':v[0],'roiPct':pct(v[1],v[0]*1000)}
                    for k,v in sorted(markets.items())},
        'passesNumeric400Only':bool(races>=100 and hits/races>=.20 and
             payouts>=4*stake and payouts-max_ticket>=4*stake and
             payouts-max_race>=4*stake)}

def policies():
    for v,overlap,pair in product(variants(),(0.,.3),
                                   ('any',)+tuple(str(i) for i in range(15))):
        yield Policy(*v,overlap,pair)

def selftest():
    fake=[{'id':str(i),'month':'202501','day':'D1','venue':'01'} for i in range(6)]
    six=[(1.,100,(1,)),(2.,0,(1,2)),(1.,0,(1,2)),(1.,0,(1,2)),
         (1.,0,(1,2,3)),(1.,0,(1,2,3))]
    assert len(PAIRS)==15
    p=Policy('cash',0.,0.,0.,'any')
    rows,bad,days=select(fake,[six]*6,p,'202501','202502')
    report=accounting(rows,bad,days)
    assert report['races']==5 and report['stakeYen']==10000
    assert report['payoutYen']==5000 and report['roiPct']==50
    assert report['trimLargestTicketRoiPct']==40
    assert report['venueDaysWithFiveRaces']==1
    print('INDEPENDENT_HURDLE_SIXMARKET_CASH_SELFTEST_OK',flush=True)

def main():
    if '--self-test' in sys.argv:selftest();return
    t=time.monotonic()
    base=base_module()
    races,audit=base.read_pinned_csv()
    X,y,ids,markets,tickets,_=base.build_actual_payout_rows(races)
    years=np.asarray([int(races[i]['month'][:4]) for i in ids],dtype='int16')
    print('HURDLE_SOURCE',json.dumps({'raceCount':len(races),
          'candidateTickets':len(y),'positiveTickets':int((y>0).sum()),
          'audit':audit},ensure_ascii=False),flush=True)
    f25=fit_hurdle(X,y,markets,years,(2024,))
    chosen=None;tested=0;eligible=0
    for v in variants():
        by_race=best_each_market(races,ids,y,tickets,markets,f25,v)
        for overlap in (0.,.3):
            for pair in ('any',)+tuple(str(i) for i in range(15)):
                policy=Policy(*v,overlap,pair)
                rows,bad,days=select(races,by_race,policy,'202501','202507')
                met=accounting(rows,bad,days)
                tested+=1
                if met['races']<100 or met['hitRacePct']<20:continue
                eligible+=1
                # Optimize monetary return with largest race removed, not accuracy.
                key=(met['trimLargestRaceRoiPct'],met['roiPct'],met['races'])
                if chosen is None or key>chosen[0]:chosen=(key,policy,met)
    if chosen is None:raise RuntimeError('NO_2025H1_PAID_RACE_FLOOR_POLICY')
    _,policy,h1=chosen
    print('HURDLE_SELECTED_2025H1',json.dumps({'policy':asdict(policy),
        'money':h1,'policiesTried':tested,'eligible':eligible},
        ensure_ascii=False),flush=True)
    v=(policy.cash_mode,policy.risk,policy.probability_exponent)
    bv=best_each_market(races,ids,y,tickets,markets,f25,v)
    rows,bad,days=select(races,bv,policy,'202507','202601')
    h2=accounting(rows,bad,days)
    print('HURDLE_2025H2_FINANCIAL_HOLDOUT',json.dumps(h2,ensure_ascii=False),flush=True)
    f26=fit_hurdle(X,y,markets,years,(2024,2025))
    bv=best_each_market(races,ids,y,tickets,markets,f26,v)
    rows,bad,days=select(races,bv,policy,'202601','202604')
    test=accounting(rows,bad,days)
    print('HURDLE_2026_FROZEN_FINANCIAL_HOLDOUT',json.dumps(test,ensure_ascii=False),flush=True)
    report={'model':'NEW two-stage probability-of-payment x conditional-paid-yen',
       'allSixMarketsAndAll15DifferentPairsExplored':True,
       'fiveRacesPerEligibleVenueDay':True,
       'priorModelChosenTicketsUsed':False,
       'settlementData':'Third-party public mirror pinned Kenseimk/keiba-agent f552ca8628646f39b05ffdbdc3ab8734939ffd66',
       'thirdPartyPayoutNotIndependentlyJraAuthenticated':True,
       'finalWinOddsNotT15CombinationQuotes':True,
       '2026NotPristineBecausePreviouslyInspected':True,
       'sourceAudit':audit,'fit2024':f25['audit'],'policyCandidatesTried':tested,
       'policyCandidatesWithMinimumHitAndCoverage':eligible,
       'selected2025H1Policy':asdict(policy),'2025H1Selection':h1,
       '2025H2UntouchedValidation':h2,'refit2024_2025':f26['audit'],
       '2026FrozenPolicyTest':test,
       'bothHoldoutsPassNumeric400':bool(h2['passesNumeric400Only'] and test['passesNumeric400Only']),
       'completeOfficialForwardT15Proof':False,'promotionAllowed':False,
       'runtimeSeconds':round(time.monotonic()-t,2)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('INDEPENDENT_HURDLE_MONEY_RESULT_WRITTEN',str(OUT),flush=True)

if __name__=='__main__':main()
