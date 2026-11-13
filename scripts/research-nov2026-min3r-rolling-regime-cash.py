#!/usr/bin/env python3
"""Prospective yearly regime adaptation on genuine settled yen (research only).

Every JRA venue-day: 3-5 DIFFERENT races, exactly 2,000 yen/race.
The same 2017-19 PRE-RACE signal/ticket templates are frozen for all years.
For each prospective target year t=2023,...,2026, select each quarter's entire
two-market + race-slate + stake allocation from the 3 *PRIOR* completed years
ONLY. No 2023+ result enters any 2023 prediction. No result-dependent
per-race wager. All returns are gross yen and one-largest-race-removed yen.

Exploration strategies are prespecified; using their evaluation results to
choose a winning strategy would be leakage. 2023-25 is retrospective
strategy-validation and 2026 Jan-Apr is a later audit, NOT a verified T-15
JRA model. Third-party source payout still requires JRA reconciliation.
"""
import collections, importlib.util, itertools, json, time, sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-min3r-rolling-regime-cash-1113.json"
MOD=ROOT/"scripts/research-nov2026-min3r-three-year-cash-selection.py"
STUDY_YEARS=(2020,2021,2022,2023,2024,2025,2026)
FORWARD_YEARS=(2023,2024,2025,2026)
PREDECLARED_MODES=("recent1","recent2_robust","three_year_robust",
                   "each_year_robust","worst_year","smooth_recent","lower_tail")
def baseline():
    spec=importlib.util.spec_from_file_location("min_three_fixed_money",MOD)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod
def policy_options(mod):
    for pair in mod.SETTINGS["pairs"]:
        for slate in mod.SETTINGS["slates"]:
            for split in mod.SETTINGS["split"]:
                if pair=="one_market" and split!=1000: continue
                for rank in mod.SETTINGS["selection"]:
                    key=f"{pair}_{slate}_{split}_{rank}"
                    yield key,(pair,slate,split,rank)
def aggregate(parts):
    if not parts: return None
    paid=sum(s["paidYen"] for s in parts)
    cost=sum(s["stakeYen"] for s in parts)
    largest=max(s["maxRacePayoutYen"] for s in parts)
    races=sum(s["races"] for s in parts)
    days=sum(s["venueDays"] for s in parts)
    if cost!=2000*races or races<3*days:raise RuntimeError("BAD_CASH_COVERAGE")
    return {"races":races,"venueDays":days,"stakeYen":cost,"paidYen":paid,
            "profitYen":paid-cost,"maxRacePayoutYen":largest,
            "cashRoiPct":round(paid*100/cost,4),
            "minusLargestRaceCashRoiPct":round(100*(paid-largest)/cost,4)}
def merit(stats, mode):
    if not all(x is not None for x in stats):return -1e50
    agg=aggregate(stats)
    robust=(agg["paidYen"]-agg["maxRacePayoutYen"])/agg["stakeYen"]
    annual=[(x["paidYen"]-x["maxRacePayoutYen"])/x["stakeYen"] for x in stats]
    recent=stats[-1]
    a,b=stats[-2:]
    y2=(a["paidYen"]+b["paidYen"]-max(a["maxRacePayoutYen"],b["maxRacePayoutYen"]))/(a["stakeYen"]+b["stakeYen"])
    if mode=="recent1":return (recent["paidYen"]-recent["maxRacePayoutYen"])/recent["stakeYen"]
    if mode=="recent2_robust":return y2
    if mode=="three_year_robust":return robust
    if mode=="each_year_robust":return sum(annual)/len(annual)
    if mode=="worst_year":return min(annual)
    if mode=="smooth_recent":return .55*y2+.30*annual[-1]+.15*robust
    if mode=="lower_tail":return .5*min(annual[-2:])+.25*robust+.25*y2
    raise ValueError(mode)
