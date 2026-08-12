#!/usr/bin/env python3
import argparse
import json
import math
from pathlib import Path

START = "2016-08-10"
END = "2026-08-09"


def sql(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            return "NULL"
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def values_stmt(table, columns, rows, conflict):
    if not rows:
        return ""
    chunks = []
    for start in range(0, len(rows), 50):
        block = rows[start:start + 50]
        vals = ",\n".join("(" + ",".join(sql(row.get(c)) for c in columns) + ")" for row in block)
        chunks.append(f"INSERT INTO {table} ({','.join(columns)}) VALUES\n{vals}\n{conflict};\n")
    return "\n".join(chunks)


def race_row(bundle):
    r = bundle["race"]
    return {
        "race_id": r.get("raceId"), "race_date": r.get("raceDate"), "venue": r.get("venue"),
        "meeting_no": r.get("meetingNo"), "meeting_day": r.get("meetingDay"), "race_no": r.get("raceNo"),
        "race_name": r.get("raceName"), "conditions": r.get("conditions"), "surface": r.get("surface"),
        "distance_m": r.get("distanceM"), "direction": r.get("direction"), "start_time_jst": r.get("startTimeJst"),
        "start_time_utc": r.get("startTimeUtc"), "weather": r.get("weather"), "track_condition": r.get("trackCondition"),
        "entry_url": r.get("entryUrl"), "result_url": r.get("resultUrl"), "status": r.get("status") or "finished",
        "refund_horse_nos_json": json.dumps(bundle.get("refundHorseNos") or [], ensure_ascii=False, separators=(",", ":")),
    }


def runner_rows(bundle):
    rid = bundle["race"]["raceId"]
    out = []
    for r in bundle.get("runners") or []:
        out.append({
            "race_id": rid, "horse_no": r.get("horseNo"), "frame_no": r.get("frameNo"), "horse_name": r.get("horseName"),
            "sex_age": r.get("sexAge"), "coat_color": r.get("coatColor"), "horse_weight": r.get("horseWeight"),
            "weight_change": r.get("weightChange"), "jockey": r.get("jockey"), "assigned_weight": r.get("assignedWeight"),
            "trainer": r.get("trainer"), "stable": r.get("stable"), "win_odds": r.get("winOdds"),
            "popularity": r.get("popularity"), "runner_status": r.get("runnerStatus") or "active",
        })
    return out


def result_rows(bundle):
    rid = bundle["race"]["raceId"]
    return [{
        "race_id": rid, "horse_no": r.get("horseNo"), "finish_position": r.get("finishPosition"),
        "result_status": r.get("resultStatus"), "time_text": r.get("timeText"), "margin_text": r.get("marginText"),
        "final3f": r.get("final3f"),
    } for r in (bundle.get("results") or [])]


def payout_rows(bundle):
    rid = bundle["race"]["raceId"]
    return [{
        "race_id": rid, "bet_type": r.get("betType"), "combination": r.get("combination"),
        "payout_yen": r.get("payoutYen"), "popularity": r.get("popularity"),
    } for r in (bundle.get("payouts") or [])]


def write_chunk(out_dir: Path, index: int, bundles):
    races = [race_row(x) for x in bundles]
    runners = [r for x in bundles for r in runner_rows(x)]
    results = [r for x in bundles for r in result_rows(x)]
    payouts = [r for x in bundles for r in payout_rows(x)]

    parts = ["-- Race Tantei ten-year official history import. Does not touch predictions or rt_public_bets.\n"]
    parts.append(values_stmt(
        "rt_races",
        ["race_id","race_date","venue","meeting_no","meeting_day","race_no","race_name","conditions","surface","distance_m","direction","start_time_jst","start_time_utc","weather","track_condition","entry_url","result_url","status","refund_horse_nos_json"],
        races,
        "ON CONFLICT(race_id) DO UPDATE SET race_date=excluded.race_date,venue=excluded.venue,meeting_no=excluded.meeting_no,meeting_day=excluded.meeting_day,race_no=excluded.race_no,race_name=excluded.race_name,conditions=excluded.conditions,surface=excluded.surface,distance_m=excluded.distance_m,direction=excluded.direction,start_time_jst=COALESCE(excluded.start_time_jst,rt_races.start_time_jst),start_time_utc=COALESCE(excluded.start_time_utc,rt_races.start_time_utc),weather=COALESCE(excluded.weather,rt_races.weather),track_condition=COALESCE(excluded.track_condition,rt_races.track_condition),entry_url=COALESCE(excluded.entry_url,rt_races.entry_url),result_url=COALESCE(excluded.result_url,rt_races.result_url),status=excluded.status,refund_horse_nos_json=excluded.refund_horse_nos_json,updated_at=CURRENT_TIMESTAMP"
    ))
    parts.append(values_stmt(
        "rt_runners",
        ["race_id","horse_no","frame_no","horse_name","sex_age","coat_color","horse_weight","weight_change","jockey","assigned_weight","trainer","stable","win_odds","popularity","runner_status"],
        runners,
        "ON CONFLICT(race_id,horse_no) DO UPDATE SET frame_no=excluded.frame_no,horse_name=excluded.horse_name,sex_age=COALESCE(excluded.sex_age,rt_runners.sex_age),coat_color=COALESCE(excluded.coat_color,rt_runners.coat_color),horse_weight=COALESCE(excluded.horse_weight,rt_runners.horse_weight),weight_change=COALESCE(excluded.weight_change,rt_runners.weight_change),jockey=COALESCE(excluded.jockey,rt_runners.jockey),assigned_weight=COALESCE(excluded.assigned_weight,rt_runners.assigned_weight),trainer=COALESCE(excluded.trainer,rt_runners.trainer),stable=COALESCE(excluded.stable,rt_runners.stable),win_odds=COALESCE(excluded.win_odds,rt_runners.win_odds),popularity=COALESCE(excluded.popularity,rt_runners.popularity),runner_status=excluded.runner_status,updated_at=CURRENT_TIMESTAMP"
    ))
    parts.append(values_stmt(
        "rt_results",
        ["race_id","horse_no","finish_position","result_status","time_text","margin_text","final3f"],
        results,
        "ON CONFLICT(race_id,horse_no) DO UPDATE SET finish_position=excluded.finish_position,result_status=excluded.result_status,time_text=excluded.time_text,margin_text=excluded.margin_text,final3f=excluded.final3f,updated_at=CURRENT_TIMESTAMP"
    ))
    parts.append(values_stmt(
        "rt_payouts",
        ["race_id","bet_type","combination","payout_yen","popularity"],
        payouts,
        "ON CONFLICT(race_id,bet_type,combination) DO UPDATE SET payout_yen=excluded.payout_yen,popularity=excluded.popularity,updated_at=CURRENT_TIMESTAMP"
    ))
    path = out_dir / f"chunk-{index:04d}.sql"
    path.write_text("\n".join(parts), encoding="utf-8")
    return {"races": len(races), "runners": len(runners), "results": len(results), "payouts": len(payouts), "path": str(path)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--chunk-races", type=int, default=200)
    args = ap.parse_args()
    if args.chunk_races < 25 or args.chunk_races > 500:
        raise SystemExit("chunk-races must be 25..500")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("chunk-*.sql"):
        old.unlink()

    current = []
    summaries = []
    seen = set()
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            bundle = json.loads(line)
            race = bundle.get("race") or {}
            date = str(race.get("raceDate") or "")
            rid = str(race.get("raceId") or "")
            if not (START <= date <= END) or not rid or rid in seen:
                continue
            seen.add(rid)
            current.append(bundle)
            if len(current) >= args.chunk_races:
                summaries.append(write_chunk(out_dir, len(summaries), current))
                current = []
    if current:
        summaries.append(write_chunk(out_dir, len(summaries), current))

    totals = {k: sum(x[k] for x in summaries) for k in ("races","runners","results","payouts")}
    report = {"start": START, "end": END, "chunks": len(summaries), **totals}
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
