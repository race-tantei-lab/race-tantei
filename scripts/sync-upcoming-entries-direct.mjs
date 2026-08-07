import {
  discoverRaceUrls,
  fetchJraPage,
  pageLooksLikeEntry,
  parseEntryPage,
  toResultUrl
} from "../dist-test/src/v1/jra.js";

const accountId = process.env.CLOUDFLARE_ACCOUNT_ID;
const databaseId = process.env.CLOUDFLARE_D1_DATABASE_ID;
const token = process.env.CLOUDFLARE_API_TOKEN;
const apiUrl = `https://api.cloudflare.com/client/v4/accounts/${accountId}/d1/database/${databaseId}/query`;
const homeUrl = process.env.JRA_HOME_URL || "https://sp.jra.jp/";
const accessDUrl = "https://www.jra.go.jp/JRADB/accessD.html";
const seedUrls = (process.env.JRA_SEED_ENTRY_URLS || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);

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
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ sql, params })
      });
      const body = await response.json();
      if (!response.ok || body?.success !== true) throw new Error(`D1_HTTP_${response.status}:${JSON.stringify(body?.errors || [])}`);
      const result = Array.isArray(body.result) ? body.result[0] : null;
      if (result?.success === false) throw new Error(`D1_QUERY_FAILED:${JSON.stringify(result)}`);
      return result?.results || [];
    } catch (error) {
      lastError = error;
      if (attempt < 5) await sleep(attempt * 1500);
    }
  }
  throw lastError;
}

function jstToday() {
  const now = new Date(Date.now() + 9 * 3600_000);
  return `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}-${String(now.getUTCDate()).padStart(2, "0")}`;
}

function chunks(values, size) {
  const output = [];
  for (let index = 0; index < values.length; index += size) output.push(values.slice(index, index + size));
  return output;
}

