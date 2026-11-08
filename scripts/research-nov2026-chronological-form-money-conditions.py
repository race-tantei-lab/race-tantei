#!/usr/bin/env python3
"""Discover actual >200%-ROI JRA ticket patterns using ONLY pre-race FORM history.

This is not a horse winner prediction model: 56 time-safe historical per-horse
features are collapsed into money-ticket conditions for ALL six bet types.
Mine actual payout ROI200 cells in 2024-2025H1, select only 1/3/8/20/50/100
individually useful conditions on 2025H2, lock, evaluate 2026 cash.
Never use 2026 payouts for condition discovery/policy selection.
No live write or production promotion. Third-party finished payout mirror and
historical final WIN quotes do NOT establish official JRA T-15 quotes.
"""
from __future__ import annotations
import importlib.util,json,math,sys,time
from itertools import combinations,permutations,product
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis-results/nov2026-chronological-form-roi200-condition-shortlists.json'
SIX=('単勝','ワイド','馬連','馬単','3連複','3連単')
POSN=7
THRESHOLDS={
 'horseWinAvg':(.03,.08,.16),
 'horseTop3Avg':(.15,.3,.5),
 'lastFinishAvg':(.2,.5,.8),
 'recentFinishAvg':(.25,.5,.75),
 'recentSpeedAvg':(13.,15.,17.),
 'recentSpeedMax':(14.,16.,18.),
 'lastSpeedAvg':(13.,15.,17.),
 'speedChangeAvg':(-1.,0.,1.),
 'jockeyWinAvg':(.05,.10,.17),
 'jockeyWinMax':(.07,.13,.20),
 'trainerWinAvg':(.05,.10,.16),
 'horseExperienceAvg':(1.,5.,15.),
 'layoffAvg':(14.,45.,100.),
 'distanceFamiliarAvg':(1.,4.,10.),
 'surfaceWinAvg':(.03,.09,.17),
 'rankFormMismatch':(0.25,.5,.75),
 'speedRelativeField':(-1.,0.,1.),
 'jockeyRelativeField':(-.03,0.,.03),
 'fieldSpeedSpread':(.3,1.,2.),
 'comboHorseWinMax':(.05,.12,.22)
}
INDEX={
 'horseWin':22,'horseTop3':23,'lastFinish':25,'recentFinish':26,
 'recentSpeed':34,'lastSpeed':33,'jockeyWin':49,'trainerWin':52,
 'horseExperience':21,'layoff':24,'distanceFamiliar':39,
 'surfaceWin':38
}
NEW_NAMES=tuple(THRESHOLDS)
CASH_CONTEXT=('rankMin','rankMax','rankSum','favorites','oddGeom',
              'rankCode','draw','venue','raceBand','fieldBand')
FORM_COMBOS=(('horseWinAvg','jockeyWinAvg'),
   ('horseWinAvg','recentSpeedAvg'),
   ('horseWinAvg','recentFinishAvg'),
   ('horseTop3Avg','recentSpeedAvg'),
   ('recentSpeedAvg','jockeyWinAvg'),
   ('jockeyWinAvg','trainerWinAvg'),
   ('lastFinishAvg','recentFinishAvg'),
   ('lastSpeedAvg','speedChangeAvg'),
   ('rankFormMismatch','jockeyWinAvg'),
   ('rankFormMismatch','recentSpeedAvg'),
   ('speedRelativeField','recentSpeedAvg'),
   ('horseExperienceAvg','recentSpeedAvg'),
   ('layoffAvg','recentSpeedAvg'),
   ('surfaceWinAvg','recentFinishAvg'),
   ('fieldSpeedSpread','recentSpeedMax'),
   ('comboHorseWinMax','recentSpeedMax'),
   ('distanceFamiliarAvg','speedRelativeField'))

