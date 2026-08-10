import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fetchJraPage } from "../dist-test/src/v1/jra.js";
import { fetchJraArchivePage } from "../dist-test/src/v1/three-month-archive.js";
import { parseLegacyRaceMeta } from "./research-legacy-race-meta.mjs";

function arg(name, fallback = null) {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const INPUT = path.resolve(arg("--input"));
const OUT = path.resolve(arg("--out"));
const META = path.resolve(arg("--meta"));
const START_DATE = arg("--start-date", "0000-01-01");
const END_DATE = arg("--end-date", "9999-12-31");
const CONCURRENCY = Math.max(1, Math.min(6, Number(arg("--concurrency", "3"))));
const ATTEMPTS = 5;

if (!INPUT || !OUT || !META) throw new Error("--input, --out and --meta are required");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function cnameFromUrl(url) {
  try {
    return decodeURIComponent(new URL(url).searchParams.get("CNAME") ?? "");
  } catch {
    return "";
  }
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
    if (attempt < ATTEMPTS) await sleep(Math.min(12_000, 1200 * attempt));
  }
  throw last instanceof Error ? last : new Error(String(last));
}

function metadataLooksComplete(meta) {
  return Boolean(
    meta
    && meta.raceName
    && !/検索ウィンドウ|緊急情報/.test(meta.raceName)
    && meta.conditions
    && ["芝", "ダート", "障害"].includes(meta.surface)
    && Number.isFinite(meta.distanceM)
    && meta.distanceM > 0
  );
}

async function mapConcurrent(values, concurrency, mapper) {
  const result = new Array(values.length);
  let cursor = 0;
  async function worker() {
    while (true) {
      const i = cursor++;
      if (i >= values.length) return;
      result[i] = await mapper(values[i], i);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, values.length) }, worker));
  return result;
}

async function main() {
  const lines = (await readFile(INPUT, "utf8")).split(/\r?\n/).filter(Boolean);
  const allRows = lines.map((line) => JSON.parse(line));
  const rows = allRows.filter((row) => row?.race?.raceDate >= START_DATE && row?.race?.raceDate <= END_DATE);
  const failures = [];
  let archivePost = 0;
  let directGet = 0;

  const enriched = await mapConcurrent(rows, CONCURRENCY, async (row, i) => {
    const resultUrl = row?.provenance?.resultUrl ?? row?.race?.resultUrl;
    if (!resultUrl) {
      failures.push({ raceId: row?.race?.raceId ?? null, error: "RESULT_URL_MISSING" });
      return row;
    }
    try {
      const fetched = await fetchOfficialHtml(resultUrl);
      if (fetched.method === "archive_post") archivePost += 1;
      else directGet += 1;
      const meta = parseLegacyRaceMeta(fetched.html, resultUrl);
      if (!metadataLooksComplete(meta)) throw new Error(`INCOMPLETE_METADATA:${JSON.stringify(meta)}`);
      const updated = {
        ...row,
        race: {
          ...row.race,
          raceName: meta.raceName,
          conditions: meta.conditions,
          surface: meta.surface,
          distanceM: meta.distanceM,
          direction: meta.direction,
          weather: meta.weather ?? row.race.weather ?? null,
          trackCondition: meta.trackCondition ?? row.race.trackCondition ?? null
        },
        provenance: {
          ...row.provenance,
          metadataSource: meta.provenance,
          metadataFetchMethod: fetched.method,
          syntheticOddsUsed: false,
          productionDatabaseWritten: false
        }
      };
      if ((i + 1) % 50 === 0 || i + 1 === rows.length) {
        console.log(JSON.stringify({ enriched: i + 1, total: rows.length, failures: failures.length }));
      }
      return updated;
    } catch (error) {
      failures.push({
        raceId: row?.race?.raceId ?? null,
        resultUrl,
        error: error instanceof Error ? `${error.name}:${error.message}` : String(error)
      });
      return row;
    }
  });

  const incomplete = enriched.filter((row) => !metadataLooksComplete(row.race)).map((row) => row.race?.raceId ?? null);
  enriched.sort((a, b) => String(a.race.raceId).localeCompare(String(b.race.raceId)));

  await mkdir(path.dirname(OUT), { recursive: true });
  await writeFile(OUT, enriched.map((row) => JSON.stringify(row)).join("\n") + (enriched.length ? "\n" : ""));
  const meta = {
    purpose: "research_only_metadata_enrichment_no_production_write",
    inputRows: allRows.length,
    selectedRows: rows.length,
    outputRows: enriched.length,
    startDate: START_DATE,
    endDate: END_DATE,
    failures,
    incompleteRaceIds: incomplete,
    fetchMethods: { archivePost, directGet },
    syntheticOddsUsed: false,
    productionDatabaseWritten: false
  };
  await writeFile(META, JSON.stringify(meta, null, 2) + "\n");
  console.log(JSON.stringify({ completed: enriched.length, failures: failures.length, incomplete: incomplete.length }));
  if (failures.length || incomplete.length) process.exitCode = 2;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
