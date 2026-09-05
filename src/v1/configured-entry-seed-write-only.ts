import { saveEntryBundle, upsertRaceSources } from "./db.js";
import { pageLooksLikeEntry, parseEntryPage, toResultUrl } from "./jra.js";
import type { Env } from "./types.js";

const FETCH_TIMEOUT_MS = 6_000;
const FETCH_CONCURRENCY = 4;
const RACE_TENS_WEIGHT = 0x52;
const RACE_UNITS_WEIGHT = 0xB5;

type Seed = { cname: string; raceDate: string; venueCode: string };
type SeedResult = { seed: string; savedRaceIds: string[]; errors: string[] };
export type ConfiguredSeedWriteAudit = {
  checkedAt: string;
  status: "ready" | "partial" | "failed";
  savedRaceIds: string[];
  seeds: SeedResult[];
};

function extractSeed(rawUrl: string): Seed | null {
  try {
    const cname = decodeURIComponent(new URL(rawUrl).searchParams.get("CNAME") ?? "");
    const match = cname.match(/^pw01dde01(\d{2})\d{4}\d{2}\d{2}01(20\d{6})\/([0-9A-Fa-f]{2})$/);
    if (!match) return null;
    const compactDate = match[2];
    return {
      cname,
      venueCode: match[1],
      raceDate: `${compactDate.slice(0, 4)}-${compactDate.slice(4, 6)}-${compactDate.slice(6, 8)}`,
    };
  } catch {
    return null;
  }
}

function configuredSeeds(env: Env, targetDate: string): Seed[] {
  return String(env.JRA_SEED_ENTRY_URLS || "")
    .split(/[\s,;]+/)
    .map((value) => value.trim())
    .filter(Boolean)
    .map(extractSeed)
    .filter((seed): seed is Seed => seed !== null && seed.raceDate === targetDate);
}

function cnameForRace(race1Cname: string, raceNo: number): string {
  const [prefix, suffixRaw] = race1Cname.split("/");
  if (!prefix || !suffixRaw || prefix.length !== 29 || raceNo < 1 || raceNo > 12) {
    throw new Error("INVALID_RACE1_CNAME");
  }
  const suffix1 = Number.parseInt(suffixRaw, 16);
  if (!Number.isFinite(suffix1)) throw new Error("INVALID_RACE1_SUFFIX");
  const tens = Math.floor(raceNo / 10);
  const units = raceNo % 10;
  const suffix = ((suffix1 + tens * RACE_TENS_WEIGHT + (units - 1) * RACE_UNITS_WEIGHT) % 256 + 256) % 256;
  const racePrefix = `${prefix.slice(0, 19)}${String(raceNo).padStart(2, "0")}${prefix.slice(21)}`;
  return `${racePrefix}/${suffix.toString(16).toUpperCase().padStart(2, "0")}`;
}

function candidateUrls(cname: string): string[] {
  const encoded = encodeURIComponent(cname);
  return [
    `https://www.jra.go.jp/JRADB/accessD.html?CNAME=${encoded}`,
    `https://sp.jra.jp/JRADB/accessD.html?CNAME=${encoded}`,
    `https://app.jra.jp/JRADB/accessD.html?CNAME=${encoded}`,
  ];
}

function decodeOfficialPage(bytes: ArrayBuffer, contentType: string | null): string {
  const declared = contentType?.match(/charset\s*=\s*([^;\s]+)/i)?.[1]?.replace(/["']/g, "") ?? null;
  const probe = new TextDecoder("windows-1252").decode(bytes.slice(0, Math.min(bytes.byteLength, 8192)));
  const meta = probe.match(/<meta[^>]+charset=["']?([^"'\s/>]+)/i)?.[1]
    ?? probe.match(/content=["'][^"']*charset=([^"';\s]+)/i)?.[1]
    ?? null;
  for (const charset of [declared, meta, "shift_jis", "utf-8"].filter((value): value is string => Boolean(value))) {
    try { return new TextDecoder(charset).decode(bytes); } catch { /* try next */ }
  }
  return new TextDecoder("utf-8").decode(bytes);
}

async function fetchOfficialEntry(cname: string): Promise<{ html: string; canonical: string } | null> {
  for (const rawUrl of candidateUrls(cname)) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(rawUrl, {
        redirect: "follow",
        signal: controller.signal,
        headers: {
          "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136 Safari/537.36",
          Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          "Accept-Language": "ja-JP,ja;q=0.9",
          Referer: "https://www.jra.go.jp/",
        },
      });
      if (!response.ok) continue;
      const bytes = await response.arrayBuffer();
      if (bytes.byteLength > 4_000_000) continue;
      const html = decodeOfficialPage(bytes, response.headers.get("content-type"));
      if (/captcha|アクセスが集中|利用を制限|Access Denied|Forbidden|Service Unavailable/i.test(html)) continue;
      if (!pageLooksLikeEntry(html)) continue;
      return {
        html,
        canonical: `https://www.jra.go.jp/JRADB/accessD.html?CNAME=${encodeURIComponent(cname)}`,
      };
    } catch {
      // try next official JRA host
    } finally {
      clearTimeout(timer);
    }
  }
  return null;
}

async function recoverSeed(env: Env, seed: Seed): Promise<SeedResult> {
  const result: SeedResult = { seed: seed.cname, savedRaceIds: [], errors: [] };
  const pending = Array.from({ length: 12 }, (_, index) => index + 1);
  let cursor = 0;
  await Promise.all(Array.from({ length: FETCH_CONCURRENCY }, async () => {
    while (true) {
      const index = cursor++;
      if (index >= pending.length) return;
      const raceNo = pending[index];
      const cname = cnameForRace(seed.cname, raceNo);
      try {
        const page = await fetchOfficialEntry(cname);
        if (!page) {
          result.errors.push(`${raceNo}R:OFFICIAL_ENTRY_UNAVAILABLE`);
          continue;
        }
        const bundle = parseEntryPage(page.html, page.canonical);
        const active = bundle.runners.filter((row) => (row.runnerStatus || "active") === "active");
        if (bundle.race.raceDate !== seed.raceDate || Number(bundle.race.raceNo) !== raceNo || active.length < 3) {
          result.errors.push(`${raceNo}R:ENTRY_VALIDATION_FAILED:${bundle.race.raceDate}:${bundle.race.raceNo}:${active.length}`);
          continue;
        }
        await saveEntryBundle(env.DB, bundle);
        await upsertRaceSources(env.DB, [page.canonical], toResultUrl);
        result.savedRaceIds.push(bundle.race.raceId);
      } catch (error) {
        result.errors.push(`${raceNo}R:${error instanceof Error ? error.message : String(error)}`);
      }
    }
  }));
  result.savedRaceIds = [...new Set(result.savedRaceIds)].sort();
  return result;
}

export async function runConfiguredEntrySeedWriteOnly(env: Env, targetDate: string): Promise<ConfiguredSeedWriteAudit> {
  const seeds = configuredSeeds(env, targetDate);
  const seedResults: SeedResult[] = [];
  for (const seed of seeds) seedResults.push(await recoverSeed(env, seed));
  const savedRaceIds = [...new Set(seedResults.flatMap((row) => row.savedRaceIds))].sort();
  const expected = seeds.length * 12;
  return {
    checkedAt: new Date().toISOString(),
    status: expected > 0 && savedRaceIds.length === expected ? "ready" : savedRaceIds.length > 0 ? "partial" : "failed",
    savedRaceIds,
    seeds: seedResults,
  };
}
