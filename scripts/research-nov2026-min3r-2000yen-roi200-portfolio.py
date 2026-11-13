#!/usr/bin/env python3
"""CASH-FIRST MODEL EXPLORATION WITH THE USER'S TWO HARD CONSTRAINTS.

ONLY portfolio configurations with actual settled cash ROI >=200% AFTER
removing the largest race payout count as "candidates". Every JRA venue-day
in the input MUST have >=3 selected DIFFERENT races, with >=JPY 2,000 total
stake PER race. No sparse 'only jackpot day' illusion, no 100 yen/day totals.

2017-21 prior cash training only; 2022 cash-forward policy discovery;
2023-26 cash audit ONLY for 2022 discovered candidate policies. Six actual
JRA cash market types, 1,030 top-ten real combination ticket templates.
A 200% pattern is allowed to be only one constituent of the overall regime.
Unranked fallback tickets fill venue-day 3 minimum, but the whole-policy
real money must pass 200% for entry in the candidate result set.

Research: third-party settled payout mirror, historical final WIN odds NOT
verified JRA official T-15, no production deploy or D1 read/write.
"""
from __future__ import annotations
import collections,csv,gzip,importlib.util,itertools,json,math,sys,time
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-three-races-2000yen-cash200-search.json"
BETS=ROOT/"analysis-results/nov2026-three-races-2000yen-cash200-ledger.csv.gz"
MIN_RACES_PER_VENUE_DAY=3
PER_RACE_SPEND=2000
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
MARKET_PAIRS=list(itertools.combinations(range(6),2))
SETTINGS={
    "slates":(3,4,5),
    "pairs":tuple(MARKET_PAIRS)+("dynamic","one_market"),
    "split":(1000,1500,1900,100),
    "selection":("highest_cash_signal","medium_score","top_two","reverse"),
    "min_positive_score_day":0,
}
TRAIN=(2017,2018,2019,2020,2021)
DISCOVERY=2022
EVAL=(2023,2024,2025,2026)
def load(path,name):
    p=ROOT/path
    spec=importlib.util.spec_from_file_location(name,p)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod
def metrics(pay,venue_day_count=0):
    arr=np.asarray(pay,dtype=np.int64)
    amount=PER_RACE_SPEND*len(arr)
    earned=int(arr.sum())
    top=int(arr.max()) if len(arr) else 0
    return {"races":len(arr),"venueDays":int(venue_day_count),
        "stakeYen":amount,"paidYen":earned,
        "profitYen":earned-amount,
        "cashRoiPct":round(100*earned/amount,4) if amount else None,
        "minusLargestRaceCashRoiPct":round(100*(earned-top)/amount,4) if amount else None,
        "hitRacePct":round(100*np.count_nonzero(arr)/len(arr),4) if len(arr) else None,
        "maxRacePayoutYen":top}
def matches_goal(obj):
    return obj["venueDays"]>0 and obj["races"]>=3*obj["venueDays"] and (
        obj["cashRoiPct"] or 0)>=200 and (
        obj["minusLargestRaceCashRoiPct"] or 0)>=200
