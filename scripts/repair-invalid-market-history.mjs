import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import {
  fetchJraPage,
  pageLooksLikeResult
} from "../dist-test/src/v1/jra.js";
import { parseHistoricalResultRunners } from "../dist-test/src/v1/three-month-history.js";

const INPUT_FILE = path.resolve(
  process.env.REPAIR_INPUT_FILE ?? "tmp/history-market-repair/invalid-races.json"
);
const OUTPUT_DIR = path.resolve(
  process.env.REPAIR_OUTPUT_DIR ?? "tmp/history-market-repair"
);
const SQL_DIR = path.join(OUTPUT_DIR, "sql");
const REQUEST_INTERVAL_MS = Math.max(
  500,
  Number(process.env.REPAIR_REQUEST_INTERVAL_MS ?? 850)
);
const FETCH_CONCURRENCY = Math.max(
  1,
  Math.min(3, Number(process.env.REPAIR_CONCURRENCY ?? 2))
);
const RACES_PER_SQL_FILE = Math.max(
  10,
  Number(process.env.REPAIR_RACES_PER_FILE ?? 30)
);
const MAX_ATTEMPTS = Math.max(
  3,
  Number(process.env.REPAIR_MAX_ATTEMPTS ?? 6)
);
const RETRY_DELAYS_MS = [0, 3_000, 10_000, 30_000, 60_000, 90_000];

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function sql(value) {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "NULL";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function extractRows(value, rows = []) {
  if (Array.isArray(value)) {
    for (const item of value) extractRows(item, rows);
    return rows;
  }
  if (!value || typeof value !== "object") return rows;
  if (
    Object.prototype.hasOwnProperty.call(value, "race_id")
    && Object.prototype.hasOwnProperty.call(value, "result_url")
  ) {
    rows.push(value);
    return rows;
  }
  for (const child of Object.values(value)) extractRows(child, rows);
  return rows;
}

function normalizeRace(raw) {
  return {
    raceId: String(raw.race_id ?? "").trim(),
    raceDate: String(raw.race_date ?? "").trim(),
    venue: String(raw.venue ?? "").trim(),
    raceNo: Number(raw.race_no ?? 0),
    resultUrl: String(raw.result_url ?? "").trim(),
    activeRunners: Number(raw.active_runners ?? 0),
    invalidReason: {
      validMarketRunners: Number(raw.valid_market_runners ?? 0),
      distinctPopularity: Number(raw.distinct_popularity ?? 0),
      minPopularity: raw.min_popularity === null ? null : Number(raw.min_popularity),
      maxPopularity: raw.max_popularity === null ? null : Number(raw.max_popularity)
    }
  };
}

function validateInputRace(race) {
  if (!race.raceId) throw new Error("REPAIR_RACE_ID_MISSING");
  if (!/^20\d{2}-\d{2}-\d{2}$/.test(race.raceDate)) {
    throw new Error(`REPAIR_RACE_DATE_INVALID:${race.raceId}:${race.raceDate}`);
  }
  if (!race.venue || race.raceNo < 1 || race.raceNo > 12) {
    throw new Error(`REPAIR_RACE_META_INVALID:${race.raceId}`);
  }
  if (!/^https:\/\/(?:www\.|sp\.)?jra\.go\.jp\//i.test(race.resultUrl)) {
    throw new Error(`REPAIR_RESULT_URL_INVALID:${race.raceId}:${race.resultUrl}`);
  }
  if (race.activeRunners < 2 || race.activeRunners > 18) {
    throw new Error(`REPAIR_ACTIVE_COUNT_INVALID:${race.raceId}:${race.activeRunners}`);
  }
}

let nextRequestAt = 0;
let throttleTail = Promise.resolve();

async function waitForRequestSlot() {
  let release;
  const previous = throttleTail;
  throttleTail = new Promise((resolve) => {
    release = resolve;
  });
  await previous;
  const waitMs = Math.max(0, nextRequestAt - Date.now());
  if (waitMs > 0) await sleep(waitMs);
  nextRequestAt = Date.now() + REQUEST_INTERVAL_MS;
  release();
}

function isBlockError(message) {
  return /HTTP_403|HTTP_429|HTTP_503|BLOCKED_PAGE|AbortError|fetch failed/i.test(message);
}

async function fetchWithRetry(race) {
  let lastError = "UNKNOWN_FETCH_ERROR";
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    const retryDelay = RETRY_DELAYS_MS[Math.min(attempt - 1, RETRY_DELAYS_MS.length - 1)] ?? 90_000;
    if (retryDelay > 0) await sleep(retryDelay);
    await waitForRequestSlot();
    try {
      const page = await fetchJraPage(race.resultUrl);
      if (!pageLooksLikeResult(page.html)) {
        throw new Error("RESULT_SIGNATURE_MISSING");
      }
      return page;
    } catch (error) {
      lastError = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
      if (isBlockError(lastError)) {
        nextRequestAt = Math.max(nextRequestAt, Date.now() + Math.min(90_000, 10_000 * attempt));
      }
    }
  }
  throw new Error(`REPAIR_FETCH_FAILED:${race.raceId}:${lastError}`);
}

