#!/usr/bin/env python3
"""Directly DISCOVER historical REAL-PAID >200% ROI ticket conditions.

Unlike prior forecast-then-test learners, mine pre-result condition conjunctions
first, keep ONLY those whose 2024 actually paid money >=200% even AFTER
removing their largest paid ticket without reducing original stake. These
discovered conditions ARE the generating rules. Freeze them before 2025.
Search buying portfolios on 2025H1 ONLY, lock, evaluate 2025H2 and 2026JanMar.

Candidates are freshly generated for all six JRA markets from seven lowest
historical final-odds runners, NOT prior-model selected wagers. Caveats:
pinned CSV is third-party JRA payout mirror, not independently official-paid
reconciled; historical final WIN odds are NOT verified official T-15 six
combination quotations. Neither full-history 200% nor prospective gain can
be inferred from a 2024 mined condition. All live production unchanged.
"""
from __future__ import annotations
from collections import defaultdict,Counter
from itertools import combinations,product
from pathlib import Path
import importlib.util,json,math,os,sys,time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis-results/nov2026-roi200-first-rule-discovery.json'
SEED=20261108
MARKETS=('単勝','ワイド','馬連','馬単','3連複','3連単')
PAIR_TYPES=tuple(combinations(range(6),2))
BASE_FEATURES={
    'rankMin':7,'rankMax':7,'rankSum':7,'favorites':4,'rankSpread':7,
    'oddGeom':8,'age':4,'weight':4,'draw':4,'rankCode':343,
    'ticketPriceSpread':5,
}
CONTEXT_FEATURES={'venue':10,'raceBand':3,'fieldBand':3,'quarter':4,
                  'favoriteOdds':4}
DISCOVERY_SIGNATURES=[
  ('rankMin',),('rankMax',),('rankSum',),('favorites',),
  ('rankSpread',),('oddGeom',),('age',),('weight',),('draw',),
  ('rankCode',),('ticketPriceSpread',),
  ('rankMin','rankMax'),('rankMin','rankSum'),
  ('rankMax','rankSum'),('rankMin','oddGeom'),
  ('rankMax','oddGeom'),('rankSum','oddGeom'),
  ('favorites','oddGeom'),('rankSpread','oddGeom'),
  ('favorites','rankSpread'),('favorites','age'),
  ('rankMin','age'),('rankMax','fieldBand'),
  ('oddGeom','draw'),('draw','rankSum'),
  ('rankCode','oddGeom')
]
SCOPES=((),('venue',),('raceBand',),('fieldBand',),('quarter',),
        ('favoriteOdds',),('venue','raceBand'),
        ('venue','fieldBand'),('raceBand','fieldBand'))
MIN_GROUP_TICKETS=(30,60,120,240)
MIN_GROUP_WINS=(2,4,8)

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError('RESEARCH_SOURCE_MISSING')
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj

