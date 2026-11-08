#!/usr/bin/env python3
"""Selective ROI200 search over INDIVIDUAL conditions (not every condition).

Condition cells are independently required to pass a CASH payout 200% ROI
(after largest single actual winner ticket removed) in 2024+2025H1.
For each such cell, discover whether the very same condition remains
financially profitable in 2025H2, select a SHORT list of 1,3,8,20,50
rules, freeze exact tickets and 5 venue-day races, then validate 2026.

Never substitute predicted horse rank, classification accuracy or log loss for
actual money. Never use 2026 labels to select rule codes, a market pair or the
length of the shortlist. Payouts from a THIRD-PARTY mirror, no official T15
six-market combination quotes: no production promotion.
"""
from __future__ import annotations
import json,math,sys,time,importlib.util
from pathlib import Path
from collections import defaultdict
from itertools import combinations,product
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis-results/nov2026-individual-roi200-cash-rule-shortlist.json'
CACHE=ROOT/'analysis-results/roi200-public-2024-26-categories-v1.npz'
META=ROOT/'analysis-results/roi200-public-2024-26-categories-v1.json'
PAIRS=tuple(combinations(range(6),2))
SHORTLIST_SIZES=(1,3,8,20,50,100)
BASELINE_MARKETS=(0,1)
SEED=20261108

def helper():
    name='individual_cash_pattern_source'
    spec=importlib.util.spec_from_file_location(name,ROOT/
            'scripts/research-nov2026-roi200-first-pattern-search.py')
    if not spec or not spec.loader:raise RuntimeError('MISSING_PATTERN_SOURCE')
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod

def history_and_categories(b):
    a=json.loads(META.read_text(encoding='utf8'))
    with np.load(CACHE,allow_pickle=False) as z:
        y=z['y'];rid=z['ids'];types=z['types']
        cat={name:z['cat_'+name] for name in
             {**b.BASE_FEATURES,**b.CONTEXT_FEATURES}}
    return a['races'],y,rid,types,cat

def find_bettable_profitable_single_conditions(b,races,y,ids,types,cat):
    dated=np.asarray([r['month'] for r in races])[ids]
    train=dated<'202507'
    validate=(dated>='202507')&(dated<'202601')
    conditions=[]
    stats={'historicalSchemas':0,'actual2024H1Robust200CashCells':0,
           'financiallyPositive2025H2SingleCells':0,
           'strong2025H2Robust200SingleCells':0}
    for schema in b.all_patterns():
        code,size=b.mixed_code(schema,types,cat)
        count=np.bincount(code[train],minlength=size)
        cash=np.bincount(code[train],weights=y[train],minlength=size)
        paid=np.bincount(code[train&(y>0)],minlength=size)
        biggest=np.zeros(size,dtype=np.int32)
        np.maximum.at(biggest,code[train&(y>0)],y[train&(y>0)])
        trimmed=(cash-biggest)/(100*np.maximum(count,1))
        eligible=(count>=30)&(paid>=3)&(trimmed>=2.)
        valid_codes=np.flatnonzero(eligible)
        stats['historicalSchemas']+=1
        stats['actual2024H1Robust200CashCells']+=len(valid_codes)
        if not len(valid_codes):continue
        # 2025H2 is a *model selection* interval, not the frozen test.
        cv_n=np.bincount(code[validate],minlength=size)
        cv_cash=np.bincount(code[validate],weights=y[validate],minlength=size)
        cv_hits=np.bincount(code[validate&(y>0)],minlength=size)
        cv_max=np.zeros(size,dtype=np.int32)
        np.maximum.at(cv_max,code[validate&(y>0)],y[validate&(y>0)])
        cv_trim=(cv_cash-cv_max)/(100*np.maximum(cv_n,1))
        cv_roi=cv_cash/(100*np.maximum(cv_n,1))
        # Select only historically profitable individual patterns. Neither
        # high train payout nor all pattern cells are applied automatically.
        for c in valid_codes:
            if cv_n[c]<10 or cv_hits[c]<2 or cv_trim[c]<1.1:
                continue
            stats['financiallyPositive2025H2SingleCells']+=1
            if cv_trim[c]>=2:
                stats['strong2025H2Robust200SingleCells']+=1
            conditions.append({
                'fields':list(schema),'code':int(c),
                'trainTickets':int(count[c]),
                'trainWins':int(paid[c]),
                '2024To2025H1ReturnPct':round(
                    100*cash[c]/(100*count[c]),4),
                '2024To2025H1TrimReturnPct':round(100*trimmed[c],4),
                '2025H2Tickets':int(cv_n[c]),
                '2025H2Wins':int(cv_hits[c]),
                '2025H2ReturnPct':round(100*cv_roi[c],4),
                '2025H2TrimReturnPct':round(100*cv_trim[c],4),
                'robustMoneyScore':float(
                    min(trimmed[c],15)*min(cv_trim[c],15)
                    *np.sqrt(cv_n[c]/(cv_n[c]+35))
                    *np.sqrt(count[c]/(count[c]+75))
                    *cv_hits[c]/(cv_hits[c]+3)),
                'stabilityMoneyScore':float(
                    min(trimmed[c],cv_trim[c],15)
                    *np.sqrt(cv_n[c]/(cv_n[c]+35))
                    *paid[c]/(paid[c]+6))
            })
    conditions.sort(key=lambda q:(-q['robustMoneyScore'],
                            -q['2025H2Tickets']))
    return conditions,stats

