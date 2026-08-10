#!/usr/bin/env python3
import argparse
import collections
import importlib.util
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_START = "2016-08-10"
EVAL_END = "2026-08-09"
UNKNOWN = {"odds", "track", "weather", "mrank", "minpop", "maxpop", "popsum", "favcnt", "distort"}
BASE_NAMES = {"venue", "surface", "dist", "field", "raceNo", "season", "rclass", "direction"}
COMBO_NAMES = {"bet", "goodcnt", "bestform", "bestspeed", "bestj", "bestt", "expcnt", "top3lastsum"}
BET_SPECS = {
    0: (1, "win"),
    1: (2, "umaren"),
    2: (2, "wide"),
    3: (2, "umatan"),
    4: (3, "trio"),
    5: (3, "trifecta"),
}


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def active_runner(row):
    return (row.get("runnerStatus") or "active") == "active"


def normalize_class_text(text):
    value = str(text or "")
    return value.replace("500万下", "1勝クラス").replace("1000万下", "2勝クラス").replace("1600万下", "3勝クラス")


def safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


def horse_key(race_id, runner):
    name = str(runner.get("horseName") or "").strip()
    return name if name else f"__missing__:{race_id}:{runner.get('horseNo')}"


def load_rules(path):
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if len(rows) != 297:
        raise RuntimeError(f"PRUNED_RULE_COUNT_INVALID:{len(rows)}")
    known_names = set()
    for rule in rows:
        for name, _ in rule.get("conditions", []):
            if name not in UNKNOWN:
                known_names.add(name)
    unsupported = known_names - BASE_NAMES - COMBO_NAMES
    if unsupported:
        raise RuntimeError(f"UNSUPPORTED_PREDAY_CONDITION_NAMES:{sorted(unsupported)}")
    return rows


def group_rules_by_bet(rules):
    out = collections.defaultdict(list)
    for rule in rules:
        bet = next((value for name, value in rule.get("conditions", []) if name == "bet"), None)
        if bet is None:
            for bt in BET_SPECS:
                out[bt].append(rule)
        else:
            out[int(bet)].append(rule)
    return out


def rule_matches_preday(rule, vals):
    for name, value in rule.get("conditions", []):
        if name in UNKNOWN:
            continue
        if vals.get(name) != value:
            return False
    return True


def prefilter_rules(rules, base, bet):
    vals = dict(base)
    vals["bet"] = bet
    kept = []
    for rule in rules:
        ok = True
        for name, value in rule.get("conditions", []):
            if name in UNKNOWN or name in (COMBO_NAMES - {"bet"}):
                continue
            if vals.get(name) != value:
                ok = False
                break
        if ok:
            kept.append(rule)
    return kept


def feature_tuple(pmod, state, race_id, runner):
    hkey = horse_key(race_id, runner)
    prior = state["horse_hist"].get(hkey, ())
    if prior:
        form = sum(row[0] for row in prior) / len(prior)
        speed = sum(row[1] for row in prior) / len(prior)
        top3 = sum(row[2] for row in prior)
        has = True
    else:
        form = 0.0
        speed = 0.0
        top3 = 0
        has = False
    jockey = str(runner.get("jockey") or "")
    trainer = str(runner.get("trainer") or "")
    jstarts, jtop3 = state["jstats"].get(jockey, (0, 0)) if jockey else (0, 0)
    tstarts, ttop3 = state["tstats"].get(trainer, (0, 0)) if trainer else (0, 0)
    jr = (jtop3 + 3) / (jstarts + 15)
    tr = (ttop3 + 3) / (tstarts + 15)
    starts = int(state["horse_starts"].get(hkey, 0))
    return (
        pmod.formcode(form, has),
        pmod.formcode(speed, has),
        pmod.ratecode(jr),
        pmod.ratecode(tr),
        pmod.startsbin(starts),
        int(top3),
    )


