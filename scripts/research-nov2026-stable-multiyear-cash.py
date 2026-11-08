#!/usr/bin/env python3
"""New hypothesis: repeated profitable calendar years, not pooled jackpot ROI.
Historical third-party results, NOT JRA T-15 odds. Research only.
2015-2022 train; 2023 selection; 2024-26 post-selection diagnostics.
"""
import importlib.util,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis-results/nov2026-stable-multiyear-cash.json'
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod
    spec.loader.exec_module(mod);return mod
def audit(picks,payout,year_mask):
    chosen=picks & year_mask[:,None]
    n=int(chosen.sum())
    if not n:return dict(bets=0,stakeYen=0,paidYen=0,roiPct=None,minusMaxRacePct=None)
    race_cash=(payout*chosen).sum(axis=1,dtype=np.int64)
    cash=int(race_cash.sum());stake=100*n
    return dict(bets=n,stakeYen=stake,paidYen=cash,roiPct=round(cash/n,3),
      minusMaxRacePct=round((cash-int(race_cash.max()))/n,3),
      winningTickets=int(((payout>0)&chosen).sum()))
def main():
    base=load('scripts/research-nov2026-decade-roi-first-sixmarkets.py','base_cash')
    rolling=load('scripts/research-nov2026-rolling-cash-roi200-conditions.py','rolling_cash')
    paid,feat,races,years=rolling.data(base)
    # Reject pooled positive jackpots: require profitability in at least
    # 5 of 8 historical years, including 2021 and 2022, each >= 30 bets.
    years_train=np.arange(2015,2023)
    candidates=[]
    for pattern in base.PATTERNS:
        codes,groups=base.mixed_code(feat,pattern)
        annual=[]
        for yr in years_train:
            key=codes[years==yr].ravel()
            money=paid[years==yr].ravel()
            count=np.bincount(key,minlength=groups)
            cash=np.bincount(key,weights=money,minlength=groups)
            # New robustness hypothesis: remove the largest RACE payout
            # within each cell for EACH training year before ranking.
            largest=np.zeros(groups,dtype=np.float64)
            year_rows=np.flatnonzero(years==yr)
            for j in year_rows:
                positive=paid[j]>0
                if not np.any(positive):continue
                unique,reverse=np.unique(codes[j,positive],return_inverse=True)
                race_totals=np.bincount(reverse,weights=paid[j,positive])
                largest[unique]=np.maximum(largest[unique],race_totals)
            annual.append((count,np.maximum(0,cash-largest)))
        support=np.stack([x[0] for x in annual])
        income=np.stack([x[1] for x in annual])
        roi=np.divide(income,support,out=np.zeros_like(income),where=support>0)
        valid=support>=30
        positive=valid&(roi>=110)
        qualify=(support.sum(axis=0)>=500)&(positive.sum(axis=0)>=5)&positive[-1]&positive[-2]
        # Worst year and consistency are primary; pooled payout secondary.
        for group in np.flatnonzero(qualify):
            v=roi[:,group][valid[:,group]]
            score=(float(np.median(v)),float(np.quantile(v,.25)),int(support[:,group].sum()))
            candidates.append((score,pattern,int(group)))
    candidates.sort(key=lambda x:x[0],reverse=True)
    # Select rule-count using 2023 only, not 2024/25/26 outcomes.
    policies=[]
    for k in (1,3,5,10):
        signals=np.zeros_like(paid,dtype=bool)
        for _,pattern,group in candidates[:k]:
            codes,_=base.mixed_code(feat,pattern)
            signals|=(codes==group)
        # One ticket per market per race; choose two distinct markets.
        # Eligibility is based on historical stability, never race payouts.
        picks=np.zeros_like(signals)
        for m in range(6):
            a,b=int(base.START_MARKET[m]),int(base.START_MARKET[m+1])
            idx=np.argmax(signals[:,a:b],axis=1)
            rows=np.arange(len(years))
            valid=signals[rows,a+idx]
            picks[rows[valid],a+idx[valid]]=True
        # Only races with two or more distinct market signals; deterministic
        # first two markets. Equal stakes; 2 tickets per eligible race.
        market_mask=np.zeros((len(years),6),dtype=bool)
        for m in range(6):
            a,b=int(base.START_MARKET[m]),int(base.START_MARKET[m+1])
            market_mask[:,m]=picks[:,a:b].any(axis=1)
        chosen=np.zeros_like(picks)
        count=np.zeros(len(years),dtype=np.int8)
        for m in range(6):
            a,b=int(base.START_MARKET[m]),int(base.START_MARKET[m+1])
            accept=market_mask[:,m]&(count<2)
            chosen[accept,a:b]=picks[accept,a:b]
            count+=accept
        chosen[count!=2]=False
        stats=audit(chosen,paid,years==2023)
        # Require 100 settled races; do not select one-jackpot policies.
        n_races=int(np.sum(np.any(chosen & (years==2023)[:,None],axis=1)))
        stats['races']=n_races
        stats['passes2023SupportGate']=n_races>=100
        score=(stats['minusMaxRacePct'] or 0) if n_races>=100 else -1.
        policies.append((score,k,chosen,stats))
    policies.sort(key=lambda x:x[0],reverse=True)
    best=policies[0] if policies and policies[0][0]>=0 else None
    report={'hypothesis':'per-year maximum race payout removed; >=5/8 years and both 2021,2022 robust positive',
       'source':'third-party pinned JRA results payout mirror; final win odds are not T15',
       'officialT15Verified':False,'2025And2026PreviouslyInspected':True,
       'trainingYears':'2015-2022','selectionYear':2023,
       'qualifiedConditions':len(candidates),'productionDeployed':False,
       'selectionPolicySupportFloorRaces':100,'selectionPolicyCount':len(policies)}
    if best:
        _,k,chosen,selection=best
        report.update(selectedRuleCount=k,selection2023=selection,
          holdoutDiagnostics={str(y):audit(chosen,paid,years==y) for y in (2024,2025,2026)},
          chosenRules=[{'pattern':list(p),'code':g,'score':list(s)} for s,p,g in candidates[:k]],
          passes=False)
        # 2024+ are not pristine holdouts; T15 missing => cannot pass.
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('STABLE_MULTYEAR_CASH',json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
