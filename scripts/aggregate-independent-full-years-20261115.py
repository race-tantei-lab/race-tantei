#!/usr/bin/env python3
"""Aggregate REAL cash6/cash96 year-by-year results, never impute missing year."""
import collections,json,glob
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts"/"full-years"
files=sorted(BASE.glob("independent-year-roi-*.json"))
modes=("cash6","cash96")
report={"source":"deployed cash6/cash96 source functions, final JRA odds retrospective","yearsSeen":[],"modes":{}}
for mode in modes:
    years={};all_bets=[];total_selected=0;fail=0
    for p in files:
        j=json.loads(p.read_text())
        y=str(j["year"])
        m=j["modeResults"][mode]
        total_selected+=m["selectedRaces"];fail+=m["skipped"]
        years[y]={k:m[k] for k in ("selectedRaces","fullySettledRaces","skipped","coveragePct","totalStakeYen","totalPaidYen","roiPct","roiAfterLargestTicketPct","hitRacePct")}
        all_bets+=m["bets"]
    stake=sum(x["stake"] for x in all_bets);pay=sum(x["paid"] for x in all_bets)
    report["modes"][mode]={"years":years,"yearCount":len(years),"chosenRaces":total_selected,"settledRaces":len(all_bets),"missingRaces":fail,
      "stakeYen":stake,"paidYen":pay,
      "roiPct":round(100*pay/stake,4) if stake else None,
      "hitRacePct":round(100*sum(x["hit"] for x in all_bets)/len(all_bets),4) if all_bets else None,
      "roiAfterLargestTicketPct":round(100*(pay-max((max(x["paidTickets"]) for x in all_bets),default=0))/stake,4) if stake else None,
      "roiAfterLargestRacePct":round(100*(pay-max((x["paid"] for x in all_bets),default=0))/stake,4) if stake else None,
      "complete2017to2026":all(str(y) in years for y in range(2017,2027)),
      "coverageComplete":bool(stake and fail==0 and all(str(y) in years for y in range(2017,2027)))}
report["yearsSeen"]=sorted({str(json.loads(p.read_text())["year"]) for p in files})
ROOT.joinpath("artifacts").mkdir(exist_ok=True)
output=ROOT/"artifacts/independent-2017-2026-retrospective-roi-summary.json"
output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
print("INDEPENDENT_2017_2026_TOTAL_ROI",json.dumps(report,ensure_ascii=False),flush=True)
if not all(report["modes"][m]["complete2017to2026"] for m in modes):
    print("SOME_YEARS_NOT_YET_COMPLETED_ROI_NOT_FULL_PERIOD",flush=True)
