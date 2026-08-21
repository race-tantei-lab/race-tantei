import { saveEntryBundle, setState, upsertRaceSources } from "./db.js";
import { pageLooksLikeEntry, parseEntryPage, toResultUrl } from "./jra.js";
import type { Env } from "./types.js";

const STATE_KEY = "worker_upcoming_entry_derived_repair";
const FETCH_TIMEOUT_MS = 5_000;
const FETCH_CONCURRENCY = 4;

const VENUE_CODES: Record<string, string> = {
  札幌: "01", 函館: "02", 福島: "03", 新潟: "04", 東京: "05",
  中山: "06", 中京: "07", 京都: "08", 阪神: "09", 小倉: "10",
};

// JRA accessD CNAME checksum deltas inferred from multiple known official
// race URLs. We only use derivation when every changed character belongs to a
// position whose weight is known; otherwise we fail closed and leave the older
// bounded probe repair as the fallback.
const KNOWN_POSITION_WEIGHTS = new Map<number, number>([
  [10, 0x4A], // venue code units
  [16, 0x31], // meeting number units
  [18, 0x73], // meeting day units
  [19, 0x52], // race number tens
  [20, 0xB5], // race number units
  [27, 0x5A], // calendar day tens
  [28, 0xBD], // calendar day units
]);

const RACE_TENS_WEIGHT = 0x52;
const RACE_UNITS_WEIGHT = 0xB5;

type MissingGroup = {
  raceDate: string;
  venue: string;
  meetingNo: number;
  meetingDay: number;
  readyRaces: number;
};

type PriorAnchor = {
  raceDate: string;
  entryUrl: string;
};

type Audit = {
  checkedAt: string;
  status: string;
  raceDate: string | null;
  venue: string | null;
  priorRaceDate: string | null;
  priorCname: string | null;
  derivedRace1Cname: string | null;
  savedRaceIds: string[];
  errors: string[];
};

function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}:${error.message}` : String(error);
}

function jstDate(now = new Date(), offsetDays = 0): string {
  const jst = new Date(now.getTime() + 9 * 60 * 60 * 1000 + offsetDays * 24 * 60 * 60 * 1000);
  return jst.toISOString().slice(0, 10);
}

function jstWeekday(now = new Date()): number {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).getUTCDay();
}

function mod256(value: number): number {
  return ((value % 256) + 256) % 256;
}

function suffixHex(value: number): string {
  return mod256(value).toString(16).toUpperCase().padStart(2, "0");
}

function extractCname(entryUrl: string): string | null {
  try {
    const url = new URL(entryUrl);
    const cname = decodeURIComponent(url.searchParams.get("CNAME") ?? "");
    return /^pw01dde01[A-Za-z0-9]+\/[0-9A-Fa-f]{2}$/.test(cname) ? cname : null;
  } catch {
    return null;
  }
}

function buildRace1Prefix(group: MissingGroup): string {
  const venueCode = VENUE_CODES[group.venue];
  if (!venueCode) throw new Error(`UNKNOWN_VENUE:${group.venue}`);
  const year = group.raceDate.slice(0, 4);
  const compactDate = group.raceDate.replaceAll("-", "");
  return `pw01dde01${venueCode}${year}${String(group.meetingNo).padStart(2, "0")}${String(group.meetingDay).padStart(2, "0")}01${compactDate}`;
}

function deriveRace1Cname(priorCname: string, targetPrefix: string): string | null {
  const [priorPrefix, suffixRaw] = priorCname.split("/");
  if (!priorPrefix || !suffixRaw || priorPrefix.length !== 29 || targetPrefix.length !== 29) return null;
  if (!/^pw01dde01/.test(priorPrefix) || !/^pw01dde01/.test(targetPrefix)) return null;
  let suffix = Number.parseInt(suffixRaw, 16);
  if (!Number.isFinite(suffix)) return null;

  for (let index = 0; index < targetPrefix.length; index += 1) {
    const before = priorPrefix[index] ?? "";
    const after = targetPrefix[index] ?? "";
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
  const tens = Math.floor(raceNo / 10);
  const units = raceNo % 10;
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
    ?? probe.match(/content=["'][^"']*charset=([^"';\s]+)/i)?.[1]
    ?? null;
  for (const charset of [declared, meta, "shift_jis", "utf-8"].filter((value): value is string => Boolean(value))) {
    try { return new TextDecoder(charset).decode(bytes); } catch { /* continue */ }
  }
  return new TextDecoder("utf-8").decode(bytes);
}

async function fetchOfficialEntry(cname: string): Promise<string | null> {
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
          "Cache-Control": "no-cache",
          Pragma: "no-cache",
          Referer: "https://www.jra.go.jp/",
          "Upgrade-Insecure-Requests": "1",
        },
      });
      if (!response.ok) continue;
      const bytes = await response.arrayBuffer();
      if (bytes.byteLength > 4_000_000) continue;
      const html = decodePage(bytes, response.headers.get("content-type"));
      if (/captcha|アクセスが集中|利用を制限|Access Denied|Forbidden|Service Unavailable/i.test(html)) continue;
      if (!pageLooksLikeEntry(html)) continue;
      return html;
    } catch {
      // Try the next official JRA host.
    } finally {
      clearTimeout(timer);
    }
  }
  return null;
}

async function firstMissingGroup(db: D1Database, now: Date): Promise<MissingGroup | null> {
  const day = jstWeekday(now);
  const targetDate = day === 5 ? jstDate(now, 1) : jstDate(now, 0);
  const result = await db.prepare(`
    WITH per_race AS (
      SELECT r.race_id,r.race_date,r.venue,r.meeting_no,r.meeting_day,r.race_no,
             SUM(CASE WHEN rr.runner_status='active' THEN 1 ELSE 0 END) AS activeRunners
      FROM rt_races r
      LEFT JOIN rt_runners rr ON rr.race_id=r.race_id
      WHERE r.race_date=?
      GROUP BY r.race_id,r.race_date,r.venue,r.meeting_no,r.meeting_day,r.race_no
    )
    SELECT race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,
           SUM(CASE WHEN activeRunners>=3 THEN 1 ELSE 0 END) AS readyRaces
    FROM per_race
    GROUP BY race_date,venue,meeting_no,meeting_day
    HAVING readyRaces < 12
    ORDER BY CASE venue WHEN '中京' THEN 0 WHEN '新潟' THEN 1 WHEN '札幌' THEN 2 ELSE 3 END,venue
    LIMIT 1
  `).bind(targetDate).first<MissingGroup>();
  return result ? {
    raceDate: String(result.raceDate),
    venue: String(result.venue),
    meetingNo: Number(result.meetingNo),
    meetingDay: Number(result.meetingDay),
    readyRaces: Number(result.readyRaces),
  } : null;
}

async function priorAnchor(db: D1Database, group: MissingGroup): Promise<PriorAnchor | null> {
  const row = await db.prepare(`
    SELECT race_date AS raceDate,entry_url AS entryUrl
    FROM rt_races
    WHERE venue=? AND race_no=1 AND race_date<?
      AND entry_url LIKE '%/JRADB/accessD.html?CNAME=pw01dde01%'
    ORDER BY race_date DESC
    LIMIT 1
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
  await upsertRaceSources(env.DB, [canonical], toResultUrl);
  return bundle.race.raceId;
}

