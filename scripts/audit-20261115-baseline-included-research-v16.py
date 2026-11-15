#!/usr/bin/env python3
"""Audit the completed baseline-inclusive learned-money research summary.

Read report ONLY; every count/cash figure must reconcile independently
against the immutable original archived baseline statistics and the
per-year aggregates. No future-leaking offline train-test claim is made.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

def recompute(report):
    assert report["status"]=="BASELINE_INCLUDED_ROLLING_NEW_MONEY_SEARCH_COMPLETED"
    assert report["baselineExistingModelIncluded"] is True
    assert report["baselineQualifiedCount"]==1
    assert report["newCausalCashModelsSearched"]==1890
    assert report["newOnlineLearnedMethodologiesSearched"]==32
    assert report["modelCountSearched"]==1923
    assert report["totalHistoricalQualified"]==(
        1+report["newCausalCashModelsQualified"]+
        report["newOnlineLearnedMethodologiesQualified"])
    assert report["newCausalCashModelsQualified"]+report["newOnlineLearnedMethodologiesQualified"]>0
    assert report["totalHistoricalQualified"]<=report["modelCountSearched"]
    baseline=report["baseline"]
    x=baseline["total"]
    assert x["receivedYen"]==118212500 and x["stakeYen"]==27720000
    assert x["boughtRaces"]==13860 and x["venueDays"]==2772
    assert 426.45<x["roiPct"]<426.46 and x["qualified"]
    assert x["afterLargestPaidRaceRoiPct"]>200
    for label in ("baseline","bestNewByProfit","bestNewByRoi"):
        data=report[label] if label!="baseline" else {"money":baseline}
        if label!="baseline":
            assert data and data["family"].startswith("new_")
            if data["family"]=="new_causal_cash_forecaster":
                method=data["method"]
                assert method["racesPerVenueDay"]>=3
                assert not(method["racesPerVenueDay"]==5 and method["stakeMode"]=="equal")
        money=data["money"]
        total=money["total"]
        years=money["annual"]
        assert list(sorted(years))==[str(y) for y in range(2017,2027)]
        for col in ("stakeYen","receivedYen","profitYen","boughtRaces","venueDays","hitRaces"):
            expected=sum(int(years[y][col]) for y in years)
            assert expected==total[col],(label,col,expected,total[col])
        assert total["profitYen"]==total["receivedYen"]-total["stakeYen"]
        assert total["boughtRaces"]>=3*total["venueDays"]
        assert total["qualified"]
        assert total["receivedYen"]-total["maxPaidSingleRaceYen"]>=2*total["stakeYen"]
        assert total["hitRaces"]*5>=total["boughtRaces"]
    improved_money=report["bestNewByProfit"]["money"]["total"]
    improved_roi=report["bestNewByRoi"]["money"]["total"]
    assert improved_money["profitYen"]>x["profitYen"]
    assert improved_roi["roiPct"]>x["roiPct"]
    info=report["informationControls"]
    assert info["newModelGeneratedDistinctUnderlyingHorsePredictions"] is False
    assert info["originalArchivedTicketOddsAreRetrospectiveFinalNotOfficialT15"] is True
    assert info["independentOutOfSampleRoi200Certified"] is False
    assert report["productionModified"] is False
    return {
        "status":"BASELINE_INCLUSIVE_NEW_CASH_MODEL_RESEARCH_INDEPENDENT_ACCOUNTING_PASS",
        "enumeratedMethods":report["modelCountSearched"],
        "baselineQualified":report["baselineQualifiedCount"],
        "newCashModelsQualified":report["newCausalCashModelsQualified"],
        "newOnlineMethodologiesQualified":report["newOnlineLearnedMethodologiesQualified"],
        "newTotalQualified":report["newCausalCashModelsQualified"]+report["newOnlineLearnedMethodologiesQualified"],
        "allQualified":report["totalHistoricalQualified"],
        "baselineMoney":baseline["total"],
        "newMaximumProfit":{
            "method":report["bestNewByProfit"]["method"],
            "family":report["bestNewByProfit"]["family"],
            "cash":improved_money,
            "extraProfitOverBaselineYen":improved_money["profitYen"]-x["profitYen"],
            "annualCash":report["bestNewByProfit"]["money"]["annual"],
        },
        "newMaximumRoi":{
            "method":report["bestNewByRoi"]["method"],
            "family":report["bestNewByRoi"]["family"],
            "cash":improved_roi,
            "extraProfitOverBaselineYen":improved_roi["profitYen"]-x["profitYen"],
            "annualCash":report["bestNewByRoi"]["money"]["annual"],
        },
        "forwardUseCertification":False,
        "reasonNotLiveProven":"underlying frozen horse predictor trained on full archive; original market odds final, not verified pre-T15",
        "productionChanged":False,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",required=True)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    input_obj=json.loads(Path(a.source).read_text(encoding="utf8"))
    output=recompute(input_obj)
    dest=Path(a.out)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("CAUSAL_MONEY_MODEL_BASELINE_INCLUSIVE_FINAL_AUDIT",
          json.dumps({
            "status":output["status"],"enumeratedMethods":output["enumeratedMethods"],
            "baselineQualified":output["baselineQualified"],
            "newCashModelsQualified":output["newCashModelsQualified"],
            "newOnlineMethodologiesQualified":output["newOnlineMethodologiesQualified"],
            "newTotalQualified":output["newTotalQualified"],
            "allQualified":output["allQualified"],
            "maxProfitMethod":output["newMaximumProfit"]["method"],
            "maxProfitCash":output["newMaximumProfit"]["cash"],
            "extraProfitOverBaselineYen":output["newMaximumProfit"]["extraProfitOverBaselineYen"],
            "maxRoiMethod":output["newMaximumRoi"]["method"],
            "maxRoiCash":output["newMaximumRoi"]["cash"],
            "forwardUseCertification":False,
        },ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