def categoricals(races,X,ids,types,tickets):
    n=len(ids)
    out={k:np.empty(n,dtype=np.uint16 if radix>255 else np.uint8)
         for k,radix in {**BASE_FEATURES,**CONTEXT_FEATURES}.items()}
    rank_min=out['rankMin'];rank_max=out['rankMax']
    rank_sum=out['rankSum'];fav_cnt=out['favorites']
    rankspread=out['rankSpread'];rankcode=out['rankCode']
    venue=out['venue'];rband=out['raceBand'];fband=out['fieldBand']
    quarter=out['quarter'];fave_odds=out['favoriteOdds']
    for rid,r in enumerate(races):
        a=int(np.searchsorted(ids,rid,'left'))
        b=int(np.searchsorted(ids,rid,'right'))
        if b-a!=336:raise RuntimeError('NO_INDEPENDENT_TOP7_SIX_MARKET_UNIVERSE')
        ranking={h[0]:i for i,h in enumerate(r['horses'][:7])}
        code=int(r['venue'])-1
        v=np.clip(code,0,9)
        month=int(r['month'][4:])
        fields=len(r['horses'])
        fob=float(r['horses'][0][1])
        favband=0 if fob<2 else 1 if fob<3 else 2 if fob<4.5 else 3
        for j in range(a,b):
            ranks=tuple(ranking[k] for k in tickets[j][1])
            least=min(ranks);greatest=max(ranks)
            rank_min[j]=least;rank_max[j]=greatest
            rank_sum[j]=min(sum(ranks)//2,6)
            fav_cnt[j]=sum(z<=1 for z in ranks)
            rankspread[j]=greatest-least
            slots=list(ranks)+[0]*(3-len(ranks))
            rankcode[j]=slots[0]*49+slots[1]*7+slots[2]
        venue[a:b]=v
        rband[a:b]=min((r['no']-1)//4,2)
        fband[a:b]=0 if fields<=11 else 1 if fields<=14 else 2
        quarter[a:b]=(month-1)//3
        fave_odds[a:b]=favband
    # Existing 35 features consist only of ticket input fields known BEFORE
    # the race result, apart from the final-price timing limitation.
    odd=np.exp(X[:,16]+X[:,17]+X[:,18])
    lengths=np.asarray([1,2,2,2,3,3],dtype=np.int8)[types]
    geom=np.exp((X[:,16]+X[:,17]+X[:,18])/lengths)
    out['oddGeom'][:]=np.digitize(geom,[2,3.5,5.5,8,12,20,40]).astype(np.uint8)
    out['age'][:]=np.digitize(X[:,26]*18,[3.3,4.3,5.3]).astype(np.uint8)
    out['weight'][:]=np.digitize(X[:,27]*80,[53,55,57]).astype(np.uint8)
    out['draw'][:]=np.digitize(X[:,28]*18,[4,9,14]).astype(np.uint8)
    out['ticketPriceSpread'][:]=np.digitize(
       np.maximum(X[:,22],1.)/np.maximum(X[:,21],1.),
       [1.5,2.5,4.,8.]).astype(np.uint8)
    for name,radix in {**BASE_FEATURES,**CONTEXT_FEATURES}.items():
        if np.any(out[name]>=radix):raise RuntimeError('PRE_RESULT_CATEGORY_OVERFLOW:'+name)
    return out

def all_patterns():
    seen=set()
    for signature,context in product(DISCOVERY_SIGNATURES,SCOPES):
        fields=('market',)+signature+context
        if len(fields)!=len(set(fields)):continue
        if fields in seen:continue
        seen.add(fields)
        yield fields

def mixed_code(fields,types,cat):
    code=types.astype(np.int32)
    radix=6
    for name in fields[1:]:
        width=(BASE_FEATURES|CONTEXT_FEATURES)[name]
        code=code*width+cat[name].astype(np.int32)
        radix*=width
    if radix>6*343*10*10*5:raise RuntimeError('EXCESSIVE_RULE_CARDINALITY')
    return code,radix

def mine_roi200_rules(types,cat,y,train,all_year_indices):
    # Numeric min actual payout: each ticket costs ¥100, and y carries its
    # actual paid yen per ¥100 ticket. No odds projection/horse win metric.
    win_train=train&(y>0)
    rule_types=[];accepted=Counter()
    best_rule_examples=[]
    group_max_count=0
    # Four independent minimum support settings. Mine 2024 alone;
    # 2025 H1 outcomes are NOT permitted inside these ROI cells.
    scores={limit:{scope:np.zeros(len(y),dtype=np.float32)
                   for scope in ('broad','context','all')}
            for limit in MIN_GROUP_TICKETS}
    scored_sources={limit:{scope:np.zeros(len(y),dtype=np.uint8)
                   for scope in ('broad','context','all')}
            for limit in MIN_GROUP_TICKETS}
    cols=0;num_pass=0;eligible_codes=0
    for fields in all_patterns():
        cols+=1
        group,ngroups=mixed_code(fields,types,cat)
        cnt=np.bincount(group[train],minlength=ngroups)
        paid=np.bincount(group[train],weights=y[train],minlength=ngroups)
        winning=np.bincount(group[win_train],minlength=ngroups)
        largest=np.zeros(ngroups,dtype=np.int32)
        np.maximum.at(largest,group[win_train],y[win_train])
        # Trim keeps original investment (the stake for the largest paid
        # ticket is NOT returned to the denominator).
        trimmed=(paid-largest)/np.maximum(cnt*100,1)
        pass200=(trimmed>=2.)&(paid>=2*cnt*100)&(winning>=2)
        nqual=int(np.sum(pass200&(cnt>=30)))
        if nqual:
            eligible_codes+=nqual
            group_max_count=max(group_max_count,int(np.max(cnt[pass200&(cnt>=30)])))
        for limit in MIN_GROUP_TICKETS:
            valid=pass200&(cnt>=limit)
            valid &= (winning >= (2 if limit==30 else 3 if limit==60 else 4 if limit==120 else 6))
            size=int(valid.sum())
            if not size:continue
            accepted[(limit,len(fields)-1)]+=size
            scope='broad' if len(fields)==2 else 'context'
            raw=np.clip(trimmed,2.,20.)
            confidence=np.minimum(cnt/(cnt+80.),.95)*winning/(winning+5.)
            # Exact search score is SUPPORTED TRIMMED ROI from past bets.
            score=(np.maximum(raw-1,0.)*confidence).astype(np.float32)
            score[~valid]=0
            idx=group
            values=score[idx]
            np.maximum(scores[limit][scope],values,
                       out=scores[limit][scope])
            np.maximum(scores[limit]['all'],values,
                       out=scores[limit]['all'])
        if nqual:
            rows=np.flatnonzero(pass200&(cnt>=60))
            if len(rows):
                order=np.argsort(-trimmed[rows])[:3]
                for c in rows[order]:
                    best_rule_examples.append({
                        'fields':fields,'categoryCode':int(c),
                        'sampleTickets2024':int(cnt[c]),
                        'paidWinningTickets2024':int(winning[c]),
                        'roiPct2024':round(100*paid[c]/(cnt[c]*100),4),
                        'trimLargestTicketRoiPct2024':round(100*trimmed[c],4)
                    })
    summary={'featureSchemasSearched':cols,
        'totalDistinct2024QualifiedPatternCellsBeforeMinSupport':eligible_codes,
        'maxGroupSupport':group_max_count,
        'eligibleByMinSupportAndRuleComplexity':{
           str(k):v for k,v in accepted.items()},
        'historical2024RuleSamples':sorted(
           best_rule_examples,key=lambda x:-x['sampleTickets2024'])[:25],
        'everyAcceptedRuleHad2024PaidRoiAndTrimmedPaidRoiAtLeast200':True,
        '2025Or2026OutcomeLabelsSeenDuringMining':False}
    return scores,summary

def best_tickets_per_race(races,ids,types,score,period):
    # Score is computed ONLY from financially qualifying 2024 condition cells.
    # No 2025/26 target payout is read until AFTER ticket/race choice.
    out={}
    for rid,r in enumerate(races):
        if not period[0]<=r['month']<period[1]:continue
        a=int(np.searchsorted(ids,rid,'left'))
        b=int(np.searchsorted(ids,rid,'right'))
        opts=[]
        for market in range(6):
            avail=np.flatnonzero(types[a:b]==market)
            j=a+int(avail[np.argmax(score[a:b][avail])])
            opts.append((float(score[j]),j,market))
        opts.sort(key=lambda q:(-q[0],q[2],q[1]))
        out[rid]=opts
    return out

def settle(races,top,y,cutoff,maxr,pair=None):
    groups=defaultdict(list)
    for rid,opts in top.items():
        good=[z for z in opts if z[0]>=cutoff]
        if pair is not None:
            good=[z for z in good if z[2] in pair]
        if len(good)<2:continue
        best=good[:2]
        if best[0][2]==best[1][2]:raise RuntimeError('NOT_TWO_DISTINCT_MARKETS')
        score=best[0][0]+best[1][0]
        r=races[rid]
        groups[r['day']].append((score,r['id'],r['month'],best))
    rows=[]
    for day,choices in groups.items():
        choices.sort(key=lambda x:(-x[0],x[1]))
        rows.extend(choices[:maxr])
    return rows,len(groups)

HEDGES={
    'win_favorite':(0,0),'win_second':(1,0),
    'wide_fav_two':(7,1),'wide_fav_third':(8,1),
    'wide_second_third':(13,1),'quinella_favorite':(28,2),
    'exacta_favorite':(49,3),'trio_favorite':(91,4),
}

def settle_with_historical_roi200_anchor(
        races,top,cutoff,maxr,hedge,main_market=None):
    """Two different markets. First ticket MUST satisfy a historical ROI200
    group. Second ticket is a fixed pre-result popular anchor, so its
    inclusion is evaluated as PART OF THE PORTFOLIO actual money rule.
    Anchor is NEVER chosen with settled results or hindsight.
    """
    offs,hedge_market=HEDGES[hedge]
    groups=defaultdict(list)
    for rid,opts in top.items():
        choices=[p for p in opts if p[0]>=cutoff
                 and p[2]!=hedge_market and
                 (main_market is None or p[2]==main_market)]
        if not choices:continue
        first=choices[0]
        other=(0.,rid*336+offs,hedge_market)
        r=races[rid]
        groups[r['day']].append((first[0],r['id'],r['month'],[first,other]))
    rows=[]
    for day,options in groups.items():
        options.sort(key=lambda x:(-x[0],x[1]))
        rows.extend(options[:maxr])
    return rows,len(groups)

def financial_audit(rows,days):
    n=len(rows);stake=n*2000
    # Rows hold labels only once selected; actual amount is attached by caller.
    paid=[r[-1] for r in rows]
    gross=sum(paid)
    maxrace=max(paid,default=0)
    maxsingle=max((z for row in rows for z in row[-2]),default=0)
    winning=sum(p>0 for p in paid)
    def pct(x,d):return round(100*x/d,5) if d else None
    months=defaultdict(lambda:[0,0,0])
    for r,cash in zip(rows,paid):
        m=months[r[2]];m[0]+=1;m[1]+=cash;m[2]+=int(cash>0)
    return {'races':n,'venueDaysWithPredictions':days,
      'stakesYen':stake,'returnsYen':gross,'profitYen':gross-stake,
      'roiPct':pct(gross,stake),
      'roiMinusLargestTicketPct':pct(gross-maxsingle,stake),
      'roiMinusLargestRacePct':pct(gross-maxrace,stake),
      'hitRacePct':pct(winning,n),
      'months':{key:{'races':x[0],'roiPct':pct(x[1],x[0]*2000),
          'hitRacePct':pct(x[2],x[0])} for key,x in sorted(months.items())},
      'passesRobust200And20Hit':bool(stake and n>=100 and winning/n>=.2
          and gross>=2*stake and gross-maxsingle>=2*stake
          and gross-maxrace>=2*stake)}

def paid_after_fixed_choices(rows,y):
    result=[]
    for s,rid,month,chosen in rows:
        amounts=[int(y[item_id])*10 for _,item_id,_ in chosen]
        result.append((s,rid,month,chosen,amounts,sum(amounts)))
    return result

def main():
    if '--self-test' in sys.argv:
        assert len(PAIR_TYPES)==15
        a=paid_after_fixed_choices([(1,'a','202501',[(2.,1,0),(2.,2,1)])],
                         np.asarray([0,300,200]))
        result=financial_audit(a,1)
        assert result['returnsYen']==5000 and result['stakesYen']==2000
        assert result['roiMinusLargestTicketPct']==100.
        cats={k:np.zeros(400,dtype=np.uint16 if width>255 else np.uint8)
              for k,width in {**BASE_FEATURES,**CONTEXT_FEATURES}.items()}
        p=np.zeros(400,dtype=np.int8)
        payments=np.full(400,500,dtype=np.int32)
        derived,summary=mine_roi200_rules(p,cats,payments,
              np.ones(400,dtype=bool),np.arange(400,dtype=np.int32))
        assert summary['totalDistinct2024QualifiedPatternCellsBeforeMinSupport']>0
        assert derived[30]['all'].max()>0
        print('DIRECT_ROI200_FIRST_RULE_DISCOVERY_MONEY_SELFTEST_OK',flush=True)
        return
    started=time.monotonic()
    cache_data=ROOT/'analysis-results/roi200-public-2024-26-categories-v1.npz'
    cache_meta=ROOT/'analysis-results/roi200-public-2024-26-categories-v1.json'
    if cache_data.exists() and cache_meta.exists():
        source=json.loads(cache_meta.read_text(encoding='utf8'))
        races=source['races'];audit=source['audit']
        with np.load(cache_data,allow_pickle=False) as blob:
            y=blob['y'];ids=blob['ids'];types=blob['types']
            cat={k:blob['cat_'+k] for k in {**BASE_FEATURES,**CONTEXT_FEATURES}}
        print('ROI_FIRST_FULL_PRE_RESULT_CACHE_HIT',len(y),flush=True)
    else:
        original=load('scripts/research-nov2026-sixmarket-real-paid-cash.py',
                'direct_financial_pattern_source')
        original.TOP_HORSES=7
        races,audit=original.read_pinned_csv()
        X,y,ids,types,tickets,w=original.build_actual_payout_rows(races)
        cat=categoricals(races,X,ids,types,tickets)
        cache_data.parent.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(cache_data,y=y,ids=ids,types=types,
              **{'cat_'+k:v for k,v in cat.items()})
        cache_meta.write_text(json.dumps({'races':[
           {'id':r['id'],'month':r['month'],'day':r['day']} for r in races],
           'audit':audit},ensure_ascii=False),encoding='utf8')
        print('ROI_FIRST_SOURCE_CACHE_PREPARED',len(y),flush=True)
    months=np.asarray([r['month'] for r in races])
    train=(months[ids]<'202507')
    print('DIRECT_CASH_PATTERN_INPUT',json.dumps({
        'allPaidRaces':len(races),'allIndependentTickets':len(y),
        '2024TrainingTickets':int(train.sum()),'featureNames':list(cat),
        'nonzeroPaidCandidates':int(np.sum(y>0)),
        'oldSelectedBetTicketsUsed':0},ensure_ascii=False),flush=True)
    scores,scan=mine_roi200_rules(types,cat,y,train,ids)
    print('DIRECT_ROI200_PATTERN_DISCOVERY',json.dumps({
        k:v for k,v in scan.items() if k!='historical2024RuleSamples'},
        ensure_ascii=False),flush=True)
    if not scan['totalDistinct2024QualifiedPatternCellsBeforeMinSupport']:
        raise RuntimeError('NO_REAL_PAID_2024_ROI200_PATTERNS_WITH_SINGLE_WIN_TRIM')
    selected=None;tested=0;qualified=0
    cached={}
    for minimum in MIN_GROUP_TICKETS:
        for scope in ('broad','context','all'):
            score=scores[minimum][scope]
            if not (score>0).any():continue
            for period in (('202507','202601'),('202601','202604')):
                cached[(minimum,scope,period)]=best_tickets_per_race(
                    races,ids,types,score,period)
    best_any=None;more_than100=0;maxhit=0.
    for minimum,scope,threshold,maxr in product(
         MIN_GROUP_TICKETS,('broad','context','all'),
         (.04,.08,.15,.3,.6,1.2,2.5),(1,2,3,5)):
        key=(minimum,scope,('202507','202601'))
        if key not in cached:continue
        for mode,option in [('two_roi200',p) for p in (None,)+PAIR_TYPES]+[
              ('hedge_'+name,anchor)
              for name in HEDGES for anchor in (None,0,1,2,3,4,5)]:
            if mode=='two_roi200':
                rows,days=settle(races,cached[key],threshold,maxr,option)
            else:
                if option==HEDGES[mode.removeprefix('hedge_')][1]:continue
                rows,days=settle_with_historical_roi200_anchor(
                     races,cached[key],threshold,maxr,
                     mode.removeprefix('hedge_'),option)
            m=financial_audit(paid_after_fixed_choices(rows,y),days)
            tested+=1
            if m['races']>=100:
                more_than100+=1
                maxhit=max(maxhit,m['hitRacePct'])
                rank_any=(m['roiMinusLargestRacePct'],m['roiPct'],
                          m['hitRacePct'],m['races'])
                if best_any is None or rank_any>best_any[0]:
                    best_any=(rank_any,minimum,scope,threshold,maxr,mode,option,m)
            if m['races']<100 or m['hitRacePct']<20:continue
            qualified+=1
            rank=(int(m['passesRobust200And20Hit']),
                  m['roiMinusLargestRacePct'],m['roiPct'],m['races'])
            if selected is None or rank>selected[0]:
                selected=(rank,minimum,scope,threshold,maxr,mode,option,m)
    print('DIRECT_ROI200_2025H1_FINANCIAL_POLICY_SEARCH',json.dumps({
        'tested':tested,'atLeast100Races':more_than100,
        'with20PctHitAnd100Races':qualified,'maxHistoricalHit':maxhit,
        'strongestRoiWithoutHitGate':best_any[-1] if best_any else None},
        ensure_ascii=False),flush=True)
    if selected is None:
        # Do not claim an accepted profitable prediction. Persist complete
        # negative evidence so the next exploration is not blind repetition.
        negative={'method':'2024+2025H1 actual paid ROI200 condition-first mining',
                  'conditionSearch':scan,'selected':None,
                  'candidateRulesWith100Races':more_than100,
                  'candidateRulesWith100RacesAnd20Hit':qualified,
                  'highestRoiCandidateWithoutHitFloor':(
                       best_any[-1] if best_any else None),
                  'productionChanged':False,'adopt':False,
                  'seconds':round(time.monotonic()-started,2)}
        OUT.parent.mkdir(parents=True,exist_ok=True)
        OUT.write_text(json.dumps(negative,ensure_ascii=False,indent=2)+'\n',
                       encoding='utf8')
        print('DIRECT_ROI200_NO_QUALIFIED_PORTFOLIO',str(OUT),flush=True)
        return
    _,minimum,scope,threshold,maxr,mode,option,h1=selected
    print('DIRECT_ROI200_2025H2_POLICY_CHOSEN',json.dumps({
        'minimum2024TrainingTickets':minimum,'scope':scope,
        'historicScoreThreshold':threshold,'maxVenueDayRaces':maxr,
        'mode':mode,'option':option,
        'testedPolicies':tested,'eligiblePolicies':qualified,
        'actualCash':h1},ensure_ascii=False),flush=True)
    def future_money(period):
        key=(minimum,scope,period)
        if mode=='two_roi200':
            rows,days=settle(races,cached[key],threshold,maxr,option)
        else:
            rows,days=settle_with_historical_roi200_anchor(
              races,cached[key],threshold,maxr,mode.removeprefix('hedge_'),option)
        return financial_audit(paid_after_fixed_choices(rows,y),days)
    h2=h1  # 2025H2 policy-selection period, never a holdout
    yr26=future_money(('202601','202604'))
    print('DIRECT_ROI200_2025H2_SELECTION_ONLY',json.dumps(h2,ensure_ascii=False),flush=True)
    print('DIRECT_ROI200_2026_FROZEN',json.dumps(yr26,ensure_ascii=False),flush=True)
    accepted=bool(h1['passesRobust200And20Hit'] and
         h2['passesRobust200And20Hit'] and yr26['passesRobust200And20Hit'])
    report={'method':'FIRST mine conditions with ACTUAL 2024+2025H1 paid ROI >=200 after removing largest ticket; only THEN generate rules-based predictions',
        'sixPaidMarkets':True,'candidateHorsesPerRace':7,
        'independentlyGeneratedTicketCandidates':len(y),
        'ticketPredictionAlwaysBasedOnHistoricalROI200Condition':True,
        'conditionDiscoveryThrough':'2025-06',
        'policySelectionPeriod':'2025-07 through 2025-12',
        'singleOutOfTimeTest':'2026-01 through 2026-03',
        'source':audit,'conditionSearch':scan,
        'policyCandidateCount2025H1':tested,
        'qualifiedCandidateCount2025H1':qualified,
        'frozenRule':{'minConditionDiscoveryTickets':minimum,
            'conditionDiscoveryBefore':'2025-07',
            'scope':scope,'scoreThreshold':threshold,
            'maxVenueDayRaces':maxr,'strategy':mode,'strategyOption':option},
        '2025H2Selection':h1,'2026JanMar':yr26,
        'passesRobust200In2025H2SelectionAnd2026Test':accepted,
        '2026WasPreviouslyExaminedInResearch':True,
        'finalOddsNotJraT15CombinationOdds':True,
        'payoutSourceNotIndependentlyOfficialReconciled':True,
        'productionChanged':False,'adopt':False,
        'elapsedSeconds':round(time.monotonic()-started,2)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',
                   encoding='utf8')
    print('DIRECT_ROI200_FIRST_SEARCH_COMPLETE',str(OUT),flush=True)

if __name__=='__main__':main()
