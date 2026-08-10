#!/usr/bin/env python3
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "scripts" / "research-evaluate-canonical-transfer.py"

spec = importlib.util.spec_from_file_location("canonical_transfer_base_for_merge", BASE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"MODULE_LOAD_FAILED:{BASE}")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def raw_from_finalized(stat):
    return {
        "races": int(stat["races"]),
        "tickets": int(stat["tickets"]),
        "hitRaces": int(stat["hitRaces"]),
        "stakeYen": int(stat["stakeYen"]),
        "returnYen": int(stat["returnYen"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-result", required=True)
    ap.add_argument("--correction", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    result = json.loads(Path(args.base_result).read_text(encoding="utf-8"))
    correction = json.loads(Path(args.correction).read_text(encoding="utf-8"))

    assert result["selectedDemandRaces"] == 14410, result
    assert result["oddsRaces"] == 14410 and result["missingOddsRaceCount"] == 0, result
    assert result["evaluationErrorCount"] == 1 and result["evaluatedRaces"] == 14409, result
    assert len(result["evaluationErrors"]) == 1, result
    assert result["evaluationErrors"][0]["raceId"] == "2026-08-09-niigata-12", result
    assert correction["raceId"] == "2026-08-09-niigata-12", correction
    assert correction["raceDate"] == "2026-08-09", correction
    assert correction["targetRaceResultsUsedForSelection"] is False, correction
    assert correction["bettingEligibilitySource"] == "official_final_win_market", correction
    assert correction["syntheticOddsUsed"] is False, correction
    assert correction["productionDatabaseWritten"] is False and correction["productionModelChanged"] is False, correction

    period = "2025..2026-08-09"
    all_pass = True
    for course, budget in base.COURSES.items():
        corr = correction["courses"][course]
        tickets = len(corr["tickets"])
        returned = int(corr["returnYen"])
        hit = returned > 0

        overall_raw = raw_from_finalized(result["courses"][course])
        base.add_stat(overall_raw, int(budget), returned, tickets, hit)
        overall = base.finalize_stat(overall_raw)
        overall["pass200"] = bool(overall["roiPct"] is not None and overall["roiPct"] >= 200.0)
        all_pass = all_pass and overall["pass200"]

        year_raw = raw_from_finalized(result["courses"][course]["byYear"]["2026"])
        base.add_stat(year_raw, int(budget), returned, tickets, hit)
        year_final = base.finalize_stat(year_raw)

        period_raw = raw_from_finalized(result["courses"][course]["byPeriod"][period])
        base.add_stat(period_raw, int(budget), returned, tickets, hit)
        period_final = base.finalize_stat(period_raw)

        preserved_by_year = dict(result["courses"][course]["byYear"])
        preserved_by_year["2026"] = year_final
        preserved_by_period = dict(result["courses"][course]["byPeriod"])
        preserved_by_period[period] = period_final
        concentration = result["courses"][course]["returnConcentration"]

        result["courses"][course] = {
            **overall,
            "pass200": overall["pass200"],
            "byYear": preserved_by_year,
            "byPeriod": preserved_by_period,
            "returnConcentration": concentration,
        }

    result["evaluationErrorCount"] = 0
    result["evaluationErrors"] = []
    result["evaluatedRaces"] = 14410
    result["hardGateEligible"] = True
    result["allThreeCoursesAtLeast200Pct"] = bool(all_pass)
    result["finalCorrection"] = {
        "raceId": correction["raceId"],
        "reason": "Historical runner_status lagged final official betting eligibility; ticket generation used the official final win market, a pre-race source.",
        "chosenTickets": correction["chosenTickets"],
        "courseReturnsYen": {course: int(correction["courses"][course]["returnYen"]) for course in base.COURSES},
        "targetRaceResultsUsedForSelection": False,
        "syntheticOddsUsed": False,
        "productionDatabaseWritten": False,
        "productionModelChanged": False,
    }

    assert result["evaluatedRaces"] == result["selectedDemandRaces"] == 14410, result
    assert result["missingOddsRaceCount"] == 0 and result["evaluationErrorCount"] == 0, result
    assert result["hardGateEligible"] is True, result
    assert result["syntheticOddsUsed"] is False, result
    assert result["productionDatabaseWritten"] is False and result["productionModelChanged"] is False, result

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "evaluatedRaces": result["evaluatedRaces"],
        "missingOddsRaceCount": result["missingOddsRaceCount"],
        "evaluationErrorCount": result["evaluationErrorCount"],
        "hardGateEligible": result["hardGateEligible"],
        "allThreeCoursesAtLeast200Pct": result["allThreeCoursesAtLeast200Pct"],
        "roi": {course: result["courses"][course]["roiPct"] for course in base.COURSES},
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
