#!/usr/bin/env python3
import datetime as dt
import json
import os
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
AUDIT = ROOT / "analysis-results" / "critical-auto-bet-generation.json"
WORKER_BASE = "https://race-tantei-phase0.race-tantei.workers.dev"
COURSES = {"ライト": 2000, "スタンダード": 5000, "プレミアム": 10000}


def d1_query(sql, params=None):
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    database = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
    token = os.environ["CLOUDFLARE_API_TOKEN"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{database}/query"
    body = json.dumps({"sql": sql, "params": params or []}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as response:
        payload = json.loads(response.read().decode())
    if not payload.get("success"):
        raise RuntimeError(payload.get("errors"))
    return payload.get("result", [{}])[0].get("results", [])


def jst_date(now):
    return (now + dt.timedelta(hours=9)).date().isoformat()


def strict_complete(race_id):
    rows = d1_query("SELECT course,bet_type AS betType,combination,stake_yen AS stakeYen,source_prediction_id AS sourcePredictionId FROM rt_public_bets WHERE race_id=? ORDER BY course,bet_type,combination", [race_id])
    if len(rows) != 6:
        return False
    signatures = []
    for course, budget in COURSES.items():
        current = [row for row in rows if row.get("course") == course]
        if len(current) != 2 or len({str(row.get("betType")) for row in current}) != 2:
            return False
        if any(int(row.get("sourcePredictionId") or 0) != -2 for row in current):
            return False
        if sum(int(row.get("stakeYen") or 0) for row in current) != budget:
            return False
        signatures.append("|".join(sorted(f"{row.get('betType')}:{row.get('combination')}" for row in current)))
    return len(set(signatures)) == 1


def trigger_race_page(race_id):
    req = urllib.request.Request(f"{WORKER_BASE}/races/{race_id}", headers={"User-Agent": "race-tantei-stored-preview-backup/1"})
    with urllib.request.urlopen(req, timeout=25) as response:
        response.read(1024)
        if response.status != 200:
            raise RuntimeError(f"PUBLIC_RACE_STATUS:{response.status}")


def main():
    now = dt.datetime.now(dt.timezone.utc)
    date = jst_date(now)
    state = d1_query("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1", [f"final_daily_selection:{date}"])
    if not state:
        raise RuntimeError(f"BACKUP_SELECTION_MISSING:{date}")
    payload = json.loads(state[0]["value"])
    selected = [str(row.get("raceId") or "") for row in payload.get("selected") or [] if row.get("raceId")]
    if not selected:
        raise RuntimeError(f"BACKUP_SELECTION_EMPTY:{date}")

    due = []
    future = []
    for race_id in selected:
        rows = d1_query("SELECT start_time_utc AS startTimeUtc FROM rt_races WHERE race_id=? LIMIT 1", [race_id])
        if not rows or not rows[0].get("startTimeUtc"):
            continue
        start = dt.datetime.fromisoformat(str(rows[0]["startTimeUtc"]).replace("Z", "+00:00"))
        remaining = (start - now).total_seconds()
        if 0 < remaining <= 15 * 60:
            due.append((start, race_id))
        elif remaining > 15 * 60:
            future.append(race_id)
    due.sort()

    self_healed = []
    already = []
    failures = []
    for _, race_id in due:
        if strict_complete(race_id):
            already.append(race_id)
            continue
        try:
            # This HTTP read invokes the production race-detail invariant. It is
            # DB-only at/after T-15: no odds fetch, no model scoring, no new bet.
            trigger_race_page(race_id)
            if not strict_complete(race_id):
                raise RuntimeError("STORED_PREVIEW_NOT_FINALIZED")
            self_healed.append(race_id)
        except Exception as exc:
            failures.append({"raceId": race_id, "error": f"{type(exc).__name__}:{exc}"})

    urgent = [race_id for _, race_id in due if not strict_complete(race_id)]
    audit = {
        "status": "ok" if not urgent and not failures else "error",
        "date": date,
        "checkedAt": now.isoformat().replace("+00:00", "Z"),
        "dueRaceIds": [race_id for _, race_id in due],
        "generatedRaceIds": [],
        "selfHealedRaceIds": self_healed,
        "alreadyFinalRaceIds": already,
        "remainingFutureRaceIds": future,
        "urgentMissingRaceIds": urgent,
        "failures": failures,
        "deadlineBreachRaceIds": urgent,
        "mode": "stored_preview_only",
    }
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))
    if urgent or failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
