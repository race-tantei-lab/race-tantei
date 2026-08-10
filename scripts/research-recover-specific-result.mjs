import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {
  fetchJraPage,
  pageLooksLikeResult,
  parseResultPage
} from "../dist-test/src/v1/jra.js";
import {
  parseDesktopPayouts,
  parseDesktopResultRunners
} from "../dist-test/src/v1/three-month-desktop.js";

function arg(name, fallback = null) {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const RAW_URL = arg("--url");
const OUT = path.resolve(arg("--out", "analysis-results/recovered-result.jsonl"));
const META = path.resolve(arg("--meta", "analysis-results/recovered-result-meta.json"));
const ROUNDS = Math.max(1, Number(arg("--rounds", "6")));

if (!RAW_URL) throw new Error("--url is required");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function candidateUrls(rawUrl) {
  const u = new URL(rawUrl);
  const cname = decodeURIComponent(u.searchParams.get("CNAME") ?? "");
  if (!cname) throw new Error("CNAME_MISSING");
  const desktop = cname.replace(/^sw01/i, "pw01");
  const mobile = cname.replace(/^pw01/i, "sw01");
  const encDesktop = encodeURIComponent(desktop);
  const encMobile = encodeURIComponent(mobile);
  const slashDesktop = encDesktop.replace(/%2F/gi, "/");
  const slashMobile = encMobile.replace(/%2F/gi, "/");
  const candidates = [
    rawUrl,
    `https://www.jra.go.jp/JRADB/accessS.html?CNAME=${slashDesktop}`,
    `https://jra.jp/JRADB/accessS.html?CNAME=${encDesktop}`,
    `https://jra.jp/JRADB/accessS.html?CNAME=${slashDesktop}`,
    `https://sp.jra.jp/JRADB/accessS.html?CNAME=${encMobile}`,
    `https://sp.jra.jp/JRADB/accessS.html?CNAME=${slashMobile}`
  ];
  return [...new Set(candidates)];
}

function parseBundle(page) {
  if (!pageLooksLikeResult(page.html)) throw new Error("RESULT_SIGNATURE_MISSING");
  const parsed = parseResultPage(page.html, page.url);
  const runners = parseDesktopResultRunners(page.html).map((r) => ({ ...r, winOdds: null }));
  const payouts = parsed.payouts.length > 0 ? parsed.payouts : parseDesktopPayouts(page.html);
  if (runners.filter((r) => r.runnerStatus === "active").length < 2) throw new Error(`RUNNERS_NOT_FOUND:${runners.length}`);
  if (parsed.race.status !== "cancelled" && payouts.length === 0) throw new Error("PAYOUTS_NOT_FOUND");
  return {
    race: parsed.race,
    runners,
    results: parsed.results,
    payouts,
    refundHorseNos: parsed.refundHorseNos ?? [],
    provenance: {
      resultUrl: page.url,
      source: "jra_official_targeted_recovery",
      syntheticOddsUsed: false,
      productionDatabaseWritten: false
    }
  };
}

async function main() {
  const candidates = candidateUrls(RAW_URL);
  const errors = [];
  let recovered = null;
  let recoveredUrl = null;

  for (let round = 1; round <= ROUNDS && !recovered; round += 1) {
    for (const candidate of candidates) {
      const cacheBusted = candidate.includes("?")
        ? `${candidate}&_rt_recover=${Date.now()}_${round}`
        : candidate;
      try {
        const page = await fetchJraPage(cacheBusted);
        recovered = parseBundle(page);
        recoveredUrl = page.url;
        console.log(JSON.stringify({ recovered: true, round, candidate, finalUrl: page.url, raceId: recovered.race.raceId }));
        break;
      } catch (error) {
        const message = error instanceof Error ? `${error.name}:${error.message}` : String(error);
        errors.push({ round, candidate, error: message });
        console.log(JSON.stringify({ recovered: false, round, candidate, error: message }));
      }
      await sleep(1200 * round);
    }
    if (!recovered) await sleep(4000 * round);
  }

  await mkdir(path.dirname(OUT), { recursive: true });
  const meta = {
    requestedUrl: RAW_URL,
    recovered: Boolean(recovered),
    recoveredUrl,
    attempts: errors.length + (recovered ? 1 : 0),
    errors,
    syntheticOddsUsed: false,
    productionDatabaseWritten: false
  };
  await writeFile(META, JSON.stringify(meta, null, 2) + "\n");
  if (!recovered) {
    await writeFile(OUT, "");
    process.exitCode = 2;
    return;
  }
  await writeFile(OUT, JSON.stringify(recovered) + "\n");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
