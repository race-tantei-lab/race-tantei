#!/usr/bin/env python3
"""Exhaustive 270 cash-conditioned PREDECLARED policy checks, 2023-26.

Important: evaluating all 270 using 2023-26 is a discovery DIAGNOSTIC,
not independent validation for any 270-policy selection chosen after seeing
those results. Never promote on retrospective cherry-picking. When all 270
fail, this reliably rules out this finite FAMILY, not all possible models.
"""
from pathlib import Path
import csv,importlib.util,json,sys,time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("allocation_policy",ROOT/"scripts/research-nov2026-cash-portfolio-allocation.py")
policy=importlib.util.module_from_spec(spec);sys.modules[spec.name]=policy;spec.loader.exec_module(policy)
core=policy.core
OUT=ROOT/"analysis-results/nov2026-direct-cash-all270-yearwise-audit.json"
CSV=ROOT/"analysis-results/nov2026-direct-cash-all270-exact-roi.csv"

def main():
    if "--self-test" in sys.argv:
        assert len(policy.MODES)*len(policy.RACES_PER_DAY)*len(policy.STAKES)*len(policy.CAPS)==270
        print("CASH_ALL270_FULL_PERIOD_AUDIT_SELFTEST_OK",flush=True);return
    start=time.monotonic()
    races,X,paid,year=core.source_data()
    metrics={}
    success=[]
    for cap in policy.CAPS:
        estimator,info=core.train_cash_estimator(X,paid,year,tuple(range(2017,2023)),cap)
        peryear={}
        preds={yr:core.score_for(estimator,X,year,yr) for yr in core.OOS}
        for mode in policy.MODES:
          for count in policy.RACES_PER_DAY:
            for stakes in policy.STAKES:
                rows=[]
                yearly={}
                coverage={}
                for yr in core.OOS:
                    bets,cov=policy.choose(races,paid,year,preds[yr],yr,mode,count,stakes)
                    rows.extend(bets)
                    yearly[str(yr)]=policy.summary(bets)
                    coverage[str(yr)]=cov
                combined=policy.summary(rows)
                # ROI of combined Yen bets is the ONLY profitability criterion.
                # 200% under largest payout removal with >20% hit, together
                # with at least 3 races / venue-day observed, is necessary.
                enough=(combined["minusBiggestRaceRoiPct"] is not None
                    and combined["minusBiggestRaceRoiPct"]>=200.
                    and combined["hitRacePct"]>=20.
                    and all(yearly[str(y)]["minusBiggestRaceRoiPct"] is not None
                        and yearly[str(y)]["minusBiggestRaceRoiPct"]>=200.
                        for y in core.OOS)
                    and all(coverage[str(y)]["enough3"]==coverage[str(y)]["programDays"]
                        for y in core.OOS))
                key=f"{int(cap)}_{mode}_{count}R_{stakes[0]}_{stakes[1]}"
                item={"capYen":cap,"mode":mode,"racesPerDay":count,
                      "stake1Yen":stakes[0],"stake2Yen":stakes[1],
                      "cash":combined,"year":yearly,"coverage":coverage,
                      "passesRetrospectiveFiniteCriteria":bool(enough)}
                metrics[key]=item
                if enough:success.append(key)
        top=sorted((x for x in metrics.values() if x["capYen"]==cap),
           key=lambda x:(x["cash"]["minusBiggestRaceRoiPct"] or 0),
           reverse=True)[:5]
        print("CASH_ALL270_CAP_COMPLETED",json.dumps({
          "cap":cap,"testedCandidates":sum(x["capYen"]==cap for x in metrics.values()),
          "wholeHorizonCriteriaMatches":len(success),
          "bestFiveCombinedCash":[{"mode":x["mode"],"racePerDay":x["racesPerDay"],
              "stakes":[x["stake1Yen"],x["stake2Yen"]],
              "cash":x["cash"]} for x in top]},
          ensure_ascii=False),flush=True)
    ranked=sorted(metrics.items(),key=lambda kv:(kv[1]["cash"]["minusBiggestRaceRoiPct"] or 0),reverse=True)
    report={"researchOnly":True,"cashSearchSpaceExactlyExhausted":270,
        "allPayoutsThirdPartyNotJraReconciled":True,
        "historicalWinOddsAreFinalNotOfficialT15":True,
        "2025And2026AreAlreadyResearchedNotFreshBlind":True,
        "thisIsDiscoveryNotOutOfSampleVariantSelection":True,
        "candidateReturnsAreNotModelsUntilAccepted":True,
        "passesAllRetrospectiveROI200AndHit20":len(success),
        "historicalPassKeys":success,
        "top10ByWholeHorizonMinusLargestRaceCashROI":[
             {"key":k,"cash":v["cash"],"year":v["year"]}
             for k,v in ranked[:10]],
        "fullGridMetrics":metrics,
        "seconds":round(time.monotonic()-start,2)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    fields=("key","cashCapYen","marketMode","racesPerVenueDay","stake1Yen","stake2Yen",
        "totalRaces","stakeYen","paidYen","cashRoiPct","minusLargestRaceCashRoiPct",
        "hitRatePct","passAllYearsRoi200")
    with CSV.open("w",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for key,v in metrics.items():
            cash=v["cash"]
            w.writerow({"key":key,"cashCapYen":v["capYen"],
              "marketMode":v["mode"],"racesPerVenueDay":v["racesPerDay"],
              "stake1Yen":v["stake1Yen"],"stake2Yen":v["stake2Yen"],
              "totalRaces":cash["races"],"stakeYen":cash["stakeYen"],
              "paidYen":cash["paidYen"],"cashRoiPct":cash["roiPct"],
              "minusLargestRaceCashRoiPct":cash["minusBiggestRaceRoiPct"],
              "hitRatePct":cash["hitRacePct"],
              "passAllYearsRoi200":v["passesRetrospectiveFiniteCriteria"]})
    print("CASH_ALL270_EXHAUSTIVE_FINAL",json.dumps({
       "screened":len(metrics),"retrospectiveWholeHorizon200":len(success),
       "bestFiniteCashCase":report["top10ByWholeHorizonMinusLargestRaceCashROI"][0],
       "durationSeconds":report["seconds"],
       "noProductionMutation":True
    },ensure_ascii=False),flush=True)

if __name__=="__main__":main()
