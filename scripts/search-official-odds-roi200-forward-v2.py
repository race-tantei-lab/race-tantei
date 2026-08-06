import importlib.util
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "scripts" / "official-odds-roi200-policy-v2.py"
OUTPUT = ROOT / "official-odds-roi200-forward-search.json"
APPROVAL = ROOT / "config" / "official-odds-calibration.json"
ACCOUNT_ID = os.environ["CLOUDFLARE_ACCOUNT_ID"]
DATABASE_ID = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
D1_URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"
MINIMUM_SETTLED_RACES = 400
MINIMUM_RACES_PER_FOLD = 75
CALIBRATION_SCALES = (0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.05, 1.15, 1.25)
RACE_COUNTS = (5, 7, 9, 12)
SCORE_PROFILES = (
    {"name": "roi-heavy", "roiWeight": 5.0, "probabilityWeight": 0.15, "rankPenalty": 0.015, "firstBonus": 0.04},
    {"name": "balanced", "roiWeight": 4.0, "probabilityWeight": 0.30, "rankPenalty": 0.025, "firstBonus": 0.08},
    {"name": "hit-support", "roiWeight": 3.3, "probabilityWeight": 0.55, "rankPenalty": 0.030, "firstBonus": 0.12},
    {"name": "rank-neutral", "roiWeight": 4.4, "probabilityWeight": 0.22, "rankPenalty": 0.000, "firstBonus": 0.00},
    {"name": "contrarian", "roiWeight": 5.4, "probabilityWeight": 0.08, "rankPenalty": -0.008, "firstBonus": -0.04},
)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


policy = load_module("official_forward_policy_v2", POLICY_PATH)


