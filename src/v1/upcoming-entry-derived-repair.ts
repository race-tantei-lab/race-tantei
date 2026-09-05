import { saveEntryBundle, setState, upsertRaceSources } from "./db.js";
import { pageLooksLikeEntry, parseEntryPage, toResultUrl } from "./jra.js";
import type { Env } from "./types.js";

const STATE_KEY = "worker_upcoming_entry_derived_repair";
const FETCH_TIMEOUT_MS = 5_000;
const FETCH_CONCURRENCY = 4;
const MAX_GROUPS_PER_PASS = 3;
const RETRIES_PER_RACE = 2;

const VENUE_CODES: Record<string, string> = {
  札幌: "01", 函館: "02", 福島: "03", 新潟: "04", 東京: "05",
  中山: "06", 中京: "07", 京都: "08", 阪神: "09", 小倉: "10",
};
const VENUES_BY_CODE = new Map(Object.entries(VENUE_CODES).map(([venue, code]) => [code, venue]));
const KNOWN_POSITION_WEIGHTS = new Map<number, number>([
  [10, 0x4A], [16, 0x31], [18, 0x73], [19, 0x52], [20, 0xB5], [27, 0x5A], [28, 0xBD],
]);
const RACE_TENS_WEIGHT = 0x52;
const RACE_UNITS_WEIGHT = 0xB5;

type MissingGroup = { raceDate: string; venue: string; meetingNo: number; meetingDay: number; readyRaces: number };
type PriorAnchor = { raceDate: string; entryUrl: string };
type SeedMeta = PriorAnchor & { venue: string; raceNo: number };
type GroupAudit = {
  raceDate: string; venue: string; priorRaceDate: string | null; priorCname: string | null;
  derivedRace1Cname: string | null; requestedRaceNos: number[]; savedRaceIds: string[]; status: string; errors: string[];
};
type Audit = { checkedAt: string; status: string; savedRaceIds: string[]; groups: GroupAudit[]; errors: string[] };

function errorText(error: unknown): string { return error instanceof Error ? `${error.name}:${error.message}` : String(error); }
function jstDate(now = new Date(), offsetDays = 0): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000 + offsetDays * 86400_000).toISOString().slice(0, 10);
}
function jstWeekday(now = new Date()): number { return new Date(now.getTime() + 9 * 60 * 60 * 1000).getUTCDay(); }
function mod256(value: number): number { return ((value % 256) + 256) % 256; }
function suffixHex(value: number): string { return mod256(value).toString(16).toUpperCase().padStart(2, "0"); }

function extractCname(entryUrl: string): string | null {
  try {
    const cname = decodeURIComponent(new URL(entryUrl).searchParams.get("CNAME") ?? "");
    return /^pw01dde(?:01|10)[A-Za-z0-9]+\/[0-9A-Fa-f]{2}$/.test(cname) ? cname : null;
  } catch { return null; }
}

function cnameSeedMeta(entryUrl: string): SeedMeta | null {
  const cname = extractCname(entryUrl);
  if (!cname) return null;
  const prefix = cname.split("/")[0] ?? "";
  if (!/^pw01dde(?:01|10)\d{20}$/.test(prefix) || prefix.length !== 29) return null;
  const venue = VENUES_BY_CODE.get(prefix.slice(9, 11));
  const raceNo = Number(prefix.slice(19, 21));
  const compactDate = prefix.slice(21, 29);
  if (!venue || raceNo < 1 || raceNo > 12 || !/^20\d{6}$/.test(compactDate)) return null;
  return {
    raceDate: `${compactDate.slice(0, 4)}-${compactDate.slice(4, 6)}-${compactDate.slice(6, 8)}`,
    venue,
    raceNo,
    entryUrl,
  };
}

function configuredSeedAnchor(env: Env, group: MissingGroup, exactDate: boolean): PriorAnchor | null {
  const seeds = String(env.JRA_SEED_ENTRY_URLS || "")
    .split(/[\s,;]+/)
    .map((value) => value.trim())
    .filter(Boolean)
    .map(cnameSeedMeta)
    .filter((row): row is SeedMeta => Boolean(row))
    .filter((row) => row.venue === group.venue && row.raceNo === 1)
    .filter((row) => exactDate ? row.raceDate === group.raceDate : row.raceDate < group.raceDate)
    .sort((a, b) => b.raceDate.localeCompare(a.raceDate));
  const seed = seeds[0];
  return seed ? { raceDate: seed.raceDate, entryUrl: seed.entryUrl } : null;
}

