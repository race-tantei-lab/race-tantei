#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "models" / "ten-year-race-selection-state.json.gz"
AUDIT_PATH = ROOT / "worker-selection-state-seed-audit.json"
MODEL_VERSION = "ten-year-completed-model"
CHUNK_BYTES = 180_000

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS rt_selection_state_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS rt_selection_state_chunk (generation TEXT NOT NULL,seq INTEGER NOT NULL,data_b64 TEXT NOT NULL,PRIMARY KEY(generation,seq))",
]


def d1_endpoint() -> str:
    return f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/d1/database/{os.environ['CLOUDFLARE_D1_DATABASE_ID']}/query"


def d1_request(body: dict) -> list[dict]:
    request = urllib.request.Request(
        d1_endpoint(),
        data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("success"):
        raise RuntimeError(f"D1_REQUEST_FAILED:{payload}")
    result = payload.get("result") or []
    for item in result:
        if item.get("success") is False:
            raise RuntimeError(f"D1_QUERY_FAILED:{item}")
    return result


def query(sql: str, params: list | None = None) -> list[dict]:
    result = d1_request({"sql": sql, "params": params or []})
    return (result[0].get("results") or []) if result else []


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raw = STATE_PATH.read_bytes()
    state = json.loads(gzip.decompress(raw).decode("utf-8"))
    through_date = str(state.get("throughDate") or "")
    current_quarter = str(state.get("currentQuarter") or "")
    if not through_date or not current_quarter:
        raise RuntimeError("CANONICAL_SELECTION_STATE_INVALID")
    state_sha = sha256(raw)
    generation = state_sha[:24]
    chunks = [raw[index:index + CHUNK_BYTES] for index in range(0, len(raw), CHUNK_BYTES)]
    audit = {
        "status": "DRY_RUN_OK",
        "modelVersion": MODEL_VERSION,
        "stateSha256": state_sha,
        "generation": generation,
        "throughDate": through_date,
        "currentQuarter": current_quarter,
        "byteLength": len(raw),
        "chunkCount": len(chunks),
        "applied": False,
    }
    if args.apply:
        for sql in SCHEMA:
            query(sql)
        query("DELETE FROM rt_selection_state_chunk WHERE generation=?", [generation])
        for seq, chunk in enumerate(chunks):
            query(
                "INSERT INTO rt_selection_state_chunk(generation,seq,data_b64) VALUES(?,?,?)",
                [generation, seq, base64.b64encode(chunk).decode("ascii")],
            )
        rows = query("SELECT COUNT(*) AS n FROM rt_selection_state_chunk WHERE generation=?", [generation])
        if not rows or int(rows[0].get("n") or 0) != len(chunks):
            raise RuntimeError(f"SELECTION_STATE_CHUNK_COUNT_MISMATCH:{rows}:{len(chunks)}")
        metadata = {
            "ready": "1",
            "modelVersion": MODEL_VERSION,
            "stateSha256": state_sha,
            "generation": generation,
            "throughDate": through_date,
            "currentQuarter": current_quarter,
            "byteLength": str(len(raw)),
            "chunkCount": str(len(chunks)),
        }
        for key, value in metadata.items():
            query(
                "INSERT INTO rt_selection_state_meta(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",
                [key, value],
            )
        verify = {row["key"]: row["value"] for row in query("SELECT key,value FROM rt_selection_state_meta")}
        for key, value in metadata.items():
            if verify.get(key) != value:
                raise RuntimeError(f"SELECTION_STATE_META_MISMATCH:{key}:{verify.get(key)}:{value}")
        query("DELETE FROM rt_selection_state_chunk WHERE generation<>?", [generation])
        audit.update({"status": "SEEDED_D1_OK", "applied": True})
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