def score_race(pmod, rules_by_bet, state, bundle):
    race = bundle["race"]
    race_id = str(race["raceId"])
    runners = [row for row in bundle.get("runners", []) if active_runner(row)]
    runners.sort(key=lambda row: int(row.get("horseNo") or 0))
    n = len(runners)
    if n < 3:
        return None
    venue = str(race.get("venue") or "")
    if venue not in pmod.VENUE_MAP:
        raise RuntimeError(f"UNKNOWN_VENUE:{race_id}:{venue}")
    surface = str(race.get("surface") or "障害")
    distance = int(race.get("distanceM") or 0)
    race_no = int(race.get("raceNo") or 0)
    if distance <= 0 or race_no <= 0:
        raise RuntimeError(f"INVALID_RACE_META:{race_id}:{distance}:{race_no}")
    conditions = normalize_class_text(race.get("conditions"))
    race_name = normalize_class_text(race.get("raceName"))
    base = {
        "venue": pmod.VENUE_MAP[venue],
        "surface": {"芝": 0, "ダート": 1, "障害": 2}.get(surface, 2),
        "dist": pmod.distbin(distance),
        "field": pmod.fieldbin(n),
        "raceNo": pmod.rnobin(race_no),
        "season": pmod.seasonbin(int(str(race["raceDate"])[5:7])),
        "rclass": pmod.classbin(race_name, conditions),
        "direction": pmod.directionbin(venue, surface, distance, race.get("direction")),
    }
    features = [feature_tuple(pmod, state, race_id, runner) for runner in runners]
    race_score = 0.0
    possible_bets = set()
    positive_combo_counts = collections.Counter()
    for bt, (k, _) in BET_SPECS.items():
        if n < k:
            continue
        candidate_rules = prefilter_rules(rules_by_bet.get(bt, []), base, bt)
        if not candidate_rules:
            continue
        for positions in itertools.combinations(range(n), k):
            fs = [features[i] for i in positions]
            vals = dict(base)
            vals.update({
                "bet": bt,
                "goodcnt": min(3, sum(1 for row in fs if row[0] >= 3)),
                "bestform": max(row[0] for row in fs),
                "bestspeed": max(row[1] for row in fs),
                "bestj": max(row[2] for row in fs),
                "bestt": max(row[3] for row in fs),
                "expcnt": min(3, sum(1 for row in fs if row[4] >= 2)),
                "top3lastsum": min(7, sum(row[5] for row in fs)),
            })
            best = 0.0
            for rule in candidate_rules:
                if rule_matches_preday(rule, vals):
                    best = max(best, float(rule.get("newScore", 0.0)))
            if best > 0:
                possible_bets.add(bt)
                positive_combo_counts[bt] += 1
                if best > race_score:
                    race_score = best
    return {
        "raceId": race_id,
        "raceDate": str(race["raceDate"]),
        "venue": venue,
        "raceNo": race_no,
        "raceName": race.get("raceName"),
        "conditions": race.get("conditions"),
        "resultUrl": race.get("resultUrl") or bundle.get("provenance", {}).get("resultUrl"),
        "runnerCount": n,
        "raceScore": race_score,
        "possibleBetTypes": sorted(possible_bets),
        "positivePredayCombinationCounts": {str(k): int(v) for k, v in sorted(positive_combo_counts.items())},
    }


def update_state_for_date(state, bundles):
    # All updates happen only after every race on the date has been scored, preventing same-day leakage.
    for bundle in bundles:
        race = bundle["race"]
        race_id = str(race["raceId"])
        runners = [row for row in bundle.get("runners", []) if active_runner(row)]
        runners_by_no = {int(row["horseNo"]): row for row in runners if safe_int(row.get("horseNo")) is not None}
        field_count = len(runners)
        results = []
        for row in bundle.get("results", []):
            hno = safe_int(row.get("horseNo"))
            pos = safe_int(row.get("finishPosition"))
            if hno is None or pos is None or pos <= 0 or hno not in runners_by_no:
                continue
            f3 = row.get("final3f")
            try:
                f3 = float(f3) if f3 is not None else None
            except Exception:
                f3 = None
            results.append((hno, pos, f3))
        valid3f = sorted((f3, hno) for hno, _, f3 in results if f3 is not None)
        speed_rank = {hno: i for i, (_, hno) in enumerate(valid3f)}
        vf = len(valid3f)
        for hno, pos, f3 in results:
            runner = runners_by_no[hno]
            hkey = horse_key(race_id, runner)
            form = max(0.0, 1.0 - (pos - 1) / max(1, field_count - 1))
            if f3 is None:
                speed = 0.5
            else:
                faster = speed_rank[hno]
                speed = 1.0 - (faster / max(1, vf - 1))
            hist = state["horse_hist"][hkey]
            hist.append((form, speed, int(pos <= 3)))
            state["horse_starts"][hkey] += 1
            jockey = str(runner.get("jockey") or "")
            trainer = str(runner.get("trainer") or "")
            if jockey:
                js = state["jstats"][jockey]
                js[0] += 1
                js[1] += int(pos <= 3)
            if trainer:
                ts = state["tstats"][trainer]
                ts[0] += 1
                ts[1] += int(pos <= 3)


