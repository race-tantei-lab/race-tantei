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
def audit(picks,payout,year_mask,stakes=(100,100),market_pair=None,starts=None):
    chosen=picks & year_mask[:,None]
    n=int(chosen.sum())
    if not n:return dict(bets=0,stakeYen=0,paidYen=0,roiPct=None,minusMaxRacePct=None)
    if market_pair is None:
        race_cash=(payout*chosen).sum(axis=1,dtype=np.int64)
        stake=100*n
    else:
        race_cash=np.zeros(len(chosen),dtype=np.int64)
        for market,amount in zip(market_pair,stakes):
            a,b=int(starts[market]),int(starts[market+1])
            race_cash+=(payout[:,a:b]*chosen[:,a:b]).sum(axis=1,dtype=np.int64)*(amount//100)
        stake=sum(stakes)*int(chosen.any(axis=1).sum())
    cash=int(race_cash.sum())
    return dict(bets=n,stakeYen=stake,paidYen=cash,roiPct=round(100*cash/stake,3),
      minusMaxRacePct=round(100*(cash-int(race_cash.max()))/stake,3),
      winningTickets=int(((payout>0)&chosen).sum()))
def fixed_five_per_venue_day(chosen,races):
    """New policy: five chronologically fixed race numbers per venue/day.
    Eligible races depend ONLY on frozen ticket signals, never payouts.
    Require both market tickets; discard incomplete venue-days.
    """
    from collections import defaultdict
    groups=defaultdict(list)
    for i,r in enumerate(races):
        if int(chosen[i].sum())==2:
            rid=str(r['id'])
            # JRA 12-digit race ID: YYYY venue meeting day race number.
            key=(rid[:4],rid[4:6],rid[6:10])
            groups[key].append((int(rid[-2:]),i))
    keep=np.zeros(len(races),dtype=bool)
    for entries in groups.values():
        entries.sort()
        if len(entries)>=5:
            for _,i in entries[:5]:keep[i]=True
    return chosen & keep[:,None],keep

def audit_policy_invariants(chosen,races):
    """Reject accidental over-selection or same-market pair in any venue-day."""
    from collections import Counter
    assert chosen.shape[0]==len(races)
    base=load('scripts/research-nov2026-decade-roi-first-sixmarkets.py','invariant_base')
    counts=Counter()
    ids=set()
    for i in np.flatnonzero(chosen.any(axis=1)):
        rid=str(races[int(i)]['id'])
        assert rid not in ids, 'duplicate race id'
        ids.add(rid)
        assert chosen[i].sum()==2, 'not exactly two bets per race'
        markets=[m for m in range(6) if chosen[i,int(base.START_MARKET[m]):int(base.START_MARKET[m+1])].any()]
        assert len(markets)==2, 'same-market duplicate tickets'
        counts[(rid[:4],rid[4:6],rid[6:10])]+=1
    assert all(n==5 for n in counts.values()), 'venue-day not exactly five races'
    return {'venueDays':len(counts),'races':len(ids),'twoDistinctMarkets':True,'fivePerVenueDay':True}

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
    # NEW HYPOTHESIS: learn which TWO market types to pair using only
    # 2023 cash, rather than always picking the first two market types.
    # Each market has at most one deterministic ticket per race.
    # This evaluates 15 predeclared market pairs x 4 rule budgets.
    # 2024+ payouts are never used to choose the pair or ticket budget.
    from itertools import combinations
    # New experiment: a policy must be supported in BOTH chronological
    # halves of 2023; choose by the weaker half's outlier-removed cash ROI.
    # This reduces selection of a single lucky six-month jackpot.
    first_half=np.asarray([int(str(r['month'])[4:6])<=6 for r in races],dtype=bool)
    # Predeclared calendar-quarter stability test; 2024+ remains evaluation only.
    quarter=np.asarray([(int(str(r['month'])[4:6])-1)//3 for r in races],dtype=np.int8)
    policy_count=0
    support_count=0
    concentration_count=0
    independent_count=0
    best=None
    for k in (1,3,5,10):
        signals=np.zeros_like(paid,dtype=bool)
        for _,pattern,group in candidates[:k]:
            codes,_=base.mixed_code(feat,pattern)
            signals|=(codes==group)
        market_picks=np.zeros_like(signals)
        for m in range(6):
            a,b=int(base.START_MARKET[m]),int(base.START_MARKET[m+1])
            idx=np.argmax(signals[:,a:b],axis=1)
            rows=np.arange(len(years))
            valid=signals[rows,a+idx]
            market_picks[rows[valid],a+idx[valid]]=True
        market_mask=np.zeros((len(years),6),dtype=bool)
        for m in range(6):
            a,b=int(base.START_MARKET[m]),int(base.START_MARKET[m+1])
            market_mask[:,m]=market_picks[:,a:b].any(axis=1)
        for m1,m2 in combinations(range(6),2):
            eligible=market_mask[:,m1]&market_mask[:,m2]
            chosen=np.zeros_like(signals)
            for m in (m1,m2):
                a,b=int(base.START_MARKET[m]),int(base.START_MARKET[m+1])
                chosen[eligible,a:b]=market_picks[eligible,a:b]
            chosen,venue_day_keep=fixed_five_per_venue_day(chosen,races)
            # NEW: cash-based asymmetric allocation; fixed ¥2000/race, 100-yen units.
            # Every allocation is selected ONLY on 2023, never on 2024+ results.
            for first_stake in (100,400,700,1000,1300,1600,1900):
                stakes=(first_stake,2000-first_stake)
                stats=audit(chosen,paid,years==2023,stakes,(m1,m2),base.START_MARKET)
                n_races=int(np.sum(venue_day_keep&(years==2023)))
                stats['races']=n_races
                first=audit(chosen,paid,(years==2023)&first_half,stakes,(m1,m2),base.START_MARKET)
                second=audit(chosen,paid,(years==2023)&~first_half,stakes,(m1,m2),base.START_MARKET)
                first_races=int(np.sum(venue_day_keep&(years==2023)&first_half))
                second_races=int(np.sum(venue_day_keep&(years==2023)&~first_half))
                stats['firstHalf2023']={**first,'races':first_races}
                stats['secondHalf2023']={**second,'races':second_races}
                quarter_stats=[]
                for q in range(4):
                    qmask=(years==2023)&(quarter==q)
                    qresult=audit(chosen,paid,qmask,stakes,(m1,m2),base.START_MARKET)
                    qresult['races']=int(np.sum(venue_day_keep&qmask))
                    quarter_stats.append(qresult)
                stats['quarters2023']=quarter_stats
                # New selection hypothesis: each quarter must have >=20 races;
                # maximize the WORST quarter's cash ROI after removing its
                # single largest paying race. No evaluation-period tuning.
                stats['passes2023SupportGate']=(n_races>=100 and first_races>=30 and second_races>=30
                      and all(q['races']>=20 for q in quarter_stats))
                # New hypothesis: select a policy by its weakest quarter after
                # removing its largest paying RACE, then penalize dependence on
                # the two largest race payouts across the entire selection year.
                # A stable quarterly return alone can conceal two jackpots.
                year_rows=np.flatnonzero(years==2023)
                selected_cash=np.zeros(len(year_rows),dtype=np.int64)
                for market,amount in zip((m1,m2),stakes):
                    a,b=int(base.START_MARKET[market]),int(base.START_MARKET[market+1])
                    selected_cash+=(paid[year_rows,a:b]*chosen[year_rows,a:b]).sum(axis=1,dtype=np.int64)*(amount//100)
                top_two=np.sort(selected_cash)[-2:]
                ex_two=int(selected_cash.sum())-int(top_two.sum())
                stats['minusTwoLargestRacesPct']=(round(100*ex_two/stats['stakeYen'],3)
                    if stats['bets'] else None)
                stats['passesConcentrationGate']=(stats['passes2023SupportGate']
                    and stats['minusTwoLargestRacesPct'] is not None
                    and stats['minusTwoLargestRacesPct']>=200)
                # NEW independent hypothesis: both market legs must generate
                # positive robust CASH returns on 2023, rather than a single
                # jackpot-rich market subsidising the second market.
                # Each leg is staked ¥100 per chosen race; no outcome is used
                # to select its ticket. 2024+ remains untouched by selection.
                leg_robust=[]
                for market in (m1,m2):
                    a,b=int(base.START_MARKET[market]),int(base.START_MARKET[market+1])
                    leg_race=(paid[year_rows,a:b]*chosen[year_rows,a:b]).sum(axis=1,dtype=np.int64)
                    leg_cash=int(leg_race.sum())
                    leg_largest=int(leg_race.max()) if len(leg_race) else 0
                    leg_robust.append(round((leg_cash-leg_largest)/n_races,3) if n_races else 0.)
                stats['marketLegMinusMaxRaceRoiPct']=leg_robust
                stats['passesIndependentMarketLegs']=(stats['passesConcentrationGate']
                    and min(leg_robust)>=110.)
                score=(min(q['minusMaxRacePct'] for q in quarter_stats)
                       if stats['passesIndependentMarketLegs'] else -1.)
                policy_count+=1
                support_count+=int(stats['passes2023SupportGate'])
                concentration_count+=int(stats['passesConcentrationGate'])
                independent_count+=int(stats['passesIndependentMarketLegs'])
                if score>=0 and (best is None or score>best[0]):
                    best=(score,k,(m1,m2),chosen.copy(),stats,stakes)
    report={'hypothesis':'per-year maximum race payout removed; >=5/8 years and both 2021,2022 robust positive',
       'source':'third-party pinned JRA results payout mirror; final win odds are not T15',
       'officialT15Verified':False,'2025And2026PreviouslyInspected':True,
       'trainingYears':'2015-2022','selectionYear':2023,
       'qualifiedConditions':len(candidates),'productionDeployed':False,
       'newHypothesis2':'exactly five deterministic qualifying races per venue/day, with two different market tickets per race','selectionPolicySupportFloorRaces':100,'selectionHalfYearFloorRaces':30,'selectionQuarterFloorRaces':20,'selectionScore':'minimum of four 2023 quarter max-race-removed ROIs, requiring 2023 ROI >=200 after excluding TWO largest payout races','selectionPolicyCount':policy_count,'cashAllocationHypothesis':'seven fixed ¥2000 allocations, 2023 selection only','supportedPolicyCount':support_count,'concentrationQualifiedPolicyCount':concentration_count,'independentMarketLegQualifiedPolicyCount':independent_count,'newHypothesis':'predeclared 15 market pairs selected on 2023 cash only'}
    if best:
        _,k,pair,chosen,selection,stakes=best
        report['policyInvariantAudit']=audit_policy_invariants(chosen,races)
        report.update(selectedRuleCount=k,selectedMarketPair=[base.MARKETS[m] for m in pair],selectedStakeYen=list(stakes),selection2023=selection,
          holdoutDiagnostics={str(y):audit(chosen,paid,years==y,stakes,pair,base.START_MARKET) for y in (2024,2025,2026)},
          chosenRules=[{'pattern':list(p),'code':g,'score':list(s)} for s,p,g in candidates[:k]],
          passes=False)
        # 2024+ are not pristine holdouts; T15 missing => cannot pass.
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('STABLE_MULTYEAR_CASH',json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