function buildRace1Prefix(group: MissingGroup, modePrefix: string): string {
  if (!/^pw01dde(?:01|10)$/.test(modePrefix)) throw new Error(`INVALID_ENTRY_MODE:${modePrefix}`);
  const venueCode = VENUE_CODES[group.venue];
  if (!venueCode) throw new Error(`UNKNOWN_VENUE:${group.venue}`);
  return `${modePrefix}${venueCode}${group.raceDate.slice(0, 4)}${String(group.meetingNo).padStart(2, "0")}${String(group.meetingDay).padStart(2, "0")}01${group.raceDate.replaceAll("-", "")}`;
}

function deriveRace1Cname(priorCname: string, targetPrefix: string): string | null {
  const [priorPrefix, suffixRaw] = priorCname.split("/");
  if (!priorPrefix || !suffixRaw || priorPrefix.length !== 29 || targetPrefix.length !== 29) return null;
  const priorMode = priorPrefix.slice(0, 9);
  if (!/^pw01dde(?:01|10)$/.test(priorMode) || !targetPrefix.startsWith(priorMode)) return null;
  let suffix = Number.parseInt(suffixRaw, 16);
  if (!Number.isFinite(suffix)) return null;
  for (let index = 0; index < targetPrefix.length; index += 1) {
    const before = priorPrefix[index] ?? "", after = targetPrefix[index] ?? "";
    if (before === after) continue;
    const weight = KNOWN_POSITION_WEIGHTS.get(index);
    if (weight === undefined || !/^\d$/.test(before) || !/^\d$/.test(after)) return null;
    suffix += (Number(after) - Number(before)) * weight;
  }
  return `${targetPrefix}/${suffixHex(suffix)}`;
}

function cnameForRace(race1Cname: string, raceNo: number): string {
  if (raceNo < 1 || raceNo > 12) throw new Error(`INVALID_RACE_NO:${raceNo}`);
  const [race1Prefix, suffixRaw] = race1Cname.split("/");
  if (!race1Prefix || !suffixRaw || race1Prefix.length !== 29) throw new Error("INVALID_RACE1_CNAME");
  const suffix1 = Number.parseInt(suffixRaw, 16);
  if (!Number.isFinite(suffix1)) throw new Error("INVALID_RACE1_SUFFIX");
  const tens = Math.floor(raceNo / 10), units = raceNo % 10;
  const suffix = suffix1 + tens * RACE_TENS_WEIGHT + (units - 1) * RACE_UNITS_WEIGHT;
  const prefix = `${race1Prefix.slice(0, 19)}${String(raceNo).padStart(2, "0")}${race1Prefix.slice(21)}`;
  return `${prefix}/${suffixHex(suffix)}`;
}