def process_date(pmod, rules_by_bet, state, date, bundles, output, stats):
    in_eval = EVAL_START <= date <= EVAL_END
    if in_eval:
        scored = []
        for bundle in bundles:
            stats["evaluationRacesSeen"] += 1
            row = score_race(pmod, rules_by_bet, state, bundle)
            if row is not None:
                scored.append(row)
        by_venue = collections.defaultdict(list)
        for row in scored:
            by_venue[row["venue"]].append(row)
        for venue, rows in by_venue.items():
            rows.sort(key=lambda row: (-row["raceScore"], row["raceNo"]))
            if len(rows) < 5:
                stats["venueDaysBelowFive"].append({"date": date, "venue": venue, "eligible": len(rows)})
                continue
            chosen = rows[:5]
            stats["venueDays"] += 1
            stats["selectedRaces"] += len(chosen)
            stats["selectedByYear"][date[:4]] += len(chosen)
            for row in chosen:
                possible = set(int(x) for x in row["possibleBetTypes"])
                required = {"win"}
                for bt in possible:
                    required.add(BET_SPECS[bt][1])
                row["requiredMarkets"] = [name for name in ("win", "umaren", "wide", "umatan", "trio", "trifecta") if name in required]
                row["sourceRuleCount"] = 297
                row["targetDayResultsUsedForSelection"] = False
                row["syntheticOddsUsed"] = False
                row["productionDatabaseWritten"] = False
                if row["raceScore"] <= 0 or not possible:
                    stats["zeroScoreSelected"] += 1
                for market in row["requiredMarkets"]:
                    stats["marketRaceDemand"][market] += 1
                output.append(row)
    update_state_for_date(state, bundles)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta", required=True)
    args = ap.parse_args()

    pmod = load_module(ROOT / "scripts" / "generate-final-preday-selection.py", "research_preday_bins")
    rules = load_rules(ROOT / args.rules)
    rules_by_bet = group_rules_by_bet(rules)
    state = {
        "horse_hist": collections.defaultdict(lambda: collections.deque(maxlen=3)),
        "horse_starts": collections.Counter(),
        "jstats": collections.defaultdict(lambda: [0, 0]),
        "tstats": collections.defaultdict(lambda: [0, 0]),
    }
    stats = {
        "evaluationRacesSeen": 0,
        "venueDays": 0,
        "selectedRaces": 0,
        "selectedByYear": collections.Counter(),
        "marketRaceDemand": collections.Counter(),
        "zeroScoreSelected": 0,
        "venueDaysBelowFive": [],
    }
    output = []
    current_date = None
    day_rows = []
    corpus_path = ROOT / args.corpus
    with corpus_path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            bundle = json.loads(line)
            date = str(bundle.get("race", {}).get("raceDate") or "")
            if not date:
                raise RuntimeError(f"RACE_DATE_MISSING_LINE:{line_no}")
            if current_date is None:
                current_date = date
            if date != current_date:
                process_date(pmod, rules_by_bet, state, current_date, day_rows, output, stats)
                if stats["evaluationRacesSeen"] and stats["evaluationRacesSeen"] % 3000 < len(day_rows):
                    print(json.dumps({
                        "throughDate": current_date,
                        "evaluationRacesSeen": stats["evaluationRacesSeen"],
                        "selectedRaces": stats["selectedRaces"],
                    }, ensure_ascii=False), flush=True)
                day_rows = []
                current_date = date
            day_rows.append(bundle)
    if current_date is not None:
        process_date(pmod, rules_by_bet, state, current_date, day_rows, output, stats)

    if stats["evaluationRacesSeen"] != 34566:
        raise RuntimeError(f"EVALUATION_RACE_COUNT_MISMATCH:{stats['evaluationRacesSeen']}")
    if stats["venueDaysBelowFive"]:
        raise RuntimeError(f"VENUE_DAYS_BELOW_FIVE:{stats['venueDaysBelowFive'][:20]}:count={len(stats['venueDaysBelowFive'])}")
    if not output:
        raise RuntimeError("NO_SELECTED_RACES")

    out_path = ROOT / args.out
    meta_path = ROOT / args.meta
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in output), encoding="utf-8")
    meta = {
        "purpose": "research_only_canonical_297_preday_demand",
        "evaluationStart": EVAL_START,
        "evaluationEnd": EVAL_END,
        "evaluationRaceCount": stats["evaluationRacesSeen"],
        "sourceRuleCount": 297,
        "venueDays": stats["venueDays"],
        "selectedRaces": stats["selectedRaces"],
        "selectedByYear": dict(sorted(stats["selectedByYear"].items())),
        "marketRaceDemand": {name: int(stats["marketRaceDemand"].get(name, 0)) for name in ("win", "umaren", "wide", "umatan", "trio", "trifecta")},
        "zeroScoreSelected": stats["zeroScoreSelected"],
        "venueDaysBelowFive": stats["venueDaysBelowFive"],
        "selectionRule": "behavior-equivalent 297 canonical rules; prior-date history only; top five by preday max score per venue/day; raceNo ascending ties",
        "orderedMarketsCollapsedToHorseCombinationsForPredaySelection": True,
        "reason": "Preday-known rule features are order-symmetric; order-dependent market features are ignored at preday selection exactly as production rule_score(preday=True).",
        "targetDayResultsUsedForSelection": False,
        "historicalClassNormalizationApplied": True,
        "syntheticOddsUsed": False,
        "productionDatabaseWritten": False,
        "productionModelChanged": False,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
