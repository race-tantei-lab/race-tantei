import { mkdir, rm, writeFile, appendFile } from "node:fs/promises";
import path from "node:path";
import {
  fetchJraPage,
  pageLooksLikeResult,
  parseResultPage
} from "../dist-test/src/v1/jra.js";
import { getArchiveResultUrls } from "../dist-test/src/v1/three-month-archive.js";
import {
  parseDesktopPayouts,
  parseDesktopResultRunners
} from "../dist-test/src/v1/three-month-desktop.js";
import {
  WALK_FORWARD_ARCHIVE_MONTHS,
  WALK_FORWARD_SCOPE_VERSION,
  isWalkForwardArchiveDate
} from "../dist-test/src/v1/walk-forward-scope.js";

const OUTPUT_DIR = path.resolve("tmp/history-backfill");
const FETCH_CONCURRENCY = Math.max(4, Number(process.env.BACKFILL_CONCURRENCY ?? 24));
const RACES_PER_SQL_FILE = Math.max(10, Number(process.env.BACKFILL_RACES_PER_FILE ?? 40));
const MAX_ATTEMPTS = 4;

function sql(value) {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "NULL";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function cname(url) {
  try {
    return decodeURIComponent(new URL(url).searchParams.get("CNAME") ?? "");
  } catch {
    return "";
  }
}

function archiveRaceDate(url) {
  const match = cname(url).match(/(20\d{6})\/[0-9A-F]{2}$/i);
  if (!match?.[1]) return null;
  const raw = match[1];
  return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
}

function sortedUniqueUrls(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => {
    const dateOrder = (archiveRaceDate(a) ?? "").localeCompare(archiveRaceDate(b) ?? "");
    return dateOrder !== 0 ? dateOrder : cname(a).localeCompare(cname(b));
  });
}

