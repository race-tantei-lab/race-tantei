import argparse, datetime, importlib.util, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEADLINES = {
    "2026-08-09-niigata-11": "2026-08-09T08:35:00+00:00",
    "2026-08-09-chukyo-11": "2026-08-09T08:45:00+00:00",
    "2026-08-09-niigata-12": "2026-08-09T09:05:00+00:00",
}


def load_collector():
    p = ROOT / "scripts" / "collect-jra-official-odds.py"
    spec = importlib.util.spec_from_file_location("reconcile_collector", p)
    if spec is None or spec.loader is None:
        raise RuntimeError("COLLECTOR_LOAD_FAILED")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def key_candidate(row):
    return (str(row["course"]), str(row["betType"]), str(row["combination"]), int(row["stakeYen"]), round(float(row["assumedOdds"]), 6))


def key_existing(row):
    return (str(row["course"]), str(row["bet_type"]), str(row["combination"]), int(row["stake_yen"]), round(float(row["assumed_odds"] or 0), 6))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    collector = load_collector()
    data = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    by_race = {str(r["raceId"]): r for r in data.get("races", [])}
    now = datetime.datetime.now(datetime.timezone.utc)
    report = {"checkedAt": now.isoformat(), "races": []}

    for race_id, deadline_text in DEADLINES.items():
        candidate = by_race.get(race_id)
        if candidate is None:
            report["races"].append({"raceId": race_id, "status": "candidate_not_available"})
            continue
        expected = {key_candidate(x) for x in candidate.get("courseBets", [])}
        existing_rows = collector.d1_query(
            "SELECT course,bet_type,combination,stake_yen,assumed_odds,locked_at,source_prediction_id FROM rt_public_bets WHERE race_id=? ORDER BY course,bet_type,combination",
            [race_id],
        )
        existing = {key_existing(x) for x in existing_rows}
        if existing == expected:
            report["races"].append({"raceId": race_id, "status": "unchanged_exact_match", "rows": len(existing)})
            continue
        deadline = datetime.datetime.fromisoformat(deadline_text)
        if now >= deadline:
            report["races"].append({"raceId": race_id, "status": "different_but_deadline_passed_no_change", "existingRows": len(existing), "candidateRows": len(expected), "deadline": deadline_text})
            continue
        foreign = [x for x in existing_rows if int(x.get("source_prediction_id") or 0) != -2]
        if foreign:
            raise RuntimeError(f"REFUSE_DELETE_NON_FINAL_ROWS:{race_id}:{len(foreign)}")
        collector.d1_query("DELETE FROM rt_public_bets WHERE race_id=? AND source_prediction_id=-2", [race_id])
        locked = now.isoformat()
        for course, bet_type, combination, stake, odds in sorted(expected):
            collector.d1_query(
                "INSERT INTO rt_public_bets(race_id,course,bet_type,combination,stake_yen,assumed_odds,return_yen,settlement_status,locked_at,source_prediction_id) VALUES(?,?,?,?,?,?,NULL,'pending',?,-2)",
                [race_id, course, bet_type, combination, stake, odds, locked],
            )
        saved_rows = collector.d1_query(
            "SELECT course,bet_type,combination,stake_yen,assumed_odds FROM rt_public_bets WHERE race_id=? ORDER BY course,bet_type,combination",
            [race_id],
        )
        saved = {key_existing(x) for x in saved_rows}
        if saved != expected:
            raise RuntimeError(f"RECONCILE_VERIFY_FAILED:{race_id}:{len(saved)}:{len(expected)}")
        report["races"].append({"raceId": race_id, "status": "corrected_before_deadline", "oldRows": len(existing), "newRows": len(saved), "deadline": deadline_text, "lockedAt": locked})

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