def shortlist_score(races,types,cat,b,selected,metric):
    # Apply at most N rules, never every qualifying cell. Rules encode only
    # race/horse/odds information accessible before result settlement.
    cache={}
    result=np.zeros(len(types),dtype=np.float32)
    for rec in selected:
        sig=tuple(rec['fields'])
        if sig not in cache:
            cache[sig]=b.mixed_code(sig,types,cat)[0]
        value=float(rec[metric])
        np.maximum(result,np.where(cache[sig]==rec['code'],
                            value,0.).astype(np.float32),out=result)
    return result

def shortlist_top_market_predictions(races,types,score,period):
    options={}
    for i,r in enumerate(races):
        if not period[0]<=r['month']<period[1]:continue
        a=i*336;b=(i+1)*336
        group=score[a:b];market=types[a:b]
        candidates=[]
        for typ in range(6):
            eligible=np.flatnonzero(market==typ)
            pick=a+int(eligible[np.argmax(group[eligible])])
            candidates.append((float(score[pick]),pick,typ))
        options[i]=candidates
    return options

def get_two(opts,market_pair,hedge):
    possible=PAIRS if market_pair==-1 else (PAIRS[market_pair],)
    best=None
    for a,b in possible:
        x,z=opts[a],opts[b]
        value=x[0]+z[0]
        # All 5 races / venue-day remain in coverage. If neither market
        # contains a historically profitable cell, use the first basic
        # pre-declared candidate; this is transparently not a 200% rule.
        k=(value,min(x[0],z[0]),-a,-b,x[1],z[1])
        if best is None or k[:4]>best[:4]:best=k
    return best

def rows_for_period(races,options,pair):
    days=defaultdict(list)
    for i,c in options.items():
        k=get_two(c,pair,False)
        value=k[0]
        days[races[i]['day']].append((
            value,races[i]['id'],races[i]['month'],k[4],k[5],i))
    rows=[]
    for day,rs in days.items():
        if len(rs)<5:raise RuntimeError('NOT_FIVE_RACE_CHOICES_PER_VENUE_DAY')
        rs.sort(key=lambda v:(-v[0],v[1]))
        rows.extend(rs[:5])
    return rows,len(days)

def metrics(rows,days,y):
    n=len(rows);stake=2000*n
    a=np.asarray([int(y[z[3]])*10 for z in rows],dtype=np.int64)
    b=np.asarray([int(y[z[4]])*10 for z in rows],dtype=np.int64)
    tot=a+b
    gross=int(tot.sum())
    big_ticket=int(max(np.max(a,initial=0),np.max(b,initial=0)))
    big_race=int(np.max(tot,initial=0))
    hit=int(np.sum(tot>0))
    month=defaultdict(lambda:[0,0,0])
    for rec,ret in zip(rows,tot):
        m=month[rec[2]];m[0]+=1;m[1]+=int(ret);m[2]+=int(ret>0)
    p=lambda x,d:round(100*x/d,5) if d else None
    return {'races':n,'venueDays':days,'full5PerVenueDay':n==days*5,
       'stakeYen':stake,'returnYen':gross,'profitYen':gross-stake,
       'roiPct':p(gross,stake),
       'minusLargestTicketRoiPct':p(gross-big_ticket,stake),
       'minusLargestRaceRoiPct':p(gross-big_race,stake),
       'hitRacePct':p(hit,n),
       'byMonth':{k:{'races':v[0],'roiPct':p(v[1],v[0]*2000),
         'hitRacePct':p(v[2],v[0])} for k,v in sorted(month.items())},
       'robust200':bool(stake and n==days*5 and n>=100 and
         hit/n>=.2 and gross-big_race>=2*stake and
         gross-big_ticket>=2*stake)}

