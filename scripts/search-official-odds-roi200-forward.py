import importlib.util
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "publish-nonlinear-v4-production.py"
POLICY_PATH = ROOT / "scripts" / "official-odds-roi200-policy.py"
OUTPUT = ROOT / "official-odds-roi200-forward-search.json"
APPROVAL = ROOT / "config" / "official-odds-calibration.json"
MINIMUM_SETTLED_RACES = 400
MINIMUM_RACES_PER_FOLD = 75
CALIBRATION_SCALES = (0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.05)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = load_module("official_forward_base", BASE_PATH)
policy = load_module("official_forward_policy", POLICY_PATH)


def load_rows():
    return base.sql(
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
        LEFT JOIN rt_official_odds_snapshots o
          ON o.race_id=c.race_id
         AND o.bet_type=c.bet_type
         AND o.combination=c.combination
         AND o.captured_at_utc=c.captured_at_utc
        LEFT JOIN rt_payouts p
          ON p.race_id=c.race_id
         AND p.bet_type=c.bet_type
         AND p.combination=c.combination
        WHERE c.model_version=?
          AND c.odds_source='jra_official'
          AND (o.seconds_to_start IS NULL OR o.seconds_to_start >= 60)
        ORDER BY r.race_date, r.venue, r.race_no, c.captured_at_utc,
                 c.bet_type, c.combination
        """,
        [policy.MODEL_VERSION],
    )


def horses_from_combination(value):
    return [int(token) for token in str(value).replace("→", "-").replace("－", "-").split("-") if token.strip().isdigit()]


def organize(rows):
    snapshots = defaultdict(list)
    metadata = {}
    for row in rows:
        key = (row["raceId"], row["capturedAtUtc"])
        refunds = set(json.loads(row.get("refundHorseNosJson") or "[]"))
        horses = horses_from_combination(row["combination"])
        payout = 100 if refunds.intersection(horses) else int(row.get("payoutYen") or 0)
        snapshots[key].append({
            "betType": row["betType"],
            "combination": row["combination"],
            "modelProbability": float(row["modelProbability"]),
            "officialOdds": float(row["officialOdds"]),
            "predictedRankSum": int(row["predictedRankSum"]),
            "includesModelFirst": bool(row["includesModelFirst"]),
            "payoutYen": payout,
        })
        metadata[key] = {
            "raceId": row["raceId"],
            "raceDate": row["raceDate"],
            "venue": row["venue"],
            "raceNo": int(row["raceNo"]),
            "capturedAtUtc": row["capturedAtUtc"],
            "secondsToStart": int(row.get("secondsToStart") or 0),
        }
    by_race = defaultdict(list)
    for key, candidates in snapshots.items():
        by_race[key[0]].append((metadata[key], candidates))
    races = []
    for race_id, versions in by_race.items():
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
    return {
        **candidate,
        "conservativeProbability": max(0.0, min(model_probability, conservative)),
        "projectedRoiPct": conservative * official_odds * 100.0,
    }


def candidate_score(candidate):
    return (
        math.log(max(0.01, candidate["projectedRoiPct"] / 100.0)) * 4.0
        + math.log(max(1e-9, candidate["conservativeProbability"])) * 0.30
        - candidate["predictedRankSum"] * 0.025
        + (0.08 if candidate["includesModelFirst"] else 0.0)
    )


def select_for_course(course, candidates):
    required = policy.COURSE_TYPES[course]
    target_count = policy.COURSE_TICKET_COUNTS[course]
    caps = policy.TYPE_CAPS[course]
    by_type = defaultdict(list)
    for candidate in candidates:
        if candidate["betType"] in required:
            by_type[candidate["betType"]].append(candidate)
    for bet_type in by_type:
        by_type[bet_type].sort(key=candidate_score, reverse=True)
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
    for candidate in sorted(candidates, key=candidate_score, reverse=True):
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
    stakes = policy.allocate_stakes(course, selected)
    budget = policy.COURSE_TARGET_STAKES[course]
    projected = sum(stake * row["projectedRoiPct"] / 100.0 for row, stake in zip(selected, stakes)) / budget * 100.0
    actual_return = sum(stake / 100.0 * row["payoutYen"] for row, stake in zip(selected, stakes))
    return {
        "projectedRoiPct": projected,
        "actualReturnYen": actual_return,
        "stakeYen": budget,
        "hit": actual_return > 0,
    }


def evaluate_configuration(races, scale):
    evaluated = []
    for race in races:
        candidates = [calibrated_candidate(row, scale) for row in race["candidates"]]
        plans = {course: select_for_course(course, candidates) for course in policy.COURSES}
        if any(plan is None for plan in plans.values()):
            continue
        joint = min(plan["projectedRoiPct"] for plan in plans.values())
        if joint < policy.TARGET_ROI_PCT:
            continue
        evaluated.append({**race, "plans": plans, "jointProjectedRoiPct": joint})
    grouped = defaultdict(list)
    for race in evaluated:
        grouped[(race["raceDate"], race["venue"])].append(race)
    selected = []
    coverage = []
    for key, group in sorted(grouped.items()):
        group.sort(key=lambda race: (-race["jointProjectedRoiPct"], race["raceNo"]))
        if len(group) < policy.MINIMUM_RACES_PER_VENUE_DAY:
            continue
        picked = group[: policy.MAXIMUM_RACES_PER_VENUE_DAY]
        selected.extend(picked)
        coverage.append({"date": key[0], "venue": key[1], "selected": len(picked)})
    return selected, coverage


def split_folds(races):
    dates = sorted({race["raceDate"] for race in races})
    if len(dates) < 8:
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
        top = max(values, default=0)
        result[course] = {
            "races": len(races),
            "stakeYen": stake,
            "returnYen": round(total),
            "roiPct": total / stake * 100.0 if stake else None,
            "roiWithoutTop1Pct": (total - top) / stake * 100.0 if stake else None,
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
        "generatedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "modelVersion": policy.MODEL_VERSION,
        "productionChanged": False,
        "oddsSource": "jra_official",
        "settledOfficialOddsRaces": len(races),
        "minimumRequiredSettledRaces": MINIMUM_SETTLED_RACES,
        "targetRoiPct": policy.TARGET_ROI_PCT,
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
    for scale in CALIBRATION_SCALES:
        fold_summaries = []
        fold_coverage = []
        valid = True
        for fold in folds:
            selected, coverage = evaluate_configuration(fold, scale)
            if not selected:
                valid = False
                break
            fold_summaries.append(summarize(selected))
            fold_coverage.append(coverage)
        if not valid:
            continue
        min_roi = minimum_metric(fold_summaries, "roiPct")
        min_trimmed = minimum_metric(fold_summaries, "roiWithoutTop1Pct")
        score = min_roi * 0.75 + min_trimmed * 0.25
        row = {
            "calibrationScale": scale,
            "minimumDevelopmentRoiPct": min_roi,
            "minimumDevelopmentRoiWithoutTop1Pct": min_trimmed,
            "folds": fold_summaries,
            "coverage": fold_coverage,
            "score": score,
        }
        if best is None or row["score"] > best["score"]:
            best = row

    if best is None:
        report = {**base_report, "status": "no_configuration_with_five_races", "promotionEligible": False}
        OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    development_passed = best["minimumDevelopmentRoiPct"] >= 200.0 and best["minimumDevelopmentRoiWithoutTop1Pct"] >= 100.0
    holdout_summary = None
    holdout_passed = False
    if development_passed:
        selected_holdout, holdout_coverage = evaluate_configuration(holdout_races, best["calibrationScale"])
        holdout_summary = {
            "courses": summarize(selected_holdout),
            "coverage": holdout_coverage,
        }
        holdout_passed = (
            selected_holdout
            and min(row["roiPct"] or -1 for row in holdout_summary["courses"].values()) >= 200.0
            and min(row["roiWithoutTop1Pct"] or -1 for row in holdout_summary["courses"].values()) >= 100.0
        )

    promotion = bool(development_passed and holdout_passed)
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
                    "calibrationFactors": factors,
                    "sourceReport": "analysis-results/official-odds-roi200-forward-search.json",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
