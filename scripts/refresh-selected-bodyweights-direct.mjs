import crypto from "node:crypto";
import {
  fetchJraPage,
  pageLooksLikeEntry,
  parseEntryPage,
} from "../dist-test/src/v1/jra.js";

const accountId = process.env.CLOUDFLARE_ACCOUNT_ID;
const databaseId = process.env.CLOUDFLARE_D1_DATABASE_ID;
const token = process.env.CLOUDFLARE_API_TOKEN;
const apiUrl = `https://api.cloudflare.com/client/v4/accounts/${accountId}/d1/database/${databaseId}/query`;
const SELECTION_PREFIX = "final_daily_selection:";
const SNAPSHOT_PREFIX = "worker_bodyweight_snapshot:";
const REFRESH_OPEN_MS = 80 * 60 * 1000;
const FINALIZE_OPEN_MS = 16 * 60 * 1000;
const DEADLINE_MS = 15 * 60 * 1000;

if (!accountId || !databaseId || !token) throw new Error("CLOUDFLARE_D1_ENV_MISSING");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function d1(sql, params = []) {
  let lastError;
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    try {
      const response = await fetch(apiUrl, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ sql, params }),
      });
      const body = await response.json();
      if (!response.ok || body?.success !== true) throw new Error(`D1_HTTP_${response.status}:${JSON.stringify(body?.errors || [])}`);
      const result = Array.isArray(body.result) ? body.result[0] : null;
      if (result?.success === false) throw new Error(`D1_QUERY_FAILED:${JSON.stringify(result)}`);
      return result?.results || [];
    } catch (error) {
      lastError = error;
      if (attempt < 5) await sleep(attempt * 1200);
    }
  }
  throw lastError;
}

function jstDate(now = new Date()) {
  return new Date(now.getTime() + 9 * 3600_000).toISOString().slice(0, 10);
}

function entryCandidates(rawUrl) {
  const values = [];
  const add = (value) => { if (value && !values.includes(value)) values.push(value); };
  add(rawUrl);
  try {
    const parsed = new URL(rawUrl);
    for (const host of ["sp.jra.jp", "www.jra.go.jp", "jra.jp"]) {
      const candidate = new URL(parsed.toString());
      candidate.hostname = host;
      add(candidate.toString());
    }
  } catch {
    // The parser/fetcher will report the original invalid URL below.
  }
  return values;
}

function canonicalRows(rows) {
  return rows
    .map((row) => ({
      horseNo: Number(row.horseNo),
      horseWeight: Number(row.horseWeight),
      weightChange: row.weightChange == null ? null : Number(row.weightChange),
    }))
    .sort((a, b) => a.horseNo - b.horseNo);
}

function hashRows(rows) {
  const payload = JSON.stringify(canonicalRows(rows).map((row) => [row.horseNo, row.horseWeight, row.weightChange]));
  return crypto.createHash("sha256").update(payload).digest("hex");
}