def selected_year(mod,races,years,cash,opts,signal,gid,spec,yr):
    indices=gid[yr]
    if not len(indices):return [],None
    groups=mod.choose_day_groups(races,indices)
    parts=[]
    for q in range(4):
        if q not in spec:continue
        pair,slate,split,rank=spec[q]
        _,rows=mod.decisions(races,indices,cash,opts,signal,groups,pair,slate,split,rank,True)
        parts.extend(r for r in rows if (int(r["date"][4:6])-1)//3==q)
    byday=collections.Counter((r["date"],r["venue"]) for r in parts)
    if len(byday)!=len(groups) or any(not (3<=x<=5) for x in byday.values()):
        raise RuntimeError("THREE_TO_FIVE_RACES_NOT_MET")
    if any(r["stake1Yen"]+r["stake2Yen"]!=2000 for r in parts):
        raise RuntimeError("TWO_THOUSAND_YEN_BET_NOT_MET")
    result=mod.metrics([r["paidYen"] for r in parts],len(groups))
    return parts,result
def run():
    t=time.monotonic()
    mod=baseline()
    if "--self-test" in sys.argv:
        assert len(list(policy_options(mod)))==780
        assert aggregate([{"paidYen":8000,"stakeYen":6000,"maxRacePayoutYen":5000,"races":3,"venueDays":1}])["minusLargestRaceCashRoiPct"]==50
        assert merit([{"paidYen":8000,"stakeYen":6000,"maxRacePayoutYen":5000,"races":3,"venueDays":1}]*3,"worst_year")==.5
        print("ROLLING_MIN3R_CASH_SELFTEST_OK")
        return
    core,races,years,cash,cat,opts,signal,market,ranks=mod.feature_races()
    gid={yr:np.flatnonzero(years==yr) for yr in STUDY_YEARS}
    options=dict(policy_options(mod))
    stats={yr:{} for yr in STUDY_YEARS}
    counts={}
    for yr in STUDY_YEARS:
        indices=gid[yr]
        if not len(indices):raise RuntimeError("CASH_SOURCE_MISSING_YEAR_"+str(yr))
        groups=mod.choose_day_groups(races,indices)
        counts[yr]={"races":int(len(indices)),"venueDays":len(groups)}
        for key,(pair,slate,split,rank) in options.items():
            _,rows=mod.decisions(races,indices,cash,opts,signal,groups,pair,slate,split,rank,True)
            qs={}
            for q in range(4):
                segment=[r for r in rows if (int(r["date"][4:6])-1)//3==q]
                if segment:
                    n=len(set((r["date"],r["venue"]) for r in segment))
                    qs[q]=mod.metrics([r["paidYen"] for r in segment],n)
                    if qs[q]["races"]<3*n:raise RuntimeError("QUARTER_COVERAGE_FAILED")
            stats[yr][key]=qs
        print("ROLLING_CASH_POLICY_YEAR_CACHED",json.dumps({"year":yr,"policies":len(options),**counts[yr]}),flush=True)
    results={}
    for mode in PREDECLARED_MODES:
        selections={};reports={};ledger=[];parts=[]
        for target in FORWARD_YEARS:
            prior=(target-3,target-2,target-1)
            spec={}
            for q in range(4):
                if not any(q in stats[target][key] for key in options):continue
                admissible=[key for key in options if all(q in stats[y][key] for y in prior)]
                if not admissible:raise RuntimeError("MISSING_THREE_PRIOR_QUARTERS")
                key=max(admissible,key=lambda k:(merit([stats[y][k][q] for y in prior],mode),k))
                spec[q]=options[key]
            if not spec:raise RuntimeError("NO_YEARLY_QUARTER_RULES")
            rows,res=selected_year(mod,races,years,cash,opts,signal,gid,spec,target)
            selections[str(target)]={str(q):str(spec[q]) for q in sorted(spec)}
            reports[str(target)]=res
            ledger.extend(rows)
            parts.append(res)
        pre=aggregate(parts[:-1])
        later=aggregate(parts[-1:])
        full=aggregate(parts)
        qualified=pre["cashRoiPct"]>=200 and pre["minusLargestRaceCashRoiPct"]>=200 and later["cashRoiPct"]>=200 and later["minusLargestRaceCashRoiPct"]>=200 and full["cashRoiPct"]>=200 and full["minusLargestRaceCashRoiPct"]>=200
        results[mode]={"yearPolicies":selections,"yearlyCash":reports,"validation2023To2025":pre,
                       "holdout2026":later,"forward2023To2026":full,
                       "twoHundredCashGate":bool(qualified)}
        print("ROLLING_CASH_ADAPTIVE_RESULT",json.dumps({"mode":mode,"validation":pre,"holdout":later,"full":full,"twoHundredCashGate":qualified},ensure_ascii=False),flush=True)
    complete=[m for m,v in results.items() if v["twoHundredCashGate"]]
    report={"status":"ROLLING_FORWARD_CASH200_RESEARCH_FOUND_AWAIT_OFFICIAL_T15_AUDIT" if complete else "NO_VERIFIED_ROLLING_FORWARD_CASH200",
            "coreTrainYears":[2017,2018,2019],
            "strictCashTicketMoneyYenPerRace":2000,"minRacesPerVenueDay":3,
            "maxRacesPerVenueDay":5,"rulePoliciesConsidered":len(options),
            "predeclaredPolicyLearningMethods":PREDECLARED_MODES,
            "productionChanged":False,"officialT15OddsVerified":False,
            "officialJraPayoutReconciled":False,
            "discoveryCohort2020To2022Only":True,
            "untouchedHoldoutForStrategyComparison":False,
            "metrics":results,
            "cash200ResearchModesOnly":complete,"seconds":round(time.monotonic()-t,1)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("ROLLING_MIN3R_ROI200_FINAL",json.dumps({"status":report["status"],"completedModes":complete,"seconds":report["seconds"]}),flush=True)
if __name__=="__main__":run()
