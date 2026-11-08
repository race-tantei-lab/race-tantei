#!/usr/bin/env python3
"""Walk-forward CASH ROI200 pattern discovery: changing conditions, not a horse predictor.

For each year t, discover only profitable money conditions in t-3 ... t-1,
then freeze the year's actual win/wide/quinella/exacta/trio/trifecta tickets.
Global portfolio policy selected by 2024 REAL cash only using 2021-23 data,
then applied with rules refitted chronologically through 2024 to 2025, and
through 2025 to 2026 Jan-Apr. At each year the condition subset may change
from the preceding year using ONLY older settled payout evidence.
No future-year data, performance metrics like log loss, or old model tickets
enter selection. Official JRA T15 six-type odds unavailable and third-party
payout mirror unverified: never deploy directly.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from itertools import combinations,product
from pathlib import Path
import json,sys,time,importlib.util,math
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis-results/nov2026-three-year-rolling-roi200-paid-ticket-rules.json'
HORIZONS=(2,3,5)
SUPPORTS=(30,80,160)
TOP_COUNTS=(1,3,8,20,50)
PAIRS=(-1,)+tuple(range(15))
STAKES=(100,500,1000,1500,1900)
RACES_PER_DAY=(5,)  # enforce production venue-day maximum, not tuned on validation
SEED=20261108

def module(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if spec is None or not spec.loader:raise RuntimeError('FILE_MISSING')
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod

def data(source):
    with np.load(source.CACHE,allow_pickle=False) as v:
        paid=v['payout']
        feat={k:v[k] for k in (*source.SINGLE_BINS,'market')}
    races=json.loads(source.RACE_CACHE.read_text(encoding='utf8'))['races']
    years=np.asarray([int(r['month'][:4]) for r in races],dtype=np.int16)
    return paid,feat,races,years

def rules_lookback(source,paid,feat,years,target,horizon,support):
    train=(years>=target-horizon)&(years<target)
    dates_tr=years[train]
    paid_train=paid[train].ravel()
    if len(paid_train)<10000:raise RuntimeError('TOO_FEW_MONETARY_YEARS')
    conditions=[]
    for pattern in source.PATTERNS:
        group,n=source.mixed_code(feat,pattern)
        key=group[train].ravel()
        counts=np.bincount(key,minlength=n)
        cash=np.bincount(key,weights=paid_train,minlength=n)
        positives=paid_train>0
        positive_counts=np.bincount(key[positives],minlength=n)
        biggest=np.zeros(n,dtype=np.int32)
        np.maximum.at(biggest,key[positives],paid_train[positives])
        robust=(cash-biggest)/(100*np.maximum(counts,1))
        good=(counts>=support)&(positive_counts>=max(3,support//35))&(
           robust>=2.)
        for index in np.flatnonzero(good):
            # Pair true net cash return with support shrinkage.
            value=float(min(robust[index],20)*math.sqrt(
                    counts[index]/(counts[index]+90))*
                    positive_counts[index]/(positive_counts[index]+5))
            conditions.append((value,pattern,int(index),
                     int(counts[index]),float(robust[index]),
                     int(positive_counts[index])))
    conditions.sort(key=lambda r:(-r[0],-r[3]))
    return conditions

def scored_year(source,feat,conditions,years,target,top_k):
    row=np.flatnonzero(years==target)
    if not len(row):return None
    all_scores=np.zeros((len(row),source.N),dtype=np.float32)
    fields={key:value[row] for key,value in feat.items()}
    for q,pattern,code,_,_,__ in conditions[:top_k]:
        g,_=source.mixed_code(fields,pattern)
        np.maximum(all_scores,np.where(g==code,q,0).astype(np.float32),
                   out=all_scores)
    return all_scores,row

def race_choices(source,signals,row,races,year):
    template=source.START_MARKET
    by_day=defaultdict(list)
    for i,rid in enumerate(row):
        r=races[int(rid)]
        candidates=[]
        for j in range(6):
            first=int(template[j]);last=int(template[j+1])
            k=first+int(np.argmax(signals[i,first:last]))
            candidates.append((float(signals[i,k]),
                               int(rid)*source.N+k,j))
        by_day[r['day']].append((r['id'],candidates))
    return by_day

def pick_portfolio(source,days,policy):
    horizon,support,k,pair,stake,limit,needtwo=policy
    selected=[]
    combos=source.MARKET_PAIRS if pair<0 else (source.MARKET_PAIRS[pair],)
    for day,races in days.items():
        day_choices=[]
        for rid,offers in races:
            best=None
            for m1,m2 in combos:
                v1,v2=offers[m1],offers[m2]
                if needtwo and min(v1[0],v2[0])<=0:continue
                if v1[0]+v2[0]<=0:continue
                winner=(v1[0]+v2[0],min(v1[0],v2[0]),
                   -m1,-m2,v1[1],v2[1])
                if best is None or winner[:4]>best[:4]:best=winner
            if best is None:continue
            day_choices.append((best[0],rid,best[4],best[5]))
        day_choices.sort(key=lambda x:x[1])  # chronological race number, no retrospective ROI sorting
        selected.extend(day_choices[:limit])
    return selected

def measure(picks,paid,stake):
    n=len(picks)
    if not n:return {'races':0,'roiPct':None,'robust200':False}
    flat=paid.ravel()
    total_bets=n*2000
    p1=np.asarray([int(flat[z[2]])*(stake//100) for z in picks],dtype=np.int64)
    p2=np.asarray([int(flat[z[3]])*((2000-stake)//100) for z in picks],dtype=np.int64)
    returns=p1+p2
    gross=int(returns.sum())
    biggest=int(max(np.max(p1),np.max(p2)))
    biggestrace=int(np.max(returns))
    hit=float(np.mean(returns>0))
    p=lambda z:round(100*z/total_bets,4)
    return {'races':n,'stakeYen':total_bets,'paidYen':gross,
      'profitYen':gross-total_bets,'roiPct':p(gross),
      'minusMaxTicketPct':p(gross-biggest),
      'minusMaxRacePct':p(gross-biggestrace),
      'hitRacePct':round(hit*100,4),
      'robust200':bool(n>=100 and hit>=.2 and
        gross-biggest>=2*total_bets and gross-biggestrace>=2*total_bets)}

def main():
    if '--self-test' in sys.argv:
        assert len(PAIRS)==16 and len(TOP_COUNTS)==5
        toy=np.zeros((1,2),dtype=np.int32)
        toy[0,0]=300
        money=measure([(1.,'a',0,1)],toy,1000)
        assert money['roiPct']==150.
        print('WALKFORWARD_REAL_CASH_ROI200_MATH_OK',flush=True)
        return
    start=time.monotonic()
    base=module('scripts/research-nov2026-decade-roi-first-sixmarkets.py',
                 'historical_10runner_actual_money')
    paid,feat,races,years=data(base)
    print('ROLLING_CASH_INPUT',json.dumps(
        {'races':len(races),'allTicketCandidates':paid.size,
         'marketTypes':6,'trainingNeverUsesTargetYear':True},
         ensure_ascii=False),flush=True)
    # Build all 9 distinct historical training period rule sets ONCE.
    # The 2024 outcome is used to pick a portfolio policy ONLY.
    # Each 2025 & 2026 condition set learns exclusively from BEFORE its year.
    year_rules={}
    year_scored={}
    for target in (2024,2025,2026):
        for horizon in HORIZONS:
            # Mine all genuine cash ROI200 cells ONCE per historical window,
            # then apply support filters without repeating 83 category scans.
            baseline=rules_lookback(base,paid,feat,years,target,horizon,30)
            for support in SUPPORTS:
                selected=[q for q in baseline if q[3]>=support and
                    q[5]>=max(3,support//35)]
                year_rules[(target,horizon,support)]=selected
                print('ROLLING_CASH_ROI200_CONDITION_SET',json.dumps({
                  'targetYear':target,'lookbackYears':horizon,
                  'minPaidTicketSamples':support,
                  'historicallyProfitableCellCount':len(selected),
                  'topRule':selected[0] if selected else None},
                   ensure_ascii=False),flush=True)
                if not selected:continue
                for k in TOP_COUNTS:
                    s=scored_year(base,feat,selected,years,target,k)
                    if s is None:continue
                    signal,row=s
                    year_scored[(target,horizon,support,k)]=race_choices(
                        base,signal,row,races,target)
    selected=None;tested=0;eligible=0
    for horizon,support,k,pair,stake,limit,needtwo in product(
          HORIZONS,SUPPORTS,TOP_COUNTS,PAIRS,STAKES,RACES_PER_DAY,
          (False,True)):
        day=year_scored.get((2024,horizon,support,k))
        if day is None:continue
        policy=(horizon,support,k,pair,stake,limit,needtwo)
        chosen=pick_portfolio(base,day,policy)
        stats=measure(chosen,paid,stake)
        tested+=1
        if stats['races']<100 or stats['hitRacePct']<20:continue
        eligible+=1
        ranking=(int(stats['robust200']),stats['minusMaxRacePct'],
                 stats['roiPct'],stats['races'])
        if selected is None or ranking>selected[0]:
            selected=(ranking,policy,stats)
    if selected is None:
        result={'status':'NO_ELIGIBLE_2024_MONEY_PORTFOLIO','tested':tested}
        print('ROLLING_CASH_NONE',json.dumps(result),flush=True)
    else:
        _,policy,m2024=selected
        h,s,k,pair,stake,limit,needtwo=policy
        audit={}
        for target in (2025,2026):
            day=year_scored.get((target,h,s,k))
            if day is None:
                audit[str(target)]={'races':0,'robust200':False}
                continue
            rows=pick_portfolio(base,day,policy)
            audit[str(target)]=measure(rows,paid,stake)
            print('ROLLING_CASH_'+str(target)+'_FROZEN',json.dumps(
              audit[str(target)],ensure_ascii=False),flush=True)
        result={'status':'PASS' if (
          m2024['robust200'] and
          all(x['robust200'] for x in audit.values()))
          else 'NOT_200',
          'selected2024Policy':{'lookbackYears':h,'minimumGroupSupport':s,
            'maxProfitConditionsUsed':k,'marketPairIndex':pair,
            'stakeFirstYen':stake,'stakeSecondYen':2000-stake,
            'racesPerVenueDayMax':limit,'twoQualifyingMarketsRequired':needtwo},
          '2024CashPolicySelection':m2024,
          '2025TrueForward':audit.get('2025'),
          '2026JanAprTrueForward':audit.get('2026'),
          'historicalRuleCountByYear':{
              str(y):len(year_rules.get((y,h,s),[]))
              for y in (2024,2025,2026)},
          'exampleMoneyRule2026':year_rules.get((2026,h,s),[])[:k],
          'testedCashPoliciesOn2024':tested,
          'eligibleCashPoliciesOn2024':eligible}
        print('ROLLING_CASH_2024_POLICY_SELECT',json.dumps(
            {'policy':policy,'cash':m2024,
             'tested':tested,'eligible':eligible},
            ensure_ascii=False),flush=True)
    result['algorithm']='yearly walkforward ROI200 actual cash condition mining, minimal subset, two distinct market tickets, fully pre-result'
    result['source']='2015-2026 136 monthly pinned historical payout mirror'
    result['officialJraT15SixMarketQuoteMissing']=True
    result['thirdPartyPayoutNotIndependentlyReconciled']=True
    result['2026InspectedByOtherModelResearch']=True
    result['productionDeployed']=False
    result['adopted']=False
    result['elapsedSeconds']=round(time.monotonic()-start,2)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',
                   encoding='utf8')
    print('ROLLING_ROI200_DIRECT_PAID_FINANCIAL_RESULT',OUT,flush=True)

if __name__=='__main__':main()