def get(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError('FINANCIAL_SOURCE_MISSING')
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj

def positional_tickets():
    triples=[]
    for market in SIX:
        if market=='単勝':items=[(i,) for i in range(7)]
        elif market in ('ワイド','馬連'):
            items=list(combinations(range(7),2))
        elif market=='馬単':
            items=list(permutations(range(7),2))
        elif market=='3連複':
            items=list(combinations(range(7),3))
        elif market=='3連単':
            items=list(permutations(range(7),3))
        triples+=list(items)
    if len(triples)!=336:raise RuntimeError('NOT_ALL_SEVEN_HORSE_SIX_MARKET_TICKETS')
    return np.asarray([tuple(c)+(-1,)*(3-len(c)) for c in triples],
                      dtype=np.int16)

def form_categories(races,lookup,meta,off,horseX):
    positions=positional_tickets()
    mask=positions>=0
    n=len(races)
    arrays={name:np.zeros(336*n,dtype=np.uint8) for name in NEW_NAMES}
    empty=0
    matched=0
    for i,r in enumerate(races):
        idx=lookup.get(r['id'])
        if idx is None:
            empty+=1;continue
        start=int(off[idx])
        numbers=meta[idx]['horseNos']
        form=horseX[start:int(off[idx+1])]
        lookup_h={int(no):j for j,no in enumerate(numbers)}
        pool=[h[0] for h in r['horses'][:7]]
        if any(h not in lookup_h for h in pool):
            empty+=1;continue
        full_field=form
        best=np.stack([form[lookup_h[h]] for h in pool])
        total_runners=len(r['horses'])
        sub=positions.copy()
        sub[~mask]=0
        a=i*336;b=(i+1)*336
        def agg(feature,how='mean'):
            v=best[:,INDEX[feature]]
            f=v[sub]
            if how=='mean':
                return (np.where(mask,f,0.).sum(axis=1)/mask.sum(axis=1))
            if how=='max':
                return np.where(mask,f,-1e5).max(axis=1)
            if how=='first':
                return f[:,0]
            raise RuntimeError('INVALID_FORM_AGG')
        def fill(name,values):
            out=np.digitize(values,THRESHOLDS[name])
            if not (np.all(out>=0) and np.all(out<=3)):
                raise RuntimeError('CATEGORICAL_PRE_RACE_FORM_OUT_OF_RANGE')
            arrays[name][a:b]=out.astype(np.uint8)
        win=agg('horseWin')
        speed=agg('recentSpeed')
        speed_max=agg('recentSpeed','max')
        jockey=agg('jockeyWin')
        last=agg('lastSpeed')
        avgfield_speed=float(np.mean(full_field[:,INDEX['recentSpeed']]))
        avgfield_jockey=float(np.mean(full_field[:,INDEX['jockeyWin']]))
        fill('horseWinAvg',win)
        fill('horseTop3Avg',agg('horseTop3'))
        fill('lastFinishAvg',agg('lastFinish'))
        fill('recentFinishAvg',agg('recentFinish'))
        fill('recentSpeedAvg',speed)
        fill('recentSpeedMax',speed_max)
        fill('lastSpeedAvg',last)
        fill('speedChangeAvg',last-speed)
        fill('jockeyWinAvg',jockey)
        fill('jockeyWinMax',agg('jockeyWin','max'))
        fill('trainerWinAvg',agg('trainerWin'))
        fill('horseExperienceAvg',agg('horseExperience'))
        fill('layoffAvg',agg('layoff'))
        fill('distanceFamiliarAvg',agg('distanceFamiliar'))
        fill('surfaceWinAvg',agg('surfaceWin'))
        # Inverse market odds rank versus original pre-race historical
        # win rates. If all horses are evenly rated, no spurious result.
        before_market=np.asarray([x[1] for x in r['horses'][:7]],
                                dtype=np.float64)
        market_score=1/np.maximum(before_market,1)
        market_score/=market_score.sum()
        form_score=np.maximum(best[:,INDEX['horseWin']],.01)
        form_score/=form_score.sum()
        mismatch=np.abs(form_score-market_score)[sub]
        fill('rankFormMismatch',np.where(mask,mismatch,0).sum(axis=1)/
             mask.sum(axis=1)*7)
        fill('speedRelativeField',speed-avgfield_speed)
        fill('jockeyRelativeField',jockey-avgfield_jockey)
        fill('fieldSpeedSpread',np.full(336,
             np.std(full_field[:,INDEX['recentSpeed']])))
        fill('comboHorseWinMax',agg('horseWin','max'))
        matched+=1
    if matched<n*.75:
        raise RuntimeError('INSUFFICIENT_HORSE_FORM_MATCHES_'+str(matched))
    print('ROI200_PRE_RESULT_HORSE_FORM_JOIN',json.dumps({
        'matchedRaces':matched,'missingRaces':empty,
        'newCashFeatures':len(NEW_NAMES),'ticketCandidates':336*n},
         ensure_ascii=False),flush=True)
    return arrays

def conditions():
    seen=set()
    for f in NEW_NAMES:
        for other in [None]+list(CASH_CONTEXT):
            key=('market',f)+(tuple() if other is None else (other,))
            if key not in seen:
                seen.add(key);yield key
    for left,right in FORM_COMBOS:
        for other in [None,'oddGeom','rankMax','venue','fieldBand']:
            key=('market',left,right)+(tuple() if other is None else (other,))
            if key not in seen:
                seen.add(key);yield key

def main():
    if '--self-test' in sys.argv:
        assert positional_tickets().shape==(336,3)
        assert len(tuple(conditions()))>=200
        print('ROI200_HORSE_FORM_CASH_SUBSET_ENUMERATION_OK',flush=True)
        return
    begin=time.monotonic()
    b=get('scripts/research-nov2026-roi200-first-pattern-search.py',
          'roi200_direct_condition')
    top=get('scripts/research-nov2026-profitable-individual-rule-subsets.py',
          'roi200_individual_shortlist')
    pub=get('scripts/research-nov2026-sixmarket-real-paid-cash.py',
          'roi200_form_historical_paid')
    form=get('scripts/research-nov2026-56feature-sixmarket-pl-money.py',
          'roi200_form_chronology')
    pub.TOP_HORSES=7
    races_full,source_audit=pub.read_pinned_csv()
    names=form.read_source_horse_names()
    X,won,off,meta,archive_names,drop=form.historical_horse_features()
    lookup=form.join_pre_result_races_by_horse_identity(
                         races_full,meta,archive_names,names)
    features=form_categories(races_full,lookup,meta,off,X)
    races,y,ids,typ,oldcat=top.history_and_categories(b)
    if [r['id'] for r in races]!=[r['id'] for r in races_full]:
        raise RuntimeError('SOURCE_PUBLIC_JRA_RECORDS_NOT_PAIRED')
    oldcat.update(features)
    b.BASE_FEATURES.update({name:4 for name in NEW_NAMES})
    b.all_patterns=conditions
    money_conditions,audit=top.find_bettable_profitable_single_conditions(
                                   b,races,y,ids,typ,oldcat)
    print('ROI200_FORM_PAID_CONDITION_DISCOVERY',json.dumps({
        'scannedSchemas':audit['historicalSchemas'],
        'trainRobust200CashCells':audit['actual2024H1Robust200CashCells'],
        'candidateProfitableIn2025H2':len(money_conditions),
        'historicallyTrueT15CombinationOdds':False,
        'usesOldPreselectedTickets':False},ensure_ascii=False),flush=True)
    result=top.search(races,y,typ,oldcat,b,money_conditions)
    result['predictorType']='historically paid ROI200 pre-result 56-feature horse-form rule cell shortlist selected by held-out money'
    result['allNewFormCategories']=list(NEW_NAMES)
    result['scannedNewFinancialFeatureSchemas']=audit['historicalSchemas']
    result['train2024Through2025H1Source']=source_audit
    result['newRuleCandidatesProfitable2025H2']=len(money_conditions)
    result['2026PreviouslyExaminedByOtherStudies']=True
    result['unknownHistoricalOfficialJraT15SixMarketPrices']=True
    result['actualPayoutMirrorOfficialReconciliationMissing']=True
    result['productionModified']=False
    result['adopted']=False
    result['runtimeSeconds']=round(time.monotonic()-begin,2)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',
                   encoding='utf8')
    print('ROI200_PRE_RACE_FORM_CASH_RULE_RESULT',str(OUT),flush=True)
if __name__=='__main__':main()
