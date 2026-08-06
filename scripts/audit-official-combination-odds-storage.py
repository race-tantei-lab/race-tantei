import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "official-combination-odds-storage-audit.json"
ACCOUNT_ID = os.environ["CLOUDFLARE_ACCOUNT_ID"]
DATABASE_ID = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"


def query(sql, params=None):
    payload = json.dumps({"sql": sql, "params": params or []}).encode("utf-8")
    request = urllib.request.Request(
        URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("success"):
        raise RuntimeError(f"D1_QUERY_FAILED:{body}")
    result = body.get("result") or []
    if not result:
        return []
    return result[0].get("results") or []


def quoted(identifier):
    return '"' + str(identifier).replace('"', '""') + '"'


def main():
    tables = query("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    audit = []
    candidate_tables = []
    keywords = ("odds", "odd", "bet", "ticket", "quinella", "trifecta", "wide", "exacta", "馬連", "馬単", "ワイド", "3連")

    for table in tables:
        name = table["name"]
        columns = query(f"PRAGMA table_info({quoted(name)})")
        column_names = [row["name"] for row in columns]
        lower_values = [name.lower(), *(str(value).lower() for value in column_names)]
        relevant = any(keyword.lower() in value for keyword in keywords for value in lower_values)
        row = {
            "table": name,
            "columns": column_names,
            "schema": table.get("sql"),
            "relevantToOdds": relevant,
        }
        if relevant:
            count = query(f"SELECT COUNT(*) AS count FROM {quoted(name)}")
            row["rowCount"] = int(count[0]["count"]) if count else 0
            sample_columns = column_names[:20]
            if sample_columns:
                select_columns = ",".join(quoted(value) for value in sample_columns)
                try:
                    row["sample"] = query(f"SELECT {select_columns} FROM {quoted(name)} ORDER BY rowid DESC LIMIT 5")
                except Exception as error:
                    row["sampleError"] = str(error)
            candidate_tables.append(name)
        audit.append(row)

    direct_checks = {}
    for table_name in ("rt_odds", "rt_official_odds", "rt_bet_odds", "rt_odds_snapshots", "rt_bets", "rt_runners"):
        exists = any(row["table"] == table_name for row in audit)
        direct_checks[table_name] = {"exists": exists}
        if exists:
            info = next(row for row in audit if row["table"] == table_name)
            direct_checks[table_name].update({
                "rowCount": info.get("rowCount"),
                "columns": info.get("columns"),
                "sample": info.get("sample"),
            })

    all_columns = {row["table"]: row["columns"] for row in audit}
    combination_odds_columns = []
    for table_name, columns in all_columns.items():
        for column in columns:
            lower = column.lower()
            if "odds" in lower and lower not in {"win_odds", "assumed_odds"}:
                combination_odds_columns.append({"table": table_name, "column": column})

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "officialCombinationOddsStorageFound": bool(combination_odds_columns),
        "candidateTables": candidate_tables,
        "combinationOddsColumns": combination_odds_columns,
        "directChecks": direct_checks,
        "tables": audit,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "generatedAt": report["generatedAt"],
        "officialCombinationOddsStorageFound": report["officialCombinationOddsStorageFound"],
        "candidateTables": candidate_tables,
        "combinationOddsColumns": combination_odds_columns,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