def search(races,y,types,cat,b,conditions):
    h2=('202507','202601');future=('202601','202604')
    candidates=[]
    tried=0
    for length in SHORTLIST_SIZES:
        for metric in ('robustMoneyScore','stabilityMoneyScore'):
            ranked=sorted(conditions,key=lambda x:-x[metric])
            score=shortlist_score(races,types,cat,b,ranked[:length],metric)
            bets=shortlist_top_market_predictions(races,types,score,h2)
            for pair in (-1,)+tuple(range(15)):
                rows,days=rows_for_period(races,bets,pair)
                m=metrics(rows,days,y)
                tried+=1
                if m['hitRacePct']<20:continue
                key=(int(m['robust200']),
                     m['minusLargestRaceRoiPct'],m['roiPct'])
                candidates.append((key,length,metric,pair,m))
    if not candidates:
        return {'status':'NO_CASH_POLICY_PASSES_MIN20_HIT',
                'count':tried,'found':len(conditions),'adopt':False}
    _,n,metric,pair,h2metrics=max(candidates,key=lambda z:z[0])
    selected=sorted(conditions,key=lambda x:-x[metric])[:n]
    score=shortlist_score(races,types,cat,b,selected,metric)
    opts=shortlist_top_market_predictions(races,types,score,future)
    rows,days=rows_for_period(races,opts,pair)
    m26=metrics(rows,days,y)
    print('INDIVIDUAL_ROI200_RULES_H2_PICK',json.dumps({
         'numberOfActualConditionsSelected':n,
         'qualityMetric':metric,'marketPairIndex':pair,
         'searchedPortfolios':tried,
         'eligibleBy20PctHit':len(candidates),
         '2025H2Money':h2metrics},ensure_ascii=False),flush=True)
    print('INDIVIDUAL_ROI200_RULES_2026_FREEZE',json.dumps(m26,ensure_ascii=False),flush=True)
    return {'status':'PASS' if h2metrics['robust200'] and m26['robust200']
            else 'ROBUST200_NOT_FOUND',
       'onlySelectedSubsetCount':n,
       'eligible2025H2PredictionStrategies':len(candidates),
       'strategiesSearched':tried,
       'frozenSelection':{'numberOfConditions':n,
          'historicalValueScore':metric,'marketPairIndex':pair,
          'historicalRuleCells':selected},
       '2025H2FinancialSelectionPeriod':h2metrics,
       '2026JanMarFrozenEvaluation':m26,
       'passesRobust200Both':bool(h2metrics['robust200'] and m26['robust200']),
       'productionChanged':False,'adopt':False}

def main():
    if '--self-test' in sys.argv:
        y=np.asarray([0,500,200])
        one=[(1.0,'r','202507',1,2,0)]
        m=metrics(one,1,y)
        assert m['roiPct']==350 and m['minusLargestTicketRoiPct']==100.
        assert len(PAIRS)==15 and len(SHORTLIST_SIZES)==6
        print('INDIVIDUAL_CASH_PROFITABLE_CONDITION_SUBSET_UNIT_OK',flush=True)
        return
    start=time.monotonic()
    b=helper()
    races,y,ids,types,cat=history_and_categories(b)
    conditions,stats=find_bettable_profitable_single_conditions(
                   b,races,y,ids,types,cat)
    print('INDIVIDUAL_REAL_PAID_ROI200_CELLS',json.dumps({
        'totalConditionsChecked':stats,'candidateShortlistedRuleCells':len(conditions),
        'recordsInPayoutMirror':len(y),
        'allSixMarkets':True},ensure_ascii=False),flush=True)
    answer=search(races,y,types,cat,b,conditions)
    answer['discoveredFinancialRuleCells']=stats
    answer['totalSubsetEligibleConditionCells']=len(conditions)
    answer['modelType']='select 1,3,8,20,50 or 100 individually profitable cash rule cells, not OR over every past profitable condition'
    answer['2024To2025H1RuleMiningOnly']=True
    answer['2025H2CashPolicySelectionOnly']=True
    answer['2026CheckedOnlyAfterFreeze']=True
    answer['2026PreviouslyStudiedByOtherExperiments']=True
    answer['sixMarketOfficialT15QuotesAvailable']=False
    answer['paidMirrorIndependentlyJraReconciled']=False
    answer['runtimeSeconds']=round(time.monotonic()-start,2)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(answer,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('INDIVIDUAL_CASH_RULE_SUBSET_RESULT_WRITTEN',str(OUT),flush=True)
if __name__=='__main__':main()
