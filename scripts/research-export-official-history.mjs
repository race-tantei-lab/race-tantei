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
const LIMIT = Number(arg("--limit", "0"));
const CONCURRENCY = Math.max(1, Math.min(8, Number(arg("--concurrency", "4"))));
const MAX_ATTEMPTS = 4;

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
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    try { return await fn(); }
    catch (error) {
      last = error;
      if (attempt < MAX_ATTEMPTS) await new Promise((r) => setTimeout(r, 350 * attempt));
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

async function main() {
  const months = monthsBetween(START_MONTH, END_MONTH);
  const monthRows = [];
  for (const month of months) {
    const urls = await getArchiveResultUrls(month);
    monthRows.push({ month, count: urls.length, urls });
    console.log(JSON.stringify({ month, discovered: urls.length }));
  }
  let urls = [...new Set(monthRows.flatMap((x) => x.urls))];
  if (LIMIT > 0) urls = urls.slice(0, LIMIT);
  const failures = [];
  const bundles = await mapConcurrent(urls, CONCURRENCY, async (url, i) => {
    try {
      const bundle = await fetchBundle(url);
      if ((i + 1) % 20 === 0 || i + 1 === urls.length) console.log(JSON.stringify({ fetched: i + 1, total: urls.length }));
      return bundle;
    } catch (error) {
      failures.push({ url, error: error instanceof Error ? `${error.name}:${error.message}` : String(error) });
      return null;
    }
  });
  const ok = bundles.filter(Boolean).sort((a, b) => {
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
    syntheticOddsUsed: false,
    productionDatabaseWritten: false
  };
  await writeFile(META, JSON.stringify(meta, null, 2) + "\n");
  console.log(JSON.stringify({ completed: ok.length, failed: failures.length, out: OUT }));
  if (failures.length) process.exitCode = 2;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