def d1_query(sql, params=None):
    payload = json.dumps({"sql": sql, "params": params or []}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        D1_URL,
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("success"):
        raise RuntimeError(f"D1_QUERY_FAILED:{body}")
    result = body.get("result") or []
    return (result[0].get("results") or []) if result else []


def load_rows():
    return d1_query(
        """
        SELECT c.race_id raceId, c.captured_at_utc capturedAtUtc,
               c.bet_type betType, c.combination,
               c.model_probability modelProbability,
               c.official_odds officialOdds,
               c.predicted_rank_sum predictedRankSum,
               c.includes_model_first includesModelFirst,
               r.race_date raceDate, r.venue, r.race_no raceNo,
               r.refund_horse_nos_json refundHorseNosJson,
               o.seconds_to_start secondsToStart,
               COALESCE(p.payout_yen, 0) payoutYen
        FROM rt_official_value_candidates c
        JOIN rt_races r ON r.race_id=c.race_id AND r.status='finished'
        JOIN rt_official_odds_snapshots o
          ON o.race_id=c.race_id
         AND o.bet_type=c.bet_type
         AND o.combination=c.combination
         AND o.captured_at_utc=c.captured_at_utc
         AND o.odds_source='jra_official'
        LEFT JOIN rt_payouts p
          ON p.race_id=c.race_id
         AND p.bet_type=c.bet_type
         AND p.combination=c.combination
        WHERE c.model_version=?
          AND c.odds_source='jra_official'
          AND o.seconds_to_start >= 60
        ORDER BY r.race_date, r.venue, r.race_no, c.captured_at_utc,
                 c.bet_type, c.combination
        """,
        [policy.MODEL_VERSION],
    )


def horses_from_combination(value):
    return [
        int(token)
        for token in str(value).replace("→", "-").replace("－", "-").split("-")
        if token.strip().isdigit()
    ]


def organize(rows):
    snapshots = defaultdict(list)
    metadata = {}
    for row in rows:
        key = (row["raceId"], row["capturedAtUtc"])
        refunds = set(json.loads(row.get("refundHorseNosJson") or "[]"))
        horses = horses_from_combination(row["combination"])
        payout = 100 if refunds.intersection(horses) else int(row.get("payoutYen") or 0)
        snapshots[key].append(
            {
                "betType": row["betType"],
                "combination": row["combination"],
                "modelProbability": float(row["modelProbability"]),
                "officialOdds": float(row["officialOdds"]),
                "predictedRankSum": int(row["predictedRankSum"]),
                "includesModelFirst": bool(row["includesModelFirst"]),
                "payoutYen": payout,
            }
        )
        metadata[key] = {
            "raceId": row["raceId"],
            "raceDate": row["raceDate"],
            "venue": row["venue"],
            "raceNo": int(row["raceNo"]),
            "capturedAtUtc": row["capturedAtUtc"],
            "secondsToStart": int(row["secondsToStart"]),
        }

    by_race = defaultdict(list)
    for key, candidates in snapshots.items():
        by_race[key[0]].append((metadata[key], candidates))
    races = []
    for versions in by_race.values():
        eligible = [item for item in versions if item[0]["secondsToStart"] >= 60]
        if not eligible:
            continue
        chosen = min(eligible, key=lambda item: item[0]["secondsToStart"])
        races.append({**chosen[0], "candidates": chosen[1]})
    return sorted(races, key=lambda race: (race["raceDate"], race["venue"], race["raceNo"]))


def calibrated_candidate(candidate, scale):
    bet_type = candidate["betType"]
    model_probability = candidate["modelProbability"]
    official_odds = candidate["officialOdds"]
    market_floor = 0.68 / max(1.01, official_odds)
    shrink = max(0.20, min(1.0, policy.DEFAULT_CALIBRATION[bet_type] * scale))
    if model_probability <= market_floor:
        conservative = model_probability * shrink
    else:
        conservative = market_floor + shrink * (model_probability - market_floor)
    conservative = max(0.0, min(model_probability, conservative))
    return {
        **candidate,
        "conservativeProbability": conservative,
        "projectedRoiPct": conservative * official_odds * 100.0,
    }


def candidate_score(candidate, profile):
    return (
        math.log(max(0.01, candidate["projectedRoiPct"] / 100.0)) * profile["roiWeight"]
        + math.log(max(1e-9, candidate["conservativeProbability"])) * profile["probabilityWeight"]
        - candidate["predictedRankSum"] * profile["rankPenalty"]
        + (profile["firstBonus"] if candidate["includesModelFirst"] else 0.0)
    )


def select_for_course(course, candidates, profile):
    required = policy.COURSE_TYPES[course]
    target_count = policy.COURSE_TICKET_COUNTS[course]
    caps = policy.TYPE_CAPS[course]
    by_type = defaultdict(list)
    for candidate in candidates:
        if candidate["betType"] in required:
            by_type[candidate["betType"]].append(candidate)
    for bet_type in by_type:
        by_type[bet_type].sort(key=lambda row: candidate_score(row, profile), reverse=True)
    if any(not by_type[bet_type] for bet_type in required):
        return None

    selected = []
    signatures = set()
    counts = defaultdict(int)
    for bet_type in required:
        candidate = by_type[bet_type][0]
        selected.append(candidate)
        signatures.add((candidate["betType"], candidate["combination"]))
        counts[bet_type] += 1

    for candidate in sorted(candidates, key=lambda row: candidate_score(row, profile), reverse=True):
        if len(selected) >= target_count:
            break
        signature = (candidate["betType"], candidate["combination"])
        bet_type = candidate["betType"]
        if signature in signatures or bet_type not in required:
            continue
        if counts[bet_type] >= caps[bet_type]:
            continue
        if candidate["conservativeProbability"] < policy.COURSE_MIN_HIT_PROBABILITY[course]:
            continue
        selected.append(candidate)
        signatures.add(signature)
        counts[bet_type] += 1

    if len(selected) != target_count:
        return None
    if {row["betType"] for row in selected} != set(required):
        return None
    stakes = policy.allocate_stakes(course, selected)
    budget = policy.COURSE_TARGET_STAKES[course]
    projected = sum(
        stake * row["projectedRoiPct"] / 100.0
        for row, stake in zip(selected, stakes)
    ) / budget * 100.0
    actual_return = sum(
        stake / 100.0 * row["payoutYen"]
        for row, stake in zip(selected, stakes)
    )
    return {
        "projectedRoiPct": projected,
        "actualReturnYen": actual_return,
        "stakeYen": budget,
        "hit": actual_return > 0,
    }


def evaluate_configuration(races, scale, race_count, profile):
    grouped = defaultdict(list)
    for race in races:
        candidates = [calibrated_candidate(row, scale) for row in race["candidates"]]
        plans = {course: select_for_course(course, candidates, profile) for course in policy.COURSES}
        if any(plan is None for plan in plans.values()):
            grouped[(race["raceDate"], race["venue"])].append({**race, "plans": None})
            continue
        joint = min(plan["projectedRoiPct"] for plan in plans.values())
        grouped[(race["raceDate"], race["venue"])].append(
            {**race, "plans": plans, "jointProjectedRoiPct": joint}
        )

    selected = []
    coverage = []
    for key, group in sorted(grouped.items()):
        complete = [race for race in group if race["plans"] is not None]
        if len(complete) < policy.MINIMUM_RACES_PER_VENUE_DAY:
            return [], [{"date": key[0], "venue": key[1], "selected": 0, "complete": len(complete)}]
        complete.sort(key=lambda race: (-race["jointProjectedRoiPct"], race["raceNo"]))
        take = min(len(complete), max(policy.MINIMUM_RACES_PER_VENUE_DAY, race_count))
        picked = complete[:take]
        selected.extend(picked)
        coverage.append({"date": key[0], "venue": key[1], "selected": len(picked), "complete": len(complete)})
    return selected, coverage


def split_folds(races):
    dates = sorted({race["raceDate"] for race in races})
    if len(dates) < 10:
        return [], []
    holdout_start = dates[max(1, int(len(dates) * 0.80))]
    development = [race for race in races if race["raceDate"] < holdout_start]
    holdout = [race for race in races if race["raceDate"] >= holdout_start]
    dev_dates = sorted({race["raceDate"] for race in development})
    folds = []
    for index in range(4):
        start = int(len(dev_dates) * index / 4)
        end = int(len(dev_dates) * (index + 1) / 4)
        allowed = set(dev_dates[start:end])
        folds.append([race for race in development if race["raceDate"] in allowed])
    return folds, holdout


def summarize(races):
    result = {}
    for course in policy.COURSES:
        values = [race["plans"][course]["actualReturnYen"] for race in races]
        stake = len(races) * policy.COURSE_TARGET_STAKES[course]
        total = sum(values)
        ordered = sorted(values, reverse=True)
        top1 = ordered[0] if ordered else 0
        top3 = sum(ordered[:3])
        result[course] = {
            "races": len(races),
            "stakeYen": stake,
            "returnYen": round(total),
            "profitYen": round(total - stake),
            "roiPct": total / stake * 100.0 if stake else None,
            "roiWithoutTop1Pct": (total - top1) / stake * 100.0 if stake else None,
            "roiWithoutTop3Pct": (total - top3) / stake * 100.0 if stake else None,
            "hitRatePct": sum(value > 0 for value in values) / len(values) * 100.0 if values else None,
        }
    return result


def minimum_metric(summaries, key):
    values = []
    for summary in summaries:
        for course in policy.COURSES:
            value = summary[course][key]
            if value is None:
                return -1.0
            values.append(value)
    return min(values) if values else -1.0


def main():
    rows = load_rows()
    races = organize(rows)
    base_report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "modelVersion": policy.MODEL_VERSION,
        "productionChanged": False,
        "oddsSource": "jra_official",
        "settledOfficialOddsRaces": len(races),
        "minimumRequiredSettledRaces": MINIMUM_SETTLED_RACES,
        "targetRoiPct": policy.TARGET_ROI_PCT,
        "minimumRacesPerVenueDay": policy.MINIMUM_RACES_PER_VENUE_DAY,
        "singleOnlyPortfolioForbidden": True,
        "allRequiredCourseBetTypes": True,
    }
    if len(races) < MINIMUM_SETTLED_RACES:
        report = {**base_report, "status": "collecting_forward_official_odds", "promotionEligible": False}
        OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    folds, holdout_races = split_folds(races)
    if len(folds) != 4 or min((len(fold) for fold in folds), default=0) < MINIMUM_RACES_PER_FOLD:
        report = {**base_report, "status": "insufficient_time_folds", "promotionEligible": False}
        OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    best = None
    configurations_tested = 0
    for scale in CALIBRATION_SCALES:
        for race_count in RACE_COUNTS:
            for profile in SCORE_PROFILES:
                configurations_tested += 1
                fold_summaries = []
                fold_coverage = []
                valid = True
                for fold in folds:
                    selected, coverage = evaluate_configuration(fold, scale, race_count, profile)
                    if not selected:
                        valid = False
                        break
                    fold_summaries.append(summarize(selected))
                    fold_coverage.append(coverage)
                if not valid:
                    continue
                min_roi = minimum_metric(fold_summaries, "roiPct")
                min_trimmed1 = minimum_metric(fold_summaries, "roiWithoutTop1Pct")
                min_trimmed3 = minimum_metric(fold_summaries, "roiWithoutTop3Pct")
                score = min_roi * 0.65 + min_trimmed1 * 0.22 + min_trimmed3 * 0.13
                candidate = {
                    "calibrationScale": scale,
                    "racesPerVenueDay": race_count,
                    "scoreProfile": profile,
                    "minimumDevelopmentRoiPct": min_roi,
                    "minimumDevelopmentRoiWithoutTop1Pct": min_trimmed1,
                    "minimumDevelopmentRoiWithoutTop3Pct": min_trimmed3,
                    "folds": fold_summaries,
                    "coverage": fold_coverage,
                    "score": score,
                }
                if best is None or candidate["score"] > best["score"]:
                    best = candidate

    if best is None:
        report = {
            **base_report,
            "status": "no_configuration_with_minimum_five_races",
            "promotionEligible": False,
            "configurationsTested": configurations_tested,
        }
        OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    development_passed = (
        best["minimumDevelopmentRoiPct"] >= 200.0
        and best["minimumDevelopmentRoiWithoutTop1Pct"] >= 100.0
        and best["minimumDevelopmentRoiWithoutTop3Pct"] >= 80.0
    )
    holdout_summary = None
    holdout_passed = False
    if development_passed:
        selected_holdout, holdout_coverage = evaluate_configuration(
            holdout_races,
            best["calibrationScale"],
            best["racesPerVenueDay"],
            best["scoreProfile"],
        )
        holdout_courses = summarize(selected_holdout) if selected_holdout else {}
        holdout_summary = {"courses": holdout_courses, "coverage": holdout_coverage}
        holdout_passed = bool(
            selected_holdout
            and min(row["roiPct"] for row in holdout_courses.values()) >= 200.0
            and min(row["roiWithoutTop1Pct"] for row in holdout_courses.values()) >= 100.0
            and min(row["roiWithoutTop3Pct"] for row in holdout_courses.values()) >= 80.0
            and min((row["selected"] for row in holdout_coverage), default=0) >= 5
        )

    promotion = development_passed and holdout_passed
    factors = {
        bet_type: max(0.20, min(1.0, factor * best["calibrationScale"]))
        for bet_type, factor in policy.DEFAULT_CALIBRATION.items()
    }
    report = {
        **base_report,
        "status": "passed" if promotion else "development_failed" if not development_passed else "holdout_failed",
        "promotionEligible": promotion,
        "developmentPassed": development_passed,
        "finalHoldoutEvaluated": development_passed,
        "configurationsTested": configurations_tested,
        "bestDevelopmentConfiguration": best,
        "finalHoldout": holdout_summary,
        "calibrationFactors": factors,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if promotion:
        APPROVAL.parent.mkdir(parents=True, exist_ok=True)
        APPROVAL.write_text(
            json.dumps(
                {
                    "approved": True,
                    "modelVersion": policy.MODEL_VERSION,
                    "oddsSource": "jra_official",
                    "targetRoiPct": 200.0,
                    "minimumRacesPerVenueDay": 5,
                    "racesPerVenueDay": best["racesPerVenueDay"],
                    "scoreProfile": best["scoreProfile"],
                    "calibrationFactors": factors,
                    "sourceReport": "analysis-results/official-odds-roi200-forward-search.json",
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