function normalizeActionCname(value) {
  return value.replace(/&amp;/gi, "&").replace(/\\u0026/gi, "&").replace(/\\\//g, "/").trim();
}

function actionEntryUrls(html) {
  const found = new Map();
  const patterns = [
    /doAction\(\s*['"]\/JRADB\/accessD\.html['"]\s*,\s*['"]([^'"]+)['"]\s*\)/gi,
    /doAction\(\s*['"]https:\/\/www\.jra\.go\.jp\/JRADB\/accessD\.html['"]\s*,\s*['"]([^'"]+)['"]\s*\)/gi,
    /(?:CNAME|cname)\s*[=:]\s*['"]([^'"]*(?:pw|sw)01dde[^'"]*)['"]/gi
  ];
  for (const pattern of patterns) {
    for (const match of html.matchAll(pattern)) {
      const cname = normalizeActionCname(match[1] || "");
      if (!/(?:pw|sw)01dde/i.test(cname)) continue;
      const url = `${accessDUrl}?CNAME=${encodeURIComponent(cname)}`;
      found.set(cname, url);
    }
  }
  return [...found.values()];
}

async function discoverDoActionRaceUrls() {
  const queue = [homeUrl, accessDUrl, ...seedUrls];
  const queued = new Set(queue);
  const visited = new Set();
  const raceUrls = new Map();
  const errors = [];
  const maxPages = 180;

  while (queue.length && visited.size < maxPages) {
    const url = queue.shift();
    if (!url || visited.has(url)) continue;
    visited.add(url);
    try {
      const page = await fetchJraPage(url);
      if (pageLooksLikeEntry(page.html) && /(?:pw|sw)01dde/i.test(decodeURIComponent(page.url))) {
        const cname = new URL(page.url).searchParams.get("CNAME") || page.url;
        raceUrls.set(cname, page.url);
      }
      for (const child of actionEntryUrls(page.html)) {
        if (!queued.has(child)) {
          queued.add(child);
          queue.push(child);
        }
      }
      await sleep(80);
    } catch (error) {
      errors.push({ url, error: `${error?.name || "Error"}:${error?.message || String(error)}` });
    }
  }
  return { urls: [...raceUrls.values()], visitedPages: visited.size, errors };
}

async function saveRace(bundle) {
  const race = bundle.race;
  const now = new Date().toISOString();
  await d1(
    `INSERT INTO rt_races (
      race_id,race_date,venue,meeting_no,meeting_day,race_no,race_name,conditions,
      surface,distance_m,direction,start_time_jst,start_time_utc,weather,track_condition,
      entry_url,result_url,status,entry_updated_at,updated_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(race_id) DO UPDATE SET
      race_date=excluded.race_date,venue=excluded.venue,meeting_no=excluded.meeting_no,
      meeting_day=excluded.meeting_day,race_no=excluded.race_no,race_name=excluded.race_name,
      conditions=excluded.conditions,surface=excluded.surface,distance_m=excluded.distance_m,
      direction=excluded.direction,start_time_jst=excluded.start_time_jst,start_time_utc=excluded.start_time_utc,
      weather=COALESCE(excluded.weather,rt_races.weather),
      track_condition=COALESCE(excluded.track_condition,rt_races.track_condition),
      entry_url=excluded.entry_url,result_url=excluded.result_url,
      status=CASE WHEN rt_races.status='finished' THEN rt_races.status ELSE excluded.status END,
      entry_updated_at=excluded.entry_updated_at,updated_at=CURRENT_TIMESTAMP`,
    [
      race.raceId,race.raceDate,race.venue,race.meetingNo,race.meetingDay,race.raceNo,
      race.raceName,race.conditions,race.surface,race.distanceM,race.direction,race.startTimeJst,
      race.startTimeUtc,race.weather,race.trackCondition,race.entryUrl,race.resultUrl,race.status,now
    ]
  );

  for (const group of chunks(bundle.runners, 6)) {
    const placeholders = group.map(() => "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)").join(",");
    const params = group.flatMap((runner) => [
      race.raceId,runner.horseNo,runner.frameNo,runner.horseName,runner.sexAge,runner.coatColor,
      runner.horseWeight,runner.weightChange,runner.jockey,runner.assignedWeight,runner.trainer,
      runner.stable,runner.winOdds,runner.popularity,runner.runnerStatus
    ]);
    await d1(
      `INSERT INTO rt_runners (
        race_id,horse_no,frame_no,horse_name,sex_age,coat_color,horse_weight,weight_change,
        jockey,assigned_weight,trainer,stable,win_odds,popularity,runner_status,updated_at
      ) VALUES ${placeholders}
      ON CONFLICT(race_id,horse_no) DO UPDATE SET
        frame_no=excluded.frame_no,horse_name=excluded.horse_name,sex_age=excluded.sex_age,
        coat_color=excluded.coat_color,horse_weight=excluded.horse_weight,weight_change=excluded.weight_change,
        jockey=excluded.jockey,assigned_weight=excluded.assigned_weight,trainer=excluded.trainer,
        stable=excluded.stable,win_odds=excluded.win_odds,popularity=excluded.popularity,
        runner_status=excluded.runner_status,updated_at=CURRENT_TIMESTAMP`,
      params
    );
  }

  await d1(
    `INSERT INTO rt_race_sources (
      entry_url,result_url,race_id,status,next_fetch_at,last_entry_fetch_at,failure_count,last_error,updated_at
    ) VALUES (?,?,?,'active',?,?,0,NULL,CURRENT_TIMESTAMP)
    ON CONFLICT(entry_url) DO UPDATE SET
      result_url=excluded.result_url,race_id=excluded.race_id,status='active',
      next_fetch_at=excluded.next_fetch_at,last_entry_fetch_at=excluded.last_entry_fetch_at,
      failure_count=0,last_error=NULL,updated_at=CURRENT_TIMESTAMP`,
    [race.entryUrl, toResultUrl(race.entryUrl), race.raceId, now, now]
  );
}

async function main() {
  const today = jstToday();
  const [normalUrls, actionDiscovery] = await Promise.all([
    discoverRaceUrls(homeUrl, seedUrls),
    discoverDoActionRaceUrls()
  ]);
  const unique = new Map();
  for (const url of [...normalUrls, ...actionDiscovery.urls]) {
    try {
      const cname = decodeURIComponent(new URL(url).searchParams.get("CNAME") || url);
      unique.set(cname, url);
    } catch {
      unique.set(url, url);
    }
  }
  const urls = [...unique.values()];
  const reports = [];
  const errors = [...actionDiscovery.errors];
  for (const url of urls) {
    try {
      const page = await fetchJraPage(url);
      if (!pageLooksLikeEntry(page.html)) throw new Error("ENTRY_PAGE_SIGNATURE_MISSING");
      const bundle = parseEntryPage(page.html, page.url);
      if (bundle.race.raceDate < today) continue;
      if (!bundle.race.startTimeUtc) throw new Error("START_TIME_MISSING");
      if (bundle.runners.filter((runner) => runner.runnerStatus === "active").length < 3) throw new Error("ACTIVE_RUNNERS_TOO_FEW");
      await saveRace(bundle);
      reports.push({
        raceId: bundle.race.raceId,
        raceDate: bundle.race.raceDate,
        venue: bundle.race.venue,
        raceNo: bundle.race.raceNo,
        activeRunners: bundle.runners.filter((runner) => runner.runnerStatus === "active").length,
        runnersWithWinOdds: bundle.runners.filter((runner) => runner.runnerStatus === "active" && Number(runner.winOdds) > 1).length
      });
      await sleep(120);
    } catch (error) {
      errors.push({ url, error: `${error?.name || "Error"}:${error?.message || String(error)}` });
    }
  }
  reports.sort((a, b) => `${a.raceDate}-${a.venue}-${a.raceNo}`.localeCompare(`${b.raceDate}-${b.venue}-${b.raceNo}`, "ja"));
  const output = {
    generatedAtUtc: new Date().toISOString(),
    normalDiscoveredUrls: normalUrls.length,
    doActionVisitedPages: actionDiscovery.visitedPages,
    doActionDiscoveredRaceUrls: actionDiscovery.urls.length,
    discoveredUrls: urls.length,
    storedRaces: reports.length,
    storedActiveRunners: reports.reduce((sum, row) => sum + row.activeRunners, 0),
    racesWithAtLeastThreeWinOdds: reports.filter((row) => row.runnersWithWinOdds >= 3).length,
    races: reports,
    errorCount: errors.length,
    errors: errors.slice(0, 100)
  };
  await Bun?.write?.("upcoming-entry-direct-sync.json", JSON.stringify(output, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
