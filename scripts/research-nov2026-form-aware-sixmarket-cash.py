#!/usr/bin/env python3
"""New ticket-level real-money learner using full-form, pre-result JRA form
and all SIX market tickets, not a horse-win model or ticket policy wrapper.

Pre-race state is reconstructed chronologically from all prior races with a
separate JRA runner archive. Identity match to the third-party six-market
payout mirror is based on name + number, not post-result payout. The model
predicts paid event and conditional paid yen; money score selects independently
enumerated race/ticket combinations. A 2025H1-only rule search selects a frozen
policy; 2025H2 and 2026 Jan-Mar are held out.

Archived FINAL win quotes are NOT verified JRA T-15 combination odds, and
third-party settlement source is not independently authenticated. No production.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass,asdict
from itertools import combinations,product
from pathlib import Path
import importlib.util,json,math,time,sys
import numpy as np
from lightgbm import LGBMClassifier,LGBMRegressor

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis-results/nov2026-form-aware-sixmarket-paid-money.json'
BASIC=ROOT/'scripts/research-nov2026-sixmarket-real-paid-cash.py'
FORMS=ROOT/'scripts/research-nov2026-56feature-sixmarket-pl-money.py'
PAIRS=tuple(combinations(range(6),2))
MARKETS=('単勝','ワイド','馬連','馬単','3連複','3連単')
# Chronology-safe attributes, explicitly indexed by canonical 56-feature schema.
HORSE_INDICES=(21,22,25,26,31,33,34,39,42,48,49,51,55)
N_ATTR=len(HORSE_INDICES)
FEATURE_COUNT=35+3*N_ATTR+N_ATTR+4
SEED=20261108

def mod(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    if not spec or not spec.loader:raise RuntimeError('MISSING_MODULE:'+str(path))
    x=importlib.util.module_from_spec(spec)
    sys.modules[name]=x
    spec.loader.exec_module(x)
    return x

def enrich_with_chronological_runner_forms(races,X,ids,combos,meta,off,lookup,horseX):
    # One race's 56-feature vectors used for ALL six-market candidate tickets,
    # no old selected ticket source and no future result in any form input.
    if X.shape[1]!=35 or len(X)!=len(combos):
        raise RuntimeError('SOURCE_PAID_COMBO_ALIGNMENT')
    full=np.zeros((len(X),FEATURE_COUNT),dtype=np.float32)
    full[:,:35]=X
    field_ok=0;no_source=0
    for rid,race in enumerate(races):
        a=int(np.searchsorted(ids,rid,'left'))
        b=int(np.searchsorted(ids,rid,'right'))
        if b-a!=206:raise RuntimeError('INDEPENDENT_SIX_MARKET_TICKET_COUNT')
        idx=lookup.get(race['id'])
        if idx is None:
            no_source+=1
            continue
        source=meta[idx]['horseNos']
        feats=horseX[int(off[idx]):int(off[idx+1])]
        if len(source)!=len(feats):raise RuntimeError('CHRONOLOGICAL_FORM_ROW_ALIGNMENT')
        mapped={int(horse):feats[i,HORSE_INDICES] for i,horse in enumerate(source)}
        usable=[mapped[h[0]] for h in race['horses'] if h[0] in mapped]
        if len(usable)<6:
            no_source+=1
            continue
        # Critical: runner feature rows are from state at the start of the
        # race calendar day, not the race's finish results.
        mean=np.mean(usable,axis=0).astype(np.float32)
        for j in range(a,b):
            c=combos[j][1]
            for k,num in enumerate(c):
                if num in mapped:
                    full[j,35+k*N_ATTR:35+(k+1)*N_ATTR]=mapped[num]
            full[j,35+3*N_ATTR:35+4*N_ATTR]=mean
        full[a:b,-4:]=(
            np.asarray([[float(feats[:,21].mean()),
                         float(feats[:,22].max()),
                         float(feats[:,49].max()),
                         float(feats[:,34].std())]],dtype=np.float32))
        field_ok+=1
    if field_ok<len(races)*.75:
        raise RuntimeError('INSUFFICIENT_TRUE_CHRONOLOGICAL_FORM_COVERAGE')
    if not np.isfinite(full).all():
        raise RuntimeError('INVALID_PRE_RESULT_TICKET_FEATURE')
    print('FORM_AWARE_CASH_FEATURES',json.dumps({
      'rows':int(len(X)),'features':int(full.shape[1]),
      'joinedRaces':field_ok,'missingRaces':no_source,
      'oldModelBetSelectionsUsed':False}),flush=True)
    return full

def fit_money(X,y,ids,types,races,cutoff):
    yy=np.asarray(y,dtype=np.float32)
    years=np.asarray([int(races[int(i)]['month'][:4]) for i in ids])
    train=(years>=2024)&(years<=cutoff)
    positive=train&(yy>0)
    if int(positive.sum())<8000:raise RuntimeError('INSUFFICIENT_PAID_EVENTS')
    common=dict(n_estimators=180,learning_rate=.028,num_leaves=23,
        min_child_samples=160,colsample_bytree=.86,reg_alpha=1.2,
        reg_lambda=24.,random_state=SEED,n_jobs=2,verbosity=-1)
    event=LGBMClassifier(objective='binary',**common)
    # Discount 3連単's 120 rows relative to WIN's six rows to stop
    # class imbalance swamping smaller markets.
    multiplicity=np.asarray([6,15,15,30,20,120],dtype=np.float32)
    wt=(1./multiplicity[types[train]])
    event.fit(X[train],(y[train]>0).astype(np.int8),sample_weight=wt)
    size=LGBMRegressor(objective='huber',alpha=.8,
        **{**common,'min_child_samples':75,'n_estimators':190})
    cap=[]
    for m in range(6):
        samples=yy[positive&(types==m)]
        if len(samples)<150:raise RuntimeError('PAID_MARKET_TOO_FEW_SAMPLES')
        cap.append(float(np.quantile(samples,.99)))
    size.fit(X[positive],np.log(np.minimum(yy[positive],
                      np.asarray(cap)[types[positive]])),
             sample_weight=1./multiplicity[types[positive]])
    prob=event.predict_proba(X)[:,1].astype(np.float32)
    cond=np.exp(size.predict(X)).astype(np.float32)
    # Market-specific smearing estimated from training WINNING tickets only.
    smears=[]
    for m in range(6):
        local=positive&(types==m)
        ratios=yy[local]/np.maximum(cond[local],100.)
        smears.append(float(np.clip(np.mean(np.minimum(ratios,6)),1.,4.)))
    payout=np.maximum(cond,100.)*np.asarray(smears,dtype=np.float32)[types]
    return prob,payout,{'through':cutoff,'trainTickets':int(train.sum()),
            'positiveTrainTickets':int(positive.sum()),
            'market99PctCap':dict(zip(MARKETS,cap)),
            'trainOnlySmear':dict(zip(MARKETS,smears))}

def candidate_money_scores(prob,amount,method):
    kind,scale,penalty=method
    if kind=='linear':
        score=prob*amount
    elif kind=='sqrt_payout':
        score=prob*np.sqrt(amount)
    elif kind=='p75':
        score=np.power(np.maximum(prob,1e-8),.75)*amount
    elif kind=='capped':
        score=prob*np.minimum(amount,scale)
    else:raise RuntimeError('UNKNOWN_REAL_CASH_VARIANT')
    if penalty:
        score=score/(1.+penalty*np.log1p(amount/1000))
    return np.nan_to_num(score,nan=0,posinf=0).astype(np.float32)

def each_market_best(races,ids,types,y,tickets,score):
    best=[]
    for rid,r in enumerate(races):
        a=int(np.searchsorted(ids,rid,'left'))
        b=int(np.searchsorted(ids,rid,'right'))
        sub=score[a:b]
        subtypes=types[a:b]
        opts=[]
        for m in range(6):
            local=np.flatnonzero(subtypes==m)
            i=a+int(local[np.argmax(sub[local])])
            opts.append((float(score[i]),int(y[i]),tuple(tickets[i][1])))
        best.append(opts)
    return best

def best_pair(cands,pair,overlap):
    pairs=PAIRS if pair<0 else (PAIRS[pair],)
    best=None
    for a,b in pairs:
        left=cands[a];right=cands[b]
        shared=len(set(left[2]).intersection(right[2]))
        quality=(left[0]+right[0])*(1-overlap*shared/3)
        candidate=(quality,-a,-b,a,b,left[1],right[1])
        if best is None or candidate[:3]>best[:3]:best=candidate
    return best

def portfolio(races,by_race,period,pair,overlap):
    days=defaultdict(list)
    for i,r in enumerate(races):
        if not period[0]<=r['month']<period[1]:continue
        q,_,__,a,b,paid1,paid2=best_pair(by_race[i],pair,overlap)
        days[r['day']].append((q,r['id'],r['month'],a,b,paid1,paid2))
    rows=[];missing=0
    for day,records in days.items():
        if len(records)<5:missing+=1;continue
        rows.extend(sorted(records,key=lambda t:(-t[0],t[1]))[:5])
    return rows,missing,len(days)

def money_audit(rows,missing,days):
    n=len(rows);stake=n*2000
    returns=[(r[5]+r[6])*10 for r in rows]
    gross=sum(returns)
    biggest_ticket=max((p*10 for r in rows for p in (r[5],r[6])),default=0)
    biggest_race=max(returns,default=0)
    hit=sum(x>0 for x in returns)
    months=defaultdict(lambda:[0,0,0])
    for r,ret in zip(rows,returns):
        entry=months[r[2]]
        entry[0]+=1;entry[1]+=ret;entry[2]+=int(ret>0)
    pct=lambda v,d:round(v/d*100,5) if d else None
    return dict(races=n,venueDays=days,incompleteVenueDays=missing,
      stakeYen=stake,paidYen=gross,profitYen=gross-stake,
      roiPct=pct(gross,stake),
      roiWithoutLargestTicketPct=pct(gross-biggest_ticket,stake),
      roiWithoutLargestRacePct=pct(gross-biggest_race,stake),
      hitRacePct=pct(hit,n),
      byMonth={k:dict(races=v[0],roiPct=pct(v[1],v[0]*2000),
                hitRacePct=pct(v[2],v[0])) for k,v in sorted(months.items())},
      meetsHistoricalRobust200=bool(n>=100 and hit/n>=.2 and
         gross-biggest_ticket>=2*stake and gross-biggest_race>=2*stake and missing==0))

def variants():
    return list(product(('linear','sqrt_payout','p75','capped'),
         (5000,20000),(0.,.2)))

def main():
    if '--self-test' in sys.argv:
        assert len(PAIRS)==15 and FEATURE_COUNT==91
        f=np.asarray([1,2]);q=np.asarray([100,400])
        assert candidate_money_scores(f,q,('linear',5000,0)).tolist()==[100.,800.]
        print('SIX_MARKET_FORM_AWARE_FINANCIAL_SELFTEST_OK',flush=True)
        return
    start=time.monotonic()
    source=mod(BASIC,'form_aware_public_payout')
    form=mod(FORMS,'form_aware_chronological_56')
    races,audit=source.read_pinned_csv()
    X,y,ids,market,tickets,_=source.build_actual_payout_rows(races)
    source_names=form.read_source_horse_names()
    horseX,horselabels,offsets,meta,archive_names,miss=form.historical_horse_features()
    lookup=form.join_pre_result_races_by_horse_identity(races,meta,archive_names,source_names)
    full=enrich_with_chronological_runner_forms(races,X,ids,tickets,
                                            meta,offsets,lookup,horseX)
    p,a,fit2024=fit_money(full,y,ids,market,races,2024)
    chosen=None;tested=0;eligible=0
    for variant in variants():
        score=candidate_money_scores(p,a,variant)
        bets=each_market_best(races,ids,market,y,tickets,score)
        for pair,overlap in product((-1,)+tuple(range(15)),(0.,.3)):
            rows,missed,days=portfolio(races,bets,('202501','202507'),pair,overlap)
            met=money_audit(rows,missed,days)
            tested+=1
            if met['races']<500 or met['hitRacePct']<20 or missed:continue
            eligible+=1
            key=(int(met['meetsHistoricalRobust200']),
              met['roiWithoutLargestRacePct'],met['roiPct'],met['races'])
            if chosen is None or key>chosen[0]:
                chosen=(key,variant,pair,overlap,met)
    if chosen is None:raise RuntimeError('NO_2025H1_MONEY_POLICY_WITH_FULL_COVERAGE_AND_HIT_FLOOR')
    _,variant,pair,overlap,h1=chosen
    print('FORM_AWARE_CASH_2025_SELECTION',json.dumps({'variant':variant,
          'pair':pair,'overlap':overlap,'2025H1':h1,'policies':tested,
          'eligible':eligible},ensure_ascii=False),flush=True)
    scored=candidate_money_scores(p,a,variant)
    bets=each_market_best(races,ids,market,y,tickets,scored)
    rows,missed,days=portfolio(races,bets,('202507','202601'),pair,overlap)
    h2=money_audit(rows,missed,days)
    print('FORM_AWARE_CASH_2025H2_HOLDOUT',json.dumps(h2,ensure_ascii=False),flush=True)
    p26,a26,fit2025=fit_money(full,y,ids,market,races,2025)
    scored=candidate_money_scores(p26,a26,variant)
    bets=each_market_best(races,ids,market,y,tickets,scored)
    rows,missed,days=portfolio(races,bets,('202601','202604'),pair,overlap)
    h26=money_audit(rows,missed,days)
    print('FORM_AWARE_CASH_2026_FROZEN',json.dumps(h26,ensure_ascii=False),flush=True)
    report={'algorithm':'chronological 56-feature full field form ticket-level paid-event LightGBM + conditional paid-yen LightGBM',
        'oldPreselectedTicketsUsed':False,
        'allSixMarketsAll15Pairs':True,
        'racesPerVenueDay':5,'sourceAudit':audit,'2024Fit':fit2024,
        'policyCandidatesSearched':tested,'policyCandidatesPassingH1CoverageHit':eligible,
        'chosenVariant':variant,'chosenPair':pair,'chosenOverlap':overlap,
        '2025H1':h1,'2025H2':h2,'refit2024And2025':fit2025,
        '2026':h26,'passesBothHoldoutsRobust200':bool(
                    h2['meetsHistoricalRobust200'] and h26['meetsHistoricalRobust200']),
        'sourceIsThirdPartyNotOfficialReconciled':True,
        'preT15SixMarketOddsMissing':True,
        '2026HadBeenInspectedPreviously':True,
        'productionPromotionAllowed':False,
        'runtimeSeconds':round(time.monotonic()-start,2)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('FORM_AWARE_SIX_MARKET_CASH_RESULT',str(OUT),flush=True)

if __name__=='__main__':main()
