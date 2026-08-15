#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import pathlib
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "models" / "ten-year-runner-feature-state.json.gz"
CONFIG_PATH = ROOT / "config" / "ten-year-completed-model.json"
AUDIT_PATH = ROOT / "worker-feature-state-seed-audit.json"
MODEL_VERSION = "ten-year-completed-model"
ROW_CHUNK = 500
STATEMENTS_PER_BATCH = 5

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS rt_ml_feature_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS rt_ml_horse_hist (generation TEXT NOT NULL, horse_name TEXT NOT NULL, seq INTEGER NOT NULL, race_date TEXT NOT NULL, finish_pct REAL NOT NULL, final3f_pct REAL NOT NULL, speed_mps REAL NOT NULL, top3 INTEGER NOT NULL, distance_m INTEGER NOT NULL, surface TEXT NOT NULL, PRIMARY KEY(generation,horse_name,seq))",
    "CREATE INDEX IF NOT EXISTS rt_idx_ml_horse_hist_lookup ON rt_ml_horse_hist(generation,horse_name,seq)",
    "CREATE TABLE IF NOT EXISTS rt_ml_horse_total (generation TEXT NOT NULL, horse_name TEXT NOT NULL, n INTEGER NOT NULL, w INTEGER NOT NULL, t INTEGER NOT NULL, PRIMARY KEY(generation,horse_name))",
    "CREATE TABLE IF NOT EXISTS rt_ml_horse_surface (generation TEXT NOT NULL, horse_name TEXT NOT NULL, surface TEXT NOT NULL, n INTEGER NOT NULL, w INTEGER NOT NULL, t INTEGER NOT NULL, PRIMARY KEY(generation,horse_name,surface))",
    "CREATE TABLE IF NOT EXISTS rt_ml_horse_dist (generation TEXT NOT NULL, horse_name TEXT NOT NULL, dist_bin INTEGER NOT NULL, n INTEGER NOT NULL, w INTEGER NOT NULL, t INTEGER NOT NULL, PRIMARY KEY(generation,horse_name,dist_bin))",
    "CREATE TABLE IF NOT EXISTS rt_ml_horse_venue (generation TEXT NOT NULL, horse_name TEXT NOT NULL, venue TEXT NOT NULL, n INTEGER NOT NULL, w INTEGER NOT NULL, t INTEGER NOT NULL, PRIMARY KEY(generation,horse_name,venue))",
    "CREATE TABLE IF NOT EXISTS rt_ml_jockey (generation TEXT NOT NULL, name TEXT NOT NULL, n INTEGER NOT NULL, w INTEGER NOT NULL, t INTEGER NOT NULL, PRIMARY KEY(generation,name))",
    "CREATE TABLE IF NOT EXISTS rt_ml_trainer (generation TEXT NOT NULL, name TEXT NOT NULL, n INTEGER NOT NULL, w INTEGER NOT NULL, t INTEGER NOT NULL, PRIMARY KEY(generation,name))",
    "CREATE TABLE IF NOT EXISTS rt_ml_pair (generation TEXT NOT NULL, horse_name TEXT NOT NULL, jockey TEXT NOT NULL, n INTEGER NOT NULL, w INTEGER NOT NULL, t INTEGER NOT NULL, PRIMARY KEY(generation,horse_name,jockey))",
]
TABLES = (
    "rt_ml_horse_hist",
    "rt_ml_horse_total",
    "rt_ml_horse_surface",
    "rt_ml_horse_dist",
    "rt_ml_horse_venue",
    "rt_ml_jockey",
    "rt_ml_trainer",
    "rt_ml_pair",
)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_state() -> dict[str, Any]:
    with gzip.open(STATE_PATH, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    required = {"throughDate", "horseHist", "horseTotal", "horseSurface", "horseDist", "horseVenue", "jockey", "trainer", "pair"}
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError(f"FEATURE_STATE_KEYS_MISSING:{missing}")
    return payload


def d1_endpoint() -> str:
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    database = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
    return f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{database}/query"


def d1_request(body: dict[str, Any]) -> list[dict[str, Any]]:
    token = os.environ["CLOUDFLARE_API_TOKEN"]
    request = urllib.request.Request(
        d1_endpoint(),
        data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"D1_HTTP_{error.code}:{detail[:4000]}") from error
    if not payload.get("success"):
        raise RuntimeError(f"D1_REQUEST_FAILED:{payload}")
    result = payload.get("result") or []
    for item in result:
        if item.get("success") is False:
            raise RuntimeError(f"D1_QUERY_FAILED:{item}")
    return result


def d1_query(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    result = d1_request({"sql": sql, "params": params or []})
    return (result[0].get("results") or []) if result else []


def d1_batch(statements: list[dict[str, Any]]) -> None:
    if statements:
        d1_request({"batch": statements})


def chunks(rows: Iterable[tuple[Any, ...]], size: int) -> Iterator[list[tuple[Any, ...]]]:
    batch: list[tuple[Any, ...]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def insert_statement(table: str, columns: tuple[str, ...], rows: list[tuple[Any, ...]]) -> dict[str, Any]:
    extracts = ",".join(f"json_extract(value,'$[{index}]')" for index in range(len(columns)))
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) SELECT {extracts} FROM json_each(?)"
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return {"sql": sql, "params": [payload]}


def upload_rows(table: str, columns: tuple[str, ...], rows: Iterable[tuple[Any, ...]]) -> int:
    pending: list[dict[str, Any]] = []
    count = 0
    for group in chunks(rows, ROW_CHUNK):
        pending.append(insert_statement(table, columns, group))
        count += len(group)
        if len(pending) >= STATEMENTS_PER_BATCH:
            d1_batch(pending)
            pending = []
    d1_batch(pending)
    return count


def state_rows(state: dict[str, Any], generation: str):
    def horse_hist():
        for horse, history in state["horseHist"].items():
            if len(history) > 5:
                raise RuntimeError(f"HORSE_HISTORY_TOO_LONG:{horse}:{len(history)}")
            for seq, row in enumerate(history):
                yield (
                    generation,
                    horse,
                    seq,
                    str(row["date"]),
                    float(row.get("finishPct") or 0.0),
                    float(row.get("final3fPct") or 0.0),
                    float(row.get("speedMps") or 0.0),
                    int(row.get("top3") or 0),
                    int(row.get("distance") or 0),
                    str(row.get("surface") or "障害"),
                )

    def keyed_stats(mapping: dict[str, Any]):
        for key, value in mapping.items():
            n, w, t = value
            yield generation, key, int(n), int(w), int(t)

    return {
        "rt_ml_horse_hist": (("generation", "horse_name", "seq", "race_date", "finish_pct", "final3f_pct", "speed_mps", "top3", "distance_m", "surface"), horse_hist()),
        "rt_ml_horse_total": (("generation", "horse_name", "n", "w", "t"), keyed_stats(state["horseTotal"])),
        "rt_ml_horse_surface": (("generation", "horse_name", "surface", "n", "w", "t"), ((generation, h, str(s), int(n), int(w), int(t)) for h, s, n, w, t in state["horseSurface"])),
        "rt_ml_horse_dist": (("generation", "horse_name", "dist_bin", "n", "w", "t"), ((generation, h, int(d), int(n), int(w), int(t)) for h, d, n, w, t in state["horseDist"])),
        "rt_ml_horse_venue": (("generation", "horse_name", "venue", "n", "w", "t"), ((generation, h, str(v), int(n), int(w), int(t)) for h, v, n, w, t in state["horseVenue"])),
        "rt_ml_jockey": (("generation", "name", "n", "w", "t"), keyed_stats(state["jockey"])),
        "rt_ml_trainer": (("generation", "name", "n", "w", "t"), keyed_stats(state["trainer"])),
        "rt_ml_pair": (("generation", "horse_name", "jockey", "n", "w", "t"), ((generation, h, str(j), int(n), int(w), int(t)) for h, j, n, w, t in state["pair"])),
    }


def local_counts(state: dict[str, Any]) -> dict[str, int]:
    return {
        "rt_ml_horse_hist": sum(len(rows) for rows in state["horseHist"].values()),
        "rt_ml_horse_total": len(state["horseTotal"]),
        "rt_ml_horse_surface": len(state["horseSurface"]),
        "rt_ml_horse_dist": len(state["horseDist"]),
        "rt_ml_horse_venue": len(state["horseVenue"]),
        "rt_ml_jockey": len(state["jockey"]),
        "rt_ml_trainer": len(state["trainer"]),
        "rt_ml_pair": len(state["pair"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the canonical state to production D1")
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    model_sha = str(config["runnerProbabilityModel"]["modelWeightsSha256"])
    state_sha = sha256_file(STATE_PATH)
    generation = state_sha[:24]
    state = load_state()
    through_date = str(state["throughDate"])
    expected = local_counts(state)
    audit: dict[str, Any] = {
        "status": "DRY_RUN_OK",
        "modelVersion": MODEL_VERSION,
        "modelSha256": model_sha,
        "stateSha256": state_sha,
        "generation": generation,
        "throughDate": through_date,
        "counts": expected,
        "applied": False,
    }

    if args.apply:
        print(json.dumps({"status": "FEATURE_STATE_SEED_START", "generation": generation, "throughDate": through_date, "totalRows": sum(expected.values())}), flush=True)
        for sql in SCHEMA:
            d1_query(sql)
        existing = {row["key"]: row["value"] for row in d1_query("SELECT key,value FROM rt_ml_feature_meta")}
        if existing.get("ready") == "1" and existing.get("stateSha256") == state_sha and existing.get("currentGeneration") == generation:
            audit["status"] = "ALREADY_CURRENT"
            audit["applied"] = True
        else:
            rows_by_table = state_rows(state, generation)
            uploaded: dict[str, int] = {}
            for table in TABLES:
                d1_query(f"DELETE FROM {table} WHERE generation=?", [generation])
                columns, rows = rows_by_table[table]
                uploaded[table] = upload_rows(table, columns, rows)
                print(json.dumps({"status": "FEATURE_STATE_TABLE_UPLOADED", "table": table, "rows": uploaded[table], "expected": expected[table]}), flush=True)
                if uploaded[table] != expected[table]:
                    raise RuntimeError(f"FEATURE_STATE_UPLOAD_COUNT_MISMATCH:{table}:{uploaded[table]}:{expected[table]}")

            checks = d1_query(
                "SELECT 'rt_ml_horse_hist' AS name,COUNT(*) AS n FROM rt_ml_horse_hist WHERE generation=? UNION ALL "
                "SELECT 'rt_ml_horse_total',COUNT(*) FROM rt_ml_horse_total WHERE generation=? UNION ALL "
                "SELECT 'rt_ml_horse_surface',COUNT(*) FROM rt_ml_horse_surface WHERE generation=? UNION ALL "
                "SELECT 'rt_ml_horse_dist',COUNT(*) FROM rt_ml_horse_dist WHERE generation=? UNION ALL "
                "SELECT 'rt_ml_horse_venue',COUNT(*) FROM rt_ml_horse_venue WHERE generation=? UNION ALL "
                "SELECT 'rt_ml_jockey',COUNT(*) FROM rt_ml_jockey WHERE generation=? UNION ALL "
                "SELECT 'rt_ml_trainer',COUNT(*) FROM rt_ml_trainer WHERE generation=? UNION ALL "
                "SELECT 'rt_ml_pair',COUNT(*) FROM rt_ml_pair WHERE generation=?",
                [generation] * 8,
            )
            actual = {str(row["name"]): int(row["n"]) for row in checks}
            if actual != expected:
                raise RuntimeError(f"FEATURE_STATE_D1_COUNT_MISMATCH:{actual}:{expected}")

            metadata = {
                "ready": "1",
                "modelVersion": MODEL_VERSION,
                "modelSha256": model_sha,
                "stateSha256": state_sha,
                "currentGeneration": generation,
                "throughDate": through_date,
                "countsJson": json.dumps(expected, separators=(",", ":")),
            }
            d1_batch([
                {
                    "sql": "INSERT INTO rt_ml_feature_meta(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",
                    "params": [key, value],
                }
                for key, value in metadata.items()
            ])
            for table in TABLES:
                d1_query(f"DELETE FROM {table} WHERE generation<>?", [generation])
            audit.update({"status": "SEEDED_D1_OK", "applied": True, "d1Counts": actual})

    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
