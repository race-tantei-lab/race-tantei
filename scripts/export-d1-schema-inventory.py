import json
import os
import time
import urllib.request
from pathlib import Path

TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "3c6d1826b573b2e68cb13ec37e9e8ade")
DATABASE = os.environ.get("CLOUDFLARE_D1_DATABASE_ID", "949b5e8b-d1a4-4c4e-80d1-d031afdc03de")
ENDPOINT = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "d1-schema-inventory.json"

if not TOKEN:
    raise RuntimeError("CLOUDFLARE_API_TOKEN is not set")


def sql(query, params=None):
    body = json.dumps({"sql": query, "params": params or []}).encode()
    for attempt in range(1, 6):
        req = urllib.request.Request(
            ENDPOINT,
            data=body,
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                payload = json.loads(response.read().decode())
            if not payload.get("success"):
                raise RuntimeError(payload.get("errors"))
            return payload.get("result", [{}])[0].get("results", [])
        except Exception:
            if attempt == 5:
                raise
            time.sleep(attempt)


def safe_ident(name):
    return '"' + str(name).replace('"', '""') + '"'


tables = sql("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
out = []
for row in tables:
    name = row["name"]
    columns = sql(f"PRAGMA table_info({safe_ident(name)})")
    count = sql(f"SELECT COUNT(*) AS n FROM {safe_ident(name)}")
    out.append({
        "name": name,
        "rowCount": int(count[0]["n"]) if count else 0,
        "columns": [c["name"] for c in columns],
    })

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps({"tables": out}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"tableCount": len(out), "tables": [x["name"] for x in out]}, ensure_ascii=False))