function canonicalEntryUrl(cname: string): string {
  return `https://www.jra.go.jp/JRADB/accessD.html?CNAME=${encodeURIComponent(cname)}`;
}
function candidateUrls(cname: string): string[] {
  const encoded = encodeURIComponent(cname);
  return [
    `https://www.jra.go.jp/JRADB/accessD.html?CNAME=${encoded}`,
    `https://sp.jra.jp/JRADB/accessD.html?CNAME=${encoded}`,
    `https://app.jra.jp/JRADB/accessD.html?CNAME=${encoded}`,
  ];
}
function decodePage(bytes: ArrayBuffer, contentType: string | null): string {
  const declared = contentType?.match(/charset\s*=\s*([^;\s]+)/i)?.[1]?.replace(/["']/g, "") ?? null;
  const probe = new TextDecoder("windows-1252").decode(bytes.slice(0, Math.min(bytes.byteLength, 8192)));
  const meta = probe.match(/<meta[^>]+charset=["']?([^"'\s/>]+)/i)?.[1]
    ?? probe.match(/content=["'][^"']*charset=([^"';\s]+)/i)?.[1] ?? null;
  for (const charset of [declared, meta, "shift_jis", "utf-8"].filter((value): value is string => Boolean(value))) {
    try { return new TextDecoder(charset).decode(bytes); } catch { /* next */ }
  }
  return new TextDecoder("utf-8").decode(bytes);
}

async function fetchOfficialEntry(cname: string): Promise<string | null> {
  for (const rawUrl of candidateUrls(cname)) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(rawUrl, {
        redirect: "follow", signal: controller.signal,
        headers: {
          "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136 Safari/537.36",
          Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          "Accept-Language": "ja-JP,ja;q=0.9", "Cache-Control": "no-cache", Pragma: "no-cache",
          Referer: "https://www.jra.go.jp/", "Upgrade-Insecure-Requests": "1",
        },
      });
      if (!response.ok) continue;
      const bytes = await response.arrayBuffer();
      if (bytes.byteLength > 4_000_000) continue;
      const html = decodePage(bytes, response.headers.get("content-type"));
      if (/captcha|アクセスが集中|利用を制限|Access Denied|Forbidden|Service Unavailable/i.test(html)) continue;
      if (!pageLooksLikeEntry(html)) continue;
      return html;
    } catch { /* next official host */ }
    finally { clearTimeout(timer); }
  }
  return null;
}

async function missingGroups(db: D1Database, now: Date): Promise<MissingGroup[]> {
  const weekday = jstWeekday(now);
  // Friday prepares Saturday; Saturday prepares Sunday. On race day itself,
  // continue repairing the current day. This keeps the lightweight derived
  // repair focused on the next race day instead of re-scanning Saturday while
  // Sunday's cards are still empty.
  const targetDate = weekday === 5 || weekday === 6 ? jstDate(now, 1) : jstDate(now, 0);
  const result = await db.prepare(`
    WITH per_race AS (
      SELECT r.race_id,r.race_date,r.venue,r.meeting_no,r.meeting_day,r.race_no,
             SUM(CASE WHEN rr.runner_status='active' THEN 1 ELSE 0 END) AS activeRunners,
             MAX(CASE WHEN LENGTH(TRIM(COALESCE(r.entry_url,'')))>0 THEN 1 ELSE 0 END) AS hasEntryUrl
      FROM rt_races r LEFT JOIN rt_runners rr ON rr.race_id=r.race_id
      WHERE r.race_date=? GROUP BY r.race_id,r.race_date,r.venue,r.meeting_no,r.meeting_day,r.race_no
    )
    SELECT race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,
           SUM(CASE WHEN activeRunners>=3 AND hasEntryUrl=1 THEN 1 ELSE 0 END) AS readyRaces
    FROM per_race GROUP BY race_date,venue,meeting_no,meeting_day HAVING readyRaces < 12
    ORDER BY CASE venue WHEN '中京' THEN 0 WHEN '新潟' THEN 1 WHEN '札幌' THEN 2 ELSE 3 END,venue
  `).bind(targetDate).all<MissingGroup>();
  return (result.results ?? []).slice(0, MAX_GROUPS_PER_PASS).map((row) => ({
    raceDate: String(row.raceDate), venue: String(row.venue), meetingNo: Number(row.meetingNo),
    meetingDay: Number(row.meetingDay), readyRaces: Number(row.readyRaces),
  }));
}

async function missingRaceNos(db: D1Database, group: MissingGroup): Promise<number[]> {
  const result = await db.prepare(`
    SELECT r.race_no AS raceNo,
           SUM(CASE WHEN rr.runner_status='active' THEN 1 ELSE 0 END) AS activeRunners,
           MAX(CASE WHEN LENGTH(TRIM(COALESCE(r.entry_url,'')))>0 THEN 1 ELSE 0 END) AS hasEntryUrl
    FROM rt_races r LEFT JOIN rt_runners rr ON rr.race_id=r.race_id
    WHERE r.race_date=? AND r.venue=?
    GROUP BY r.race_id,r.race_no HAVING activeRunners < 3 OR hasEntryUrl=0 ORDER BY r.race_no
  `).bind(group.raceDate, group.venue).all<{ raceNo: number }>();
  return (result.results ?? []).map((row) => Number(row.raceNo)).filter((n) => n >= 1 && n <= 12);
}

async function priorAnchor(db: D1Database, group: MissingGroup): Promise<PriorAnchor | null> {
  const row = await db.prepare(`
    SELECT race_date AS raceDate,entry_url AS entryUrl FROM rt_races
    WHERE venue=? AND race_no=1 AND race_date<? AND entry_url LIKE '%/JRADB/accessD.html?CNAME=pw01dde%'
    ORDER BY race_date DESC LIMIT 1
  `).bind(group.venue, group.raceDate).first<PriorAnchor>();
  return row ? { raceDate: String(row.raceDate), entryUrl: String(row.entryUrl) } : null;
}

async function saveDerivedRace(env: Env, group: MissingGroup, raceNo: number, cname: string): Promise<string | null> {
  const html = await fetchOfficialEntry(cname);
  if (!html) return null;
  const canonical = canonicalEntryUrl(cname);
  const bundle = parseEntryPage(html, canonical);
  if (bundle.race.raceDate !== group.raceDate || bundle.race.venue !== group.venue || Number(bundle.race.raceNo) !== raceNo) return null;
  if (bundle.runners.filter((row) => row.runnerStatus === "active").length < 3) return null;
  await saveEntryBundle(env.DB, bundle);
  await env.DB.prepare("UPDATE rt_races SET entry_url=?,result_url=?,entry_updated_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE race_id=?")
    .bind(canonical, toResultUrl(canonical), bundle.race.raceId).run();
  await upsertRaceSources(env.DB, [canonical], toResultUrl);
  return bundle.race.raceId;
}

async function repairGroup(env: Env, group: MissingGroup): Promise<GroupAudit> {
  const audit: GroupAudit = {
    raceDate: group.raceDate, venue: group.venue, priorRaceDate: null, priorCname: null,
    derivedRace1Cname: null, requestedRaceNos: [], savedRaceIds: [], status: "idle", errors: [],
  };
  const exactSeed = configuredSeedAnchor(env, group, true);
  const prior = exactSeed ?? await priorAnchor(env.DB, group) ?? configuredSeedAnchor(env, group, false);
  if (!prior) { audit.status = "prior_anchor_missing"; return audit; }
  audit.priorRaceDate = prior.raceDate;
  const priorCname = extractCname(prior.entryUrl);
  audit.priorCname = priorCname;
  if (!priorCname) { audit.status = "prior_cname_invalid"; return audit; }
  const modePrefix = priorCname.slice(0, 9);
  const race1Cname = prior.raceDate === group.raceDate
    ? priorCname
    : deriveRace1Cname(priorCname, buildRace1Prefix(group, modePrefix));
  audit.derivedRace1Cname = race1Cname;
  if (!race1Cname) { audit.status = "derivation_not_safe"; return audit; }

  let pending = await missingRaceNos(env.DB, group);
  audit.requestedRaceNos = [...pending];
  const saved = new Set<string>();
  for (let attempt = 0; attempt < RETRIES_PER_RACE && pending.length; attempt += 1) {
    let cursor = 0;
    await Promise.all(Array.from({ length: Math.min(FETCH_CONCURRENCY, pending.length) }, async () => {
      while (true) {
        const index = cursor++;
        if (index >= pending.length) return;
        const raceNo = pending[index];
        try {
          const raceId = await saveDerivedRace(env, group, raceNo, cnameForRace(race1Cname, raceNo));
          if (raceId) saved.add(raceId);
        } catch (error) { audit.errors.push(`${group.venue}:${raceNo}R:${errorText(error)}`); }
      }
    }));
    pending = await missingRaceNos(env.DB, group);
  }
  audit.savedRaceIds = [...saved].sort();
  audit.status = pending.length === 0 ? "repaired" : audit.savedRaceIds.length ? "partial" : "derived_entries_unavailable";
  return audit;
}

export async function runUpcomingEntryDerivedRepair(env: Env, now = new Date()): Promise<Audit> {
  const audit: Audit = { checkedAt: now.toISOString(), status: "idle", savedRaceIds: [], groups: [], errors: [] };
  try {
    const groups = await missingGroups(env.DB, now);
    if (!groups.length) audit.status = "ready";
    else {
      for (const group of groups) {
        try { audit.groups.push(await repairGroup(env, group)); }
        catch (error) { audit.errors.push(`${group.venue}:${errorText(error)}`); }
      }
      audit.savedRaceIds = [...new Set(audit.groups.flatMap((group) => group.savedRaceIds))].sort();
      const remaining = await missingGroups(env.DB, now);
      audit.status = remaining.length === 0 ? "repaired" : audit.savedRaceIds.length ? "partial" : "derived_entries_unavailable";
    }
  } catch (error) { audit.status = "error"; audit.errors.push(errorText(error)); }
  await setState(env.DB, STATE_KEY, JSON.stringify(audit));
  return audit;
}