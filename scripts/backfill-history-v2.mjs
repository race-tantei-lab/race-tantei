import { execFileSync } from "node:child_process";
import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import {
  fetchJraPage,
  pageLooksLikeResult,
  parseResultPage
} from "../dist-test/src/v1/jra.js";
import {
  parseDesktopPayouts,
  parseDesktopResultRunners
} from "../dist-test/src/v1/three-month-desktop.js";
import {
  WALK_FORWARD_SCOPE_VERSION,
  isWalkForwardArchiveDate
} from "../dist-test/src/v1/walk-forward-scope.js";

const OUTPUT_DIR = path.resolve("tmp/history-backfill");
const RAW_DIR = path.join(OUTPUT_DIR, "raw");
const FETCH_CONCURRENCY = Math.min(2, Math.max(1, Number(process.env.BACKFILL_CONCURRENCY ?? 2)));
const RACES_PER_SQL_FILE = Math.max(10, Number(process.env.BACKFILL_RACES_PER_FILE ?? 40));
const MAX_ATTEMPTS = 5;
const MIN_REQUEST_INTERVAL_MS = 1_250;
const MAX_TARGET_RACES = 1_500;

const INVALID_TARGET_SQL = `
WITH per_race AS (
  SELECT r.race_id,
    SUM(CASE WHEN rr.runner_status='active' THEN 1 ELSE 0 END) AS active_runners,
    SUM(CASE WHEN rr.runner_status='active'
      AND rr.win_odds IS NOT NULL
      AND rr.win_odds>1
      AND rr.popularity BETWEEN 1 AND 18 THEN 1 ELSE 0 END) AS valid_market_runners,
    COUNT(DISTINCT CASE WHEN rr.runner_status='active' THEN rr.popularity END) AS distinct_popularity,
    MIN(CASE WHEN rr.runner_status='active' THEN rr.popularity END) AS min_popularity,
    MAX(CASE WHEN rr.runner_status='active' THEN rr.popularity END) AS max_popularity
  FROM rt_races r
  JOIN rt_runners rr ON rr.race_id=r.race_id
  WHERE r.status='finished'
    AND r.race_date BETWEEN '2024-05-01' AND '2026-08-02'
  GROUP BY r.race_id
)
SELECT r.race_id, r.race_date, r.result_url
FROM per_race p
JOIN rt_races r ON r.race_id=p.race_id
WHERE p.active_runners>=2
  AND (
    p.valid_market_runners<>p.active_runners OR
    p.distinct_popularity<>p.active_runners OR
    p.min_popularity<>1 OR
    p.max_popularity<>p.active_runners
  )
  AND r.result_url IS NOT NULL
  AND r.result_url<>''
ORDER BY r.race_date, r.venue, r.race_no;
`;

let nextRequestAt = 0;
let blockedUntil = 0;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForRequestSlot() {
  const now = Date.now();
  const scheduled = Math.max(now, nextRequestAt, blockedUntil);
  nextRequestAt = scheduled + MIN_REQUEST_INTERVAL_MS;
  if (scheduled > now) await sleep(scheduled - now);
}

function noteRemoteBlock(attempt) {
  const cooldown = Math.min(120_000, 15_000 * (2 ** Math.max(0, attempt - 1)));
  blockedUntil = Math.max(blockedUntil, Date.now() + cooldown);
}

