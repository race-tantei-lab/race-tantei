import { readFile, writeFile, mkdir } from "node:fs/promises";
import { gunzipSync } from "node:zlib";
import path from "node:path";
import process from "node:process";
import {
  fetchJraPage,
  pageLooksLikeResult,
  parseResultPage
} from "../dist-test/src/v1/jra.js";
import {
  fetchJraArchivePage,
  getArchiveResultUrls
} from "../dist-test/src/v1/three-month-archive.js";
import {
  parseDesktopPayouts,
  parseDesktopResultRunners
} from "../dist-test/src/v1/three-month-desktop.js";
import { stripHtml } from "../dist-test/src/v1/utils.js";
import { parseLegacyRaceMeta } from "./research-legacy-race-meta.mjs";

function arg(name, fallback = null) {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const D1_DIR = path.resolve(arg("--d1-dir"));
const HISTORY_2024 = path.resolve(arg("--history-2024"));
const HISTORY_2025 = path.resolve(arg("--history-2025"));
const OUT = path.resolve(arg("--out", "analysis-results/d1-history-gap-repairs.jsonl"));
const META = path.resolve(arg("--meta", "analysis-results/d1-history-gap-repairs-meta.json"));
const CONCURRENCY = Math.max(1, Math.min(4, Number(arg("--concurrency", "3"))));
const ATTEMPTS = 6;

const VENUE_CODE = {
  "札幌": "01",
  "函館": "02",
  "福島": "03",
  "新潟": "04",
  "東京": "05",
  "中山": "06",
  "中京": "07",
  "京都": "08",
  "阪神": "09",
  "小倉": "10"
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const pad2 = (value) => String(value ?? 0).padStart(2, "0");

function parseJsonl(text) {
  return text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}

async function readJsonl(file) {
  return parseJsonl(await readFile(file, "utf8"));
}

async function readGzJsonl(file) {
  return parseJsonl(gunzipSync(await readFile(file)).toString("utf8"));
}

function d1RaceToCamel(r) {
  return {
    raceId: r.race_id,
    raceDate: r.race_date,
    venue: r.venue,
    meetingNo: r.meeting_no ?? null,
    meetingDay: r.meeting_day ?? null,
    raceNo: r.race_no,
    raceName: r.race_name ?? null,
    conditions: r.conditions ?? null,
    surface: r.surface ?? null,
    distanceM: r.distance_m ?? null,
    direction: r.direction ?? null,
    startTimeJst: r.start_time_jst ?? null,
    startTimeUtc: r.start_time_utc ?? null,
    weather: r.weather ?? null,
    trackCondition: r.track_condition ?? null,
    entryUrl: r.entry_url ?? null,
    resultUrl: r.result_url ?? null,
    status: r.status ?? null
  };
}

function mergeRace(d1, fallback) {
  const base = d1RaceToCamel(d1);
  return {
    ...fallback,
    ...Object.fromEntries(Object.entries(base).filter(([, value]) => value !== null && value !== "")),
    status: fallback?.status === "finished" || fallback?.status === "cancelled" ? fallback.status : (base.status ?? fallback?.status ?? "finished")
  };
}

function cnameFromUrl(url) {
  try {
    return decodeURIComponent(new URL(url).searchParams.get("CNAME") ?? "");
  } catch {
    return "";
  }
}

function expectedCnamePrefix(race) {
  const venueCode = VENUE_CODE[race.venue];
  if (!venueCode) throw new Error(`VENUE_CODE_NOT_FOUND:${race.venue}`);
  const compactDate = race.race_date.replace(/-/g, "");
  const year = race.race_date.slice(0, 4);
  return `pw01sde10${venueCode}${year}${pad2(race.meeting_no)}${pad2(race.meeting_day)}${pad2(race.race_no)}${compactDate}`.toLowerCase();
}

async function resolveArchiveResultUrl(race, monthCache) {
  const month = race.race_date.slice(0, 7).replace("-", "");
  let promise = monthCache.get(month);
  if (!promise) {
    promise = getArchiveResultUrls(month);
    monthCache.set(month, promise);
  }
  const urls = await promise;
  const prefix = expectedCnamePrefix(race);
  const matches = urls.filter((url) => cnameFromUrl(url).toLowerCase().startsWith(prefix));
  if (matches.length !== 1) {
    throw new Error(`ARCHIVE_RACE_URL_MATCH:${race.race_id}:count=${matches.length}`);
  }
  return matches[0];
}

async function fetchOfficialHtml(resultUrl) {
  const cname = cnameFromUrl(resultUrl);
  let last = null;
  for (let attempt = 1; attempt <= ATTEMPTS; attempt += 1) {
    if (cname) {
      try {
        const page = await fetchJraArchivePage(cname);
        return { html: page.html, method: "archive_post" };
      } catch (error) {
        last = error;
      }
    }
    try {
      const page = await fetchJraPage(resultUrl);
      return { html: page.html, method: "direct_get" };
    } catch (error) {
      last = error;
    }
    if (attempt < ATTEMPTS) await sleep(Math.min(10_000, 1000 * attempt));
  }
  throw last instanceof Error ? last : new Error(String(last));
}

function normalizeOfficialText(html) {
  return stripHtml(html)
    .replace(/[０-９]/g, (char) => String(char.charCodeAt(0) - 0xfee0))
    .replace(/[：﹕]/g, ":")
    .replace(/\s+/g, " ")
    .trim();
}

function canonicalConditionsFromOfficialHtml(html, raceName) {
  const text = normalizeOfficialText(html);
  const index = raceName ? text.indexOf(raceName) : -1;
  const scopes = index >= 0
    ? [text.slice(Math.max(0, index - 180), Math.min(text.length, index + 800)), text]
    : [text];
  const patterns = [
    /(障害(?:2歳|3歳|3歳以上|4歳以上)?\s*(?:新馬|未勝利|オープン))/u,
    /((?:2歳|3歳|3歳以上|4歳以上)\s*(?:牝馬限定|牝|牡・牝)?\s*(?:新馬|未勝利|1勝クラス|2勝クラス|3勝クラス|オープン))/u,
    /(サラ系(?:2歳|3歳|3歳以上|4歳以上)\s*(?:牝馬限定|牝|牡・牝)?\s*(?:新馬|未勝利|1勝クラス|2勝クラス|3勝クラス|オープン))/u
  ];
  for (const scope of scopes) {
    for (const pattern of patterns) {
      const match = scope.match(pattern)?.[1];
      if (match) return match.replace(/^サラ系/, "").replace(/\s+/g, " ").trim();
    }
  }
  return null;
}

function metadataComplete(race) {
  return Boolean(
    race?.raceName
    && race?.conditions
    && ["芝", "ダート", "障害"].includes(race?.surface)
    && Number.isFinite(race?.distanceM)
    && race.distanceM > 0
  );
}

function outcomeComplete(bundle) {
  return Boolean(
    bundle?.race?.status === "cancelled"
    || (
      Array.isArray(bundle?.runners) && bundle.runners.length >= 2
      && Array.isArray(bundle?.results) && bundle.results.length >= 2
      && Array.isArray(bundle?.payouts) && bundle.payouts.length > 0
    )
  );
}

function repairFromLegacy(d1Race, legacy) {
  return {
    ...legacy,
    race: mergeRace(d1Race, legacy.race),
    provenance: {
      ...(legacy.provenance ?? {}),
      source: "jra_official_year_artifact_repair",
      syntheticOddsUsed: false,
      productionDatabaseWritten: false
    }
  };
}

function repairFromOfficialHtml(d1Race, html, resultUrl, method) {
  if (!pageLooksLikeResult(html)) throw new Error("RESULT_SIGNATURE_MISSING");
  const parsed = parseResultPage(html, resultUrl);
  const meta = parseLegacyRaceMeta(html, resultUrl);
  const conditionFallback = canonicalConditionsFromOfficialHtml(html, d1Race.race_name ?? parsed.race?.raceName ?? meta.raceName);
  const desktopRunners = parseDesktopResultRunners(html).map((runner) => ({ ...runner, winOdds: null }));
  const payouts = parsed.payouts?.length ? parsed.payouts : parseDesktopPayouts(html);
  const fallbackRace = {
    ...parsed.race,
    raceName: parsed.race?.raceName && !/検索ウィンドウ|緊急情報/.test(parsed.race.raceName) ? parsed.race.raceName : meta.raceName,
    conditions: parsed.race?.conditions ?? meta.conditions ?? conditionFallback,
    surface: parsed.race?.surface ?? meta.surface,
    distanceM: parsed.race?.distanceM ?? meta.distanceM,
    direction: parsed.race?.direction ?? meta.direction,
    weather: parsed.race?.weather ?? meta.weather,
    trackCondition: parsed.race?.trackCondition ?? meta.trackCondition,
    status: parsed.race?.status ?? "finished"
  };
  const race = mergeRace(d1Race, fallbackRace);
  if (!race.conditions) race.conditions = meta.conditions ?? conditionFallback;
  if (!race.surface) race.surface = meta.surface;
  if (!race.distanceM) race.distanceM = meta.distanceM;
  if (!race.direction) race.direction = meta.direction;
  if (!race.raceName || /検索ウィンドウ|緊急情報/.test(race.raceName)) race.raceName = meta.raceName;
  race.resultUrl = resultUrl;
  return {
    race,
    runners: desktopRunners,
    results: parsed.results ?? [],
    payouts,
    refundHorseNos: parsed.refundHorseNos ?? [],
    provenance: {
      resultUrl,
      source: "jra_official_targeted_d1_gap_repair",
      fetchMethod: method,
      syntheticOddsUsed: false,
      productionDatabaseWritten: false
    }
  };
}

async function mapConcurrent(values, concurrency, mapper) {
  const results = new Array(values.length);
  let cursor = 0;
  async function worker() {
    while (true) {
      const i = cursor++;
      if (i >= values.length) return;
      results[i] = await mapper(values[i], i);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, values.length) }, worker));
  return results;
}