def feature_races():
    source=load("scripts/research-nov2026-frozen-sparse-cash-model.py","sparse_condition_functions")
    core,races,years,cash,cat=source.archive()
    if cash.shape!=(len(races),1030) or len(races)<26000:
        raise RuntimeError("NOT_ALL_JRA_TOP10_RACES_CASH_AVAILABLE")
    # Training only 2017-21. Cash-based pattern extraction, not win probs.
    buckets=source.frozen_cash_rules(years,cash,cat)
    # Candidate signal accepted ONLY if past actual yen ROI minus maximum
    # ticket paid >= 200%. Historical support n>=12, paid events>=2.
    score,rule_used=source.score_rules(
        buckets,cat,minimum=12,hit_min=2,robust_min=200,confidence=.25)
    # Each market, independent best actual buyable ticket, not a virtual bet.
    opts=np.empty((len(races),6),dtype=np.int16)
    signal=np.empty((len(races),6),dtype=np.float32)
    ranks,market=core.fixed_template()
    for m in range(6):
        ids=np.flatnonzero(market==m)
        choice=np.argmax(score[:,ids],axis=1)
        opts[:,m]=ids[choice]
        signal[:,m]=score[np.arange(len(races)),opts[:,m]]
    # Cash-only deterministic fallback per market: historically highest
    # max-payout-removed mean actual yen/100 ticket (prior period ONLY).
    ix=np.flatnonzero(np.isin(years,TRAIN))
    fallback=[]
    for m in range(6):
        ids=np.flatnonzero(market==m)
        dat=cash[ix][:,ids]
        sums=np.sum(dat,dtype=np.int64,axis=0)
        maxima=np.max(dat,axis=0)
        roi=(sums-maxima)/(100*len(ix))
        eligible=np.flatnonzero(roi>=2)
        fb=int(ids[eligible[np.argmax(roi[eligible])]]) if len(eligible) else int(ids[np.argmax(roi)])
        fallback.append(fb)
        opts[:,m]=np.where(signal[:,m]>0,opts[:,m],fb)
    # All predictions freeze now before examining 2022+ ticket labels.
    del buckets,score,rule_used
    print("THREER_CASH_FIRST_RULE_EXTRACTION",json.dumps({
        "historicalTrainYears":TRAIN,"raceCount":len(races),
        "cashTicketMatrixEntries":int(cash.size),
        "historicalProfitPatternsOnly":True,
        "preselectedTop10TicketPerMarket":True,
        "frozenCashFallbackTemplates":fallback,
        "yearsAvailable":dict(collections.Counter(map(int,years)))}),flush=True)
    return core,races,years,cash,cat,opts,signal,market,ranks
def choose_day_groups(races,ix):
    groups=collections.defaultdict(list)
    for j,rid in enumerate(ix):
        r=races[int(rid)]
        groups[(r["day"],int(r["venue"]))].append(int(j))
    impossible=[k for k,v in groups.items() if len(v)<3]
    if impossible:raise RuntimeError("MISSING_3_RACES_FOR_JRA_VENUE_DAYS:"+str(impossible[:4]))
    return list(groups.values())
def bet_amounts(pair,primary,stake_first):
    if pair=="one_market":return (2000,0)
    if primary==0:return(stake_first,2000-stake_first)
    return(2000-stake_first,stake_first)