export async function runUpcomingEntryDerivedRepair(env: Env, now = new Date()): Promise<Audit> {
  const audit: Audit = {
    checkedAt: now.toISOString(), status: "idle", raceDate: null, venue: null,
    priorRaceDate: null, priorCname: null, derivedRace1Cname: null, savedRaceIds: [], errors: [],
  };
  try {
    const group = await firstMissingGroup(env.DB, now);
    if (!group) {
      audit.status = "ready";
      await setState(env.DB, STATE_KEY, JSON.stringify(audit));
      return audit;
    }
    audit.raceDate = group.raceDate;
    audit.venue = group.venue;
    const prior = await priorAnchor(env.DB, group);
    if (!prior) {
      audit.status = "prior_anchor_missing";
      await setState(env.DB, STATE_KEY, JSON.stringify(audit));
      return audit;
    }
    audit.priorRaceDate = prior.raceDate;
    const priorCname = extractCname(prior.entryUrl);
    audit.priorCname = priorCname;
    if (!priorCname) {
      audit.status = "prior_cname_invalid";
      await setState(env.DB, STATE_KEY, JSON.stringify(audit));
      return audit;
    }
    const race1Cname = deriveRace1Cname(priorCname, buildRace1Prefix(group));
    audit.derivedRace1Cname = race1Cname;
    if (!race1Cname) {
      audit.status = "derivation_not_safe";
      await setState(env.DB, STATE_KEY, JSON.stringify(audit));
      return audit;
    }

    const raceNos = Array.from({ length: 12 }, (_, index) => index + 1);
    let cursor = 0;
    const saved = new Set<string>();
    await Promise.all(Array.from({ length: FETCH_CONCURRENCY }, async () => {
      while (true) {
        const index = cursor++;
        if (index >= raceNos.length) return;
        const raceNo = raceNos[index];
        const cname = cnameForRace(race1Cname, raceNo);
        try {
          const raceId = await saveDerivedRace(env, group, raceNo, cname);
          if (raceId) saved.add(raceId);
        } catch (error) {
          audit.errors.push(`${group.venue}:${raceNo}R:${errorText(error)}`);
        }
      }
    }));
    audit.savedRaceIds = [...saved].sort();
    audit.status = audit.savedRaceIds.length === 12 ? "repaired" : audit.savedRaceIds.length ? "partial" : "derived_entries_unavailable";
  } catch (error) {
    audit.status = "error";
    audit.errors.push(errorText(error));
  }
  await setState(env.DB, STATE_KEY, JSON.stringify(audit));
  return audit;
}