async function main() {
  const races = await readGzJsonl(path.join(D1_DIR, "races.jsonl.gz"));
  const runners = await readGzJsonl(path.join(D1_DIR, "runners.jsonl.gz"));
  const results = await readGzJsonl(path.join(D1_DIR, "results.jsonl.gz"));
  const payouts = await readGzJsonl(path.join(D1_DIR, "payouts.jsonl.gz"));

  const runnerCount = new Map();
  const resultCount = new Map();
  const payoutCount = new Map();
  for (const row of runners) runnerCount.set(row.race_id, (runnerCount.get(row.race_id) ?? 0) + 1);
  for (const row of results) resultCount.set(row.race_id, (resultCount.get(row.race_id) ?? 0) + 1);
  for (const row of payouts) payoutCount.set(row.race_id, (payoutCount.get(row.race_id) ?? 0) + 1);

  const gaps = races.filter((r) => {
    const metadataGap = !r.race_name || !r.conditions || !["芝", "ダート", "障害"].includes(r.surface) || !r.distance_m;
    const outcomeGap = r.status !== "cancelled" && ((runnerCount.get(r.race_id) ?? 0) < 2 || (resultCount.get(r.race_id) ?? 0) < 2 || (payoutCount.get(r.race_id) ?? 0) < 1);
    return metadataGap || outcomeGap;
  });

  const legacy2024 = new Map((await readJsonl(HISTORY_2024)).map((row) => [row.race.raceId, row]));
  const legacy2025 = new Map((await readJsonl(HISTORY_2025)).map((row) => [row.race.raceId, row]));

  const localRepairs = [];
  const networkTargets = [];
  for (const race of gaps) {
    const year = race.race_date.slice(0, 4);
    const legacy = year === "2024" ? legacy2024.get(race.race_id) : year === "2025" ? legacy2025.get(race.race_id) : null;
    if (legacy) {
      const repaired = repairFromLegacy(race, legacy);
      if (!metadataComplete(repaired.race) || !outcomeComplete(repaired)) {
        throw new Error(`LEGACY_REPAIR_INCOMPLETE:${race.race_id}`);
      }
      localRepairs.push(repaired);
    } else {
      networkTargets.push(race);
    }
  }

  const failures = [];
  const monthCache = new Map();
  let archivePost = 0;
  let directGet = 0;
  let archiveUrlResolved = 0;
  const networkRepairs = await mapConcurrent(networkTargets, CONCURRENCY, async (race, index) => {
    let resultUrl = race.result_url;
    try {
      if (!cnameFromUrl(resultUrl)) {
        resultUrl = await resolveArchiveResultUrl(race, monthCache);
        archiveUrlResolved += 1;
      }
      if (!resultUrl) throw new Error("RESULT_URL_MISSING");
      const fetched = await fetchOfficialHtml(resultUrl);
      if (fetched.method === "archive_post") archivePost += 1;
      else directGet += 1;
      const repaired = repairFromOfficialHtml(race, fetched.html, resultUrl, fetched.method);
      if (!metadataComplete(repaired.race) || !outcomeComplete(repaired)) {
        throw new Error(`NETWORK_REPAIR_INCOMPLETE:${race.race_id}:conditions=${JSON.stringify(repaired.race.conditions)}:runners=${repaired.runners.length}:results=${repaired.results.length}:payouts=${repaired.payouts.length}`);
      }
      if ((index + 1) % 20 === 0 || index + 1 === networkTargets.length) {
        console.log(JSON.stringify({ repaired2026: index + 1, total2026: networkTargets.length, failures: failures.length }));
      }
      return repaired;
    } catch (error) {
      failures.push({ raceId: race.race_id, resultUrl, error: error instanceof Error ? `${error.name}:${error.message}` : String(error) });
      return null;
    }
  });

  const repaired = [...localRepairs, ...networkRepairs.filter(Boolean)]
    .sort((a, b) => a.race.raceId.localeCompare(b.race.raceId));
  const repairedIds = new Set(repaired.map((row) => row.race.raceId));
  const unresolved = gaps.filter((race) => !repairedIds.has(race.race_id)).map((race) => race.race_id);

  await mkdir(path.dirname(OUT), { recursive: true });
  await writeFile(OUT, repaired.map((row) => JSON.stringify(row)).join("\n") + (repaired.length ? "\n" : ""));
  const meta = {
    purpose: "research_only_d1_gap_repair",
    detectedGaps: gaps.length,
    repairedFrom2024Artifact: localRepairs.filter((row) => row.race.raceDate.startsWith("2024")).length,
    repairedFrom2025Artifact: localRepairs.filter((row) => row.race.raceDate.startsWith("2025")).length,
    networkTargets2026: networkTargets.length,
    networkRepairs2026: networkRepairs.filter(Boolean).length,
    archiveUrlResolved,
    fetchMethods: { archivePost, directGet },
    failures,
    unresolved,
    syntheticOddsUsed: false,
    productionDatabaseWritten: false
  };
  await writeFile(META, JSON.stringify(meta, null, 2) + "\n");
  console.log(JSON.stringify(meta));
  if (failures.length || unresolved.length || repaired.length !== gaps.length) process.exitCode = 2;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