function raceSql(bundle) {
  const r = bundle.race;
  const statements = [];
  statements.push(`INSERT INTO rt_races (
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
    entry_url=excluded.entry_url,result_url=excluded.result_url,status='finished',
    refund_horse_nos_json=excluded.refund_horse_nos_json,result_updated_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP;`);

  for (const x of bundle.runners) {
    statements.push(`INSERT INTO rt_runners (
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
    statements.push(`INSERT INTO rt_results (
      race_id,horse_no,finish_position,result_status,time_text,margin_text,final3f,updated_at
    ) VALUES (
      ${sql(r.raceId)},${sql(x.horseNo)},${sql(x.finishPosition)},${sql(x.resultStatus)},${sql(x.timeText)},${sql(x.marginText)},${sql(x.final3f)},CURRENT_TIMESTAMP
    ) ON CONFLICT(race_id,horse_no) DO UPDATE SET
      finish_position=excluded.finish_position,result_status=excluded.result_status,time_text=excluded.time_text,
      margin_text=excluded.margin_text,final3f=excluded.final3f,updated_at=CURRENT_TIMESTAMP;`);
  }

  for (const x of bundle.payouts) {
    statements.push(`INSERT INTO rt_payouts (
      race_id,bet_type,combination,payout_yen,popularity,updated_at
    ) VALUES (
      ${sql(r.raceId)},${sql(x.betType)},${sql(x.combination)},${sql(x.payoutYen)},${sql(x.popularity)},CURRENT_TIMESTAMP
    ) ON CONFLICT(race_id,bet_type,combination) DO UPDATE SET
      payout_yen=excluded.payout_yen,popularity=excluded.popularity,updated_at=CURRENT_TIMESTAMP;`);
  }
  return statements.join("\n");
}

async function fetchBundle(url) {
  let lastError = null;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    try {
      const page = await fetchJraPage(url);
      if (!pageLooksLikeResult(page.html)) throw new Error("RESULT_SIGNATURE_MISSING");
      const parsed = parseResultPage(page.html, page.url);
      if (!isWalkForwardArchiveDate(parsed.race.raceDate)) throw new Error(`OUT_OF_SCOPE:${parsed.race.raceDate}`);
      const runners = parseDesktopResultRunners(page.html);
      const payouts = parsed.payouts.length > 0 ? parsed.payouts : parseDesktopPayouts(page.html);
      if (runners.filter((x) => x.runnerStatus === "active" && x.winOdds !== null).length < 2) {
        throw new Error(`RUNNERS_NOT_FOUND:${runners.length}`);
      }
      if (parsed.race.status !== "cancelled" && payouts.length === 0) throw new Error("PAYOUTS_NOT_FOUND");
      return { bundle: { ...parsed, runners, payouts }, error: null };
    } catch (error) {
      lastError = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
      if (attempt < MAX_ATTEMPTS) await new Promise((resolve) => setTimeout(resolve, 250 * attempt));
    }
  }
  return { bundle: null, error: lastError ?? "UNKNOWN_ERROR" };
}

async function main() {
  await rm(OUTPUT_DIR, { recursive: true, force: true });
  await mkdir(OUTPUT_DIR, { recursive: true });

  const monthLists = await Promise.all(
    WALK_FORWARD_ARCHIVE_MONTHS.map(async (month) => {
      const discovered = await getArchiveResultUrls(month);
      return discovered.filter((url) => {
        const date = archiveRaceDate(url);
        return date !== null && isWalkForwardArchiveDate(date);
      });
    })
  );
  const urls = sortedUniqueUrls(monthLists.flat());
  console.log(`discovered ${urls.length} result pages across ${WALK_FORWARD_ARCHIVE_MONTHS.length} months`);

  let cursor = 0;
  let completed = 0;
  let fileIndex = 0;
  let fileRaceCount = 0;
  let currentFile = "";
  const failures = [];

  async function flush() {
    if (!currentFile) return;
    const name = `backfill-${String(fileIndex).padStart(4, "0")}.sql`;
    await writeFile(path.join(OUTPUT_DIR, name), `BEGIN TRANSACTION;\n${currentFile}\nCOMMIT;\n`);
    fileIndex += 1;
    fileRaceCount = 0;
    currentFile = "";
  }

  async function worker() {
    while (true) {
      const index = cursor;
      cursor += 1;
      if (index >= urls.length) return;
      const url = urls[index];
      const result = await fetchBundle(url);
      if (result.bundle) {
        currentFile += `${raceSql(result.bundle)}\n`;
        fileRaceCount += 1;
        completed += 1;
        if (fileRaceCount >= RACES_PER_SQL_FILE) await flush();
      } else {
        failures.push({ url, attempts: 0, error: result.error });
      }
      if ((index + 1) % 100 === 0 || index + 1 === urls.length) {
        console.log(`${index + 1}/${urls.length} fetched; success=${completed}; failed=${failures.length}`);
      }
    }
  }

  await Promise.all(Array.from({ length: FETCH_CONCURRENCY }, () => worker()));
  await flush();

  const prefix = `walk_forward_history:${WALK_FORWARD_SCOPE_VERSION}`;
  const stateSql = `BEGIN TRANSACTION;
INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES
  (${sql(`${prefix}:month_index`)},${sql(String(WALK_FORWARD_ARCHIVE_MONTHS.length))},CURRENT_TIMESTAMP),
  (${sql(`${prefix}:url_index`)},${sql(String(urls.length))},CURRENT_TIMESTAMP),
  (${sql(`${prefix}:failures`)},${sql(JSON.stringify(failures))},CURRENT_TIMESTAMP)
ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP;
COMMIT;\n`;
  await writeFile(path.join(OUTPUT_DIR, "zzzz-state.sql"), stateSql);
  await writeFile(path.join(OUTPUT_DIR, "summary.json"), JSON.stringify({
    scopeVersion: WALK_FORWARD_SCOPE_VERSION,
    urls: urls.length,
    completed,
    failures: failures.length,
    concurrency: FETCH_CONCURRENCY,
    sqlFiles: fileIndex
  }, null, 2));
  if (failures.length > 0) {
    await writeFile(path.join(OUTPUT_DIR, "failures.json"), JSON.stringify(failures, null, 2));
  }
  console.log(`finished: success=${completed}, failed=${failures.length}, sqlFiles=${fileIndex}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
