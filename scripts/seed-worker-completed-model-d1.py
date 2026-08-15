#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL_BIN = ROOT / "worker-assets" / "_internal" / "completed-model" / "model.bin"
METADATA = ROOT / "worker-assets" / "_internal" / "completed-model" / "metadata.json"
AUDIT = ROOT / "worker-model-d1-seed-audit.json"
MODEL_VERSION = "ten-year-completed-model"
CHUNK_BYTES = 180_000

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS rt_ml_model_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS rt_ml_model_chunk (generation TEXT NOT NULL,seq INTEGER NOT NULL,data_b64 TEXT NOT NULL,PRIMARY KEY(generation,seq))",
]


def d1_endpoint() -> str:
    return f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/d1/database/{os.environ['CLOUDFLARE_D1_DATABASE_ID']}/query"


def d1_request(body: dict) -> list[dict]:
    req = urllib.request.Request(
        d1_endpoint(),
        data=json.dumps(body, separators=(",", ":")).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        payload = json.loads(response.read().decode())
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
    if not MODEL_BIN.exists() or not METADATA.exists():
        raise RuntimeError("WORKER_MODEL_ASSET_MISSING: run build-worker-completed-model-assets.py first")

    raw = MODEL_BIN.read_bytes()
    meta = json.loads(METADATA.read_text(encoding="utf-8"))
    source_sha = str(meta.get("sourceSha256") or "")
    binary_sha = sha256(raw)
    generation = f"{source_sha[:16]}-{binary_sha[:16]}"
    chunks = [raw[i:i + CHUNK_BYTES] for i in range(0, len(raw), CHUNK_BYTES)]
    audit = {
        "status": "DRY_RUN_OK",
        "modelVersion": MODEL_VERSION,
        "sourceSha256": source_sha,
        "binarySha256": binary_sha,
        "generation": generation,
        "byteLength": len(raw),
        "chunkCount": len(chunks),
        "applied": False,
    }

    if args.apply:
        for sql in SCHEMA:
            query(sql)
        query("DELETE FROM rt_ml_model_chunk WHERE generation=?", [generation])
        for seq, chunk in enumerate(chunks):
            query(
                "INSERT INTO rt_ml_model_chunk(generation,seq,data_b64) VALUES(?,?,?)",
                [generation, seq, base64.b64encode(chunk).decode("ascii")],
            )
        rows = query(
            "SELECT COUNT(*) AS n,SUM(LENGTH(data_b64)) AS chars FROM rt_ml_model_chunk WHERE generation=?",
            [generation],
        )
        if not rows or int(rows[0].get("n") or 0) != len(chunks):
            raise RuntimeError(f"WORKER_MODEL_CHUNK_COUNT_MISMATCH:{rows}:{len(chunks)}")
        metadata = {
            "ready": "1",
            "modelVersion": MODEL_VERSION,
            "sourceSha256": source_sha,
            "binarySha256": binary_sha,
            "generation": generation,
            "byteLength": str(len(raw)),
            "chunkCount": str(len(chunks)),
        }
        for key, value in metadata.items():
            query(
                "INSERT INTO rt_ml_model_meta(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",
                [key, value],
            )
        verify = {row["key"]: row["value"] for row in query("SELECT key,value FROM rt_ml_model_meta")}
        for key, value in metadata.items():
            if verify.get(key) != value:
                raise RuntimeError(f"WORKER_MODEL_META_MISMATCH:{key}:{verify.get(key)}:{value}")
        query("DELETE FROM rt_ml_model_chunk WHERE generation<>?", [generation])
        audit.update({"status": "SEEDED_D1_OK", "applied": True})

    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