function repairedMarket(race, html) {
  const runners = parseHistoricalResultRunners(html);
  const active = runners.filter((runner) => runner.runnerStatus === "active");
  if (active.length !== race.activeRunners) {
    throw new Error(
      `REPAIR_ACTIVE_COUNT_MISMATCH:${race.raceId}:${active.length}:${race.activeRunners}`
    );
  }
  const ranks = active.map((runner) => runner.popularity);
  const completePopularity = ranks.every((rank) =>
    rank !== null
    && Number.isInteger(rank)
    && rank >= 1
    && rank <= active.length
  ) && new Set(ranks).size === active.length;
  if (!completePopularity) {
    throw new Error(`REPAIR_POPULARITY_INVALID:${race.raceId}:${JSON.stringify(ranks)}`);
  }
  const invalidOdds = active.filter((runner) =>
    runner.winOdds === null
    || !Number.isFinite(runner.winOdds)
    || runner.winOdds <= 1
  );
  if (invalidOdds.length > 0) {
    throw new Error(
      `REPAIR_ODDS_INVALID:${race.raceId}:${JSON.stringify(invalidOdds.map((runner) => runner.horseNo))}`
    );
  }
  return active.map((runner) => ({
    horseNo: runner.horseNo,
    popularity: runner.popularity,
    winOdds: runner.winOdds
  }));
}

function marketSql(race, runners) {
  const lines = [];
  for (const runner of runners) {
    lines.push(`UPDATE rt_runners
SET popularity=${sql(runner.popularity)},
    win_odds=${sql(runner.winOdds)},
    updated_at=CURRENT_TIMESTAMP
WHERE race_id=${sql(race.raceId)}
  AND horse_no=${sql(runner.horseNo)}
  AND runner_status='active';`);
  }
  return lines.join("\n");
}

async function main() {
  const payload = JSON.parse(await readFile(INPUT_FILE, "utf8"));
  const rawRows = extractRows(payload);
  const byRace = new Map();
  for (const raw of rawRows) {
    const race = normalizeRace(raw);
    validateInputRace(race);
    byRace.set(race.raceId, race);
  }
  const races = [...byRace.values()].sort((a, b) =>
    a.raceDate.localeCompare(b.raceDate)
      || a.venue.localeCompare(b.venue, "ja")
      || a.raceNo - b.raceNo
  );
  if (races.length === 0) {
    throw new Error("REPAIR_TARGETS_EMPTY");
  }

  await rm(SQL_DIR, { recursive: true, force: true });
  await mkdir(SQL_DIR, { recursive: true });

  let cursor = 0;
  let completed = 0;
  const repaired = new Array(races.length);
  const failures = [];

  async function worker() {
    while (true) {
      const index = cursor++;
      if (index >= races.length) return;
      const race = races[index];
      try {
        const page = await fetchWithRetry(race);
        const market = repairedMarket(race, page.html);
        repaired[index] = {
          race,
          finalUrl: page.url,
          market
        };
        completed += 1;
      } catch (error) {
        failures.push({
          race,
          error: error instanceof Error ? error.message : String(error)
        });
      }
      const processed = completed + failures.length;
      if (processed % 25 === 0 || processed === races.length) {
        console.log(
          `${processed}/${races.length}; success=${completed}; failed=${failures.length}`
        );
      }
    }
  }

  await Promise.all(
    Array.from({ length: Math.min(FETCH_CONCURRENCY, races.length) }, () => worker())
  );

  await writeFile(
    path.join(OUTPUT_DIR, "failures.json"),
    JSON.stringify(failures, null, 2) + "\n",
    "utf8"
  );
  const summary = {
    targets: races.length,
    completed,
    failures: failures.length,
    requestIntervalMs: REQUEST_INTERVAL_MS,
    concurrency: FETCH_CONCURRENCY,
    maxAttempts: MAX_ATTEMPTS,
    firstRaceDate: races[0]?.raceDate ?? null,
    lastRaceDate: races.at(-1)?.raceDate ?? null
  };
  await writeFile(
    path.join(OUTPUT_DIR, "summary.json"),
    JSON.stringify(summary, null, 2) + "\n",
    "utf8"
  );

  if (failures.length > 0 || completed !== races.length) {
    throw new Error(`REPAIR_FETCH_INCOMPLETE:${completed}:${failures.length}:${races.length}`);
  }

  let fileIndex = 0;
  for (let offset = 0; offset < repaired.length; offset += RACES_PER_SQL_FILE) {
    const group = repaired.slice(offset, offset + RACES_PER_SQL_FILE);
    const body = group
      .map((item) => marketSql(item.race, item.market))
      .join("\n");
    const fileName = `repair-${String(fileIndex).padStart(4, "0")}.sql`;
    await writeFile(path.join(SQL_DIR, fileName), `${body}\n`, "utf8");
    fileIndex += 1;
  }

  summary.sqlFiles = fileIndex;
  await writeFile(
    path.join(OUTPUT_DIR, "summary.json"),
    JSON.stringify(summary, null, 2) + "\n",
    "utf8"
  );
  console.log(JSON.stringify(summary));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
