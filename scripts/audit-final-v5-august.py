import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

OUTPUT = Path("final-v5-august-audit.json")
MODEL = "v5.0.0-nonlinear-course-policy"
START = "2026-08-01"
END = "2026-08-02"
TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
DATABASE = os.environ.get("CLOUDFLARE_D1_DATABASE_ID")

if not TOKEN or not ACCOUNT or not DATABASE:
    raise RuntimeError("FINAL_V5_AUDIT_CLOUDFLARE_ENV_MISSING")

ENDPOINT = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query"


def sql(query, params=None):
    body = json.dumps({"sql": query, "params": params or []}).encode()
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"FINAL_V5_AUDIT_HTTP_{error.code}:{detail}") from error
    if not payload.get("success"):
        raise RuntimeError(f"FINAL_V5_AUDIT_D1_ERROR:{payload.get('errors')}")
    return payload.get("result", [{}])[0].get("results", [])


def n(value):
    return int(value or 0)


def main():
    prediction = sql(
        """SELECT COUNT(*) predictions,COUNT(DISTINCT p.race_id) predictionRaces
        FROM rt_predictions p JOIN rt_races r ON r.race_id=p.race_id
        WHERE p.model_version=? AND r.race_date BETWEEN ? AND ?""",
        [MODEL, START, END],
    )[0]
    runner = sql(
        """SELECT COUNT(*) runnerRows
        FROM rt_prediction_runners pr JOIN rt_predictions p ON p.id=pr.prediction_id
        JOIN rt_races r ON r.race_id=p.race_id
        WHERE p.model_version=? AND r.race_date BETWEEN ? AND ?""",
        [MODEL, START, END],
    )[0]
    bet = sql(
        """SELECT COUNT(*) bets,COUNT(DISTINCT b.race_id) selectedRaces,
          COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN 1 ELSE 0 END),0) settledBets,
          COALESCE(SUM(CASE WHEN b.settlement_status<>'settled' THEN 1 ELSE 0 END),0) unsettledBets
        FROM rt_bets b JOIN rt_predictions p ON p.id=b.prediction_id
        JOIN rt_races r ON r.race_id=p.race_id
        WHERE p.model_version=? AND r.race_date BETWEEN ? AND ?""",
        [MODEL, START, END],
    )[0]
    summary = {**prediction, **runner, **bet}
    rows = sql(
        """
        SELECT r.race_date raceDate,
          CASE WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
               WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
               WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム' END course,
          COUNT(DISTINCT b.race_id) races,
          COUNT(*) tickets,
          COALESCE(SUM(b.stake_yen),0) stakeYen,
          COALESCE(SUM(b.return_yen),0) returnYen,
          COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) hitRaces,
          COALESCE(SUM(CASE WHEN b.settlement_status<>'settled' THEN 1 ELSE 0 END),0) unsettledTickets
        FROM rt_bets b
        JOIN rt_predictions p ON p.id=b.prediction_id
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE p.model_version=? AND r.race_date BETWEEN ? AND ?
        GROUP BY r.race_date,course
        ORDER BY r.race_date,course
        """,
        [MODEL, START, END],
    )
    dates = {}
    aggregate = {}
    for row in rows:
        race_date = row["raceDate"]
        course = row["course"]
        stake = n(row["stakeYen"])
        returned = n(row["returnYen"])
        races = n(row["races"])
        item = {
            "races": races,
            "tickets": n(row["tickets"]),
            "stakeYen": stake,
            "returnYen": returned,
            "profitYen": returned - stake,
            "roiPct": round(returned / stake * 100, 4) if stake else None,
            "hitRaces": n(row["hitRaces"]),
            "hitRatePct": round(n(row["hitRaces"]) / races * 100, 4) if races else None,
            "unsettledTickets": n(row["unsettledTickets"]),
        }
        dates.setdefault(race_date, {})[course] = item
        agg = aggregate.setdefault(course, {"races": 0, "tickets": 0, "stakeYen": 0, "returnYen": 0, "hitRaces": 0, "unsettledTickets": 0})
        for key in ("races", "tickets", "stakeYen", "returnYen", "hitRaces", "unsettledTickets"):
            agg[key] += item[key]
    for row in aggregate.values():
        row["profitYen"] = row["returnYen"] - row["stakeYen"]
        row["roiPct"] = round(row["returnYen"] / row["stakeYen"] * 100, 4) if row["stakeYen"] else None
        row["hitRatePct"] = round(row["hitRaces"] / row["races"] * 100, 4) if row["races"] else None
    numeric_summary = {key: n(value) for key, value in summary.items()}
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "modelVersion": MODEL,
        "summary": numeric_summary,
        "complete": numeric_summary["predictionRaces"] == 72 and numeric_summary["selectedRaces"] == 30 and numeric_summary["bets"] > 0 and numeric_summary["unsettledBets"] == 0,
        "dates": dates,
        "aggregate": aggregate,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