def decisions(races,ix,cash,opts,score,groups,market_choice,slate,stake_first,ranking,ledger=False):
    n=len(ix)
    a=np.empty(n,dtype=np.int16);b=np.empty(n,dtype=np.int16)
    strength=np.zeros(n,dtype=np.float64)
    first_cash=np.zeros(n,dtype=np.float64)
    second_cash=np.zeros(n,dtype=np.float64)
    # Fixed-pair models or cash regime-specific dynamic market switches.
    for j,rid in enumerate(ix):
        sig=score[rid]
        if market_choice=="dynamic":
            choice=np.argsort(-sig,kind="stable")
            pair=[int(choice[0]),int(choice[1])]
        elif market_choice=="one_market":
            pair=[int(np.argmax(sig)),int(np.argmax(sig))]
        else:
            pair=list(market_choice)
            if sig[pair[1]]>sig[pair[0]]:
                pair.reverse()
        a[j]=opts[rid,pair[0]]
        b[j]=opts[rid,pair[1]]
        first_cash[j]=sig[pair[0]]
        second_cash[j]=sig[pair[1]]
    if ranking=="highest_cash_signal":
        strength=first_cash+.2*second_cash
    elif ranking=="medium_score":
        strength=np.sqrt(np.maximum(0,first_cash)*(1+np.maximum(0,second_cash)))
    elif ranking=="top_two":
        strength=np.minimum(first_cash,second_cash)+.1*first_cash
    elif ranking=="reverse":
        strength=1/(1+first_cash+.2*second_cash)
    else:raise RuntimeError("UNEXPECTED_RACE_PRIORITY")
    chosen=[]
    for day in groups:
        # Strict 3 <= n <=5 for EVERY venue-day; ties by ID, never by cash.
        ordered=sorted(day,key=lambda j:(-strength[j],str(races[int(ix[j])]["id"])))
        chosen.extend(ordered[:slate])
    chosen=np.asarray(chosen,dtype=np.int32)
    ixsel=ix[chosen]
    assert len(chosen)>=len(groups)*MIN_RACES_PER_VENUE_DAY
    s1,s2=bet_amounts(market_choice,0,stake_first)
    # Guaranteed ¥2,000 per race, actual JPY money labels.
    returned=(cash[ixsel,a[chosen]].astype(np.int64)*(s1//100)+
              cash[ixsel,b[chosen]].astype(np.int64)*(s2//100))
    if len(returned)!=len(chosen):raise RuntimeError("CASH_LEDGER_MISALIGN")
    summary=metrics(returned,len(groups))
    assert summary["stakeYen"]==PER_RACE_SPEND*len(chosen)
    if not ledger:return summary,None
    rows=[]
    for z,j in enumerate(chosen):
        r=races[int(ix[j])];aidx=int(a[j]);bidx=int(b[j])
        rows.append({"year":int(r["month"][:4]),"date":r["day"],
            "venue":r["venue"],"raceId":r["id"],"raceNo":r["raceNo"],
            "ticket1Market":MARKETS[int(market[aidx])],
            "ticket1Template":aidx,
            "ticket2Market":MARKETS[int(market[bidx])] if s2 else "",
            "ticket2Template":bidx if s2 else "",
            "stake1Yen":s1,"stake2Yen":s2,
            "paidYen":int(returned[z])})
    return summary,rows
def main():
    if "--self-test" in sys.argv:
        assert len(MARKET_PAIRS)==15
        assert matches_goal({"venueDays":1,"races":3,"cashRoiPct":215,"minusLargestRaceCashRoiPct":201})
        assert not matches_goal({"venueDays":2,"races":3,"cashRoiPct":500,"minusLargestRaceCashRoiPct":300})
        assert not matches_goal({"venueDays":1,"races":3,"cashRoiPct":215,"minusLargestRaceCashRoiPct":180})
        assert metrics([3000,2000,1000],1)["cashRoiPct"]==100.
        assert all(sum(bet_amounts(c,0,1000))==2000
                   for c in ("one_market","dynamic",(0,1)))
        print("MIN3R_2000YEN_CASH_ACCOUNTING_SELFTEST_OK");return
    t=time.monotonic()
    core,races,years,cash,cat,opts,signal,market,ranks=feature_races()
    ix=np.flatnonzero(years==DISCOVERY)
    groups=choose_day_groups(races,ix)
    search=[]
    tried=0
    best_diagnostic=None
    quarter_options={q:[] for q in range(4)}
    for pair in SETTINGS["pairs"]:
      for slate in SETTINGS["slates"]:
        for stake in SETTINGS["split"]:
          if pair=="one_market" and stake!=1000:continue
          for rank in SETTINGS["selection"]:
            z,receipts=decisions(races,ix,cash,opts,signal,
                                groups,pair,slate,stake,rank,True)
            tried+=1
            spec={"marketPair":"-".join(map(str,pair)) if isinstance(pair,tuple) else pair,
                  "slate":slate,"firstStake":stake,"ranking":rank}
            setup={**spec,"cash2022":z}
            # Never allow a below-200 portfolio into an actual candidate.
            if matches_goal(z):search.append(setup)
            if best_diagnostic is None or (
              z["minusLargestRaceCashRoiPct"]>best_diagnostic["cash2022"]["minusLargestRaceCashRoiPct"]):
                 best_diagnostic=setup
            for q in range(4):
                v=[r for r in receipts if (int(r["date"][4:6])-1)//3==q]
                days=len({(r["date"],r["venue"]) for r in v})
                qt=metrics([r["paidYen"] for r in v],days)
                if not v or qt["races"]<3*days:
                    raise RuntimeError("QUARTER_3R_VENUE_DAY_GAP")
                quarter_options[q].append({"q":q,"policy":spec,"cash":qt})
    # Historical positive-cash rule candidates are already frozen from
    # 2017-21. But selecting ONE 2022 market/race regime for the whole
    # year is unnecessarily rigid. Build a quarter-switched portfolio of
    # market-pair+stake/race selection rules. Every component still buys
    # >=3 actual races per venue-day at JPY2000 per race.
    # The 2022 returns below are discovery labels ONLY, never a forward test.
    shortlist={}
    for q,records in quarter_options.items():
        top_robust=sorted(records,
             key=lambda x:(-x["cash"]["minusLargestRaceCashRoiPct"],
                           -x["cash"]["cashRoiPct"]))[:18]
        top_gross=sorted(records,
             key=lambda x:(-x["cash"]["cashRoiPct"],
                           -x["cash"]["minusLargestRaceCashRoiPct"]))[:18]
        top_cash=sorted(records,
             key=lambda x:(-x["cash"]["paidYen"],x["cash"]["maxRacePayoutYen"]))[:18]
        used=set();shortlist[q]=[]
        for z in top_robust+top_gross+top_cash:
            k=(z["policy"]["marketPair"],z["policy"]["slate"],
                z["policy"]["firstStake"],z["policy"]["ranking"])
            if k not in used:
                used.add(k);shortlist[q].append(z)
    switch_search_count=0
    switch_candidates=0
    best_switch=None
    for components in itertools.product(*(shortlist[q] for q in range(4))):
        switch_search_count+=1
        cells=[z["cash"] for z in components]
        stake=sum(z["stakeYen"] for z in cells)
        payout=sum(z["paidYen"] for z in cells)
        largest=max(z["maxRacePayoutYen"] for z in cells)
        days=sum(z["venueDays"] for z in cells)
        bet_races=sum(z["races"] for z in cells)
        if bet_races<3*days or stake!=PER_RACE_SPEND*bet_races:
            raise RuntimeError("SEASONAL_PORTFOLIO_VIOLATES_MINIMUM_3R_OR_BUDGET")
        gross=100*payout/stake
        trimmed=100*(payout-largest)/stake
        # Only the complete 2022-money-200% portfolio is a candidate.
        if gross>=200 and trimmed>=200:
            switch_candidates+=1
            if best_switch is None or trimmed>best_switch["money2022"]["minusLargestRaceCashRoiPct"]:
                best_switch={"quarterRules":{
                    str(q):components[q]["policy"] for q in range(4)},
                  "money2022":{"races":bet_races,"venueDays":days,
                    "stakeYen":stake,"paidYen":payout,
                    "cashRoiPct":round(gross,4),
                    "minusLargestRaceCashRoiPct":round(trimmed,4),
                    "maxRacePayoutYen":largest}}
    search.sort(key=lambda c:(-c["cash2022"]["minusLargestRaceCashRoiPct"],
                                -c["cash2022"]["races"]))
    # Prefer the quarter-switched 200% rule, if found.
    regular=search[0] if search else None
    chosen=best_switch or ({"quarterRules":{str(q):{
              k:regular[k] for k in ("marketPair","slate","firstStake","ranking")
              } for q in range(4)},
          "money2022":regular["cash2022"]} if regular else None)
    report={"status":"ACTUAL_CASH200_MIN3R_DISCOVERED" if chosen else "NO_CASH200_MIN3R_YET",
        "mode":"cash-mined patterns ONLY, at least 3 JRA races per venue-day, JPY2000 per race, max-race removed actual cash ROI200",
        "allHistoricalHorseBetTemplates":1030,
        "actualPayoutTicketEvents":int(cash.size),
        "priorCashTrainYears":TRAIN,
        "regimeSelectionYear":DISCOVERY,
        "laterYearsUnseenForPolicySelection":list(EVAL),
        "minimumRacesEveryVenueDay":MIN_RACES_PER_VENUE_DAY,
        "yenSpentPerRace":PER_RACE_SPEND,
        "full2022VenueDays":len(groups),
        "flatPoliciesChecked":tried,
        "flatPortfolioQualified200":len(search),
        "regimeCombinationCountChecked":switch_search_count,
        "regimePortfolioQualified200":switch_candidates,
        "bestFlatDiagnosticsNotACandidateUnless200":best_diagnostic,
        "independentlyOfficialT15Verified":False,
        "thirdPartyPayoutReconciledWithJRA":False,
        "2025And2026AlreadyExaminedElsewhere":True,
        "productionModified":False}
    if chosen:
        year_reports={};all_cash_rows=[]
        for yr in (2017,2018,2019,2020,2021,2022,*EVAL):
            ids=np.flatnonzero(years==yr)
            days=choose_day_groups(races,ids)
            rows_by_q={}
            for q in range(4):
                spec=chosen["quarterRules"][str(q)]
                pair_spec=spec["marketPair"]
                pair=tuple(map(int,pair_spec.split("-"))) if "-" in pair_spec else pair_spec
                z,recs=decisions(races,ids,cash,opts,signal,days,
                 pair,spec["slate"],spec["firstStake"],spec["ranking"],True)
                rows_by_q[q]=[r for r in recs if
                             (int(r["date"][4:6])-1)//3==q]
            combined=[r for v in rows_by_q.values() for r in v]
            # Verify exactly the configured 3-5 races are purchased
            # per venue-day and each race has exactly JPY2000 stake.
            byday=collections.Counter((r["date"],r["venue"]) for r in combined)
            if len(byday)!=len(days) or min(byday.values(),default=0)<3 or any(
                r["stake1Yen"]+r["stake2Yen"]!=2000 for r in combined):
                raise RuntimeError("EXACT_3R_EACH_DAY_REAL_MONEY_VIOLATION")
            m=metrics([r["paidYen"] for r in combined],len(days))
            year_reports[str(yr)]=m
            all_cash_rows.extend(combined)
            print("CASH_3R_REGIME_YEARLY_ACTUAL_YEN",json.dumps({"year":yr,"cash":m},ensure_ascii=False),flush=True)
        verified2022=year_reports["2022"]
        if verified2022["stakeYen"]!=chosen["money2022"]["stakeYen"] or (
            verified2022["paidYen"]!=chosen["money2022"]["paidYen"]):
            raise RuntimeError("REGIME_PRESELECTION_AND_LEDGER_PAYOUT_DIFFER")
        post=[r for r in all_cash_rows if r["year"]>=2023]
        all_years=metrics([r["paidYen"] for r in all_cash_rows],
             sum(z["venueDays"] for z in year_reports.values()))
        later=metrics([r["paidYen"] for r in post],
             sum(year_reports[str(y)]["venueDays"] for y in EVAL))
        report.update({"chosenQuarterSwitchCash200Candidate":chosen,
            "yearlyRealCash":year_reports,
            "all2017To2026Money":all_years,
            "forward2023To2026Money":later,
            "fullHistoricalMoney200":matches_goal(all_years),
            "forward2023To2026Money200":matches_goal(later),
            "eachForwardYearMoney200":all(
                matches_goal(year_reports[str(y)]) for y in EVAL)})
        # Candidate policy must be a candidate on full chronological
        # 2017-2026 AND forward slice before being labeled verified.
        report["status"]="FULL_HISTORICAL_AND_FORWARD_CASH200_CANDIDATE_FOUND" if (
            report["fullHistoricalMoney200"] and
            report["forward2023To2026Money200"]) else "HISTORICAL_DISCOVERY_ONLY_NEEDS_INDEPENDENT_CASH200"
        BETS.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(BETS,"wt",encoding="utf8",newline="") as fh:
            w=csv.DictWriter(fh,fieldnames=list(all_cash_rows[0]))
            w.writeheader();w.writerows(all_cash_rows)
    report["seconds"]=round(time.monotonic()-t,2)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("MIN3R_2000YEN_ROI200_DISCOVERY_FINAL",json.dumps({
       "status":report["status"],
       "2022VenueDays":len(groups),
       "total2022MinimumStakeYen":len(groups)*3*PER_RACE_SPEND,
       "flatPoliciesChecked":tried,
       "quarterSwitchedPolicyPortfoliosChecked":switch_search_count,
       "qualifyingQuarterSwitch":switch_candidates,
       "bestFlatBelow200Diagnostics":best_diagnostic["cash2022"],
       "chosen2022":chosen["money2022"] if chosen else None,
       "combined2017To2026":report.get("all2017To2026Money"),
       "combined2023To2026":report.get("forward2023To2026Money"),
       "productionChanged":False,
       "seconds":report["seconds"]},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