async function refreshRace(row, now) {
  const known = await d1(
    "SELECT horse_no AS horseNo FROM rt_runners WHERE race_id=? ORDER BY horse_no",
    [row.raceId],
  );
  const knownHorseNos = known.map((runner) => Number(runner.horseNo)).filter(Number.isInteger).sort((a, b) => a - b);
  if (knownHorseNos.length < 3) throw new Error(`BODYWEIGHT_KNOWN_RUNNERS_TOO_FEW:${row.raceId}:${knownHorseNos.length}`);

  const errors = [];
  for (const url of entryCandidates(row.entryUrl)) {
    try {
      const page = await fetchJraPage(url);
      if (!pageLooksLikeEntry(page.html)) throw new Error("NOT_ENTRY_PAGE");
      const bundle = parseEntryPage(page.html, page.url);
      if (bundle.race.raceId !== row.raceId) throw new Error(`RACE_ID_MISMATCH:${bundle.race.raceId}`);
      const parsedHorseNos = bundle.runners.map((runner) => Number(runner.horseNo)).filter(Number.isInteger).sort((a, b) => a - b);
      if (parsedHorseNos.length !== knownHorseNos.length || parsedHorseNos.some((horseNo, index) => horseNo !== knownHorseNos[index])) {
        throw new Error(`HORSE_SET_INCOMPLETE:${parsedHorseNos.length}/${knownHorseNos.length}`);
      }
      const active = bundle.runners.filter((runner) => (runner.runnerStatus || "active") === "active");
      if (active.length < 3) throw new Error(`ACTIVE_RUNNERS_TOO_FEW:${active.length}`);
      const missing = active.filter((runner) => !Number.isInteger(Number(runner.horseWeight)) || Number(runner.horseWeight) < 250 || Number(runner.horseWeight) > 700);
      if (missing.length) throw new Error(`BODYWEIGHT_NOT_PUBLISHED:${missing.map((runner) => runner.horseNo).join(",")}`);

      for (const runner of bundle.runners) {
        const activeRunner = (runner.runnerStatus || "active") === "active";
        await d1(
          "UPDATE rt_runners SET horse_weight=?,weight_change=?,runner_status=?,updated_at=CURRENT_TIMESTAMP WHERE race_id=? AND horse_no=?",
          [
            activeRunner ? Number(runner.horseWeight) : null,
            activeRunner && runner.weightChange != null ? Number(runner.weightChange) : null,
            runner.runnerStatus || "active",
            row.raceId,
            Number(runner.horseNo),
          ],
        );
      }

      const activeRows = canonicalRows(active);
      const snapshot = {
        version: 1,
        raceId: row.raceId,
        fetchedAt: now.toISOString(),
        sourceUrl: page.url,
        snapshotSha256: hashRows(activeRows),
        activeRunners: activeRows,
      };
      await d1(
        `INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
         ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP`,
        [`${SNAPSHOT_PREFIX}${row.raceId}`, JSON.stringify(snapshot)],
      );

      const saved = await d1(
        "SELECT horse_no AS horseNo,horse_weight AS horseWeight,weight_change AS weightChange FROM rt_runners WHERE race_id=? AND COALESCE(runner_status,'active')='active' ORDER BY horse_no",
        [row.raceId],
      );
      if (saved.length !== activeRows.length || saved.some((runner, index) => {
        const expected = activeRows[index];
        return Number(runner.horseNo) !== expected.horseNo
          || Number(runner.horseWeight) !== expected.horseWeight
          || (runner.weightChange == null ? null : Number(runner.weightChange)) !== expected.weightChange;
      })) throw new Error("BODYWEIGHT_D1_VERIFY_FAILED");
      return snapshot;
    } catch (error) {
      errors.push(`${url}:${error?.name || "Error"}:${error?.message || String(error)}`);
    }
  }
  throw new Error(`BODYWEIGHT_REFRESH_FAILED:${row.raceId}:${errors.join("|")}`);
}

async function main() {
  const now = new Date();
  const date = jstDate(now);
  const selectionRows = await d1("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1", [`${SELECTION_PREFIX}${date}`]);
  if (!selectionRows.length) {
    console.log(JSON.stringify({ status: "selection_missing", date, refreshedRaceIds: [], pendingRaceIds: [] }));
    return;
  }
  const selection = JSON.parse(String(selectionRows[0].value || "{}"));
  const ids = Array.isArray(selection.selected) ? selection.selected.map((row) => String(row.raceId || "")).filter(Boolean) : [];
  if (!ids.length) throw new Error("BODYWEIGHT_SELECTION_EMPTY");

  const refreshedRaceIds = [];
  const pendingRaceIds = [];
  const finalWindowPendingRaceIds = [];
  for (const raceId of ids) {
    const rows = await d1(
      `SELECT r.race_id AS raceId,r.entry_url AS entryUrl,r.start_time_utc AS startTimeUtc,
              CASE WHEN EXISTS(SELECT 1 FROM rt_public_bets b WHERE b.race_id=r.race_id) THEN 1 ELSE 0 END AS locked
       FROM rt_races r WHERE r.race_id=? LIMIT 1`,
      [raceId],
    );
    if (!rows.length || Number(rows[0].locked) === 1) continue;
    const startMs = Date.parse(String(rows[0].startTimeUtc || ""));
    if (!Number.isFinite(startMs)) continue;
    const remaining = startMs - now.getTime();
    if (remaining <= DEADLINE_MS || remaining > REFRESH_OPEN_MS) continue;
    try {
      await refreshRace(rows[0], now);
      refreshedRaceIds.push(raceId);
    } catch (error) {
      pendingRaceIds.push({ raceId, error: `${error?.name || "Error"}:${error?.message || String(error)}` });
      if (remaining <= FINALIZE_OPEN_MS) finalWindowPendingRaceIds.push(raceId);
    }
  }

  const report = {
    status: finalWindowPendingRaceIds.length ? "final_window_pending" : pendingRaceIds.length ? "retrying" : "ok",
    date,
    checkedAt: now.toISOString(),
    refreshedRaceIds,
    pendingRaceIds,
    finalWindowPendingRaceIds,
  };
  console.log(JSON.stringify(report));
  // Signal the acquisition miss for observability only. The workflow deliberately
  // keeps running the canonical finalizer so a transient bodyweight problem never
  // becomes a missing pre-race prediction.
  if (finalWindowPendingRaceIds.length) process.exitCode = 2;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
