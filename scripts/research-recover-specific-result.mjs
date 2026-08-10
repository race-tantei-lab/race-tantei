import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {
  fetchJraPage,
  pageLooksLikeResult,
  parseResultPage
} from "../dist-test/src/v1/jra.js";
import { fetchJraArchivePage } from "../dist-test/src/v1/three-month-archive.js";
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
const ROUNDS = Math.max(1, Number(arg("--rounds", "4")));

if (!RAW_URL) throw new Error("--url is required");

const raw = new URL(RAW_URL);
const CNAME = decodeURIComponent(raw.searchParams.get("CNAME") ?? "");
if (!CNAME) throw new Error("CNAME_MISSING");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function candidateUrls(rawUrl) {
  const cname = CNAME;
  const desktop = cname.replace(/^sw01/i, "pw01");
  const mobile = cname.replace(/^pw01/i, "sw01");
  const encDesktop = encodeURIComponent(desktop);
  const encMobile = encodeURIComponent(mobile);
  const slashDesktop = encDesktop.replace(/%2F/gi, "/");
  const slashMobile = encMobile.replace(/%2F/gi, "/");
  return [...new Set([
    rawUrl,
    `https://www.jra.go.jp/JRADB/accessS.html?CNAME=${slashDesktop}`,
    `https://jra.jp/JRADB/accessS.html?CNAME=${encDesktop}`,
    `https://jra.jp/JRADB/accessS.html?CNAME=${slashDesktop}`,
    `https://sp.jra.jp/JRADB/accessS.html?CNAME=${encMobile}`,
    `https://sp.jra.jp/JRADB/accessS.html?CNAME=${slashMobile}`
  ])];
}

function parseBundle(page, canonicalUrl = page.url) {
  if (!pageLooksLikeResult(page.html)) throw new Error("RESULT_SIGNATURE_MISSING");
  const parsed = parseResultPage(page.html, canonicalUrl);
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
      resultUrl: canonicalUrl,
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
  let recoveredMethod = null;

  for (let round = 1; round <= ROUNDS && !recovered; round += 1) {
    try {
      const page = await fetchJraArchivePage(CNAME);
      recovered = parseBundle({ html: page.html, url: RAW_URL }, RAW_URL);
      recoveredUrl = RAW_URL;
      recoveredMethod = "archive_post";
      console.log(JSON.stringify({ recovered: true, round, method: recoveredMethod, raceId: recovered.race.raceId }));
      break;
    } catch (error) {
      const message = error instanceof Error ? `${error.name}:${error.message}` : String(error);
      errors.push({ round, method: "archive_post", candidate: RAW_URL, error: message });
      console.log(JSON.stringify({ recovered: false, round, method: "archive_post", error: message }));
    }

    for (const candidate of candidates) {
      try {
        const page = await fetchJraPage(candidate);
        recovered = parseBundle(page, RAW_URL);
        recoveredUrl = page.url;
        recoveredMethod = "direct_get";
        console.log(JSON.stringify({ recovered: true, round, method: recoveredMethod, candidate, finalUrl: page.url, raceId: recovered.race.raceId }));
        break;
      } catch (error) {
        const message = error instanceof Error ? `${error.name}:${error.message}` : String(error);
        errors.push({ round, method: "direct_get", candidate, error: message });
        console.log(JSON.stringify({ recovered: false, round, method: "direct_get", candidate, error: message }));
      }
      await sleep(1000 * round);
    }
    if (!recovered) await sleep(3000 * round);
  }

  await mkdir(path.dirname(OUT), { recursive: true });
  const meta = {
    requestedUrl: RAW_URL,
    cname: CNAME,
    recovered: Boolean(recovered),
    recoveredUrl,
    recoveredMethod,
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
