#!/usr/bin/env python3
"""ROI-first FEATURE SUBSET search: use ONLY financially useful pre-race patterns.

Mine 2024+2025H1 actual paid ticket group conditions with >=200% net/gross
historical ROI (remove largest payment, retain stake). Use one subset only:
rank/draw, price, race context, horse form, single-rule, or all; choose
supported threshold & one of 15 market-pair policies based on 2025H2 cash,
then lock and test 2026 Jan-Mar, 5 races per venue-day and two different JRA
bet types. Prior race-tantei selected tickets are NEVER used.
No production changes. Final WIN quotes are NOT official JRA T-15 six-type
combination odds; payouts from a third-party mirror are not verified official.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from itertools import combinations,product
from pathlib import Path
import importlib.util,json,time,math,sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'analysis-results/roi200-public-2024-26-categories-v1.npz'
RACES=ROOT/'analysis-results/roi200-public-2024-26-categories-v1.json'
OUT=ROOT/'analysis-results/nov2026-selective-roi200-condition-subsets.json'
PAIRS=tuple(combinations(range(6),2))
SEED=20261108
FAMILIES=('all','simple','rank','odds','context','horse')
MIN_SUPPORTS=(30,80,160)
STYLES=('max_return','stable_return')
MARKETS=('単勝','ワイド','馬連','馬単','3連複','3連単')

def module(path,name):
    s=importlib.util.spec_from_file_location(name,ROOT/path)
    if not s or not s.loader:raise RuntimeError('NO_RESEARCH_SOURCE')
    mod=importlib.util.module_from_spec(s)
    sys.modules[s.name]=mod
    s.loader.exec_module(mod)
    return mod

def load_data(base):
    if not DATA.exists() or not RACES.exists():
        raise RuntimeError('SOURCE_CACHE_NOT_MATERIALIZED')
    meta=json.loads(RACES.read_text(encoding='utf8'))
    with np.load(DATA,allow_pickle=False) as b:
        y=b['y']
        ids=b['ids']
        typ=b['types']
        cat={k:b['cat_'+k] for k in {**base.BASE_FEATURES,**base.CONTEXT_FEATURES}}
    races=meta['races']
    if len(y)!=len(ids) or len(y)!=len(typ) or len(races)*336!=len(y):
        raise RuntimeError('UNIVERSE_7_HORSE_SIX_MARKET_ALIGNMENT')
    dates=np.asarray([x['month'] for x in races])
    return races,y,ids,typ,cat,dates,meta['audit']

def family_membership(fields):
    names=set(fields[1:])
    members={'all'}
    if len(fields)<=2:members.add('simple')
    if names.intersection(('rankMin','rankMax','rankSum','favorites',
                           'rankSpread','rankCode')):
        members.add('rank')
    if names.intersection(('oddGeom','ticketPriceSpread','favoriteOdds')):
        members.add('odds')
    if names.intersection(('age','weight','draw')):
        members.add('horse')
    if names.intersection(('venue','raceBand','fieldBand','quarter')):
        members.add('context')
    return members

def discover_selective_cash_conditions(base,types,cat,y,ids,dates):
    """2024+H1 FINANCIAL discovery; no 2025H2/2026 paid target in score."""
    periods=dates[ids]
    t0=periods<'202501'
    t1=(periods>='202501')&(periods<'202507')
    train=t0|t1
    working_keys=list(product(MIN_SUPPORTS,FAMILIES,STYLES))
    scores={k:np.zeros(len(y),dtype=np.float32) for k in working_keys}
    mined={key:[] for key in working_keys}
    research=Counter()
    # Selectively deploy JUST one profitable condition category family,
    # not all conditions conjunctively and not all historical condition cells.
    for schema in base.all_patterns():
        code,n=base.mixed_code(schema,types,cat)
        members=family_membership(schema)
        cnt=np.bincount(code[train],minlength=n)
        paid=np.bincount(code[train],weights=y[train],minlength=n)
        hits=np.bincount(code[train&(y>0)],minlength=n)
        biggest=np.zeros(n,dtype=np.int32)
        np.maximum.at(biggest,code[train&(y>0)],y[train&(y>0)])
        # Densest ROI floor: preserve all ¥100 stakes even when excluding
        # highest individual paid ticket. NEVER credit unpurchased tickets.
        trimmed=(paid-biggest)/(np.maximum(cnt,1)*100.)
        raw=paid/(np.maximum(cnt,1)*100.)
        c0=np.bincount(code[t0],minlength=n)
        c1=np.bincount(code[t1],minlength=n)
        p0=np.bincount(code[t0],weights=y[t0],minlength=n)
        p1=np.bincount(code[t1],weights=y[t1],minlength=n)
        roi0=p0/(np.maximum(c0,1)*100.)
        roi1=p1/(np.maximum(c1,1)*100.)
        research['testedPreRaceSchemas']+=1
        for support in MIN_SUPPORTS:
            valid=(cnt>=support)&(hits>=max(3,support//25))&(
                  trimmed>=2.)&(raw>=2.)
            acceptable=np.flatnonzero(valid)
            if not len(acceptable):continue
            research['2024H1CombinedRobust200CellsAtSupport'+str(support)]+=len(acceptable)
            # A matching rule's score is its OWN real historical monetary
            # return, not an unrelated model's win probability.
            gross_score=np.clip(trimmed,2.,16.)*(
                hits/(hits+5.))*np.sqrt(cnt/(cnt+75.))
            # A second version emphasizes rules that held in BOTH observed
            # historical eras, instead of a single period's lucky result.
            trust=np.clip(np.minimum(roi0,roi1)/2.,0.,1.)
            trust *= np.minimum(c0/(c0+15.),c1/(c1+15.))
            for family in members:
                for style in STYLES:
                    k=(support,family,style)
                    values=(gross_score*trust if style=='stable_return'
                           else gross_score)
                    new=values[code].astype(np.float32)
                    np.maximum(scores[k],new,out=scores[k])
                    # Keep precise pre-result condition codes needed to
                    # generate the frozen bet tickets later.
                    for ix in acceptable:
                        if len(mined[k])<4000:
                            mined[k].append({
                                'fields':list(schema),'groupCode':int(ix),
                                'trainingTicketCount':int(cnt[ix]),
                                'actual2024Through2025H1RoiPct':round(
                                    100*raw[ix],3),
                                'actualRoiExLargestTicketPct':round(
                                    100*trimmed[ix],3),
                                'trainingPaidTicketCount':int(hits[ix]),
                                'year2024ActualRoiPct':round(100*roi0[ix],3),
                                '2025H1ActualRoiPct':round(100*roi1[ix],3)})
    for key in list(scores):
        if not np.any(scores[key]>0):
            scores.pop(key)
            mined.pop(key,None)
    research['nonemptyScoreAndRuleFamilies']=len(scores)
    research['trainTickets']=int(train.sum())
    research['2025H2Or2026PayoutUsedForRuleDiscovery']=False
    return scores,mined,dict(research)

def race_market_best(races,y,ids,types,score,period):
    """Ranking solely on pre-result ROI subset score. For each race return
    highest-scoring ticket per distinct market, with LABEL ATTACHED only
    after a wager is chosen, never used to choose an option.
    """
    out={}
    for i,r in enumerate(races):
        if not period[0]<=r['month']<period[1]:continue
        a=i*336;b=(i+1)*336
        best=[]
        sub=score[a:b]
        for market in range(6):
            mask=np.flatnonzero(types[a:b]==market)
            ix=a+int(mask[np.argmax(sub[mask])])
            best.append((float(score[ix]),ix,market))
        out[i]=best
    return out

def choose(candidates,pair,prefer_qualifying_two):
    if pair==-1:
        options=PAIRS
    else:options=(PAIRS[pair],)
    selected=None
    for a,b in options:
        x,z=candidates[a],candidates[b]
        # A single-condition model uses only the matching high-value
        # pre-race conditions. The fixed fallback for the second market
        # avoids pretending every market has a 200%-qualified condition.
        if prefer_qualifying_two and min(x[0],z[0])<=0:
            continue
        value=x[0]+z[0]
        if value<=0:continue
        candidate=(value,min(x[0],z[0]),-a,-b,x[1],z[1])
        if selected is None or candidate[:4]>selected[:4]:
            selected=candidate
    return selected

def portfolio(races,options,types,rule,period):
    support,family,style,pair,two_positive,limit=rule
    selected=defaultdict(list)
    unmatched=0
    for i,market in options.items():
        picked=choose(market,pair,two_positive)
        if picked is None:
            unmatched+=1
            continue
        val,second,_,__,a,b=picked
        day=races[i]['day']
        selected[day].append((val,second,races[i]['id'],
                              races[i]['month'],a,b,i))
    rows=[]
    for day,v in selected.items():
        v.sort(key=lambda x:(-x[0],-x[1],x[2]))
        for c in v[:limit]:
            # Actual y labels read ONLY in accounting(), never above.
            rows.append(c)
    return rows,len(selected),unmatched

def financial_audit(rows,days,y):
    n=len(rows);stake=2000*n
    p1=np.asarray([int(y[t[4]])*10 for t in rows],dtype=np.int64)
    p2=np.asarray([int(y[t[5]])*10 for t in rows],dtype=np.int64)
    paid=p1+p2
    gross=int(paid.sum())
    max_ticket=int(max(max(p1,default=0),max(p2,default=0)))
    max_race=int(max(paid,default=0))
    hit=int(np.sum(paid>0))
    fun=lambda a,b:round(100*a/b,5) if b else None
    months=defaultdict(lambda:[0,0,0])
    for row,value in zip(rows,paid):
        x=months[row[3]]
        x[0]+=1;x[1]+=int(value);x[2]+=int(value>0)
    return {'races':n,'venueDaysWithPredictions':days,
      'stakeYen':stake,'payoutYen':gross,'profitYen':gross-stake,
      'roiPct':fun(gross,stake),
      'minusLargestTicketRoiPct':fun(gross-max_ticket,stake),
      'minusLargestRaceRoiPct':fun(gross-max_race,stake),
      'paidRacePct':fun(hit,n),
      'byMonth':{m:{'races':z[0],'roiPct':fun(z[1],z[0]*2000),
                 'paidRacePct':fun(z[2],z[0])} for m,z in sorted(months.items())},
      'robust200':bool(n>=100 and hit/n>=.2
          and gross>=2*stake and gross-max_ticket>=2*stake
          and gross-max_race>=2*stake)}

def run_search(races,y,ids,typ,score_bank,rulebook,discovery):
    H2=('202507','202601');YR26=('202601','202604')
    strategies=[]
    for key,score in score_bank.items():
        for period in (H2,YR26):
            options=race_market_best(races,y,ids,typ,score,period)
            for pair,two_positive,limit in product(
                    (-1,)+tuple(range(15)),(False,True),(1,2,3,5)):
                rule=(*key,pair,two_positive,limit)
                rows,days,unmatched=portfolio(
                       races,options,typ,rule,period)
                if period==H2:
                    m=financial_audit(rows,days,y)
                    if m['races']<100 or m['paidRacePct']<20:
                        continue
                    strategies.append((rule,m))
    best=None;num_eligible=len(strategies);n_tested=0
    # Selection by cash ONLY on 2025H2. 2026 outcomes never used here.
    for rule,h2 in strategies:
        score=score_bank[rule[:3]]
        key=(int(h2['robust200']),
             h2['minusLargestRaceRoiPct'],
             h2['minusLargestTicketRoiPct'],h2['roiPct'],
             h2['races'])
        if best is None or key>best[0]:
            best=(key,rule,h2)
    if best is None:
        return {'status':'NO_CANDIDATE_WITH_MIN_100_RACES_AND_20PCT_PAID_RACES',
          'scoreFamilies':len(score_bank),'candidatesPassingFinancialHitFloor':0,
          'discovery':discovery,'adopt':False}
    _,rule,h2=best
    # The 2026 holdout is checked only AFTER rule is frozen.
    future_opts=race_market_best(races,y,ids,typ,
                      score_bank[rule[:3]],YR26)
    future_rows,days,unmatched=portfolio(races,future_opts,typ,rule,YR26)
    m26=financial_audit(future_rows,days,y)
    matching_conditions=rulebook[rule[:3]]
    print('SELECTIVE_ROI200_2025H2_SELECTED',json.dumps({
       'selectiveRule':rule,'financial':h2,
       'rulesInChosenFamily':len(matching_conditions),
       'scoredSubsetFamilies':len(score_bank),
       'eligiblePolicies':num_eligible},ensure_ascii=False),flush=True)
    print('SELECTIVE_ROI200_2026_FROZEN',json.dumps(m26,ensure_ascii=False),flush=True)
    return {'status':'PASS' if (h2['robust200'] and m26['robust200'])
       else 'NOT_ACCEPTABLE_200',
       'discovery':discovery,
       'policiesPassingMin100RacesAnd20Pct2025H2':num_eligible,
       'selectedSelectiveRule':{'min2024Through2025H1Support':rule[0],
             'conditionFamily':rule[1],'scoreVariant':rule[2],
             'marketPairIndex':rule[3],'requireBothMarketsQualify':rule[4],
             'racesPerVenueDayMaximum':rule[5]},
       'chosen2024H1Roi200ConditionExamples':matching_conditions[:30],
       'numberOfAvailableRulesInSelectedSubset':len(matching_conditions),
       '2025H2CashPolicySelection':h2,'2026JanMarFrozen':m26,
       'passesRobust200BothSelectionAndFrozen2026':bool(
                  h2['robust200'] and m26['robust200']),
       'historicalFinalWinOddsNotOfficialT15CombinationOdds':True,
       'thirdPartySettlementsNotReconciledWithOfficialJRA':True,
       '2026HadBeenStudiedBeforeByOtherResearch':True,
       'productionChanged':False,'adopt':False}

def main():
    if '--self-test' in sys.argv:
        rows=[(2.,1.,'r','202507',1,2,0)]
        m=financial_audit(rows,1,np.asarray([0,500,200]))
        assert m['roiPct']==350 and m['minusLargestTicketRoiPct']==100
        c=[(1.,1,0),(3.,2,1),(2.,3,2),
           (0.,4,3),(0.,5,4),(0.,6,5)]
        assert choose(c,-1,False)[-2:]==(2,3)
        assert choose(c,-1,True)[-2:]==(2,3)
        print('SELECTIVE_FINANCIAL_ROI200_SUBSET_DISCOVERY_UNIT_OK',flush=True)
        return
    began=time.monotonic()
    base=module('scripts/research-nov2026-roi200-first-pattern-search.py',
                 'roi_rule_minery')
    races,y,ids,typ,cat,dates,audit=load_data(base)
    print('SELECTIVE_FINANCIAL_PATTERN_UNIVERSE',json.dumps(
        {'races':len(races),'independentSevenRunnerSixMarketTickets':len(y),
        'actualPaidTickets':int((y>0).sum()),
        'notOldModelSelectedTickets':True},ensure_ascii=False),flush=True)
    scores,rulebook,discovery=discover_selective_cash_conditions(
                     base,typ,cat,y,ids,dates)
    print('SELECTIVE_ROI200_DISCOVERY',json.dumps(discovery,ensure_ascii=False),
          flush=True)
    if not scores:raise RuntimeError('NO_REAL_MONEY_ROI200_CONDITIONS_DISCOVERED')
    result=run_search(races,y,ids,typ,scores,rulebook,discovery)
    result['algorithm']='select individually profitable >=200% subset of independent group conditions, ticket chosen by own condition-paid-money; no fixed horse predictive head'
    result['dataSource']='pinned 2024-2026 third-party historical JRA six-market actual payout mirror'
    result['exploredRuleSubsets']={'families':list(FAMILIES),
       'minimumSampleSupport':list(MIN_SUPPORTS),
       'financialResponse':list(STYLES),
       'differentMarketPairs':15,
       'focusOneProfitableSubsetAtATime':True}
    result['elapsedSeconds']=round(time.monotonic()-began,2)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',
                   encoding='utf8')
    print('SELECTIVE_ROI200_FINANCIAL_RESULT',str(OUT),flush=True)
if __name__=='__main__':main()