function sql(value) {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "NULL";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function cname(url) {
  try { return decodeURIComponent(new URL(url).searchParams.get("CNAME") ?? ""); }
  catch { return ""; }
}

function canonicalResultUrl(rawUrl) {
  const url = new URL(rawUrl);
  const currentCname = decodeURIComponent(url.searchParams.get("CNAME") ?? "");
  if (!currentCname) throw new Error(`RESULT_CNAME_MISSING:${rawUrl}`);
  const desktopCname = currentCname.replace(/^sw01sde/i, "pw01sde");
  if (!/^pw01sde/i.test(desktopCname)) throw new Error(`RESULT_CNAME_INVALID:${currentCname}`);
  url.protocol = "https:";
  url.hostname = "www.jra.go.jp";
  url.pathname = "/JRADB/accessS.html";
  url.search = "";
  url.searchParams.set("CNAME", desktopCname);
  return url.toString();
}

function sortedUniqueUrls(values) {
  return [...new Set(values.filter(Boolean).map(canonicalResultUrl))]
    .sort((a, b) => cname(a).localeCompare(cname(b)));
}

function collectResultRows(value, rows = []) {
  if (Array.isArray(value)) {
    for (const item of value) collectResultRows(item, rows);
    return rows;
  }
  if (!value || typeof value !== "object") return rows;
  if (typeof value.result_url === "string") rows.push(value);
  for (const nested of Object.values(value)) collectResultRows(nested, rows);
  return rows;
}

function loadInvalidTargetUrls() {
  const stdout = execFileSync(
    "npx",
    [
      "wrangler",
      "d1",
      "execute",
      "race-tantei-phase0",
      "--remote",
      "--command",
      INVALID_TARGET_SQL,
      "--json",
      "--config",
      "wrangler.jsonc"
    ],
    {
      encoding: "utf8",
      maxBuffer: 32 * 1024 * 1024,
      env: process.env
    }
  );
  const payload = JSON.parse(stdout);
  const rows = collectResultRows(payload);
  const urls = sortedUniqueUrls(rows.map((row) => row.result_url));
  if (urls.length > MAX_TARGET_RACES) {
    throw new Error(`REPAIR_TARGET_COUNT_TOO_LARGE:${urls.length}`);
  }
  return urls;
}

function validateRunnerMarket(runners) {
  const active = runners.filter((runner) => runner.runnerStatus === "active");
  const ranks = active.map((runner) => runner.popularity);
  const complete = active.length >= 2
    && active.length <= 18
    && ranks.every((rank) => Number.isInteger(rank) && rank >= 1 && rank <= active.length)
    && new Set(ranks).size === active.length
    && active.every((runner) => Number.isFinite(runner.winOdds) && runner.winOdds > 1);
  return {
    complete,
    activeRunners: active.length,
    ranks,
    missingOdds: active.filter((runner) => !Number.isFinite(runner.winOdds) || runner.winOdds <= 1)
      .map((runner) => runner.horseNo)
  };
}

function raceSql(bundle) {
  const r = bundle.race;
  const out = [];
  out.push(`INSERT INTO rt_races (
    race_id,race_date,venue,meeting_no,meeting_day,race_no,race_name,conditions,
    surface,distance_m,direction,start_time_jst,start_time_utc,weather,track_condition,
    entry_url,result_url,status,refund_horse_nos_json,entry_updated_at,result_updated_at,updated_at
  ) VALUES (
    ${sql(r.raceId)},${sql(r.raceDate)},${sql(r.venue)},${sql(r.meetingNo)},${sql(r.meetingDay)},${sql(r.raceNo)},${sql(r.raceName)},${sql(r.conditions)},
    ${sql(r.surface)},${sql(r.distanceM)},${sql(r.direction)},${sql(r.startTimeJst)},${sql(r.startTimeUtc)},${sql(r.weather)},${sql(r.trackCondition)},
    ${sql(r.entryUrl)},${sql(r.resultUrl)},'finished',${sql(JSON.stringify(bundle.refundHorseNos ?? []))},CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
  ) ON CONFLICT(race_id) DO UPDATE SET
    race_date=excluded.race_date,venue=excluded.venue,meeting_no=excluded.meeting_no,meeting_day=excluded.meeting_day,
    race_no=excluded.race_no,race_name=excluded.race_name,conditions=excluded.conditions,surface=excluded.surface,
    distance_m=excluded.distance_m,direction=excluded.direction,start_time_jst=excluded.start_time_jst,
    start_time_utc=excluded.start_time_utc,weather=excluded.weather,track_condition=excluded.track_condition,
    entry_url=excluded.entry_url,result_url=excluded.result_url,status='finished',refund_horse_nos_json=excluded.refund_horse_nos_json,
    result_updated_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP;`);

  for (const x of bundle.runners) {
    out.push(`INSERT INTO rt_runners (
      race_id,horse_no,frame_no,horse_name,sex_age,coat_color,horse_weight,weight_change,
      jockey,assigned_weight,trainer,stable,win_odds,popularity,runner_status,updated_at
    ) VALUES (
      ${sql(r.raceId)},${sql(x.horseNo)},${sql(x.frameNo)},${sql(x.horseName)},${sql(x.sexAge)},${sql(x.coatColor)},${sql(x.horseWeight)},${sql(x.weightChange)},
      ${sql(x.jockey)},${sql(x.assignedWeight)},${sql(x.trainer)},${sql(x.stable)},${sql(x.winOdds)},${sql(x.popularity)},${sql(x.runnerStatus)},CURRENT_TIMESTAMP
    ) ON CONFLICT(race_id,horse_no) DO UPDATE SET
      frame_no=excluded.frame_no,horse_name=excluded.horse_name,sex_age=excluded.sex_age,coat_color=excluded.coat_color,
      horse_weight=excluded.horse_weight,weight_change=excluded.weight_change,jockey=excluded.jockey,
      assigned_weight=excluded.assigned_weight,trainer=excluded.trainer,stable=excluded.stable,
      win_odds=excluded.win_odds,popularity=excluded.popularity,runner_status=excluded.runner_status,updated_at=CURRENT_TIMESTAMP;`);
  }

  for (const x of bundle.results) {
    out.push(`INSERT INTO rt_results (
      race_id,horse_no,finish_position,result_status,time_text,margin_text,final3f,updated_at
    ) VALUES (
      ${sql(r.raceId)},${sql(x.horseNo)},${sql(x.finishPosition)},${sql(x.resultStatus)},${sql(x.timeText)},${sql(x.marginText)},${sql(x.final3f)},CURRENT_TIMESTAMP
    ) ON CONFLICT(race_id,horse_no) DO UPDATE SET
      finish_position=excluded.finish_position,result_status=excluded.result_status,time_text=excluded.time_text,
      margin_text=excluded.margin_text,final3f=excluded.final3f,updated_at=CURRENT_TIMESTAMP;`);
  }

  for (const x of bundle.payouts) {
    out.push(`INSERT INTO rt_payouts (
      race_id,bet_type,combination,payout_yen,popularity,updated_at
    ) VALUES (
      ${sql(r.raceId)},${sql(x.betType)},${sql(x.combination)},${sql(x.payoutYen)},${sql(x.popularity)},CURRENT_TIMESTAMP
    ) ON CONFLICT(race_id,bet_type,combination) DO UPDATE SET
      payout_yen=excluded.payout_yen,popularity=excluded.popularity,updated_at=CURRENT_TIMESTAMP;`);
  }
  return out.join("\n");
}

async function fetchBundle(url) {
  let lastError = "UNKNOWN_ERROR";
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    try {
      await waitForRequestSlot();
      const page = await fetchJraPage(url);
      if (!pageLooksLikeResult(page.html)) throw new Error("RESULT_SIGNATURE_MISSING");
      const parsed = parseResultPage(page.html, page.url);
      if (!isWalkForwardArchiveDate(parsed.race.raceDate)) {
        throw new Error(`OUT_OF_SCOPE:${parsed.race.raceDate}`);
      }
      const runners = parseDesktopResultRunners(page.html);
      const market = validateRunnerMarket(runners);
      if (!market.complete) {
        throw new Error(`RUNNER_MARKET_INVALID:${JSON.stringify(market)}`);
      }
      const payouts = parsed.payouts.length > 0 ? parsed.payouts : parseDesktopPayouts(page.html);
      if (parsed.race.status !== "cancelled" && payouts.length === 0) {
        throw new Error("PAYOUTS_NOT_FOUND");
      }
      return { bundle: { ...parsed, runners, payouts }, error: null };
    } catch (error) {
      lastError = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
      if (/HTTP_(403|429|503)|BLOCKED_PAGE/.test(lastError)) noteRemoteBlock(attempt);
      if (attempt < MAX_ATTEMPTS) {
        await sleep(Math.min(30_000, 2_000 * (2 ** (attempt - 1))));
      }
    }
  }
  return { bundle: null, error: lastError };
}

