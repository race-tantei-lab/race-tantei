import { extractEntryLinks, fetchJraPage, pageLooksLikeEntry, parseEntryPage } from "../dist-test/src/v1/jra.js";

const ACCESS_D = "https://www.jra.go.jp/JRADB/accessD.html";
const TARGET_DATE = process.env.JRA_TARGET_RACE_DATE || "2026-08-08";
const TARGET_VENUE = process.env.JRA_TARGET_VENUE || "札幌";
const PREFIX = process.env.JRA_ENTRY_ANCHOR_PREFIX || "pw01dde0101202601050120260808";
const PAUSE_MS = Number(process.env.JRA_ANCHOR_PROBE_PAUSE_MS || 160);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function findCurrentEntryAnchor() {
  const errors = [];
  for (let value = 0; value <= 255; value += 1) {
    const suffix = value.toString(16).toUpperCase().padStart(2, "0");
    const cname = `${PREFIX}/${suffix}`;
    const url = `${ACCESS_D}?CNAME=${encodeURIComponent(cname)}`;
    try {
      const page = await fetchJraPage(url);
      if (!pageLooksLikeEntry(page.html)) {
        await sleep(PAUSE_MS);
        continue;
      }
      const bundle = parseEntryPage(page.html, page.url);
      if (bundle.race.raceDate !== TARGET_DATE || bundle.race.venue !== TARGET_VENUE || bundle.race.raceNo !== 1) {
        await sleep(PAUSE_MS);
        continue;
      }
      const links = extractEntryLinks(page.html, page.url);
      return {
        found: true,
        suffix,
        anchorUrl: page.url,
        raceId: bundle.race.raceId,
        runnerCount: bundle.runners.length,
        discoveredLinks: links,
        probes: value + 1,
        errors,
      };
    } catch (error) {
      errors.push(`${suffix}:${error?.name || "Error"}:${error?.message || String(error)}`);
    }
    await sleep(PAUSE_MS);
  }
  return {
    found: false,
    suffix: null,
    anchorUrl: null,
    raceId: null,
    runnerCount: 0,
    discoveredLinks: [],
    probes: 256,
    errors: errors.slice(0, 30),
  };
}
