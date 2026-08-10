import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
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

function arg(name, fallback = null) {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const START_MONTH = arg("--start-month", "201605");
const END_MONTH = arg("--end-month", START_MONTH);
const OUT = path.resolve(arg("--out", `analysis-results/research-history-${START_MONTH}-${END_MONTH}.jsonl`));
const META = path.resolve(arg("--meta", `analysis-results/research-history-${START_MONTH}-${END_MONTH}-meta.json`));
const CONCURRENCY = Math.max(1, Math.min(8, Number(arg("--concurrency", "2"))));
const MAX_ATTEMPTS_PER_CALL = 4;
const MONTH_DISCOVERY_ATTEMPTS = 8;
const REPAIR_PASSES = 3;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function parseYm(value) {
  if (!/^\d{6}$/.test(value)) throw new Error(`INVALID_MONTH:${value}`);
  return [Number(value.slice(0, 4)), Number(value.slice(4, 6))];
}

function monthsBetween(start, end) {
  let [y, m] = parseYm(start);
  const [ey, em] = parseYm(end);
  if (y > ey || (y === ey && m > em)) throw new Error("INVALID_MONTH_RANGE");
  const out = [];
  while (y < ey || (y === ey && m <= em)) {
    out.push(`${y}${String(m).padStart(2, "0")}`);
    if (m === 12) { y += 1; m = 1; } else { m += 1; }
  }
  return out;
}

async function retry(fn) {
  let last = null;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS_PER_CALL; attempt += 1) {
    try { return await fn(); }
    catch (error) {
      last = error;
      if (attempt < MAX_ATTEMPTS_PER_CALL) await sleep(600 * attempt);
    }
  }
  throw last;
}

async function discoverMonth(month) {
  let last = null;
  for (let attempt = 1; attempt <= MONTH_DISCOVERY_ATTEMPTS; attempt += 1) {
    try {
      const urls = await getArchiveResultUrls(month);
      if (!Array.isArray(urls) || urls.length === 0) throw new Error(`NO_ARCHIVE_RESULTS:${month}`);
      if (attempt > 1) console.log(JSON.stringify({ phase: "month-discovery-recovered", month, attempt, discovered: urls.length }));
      return urls;
    } catch (error) {
      last = error;
      console.log(JSON.stringify({
        phase: "month-discovery-retry",
        month,
        attempt,
        error: error instanceof Error ? `${error.name}:${error.message}` : String(error)
      }));
      if (attempt < MONTH_DISCOVERY_ATTEMPTS) await sleep(1800 * attempt);
    }
  }
  throw last;
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

async function fetchBundle(url) {
  return retry(async () => {
    const page = await fetchJraPage(url);
    if (!pageLooksLikeResult(page.html)) throw new Error("RESULT_SIGNATURE_MISSING");
    const parsed = parseResultPage(page.html, page.url);
    const desktopRunners = parseDesktopResultRunners(page.html).map((r) => ({ ...r, winOdds: null }));
    const payouts = parsed.payouts.length > 0 ? parsed.payouts : parseDesktopPayouts(page.html);
    if (desktopRunners.filter((r) => r.runnerStatus === "active").length < 2) {
      throw new Error(`RUNNERS_NOT_FOUND:${desktopRunners.length}`);
    }
    if (parsed.race.status !== "cancelled" && payouts.length === 0) throw new Error("PAYOUTS_NOT_FOUND");
    return {
      race: parsed.race,
      runners: desktopRunners,
      results: parsed.results,
      payouts,
      refundHorseNos: parsed.refundHorseNos ?? [],
      provenance: {
        resultUrl: page.url,
        source: "jra_official_archive",
        syntheticOddsUsed: false,
        productionDatabaseWritten: false
      }
    };
  });
}

async function fetchOne(url) {
  try {
    return { url, bundle: await fetchBundle(url), error: null };
  } catch (error) {
    return { url, bundle: null, error: error instanceof Error ? `${error.name}:${error.message}` : String(error) };
  }
}

async function main() {
  const months = monthsBetween(START_MONTH, END_MONTH);
  const monthRows = [];
  for (const month of months) {
    const urls = await discoverMonth(month);
    monthRows.push({ month, count: urls.length, urls });
    console.log(JSON.stringify({ month, discovered: urls.length }));
  }

  const urls = [...new Set(monthRows.flatMap((x) => x.urls))];
  const byUrl = new Map();
  let failures = [];

  const initial = await mapConcurrent(urls, CONCURRENCY, async (url, i) => {
    const r = await fetchOne(url);
    if ((i + 1) % 20 === 0 || i + 1 === urls.length) {
      console.log(JSON.stringify({ phase: "initial", fetched: i + 1, total: urls.length }));
    }
    return r;
  });

  for (const r of initial) {
    if (r.bundle) byUrl.set(r.url, r.bundle);
    else failures.push({ url: r.url, error: r.error });
  }

  for (let pass = 1; pass <= REPAIR_PASSES && failures.length > 0; pass += 1) {
    const pending = failures.map((x) => x.url);
    console.log(JSON.stringify({ phase: "repair", pass, pending: pending.length }));
    await sleep(2500 * pass);
    failures = [];
    for (let i = 0; i < pending.length; i += 1) {
      const url = pending[i];
      const r = await fetchOne(url);
      if (r.bundle) byUrl.set(url, r.bundle);
      else failures.push({ url, error: r.error });
      await sleep(1200 * pass);
    }
  }

  const ok = [...byUrl.values()].sort((a, b) => {
    const ad = `${a.race.raceDate}-${a.race.venue}-${String(a.race.raceNo).padStart(2, "0")}`;
    const bd = `${b.race.raceDate}-${b.race.venue}-${String(b.race.raceNo).padStart(2, "0")}`;
    return ad.localeCompare(bd);
  });

  await mkdir(path.dirname(OUT), { recursive: true });
  await writeFile(OUT, ok.map((row) => JSON.stringify(row)).join("\n") + (ok.length ? "\n" : ""));
  const meta = {
    scope: { startMonth: START_MONTH, endMonth: END_MONTH, months },
    purpose: "research_only_no_production_write",
    discovered: monthRows.map(({ month, count }) => ({ month, count })),
    requestedUrls: urls.length,
    completed: ok.length,
    failures,
    concurrency: CONCURRENCY,
    monthDiscoveryAttempts: MONTH_DISCOVERY_ATTEMPTS,
    repairPasses: REPAIR_PASSES,
    syntheticOddsUsed: false,
    productionDatabaseWritten: false
  };
  await writeFile(META, JSON.stringify(meta, null, 2) + "\n");
  console.log(JSON.stringify({ completed: ok.length, failed: failures.length, out: OUT }));
  if (failures.length) {
    console.error(JSON.stringify({ unresolvedFailures: failures }));
    process.exitCode = 2;
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
