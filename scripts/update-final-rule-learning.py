import json
import math
import os
import time
import urllib.request
from datetime import datetime, timezone

TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "3c6d1826b573b2e68cb13ec37e9e8ade")
DATABASE = os.environ.get("CLOUDFLARE_D1_DATABASE_ID", "949b5e8b-d1a4-4c4e-80d1-d031afdc03de")
ENDPOINT = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query"
STATE_KEY = "final_rule_learning:state"

BET_INDEX = {"単勝": 0, "馬連": 1, "ワイド": 2, "馬単": 3, "3連複": 4, "3連単": 5}
VENUE_INDEX = {"東京": 0, "中山": 1, "京都": 2, "阪神": 3, "中京": 4, "新潟": 5, "福島": 6, "小倉": 7, "札幌": 8, "函館": 9}
ODDS_EDGES = [2, 3, 5, 7, 10, 15, 20, 30, 50, 75, 100, 150, 300, 500, 800, 1200, 2000]
PRIOR_STAKE_YEN = 100_000
MIN_FACTOR = 0.80
MAX_FACTOR = 1.20

if not TOKEN:
    raise RuntimeError("CLOUDFLARE_API_TOKEN is not set")


def d1_query(sql, params=None):
    body = json.dumps({"sql": sql, "params": params or []}, ensure_ascii=False).encode("utf-8")
    last_error = None
    for attempt in range(1, 7):
        request = urllib.request.Request(
            ENDPOINT,
            data=body,
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not payload.get("success"):
                raise RuntimeError(f"D1_ERROR:{payload.get('errors')}")
            time.sleep(0.05)
            return payload.get("result", [{}])[0].get("results", [])
        except Exception as error:
            last_error = error
            if attempt == 6:
                raise
            time.sleep(attempt * 1.5)
    raise last_error


def odds_bin(value):
    try:
        odds = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(odds) or odds <= 1.0:
        return None
    index = 0
    while index < len(ODDS_EDGES) and odds >= ODDS_EDGES[index]:
        index += 1
    return index


def clamp(value, low, high):
    return max(low, min(high, value))


def add_bucket(buckets, key, row):
    item = buckets.setdefault(key, {"samples": 0, "races": set(), "stakeYen": 0, "returnYen": 0})
    item["samples"] += 1
    item["races"].add(str(row["raceId"]))
    item["stakeYen"] += int(row.get("stakeYen") or 0)
    item["returnYen"] += int(row.get("returnYen") or 0)


def finalize_bucket(item):
    stake = int(item["stakeYen"])
    returned = int(item["returnYen"])
    posterior_roi = (returned + PRIOR_STAKE_YEN) / max(1, stake + PRIOR_STAKE_YEN)
    factor = clamp(math.sqrt(max(0.01, posterior_roi)), MIN_FACTOR, MAX_FACTOR)
    return {
        "samples": int(item["samples"]),
        "races": len(item["races"]),
        "stakeYen": stake,
        "returnYen": returned,
        "roiPct": round(returned / stake * 100.0, 4) if stake else None,
        "factor": round(factor, 8),
    }


def load_settled_live_tickets():
    return d1_query(
        """
        WITH grouped AS (
          SELECT
            b.race_id AS raceId,
            b.bet_type AS betType,
            b.combination AS combination,
            r.venue AS venue,
            COUNT(*) AS rows,
            SUM(CASE WHEN b.settlement_status='settled' THEN 1 ELSE 0 END) AS settledRows,
            SUM(b.stake_yen) AS stakeYen,
            SUM(CASE WHEN b.settlement_status='settled' THEN COALESCE(b.return_yen,0) ELSE 0 END) AS returnYen,
            AVG(CASE WHEN b.assumed_odds>1 THEN b.assumed_odds END) AS assumedOdds
          FROM rt_public_bets b
          JOIN rt_races r ON r.race_id=b.race_id
          WHERE b.source_prediction_id=-2
            AND b.locked_at IS NOT NULL
            AND r.start_time_utc IS NOT NULL
            AND datetime(b.locked_at) < datetime(r.start_time_utc)
          GROUP BY b.race_id,b.bet_type,b.combination,r.venue
        )
        SELECT raceId,betType,combination,venue,stakeYen,returnYen,assumedOdds
        FROM grouped
        WHERE rows=settledRows AND rows>0
        ORDER BY raceId,betType,combination
        """
    )


def build_state(rows):
    buckets = {}
    live_races = set()
    usable = 0
    for row in rows:
        bet = BET_INDEX.get(str(row.get("betType") or ""))
        venue = VENUE_INDEX.get(str(row.get("venue") or ""))
        obin = odds_bin(row.get("assumedOdds"))
        if bet is None or venue is None or obin is None:
            continue
        usable += 1
        live_races.add(str(row["raceId"]))
        keys = (
            f"b:{bet}",
            f"b:{bet}|v:{venue}",
            f"b:{bet}|o:{obin}",
            f"b:{bet}|v:{venue}|o:{obin}",
        )
        for key in keys:
            add_bucket(buckets, key, row)

    return {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "settled pre-start-locked final live public bets only",
        "immutableHistory": True,
        "priorStakeYen": PRIOR_STAKE_YEN,
        "factorRange": [MIN_FACTOR, MAX_FACTOR],
        "settledUniqueTickets": usable,
        "settledRaces": len(live_races),
        "buckets": {key: finalize_bucket(value) for key, value in sorted(buckets.items())},
    }


def save_state(state):
    encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    d1_query(
        """
        INSERT INTO rt_system_state(state_key,state_value,updated_at)
        VALUES(?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
        """,
        [STATE_KEY, encoded],
    )
    check = d1_query("SELECT state_value AS value FROM rt_system_state WHERE state_key=?", [STATE_KEY])
    if not check or str(check[0].get("value") or "") != encoded:
        raise RuntimeError("FINAL_RULE_LEARNING_STATE_VERIFY_FAILED")


def main():
    rows = load_settled_live_tickets()
    state = build_state(rows)
    save_state(state)
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    main()