async function writeSummary(values) {
  await writeFile(
    path.join(OUTPUT_DIR, "summary.json"),
    JSON.stringify(values, null, 2)
  );
}

async function main() {
  await rm(OUTPUT_DIR, { recursive: true, force: true });
  await mkdir(RAW_DIR, { recursive: true });

  const urls = loadInvalidTargetUrls();
  console.log(`repair targets from D1 audit: ${urls.length}`);

  if (urls.length === 0) {
    await writeFile(path.join(OUTPUT_DIR, "backfill-0000.sql"), "SELECT 1;\n");
    await writeFile(
      path.join(OUTPUT_DIR, "zzzz-state.sql"),
      `INSERT INTO rt_system_state(state_key,state_value,updated_at)
VALUES (
  ${sql(`walk_forward_history:${WALK_FORWARD_SCOPE_VERSION}:last_market_repair`)},
  ${sql(JSON.stringify({ repairedRaces: 0, completedAt: new Date().toISOString() }))},
  CURRENT_TIMESTAMP
)
ON CONFLICT(state_key) DO UPDATE SET
  state_value=excluded.state_value,
  updated_at=CURRENT_TIMESTAMP;\n`
    );
    await writeSummary({
      scopeVersion: WALK_FORWARD_SCOPE_VERSION,
      targets: 0,
      completed: 0,
      failures: 0,
      concurrency: FETCH_CONCURRENCY,
      sqlFiles: 1,
      targetedRepair: true
    });
    console.log("no invalid races remain");
    return;
  }

  let cursor = 0;
  let completed = 0;
  const failures = [];
  const startedAt = Date.now();

  async function worker() {
    while (true) {
      const index = cursor++;
      if (index >= urls.length) return;
      const url = urls[index];
      const result = await fetchBundle(url);
      if (result.bundle) {
        await writeFile(path.join(RAW_DIR, `${String(index).padStart(6, "0")}.sql`), raceSql(result.bundle));
        completed += 1;
      } else {
        failures.push({ url, attempts: MAX_ATTEMPTS, error: result.error });
      }
      if ((index + 1) % 25 === 0 || index + 1 === urls.length) {
        const elapsedMinutes = Math.round((Date.now() - startedAt) / 6000) / 10;
        console.log(`${index + 1}/${urls.length}; success=${completed}; failed=${failures.length}; elapsed=${elapsedMinutes}m`);
      }
    }
  }

  await Promise.all(Array.from({ length: FETCH_CONCURRENCY }, () => worker()));

  if (failures.length > 0) {
    await writeFile(path.join(OUTPUT_DIR, "failures.json"), JSON.stringify(failures, null, 2));
    await writeSummary({
      scopeVersion: WALK_FORWARD_SCOPE_VERSION,
      targets: urls.length,
      completed,
      failures: failures.length,
      concurrency: FETCH_CONCURRENCY,
      sqlFiles: 0,
      targetedRepair: true
    });
    throw new Error(`TARGETED_REPAIR_FETCH_FAILED:${failures.length}/${urls.length}`);
  }

  const rawFiles = (await readdir(RAW_DIR)).filter((name) => name.endsWith(".sql")).sort();
  let outputIndex = 0;
  for (let offset = 0; offset < rawFiles.length; offset += RACES_PER_SQL_FILE) {
    const group = rawFiles.slice(offset, offset + RACES_PER_SQL_FILE);
    const bodies = await Promise.all(group.map((name) => readFile(path.join(RAW_DIR, name), "utf8")));
    const outputName = `backfill-${String(outputIndex).padStart(4, "0")}.sql`;
    await writeFile(path.join(OUTPUT_DIR, outputName), `${bodies.join("\n")}\n`);
    outputIndex += 1;
  }

  const stateSql = `INSERT INTO rt_system_state(state_key,state_value,updated_at)
VALUES (
  ${sql(`walk_forward_history:${WALK_FORWARD_SCOPE_VERSION}:last_market_repair`)},
  ${sql(JSON.stringify({
    repairedRaces: completed,
    completedAt: new Date().toISOString()
  }))},
  CURRENT_TIMESTAMP
)
ON CONFLICT(state_key) DO UPDATE SET
  state_value=excluded.state_value,
  updated_at=CURRENT_TIMESTAMP;\n`;
  await writeFile(path.join(OUTPUT_DIR, "zzzz-state.sql"), stateSql);

  await writeSummary({
    scopeVersion: WALK_FORWARD_SCOPE_VERSION,
    targets: urls.length,
    completed,
    failures: 0,
    concurrency: FETCH_CONCURRENCY,
    sqlFiles: outputIndex,
    targetedRepair: true,
    completePopularityRequired: true
  });
  console.log(`finished targeted repair: success=${completed}, failed=0, sqlFiles=${outputIndex}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
