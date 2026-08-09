import type { Env } from "./types.js";
import { discoverRaceUrls, toResultUrl } from "./jra.js";
import { upsertRaceSources } from "./db.js";

function configuredSeeds(env: Env): string[] {
  return env.JRA_SEED_ENTRY_URLS.split(",").map((value) => value.trim()).filter(Boolean);
}

export async function getRecentRealEntrySeeds(db: D1Database, limit = 8): Promise<string[]> {
  const rows = await db.prepare(`
    SELECT DISTINCT entry_url AS entryUrl
    FROM rt_races
    WHERE entry_url LIKE 'https://%/JRADB/accessD.html?%'
    ORDER BY race_date DESC, updated_at DESC
    LIMIT ?
  `).bind(limit).all<{ entryUrl: string }>();
  return rows.results.map((row) => row.entryUrl).filter(Boolean);
}

export async function expandRaceSourcesFromRecentPages(env: Env): Promise<{ seeds: number; discovered: number }> {
  const recent = await getRecentRealEntrySeeds(env.DB, 8);
  const seeds = [...new Set([...recent, ...configuredSeeds(env)])];
  const urls = await discoverRaceUrls(env.JRA_HOME_URL, seeds);
  if (urls.length) await upsertRaceSources(env.DB, urls, toResultUrl);
  return { seeds: seeds.length, discovered: urls.length };
}
