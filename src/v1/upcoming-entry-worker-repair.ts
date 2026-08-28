import { saveEntryBundle, setState, upsertRaceSources } from "./db.js";
import { pageLooksLikeEntry, parseEntryPage, toResultUrl } from "./jra.js";
import type { Env, RaceRecord } from "./types.js";

const REPAIR_STATE_KEY = "worker_upcoming_entry_repair";
const PROBE_PREFIX = "worker_upcoming_entry_probe:";
const PROBE_BATCH = 48;
const FETCH_CONCURRENCY = 8;
const FETCH_TIMEOUT_MS = 4_000;

const VENUE_CODES: Record<string, string> = {
  札幌: "01", 函館: "02", 福島: "03", 新潟: "04", 東京: "05",
  中山: "06", 中京: "07", 京都: "08", 阪神: "09", 小倉: "10",
};

const PROBE_MODES = [
  { family: "sw01dde", viewMode: "01" },
  { family: "pw01dde", viewMode: "01" },
  { family: "sw01dde", viewMode: "10" },
  { family: "pw01dde", viewMode: "10" },
] as const;

type MissingGroup = {
  raceDate: string;
  venue: string;
  meetingNo: number;
  meetingDay: number;
  storedRaces: number;
  readyRaces: number;
};

type ProbeState = { modeIndex: number; cursor: number };
type EntryFetch = { html: string; sourceUrl: string };
type Anchor = { cname: string; html: string; probed: number };

type RepairAudit = {
  checkedAt: string;
  status: string;
  targetDate: string | null;
  targetVenue: string | null;
  probed: number;
  anchorFound: boolean;
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

function canonicalEntryUrl(cname: string): string {
  return `https://www.jra.go.jp/JRADB/accessD.html?CNAME=${encodeURIComponent(cname)}`;
}

function cnameFromEntryUrl(entryUrl: string): string | null {
  try {
    const raw = new URL(entryUrl).searchParams.get("CNAME") ?? "";
    const value = decodeURIComponent(raw);
    return /^(?:pw|sw)01dde[A-Za-z0-9]+\/[0-9A-Fa-f]{2}$/.test(value) ? value : null;
  } catch {
    return null;
  }
}

function officialCandidateUrls(cname: string): string[] {
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
    try { return new TextDecoder(charset).decode(bytes); } catch { /* continue */ }
  }
  return new TextDecoder("utf-8").decode(bytes);
}

async function fetchOfficialEntry(cname: string): Promise<EntryFetch | null> {
  const errors: string[] = [];
  for (const url of officialCandidateUrls(cname)) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
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
      if (!response.ok) {
        errors.push(`${new URL(url).hostname}:HTTP_${response.status}`);
        continue;
      }
      const bytes = await response.arrayBuffer();
      if (bytes.byteLength > 4_000_000) throw new Error("ENTRY_BODY_TOO_LARGE");
      const html = decodeOfficialPage(bytes, response.headers.get("content-type"));
      if (/captcha|アクセスが集中|利用を制限|Access Denied|Forbidden|Service Unavailable/i.test(html)) {
        errors.push(`${new URL(url).hostname}:BLOCKED_PAGE`);
        continue;
      }
      if (!pageLooksLikeEntry(html)) continue;
      return { html, sourceUrl: response.url || url };
    } catch (error) {
      errors.push(`${new URL(url).hostname}:${errorText(error)}`);
    } finally {
      clearTimeout(timer);
    }
  }
  return null;
}

function cnameCandidates(html: string): string[] {
  const normalized = html
    .replace(/&amp;/gi, "&")
    .replace(/\\u0026/gi, "&")
    .replace(/\\\//g, "/");
  const found = new Set<string>();
  for (const match of normalized.matchAll(/((?:pw|sw)01dde[A-Za-z0-9%/]+)/gi)) {
    let value = String(match[1] ?? "").replace(/["'<>\s].*$/, "");
    try { value = decodeURIComponent(value); } catch { /* keep raw */ }
    if (/(?:pw|sw)01dde/i.test(value)) found.add(value);
  }
  return [...found];
}

function cnamePrefix(group: MissingGroup, raceNo: number, mode: typeof PROBE_MODES[number]): string {
  const venueCode = VENUE_CODES[group.venue];
  if (!venueCode) throw new Error(`UNKNOWN_VENUE:${group.venue}`);
  const year = group.raceDate.slice(0, 4);
  const date = group.raceDate.replaceAll("-", "");
  return `${mode.family}${mode.viewMode}${venueCode}${year}${String(group.meetingNo).padStart(2, "0")}${String(group.meetingDay).padStart(2, "0")}${String(raceNo).padStart(2, "0")}${date}`;
}

async function missingGroups(db: D1Database, now: Date): Promise<MissingGroup[]> {
  const today = jstDate(now);
  const maxDate = jstDate(now, 2);
  const result = await db.prepare(`
    WITH per_race AS (
      SELECT r.race_id,r.race_date,r.venue,r.meeting_no,r.meeting_day,r.race_no,
             SUM(CASE WHEN COALESCE(rr.runner_status,'active')='active' THEN 1 ELSE 0 END) AS activeRunners
      FROM rt_races r
      LEFT JOIN rt_runners rr ON rr.race_id=r.race_id
      WHERE r.race_date>=? AND r.race_date<=?
      GROUP BY r.race_id,r.race_date,r.venue,r.meeting_no,r.meeting_day,r.race_no
    )
    SELECT race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,
           COUNT(*) AS storedRaces,
           SUM(CASE WHEN activeRunners>=3 THEN 1 ELSE 0 END) AS readyRaces
    FROM per_race
    GROUP BY race_date,venue,meeting_no,meeting_day
    HAVING readyRaces < storedRaces
    ORDER BY race_date,venue
  `).bind(today, maxDate).all<MissingGroup>();

  const day = jstWeekday(now);
  const tomorrow = jstDate(now, 1);
  const rows = (result.results ?? []).map((row) => ({
    ...row,
    meetingNo: Number(row.meetingNo),
    meetingDay: Number(row.meetingDay),
    storedRaces: Number(row.storedRaces),
    readyRaces: Number(row.readyRaces),
  }));
  // Friday must finish Saturday first. Saturday must finish the current day before Sunday.
  if (day === 5) return rows.filter((row) => row.raceDate === tomorrow);
  if (day === 6 || day === 0) return rows.sort((a, b) => a.raceDate.localeCompare(b.raceDate));
  return rows;
}

async function existingOfficialAnchor(db: D1Database, group: MissingGroup): Promise<Anchor | null> {
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId,r.race_no AS raceNo,r.entry_url AS entryUrl,
           SUM(CASE WHEN COALESCE(rr.runner_status,'active')='active' THEN 1 ELSE 0 END) AS activeRunners
    FROM rt_races r
    LEFT JOIN rt_runners rr ON rr.race_id=r.race_id
    WHERE r.race_date=? AND r.venue=? AND LENGTH(TRIM(COALESCE(r.entry_url,'')))>0
    GROUP BY r.race_id,r.race_no,r.entry_url
    HAVING activeRunners>=3
    ORDER BY r.race_no
    LIMIT 4
  `).bind(group.raceDate, group.venue).all<{ raceId: string; raceNo: number; entryUrl: string; activeRunners: number }>();

  for (const row of rows.results ?? []) {
    const cname = cnameFromEntryUrl(String(row.entryUrl ?? ""));
    if (!cname) continue;
    const page = await fetchOfficialEntry(cname);
    if (!page) continue;
    try {
      const bundle = parseEntryPage(page.html, canonicalEntryUrl(cname));
      const active = bundle.runners.filter((runner) => (runner.runnerStatus || "active") === "active");
      if (bundle.race.raceDate === group.raceDate && bundle.race.venue === group.venue && active.length >= 3) {
        return { cname, html: page.html, probed: 0 };
      }
    } catch { /* stale/invalid stored URL; try another stored entry */ }
  }
  return null;
}

async function loadProbeState(db: D1Database, group: MissingGroup): Promise<ProbeState> {
  const key = `${PROBE_PREFIX}${group.raceDate}:${group.venue}`;
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(key).first<{ value: string }>();
  if (!row?.value) return { modeIndex: 0, cursor: 0 };
  try {
    const parsed = JSON.parse(row.value) as ProbeState;
    return {
      modeIndex: Math.max(0, Math.min(PROBE_MODES.length - 1, Number(parsed.modeIndex) || 0)),
      cursor: Math.max(0, Math.min(255, Number(parsed.cursor) || 0)),
    };
  } catch {
    return { modeIndex: 0, cursor: 0 };
  }
}

async function saveProbeState(db: D1Database, group: MissingGroup, state: ProbeState): Promise<void> {
  await setState(db, `${PROBE_PREFIX}${group.raceDate}:${group.venue}`, JSON.stringify(state));
}

async function probeAnchor(db: D1Database, group: MissingGroup): Promise<Anchor | null> {
  const state = await loadProbeState(db, group);
  const mode = PROBE_MODES[state.modeIndex];
  if (!mode) return null;
  const values = Array.from({ length: Math.min(PROBE_BATCH, 256 - state.cursor) }, (_, index) => state.cursor + index);
  const prefix = cnamePrefix(group, 1, mode);
  let nextIndex = 0;
  let found: { cname: string; html: string } | null = null;

  await Promise.all(Array.from({ length: Math.min(FETCH_CONCURRENCY, values.length) }, async () => {
    while (!found) {
      const index = nextIndex++;
      if (index >= values.length) return;
      const suffix = values[index].toString(16).toUpperCase().padStart(2, "0");
      const cname = `${prefix}/${suffix}`;
      const page = await fetchOfficialEntry(cname);
      if (!page || found) continue;
      try {
        const bundle = parseEntryPage(page.html, canonicalEntryUrl(cname));
        if (
          bundle.race.raceDate === group.raceDate
          && bundle.race.venue === group.venue
          && Number(bundle.race.raceNo) === 1
          && bundle.runners.filter((row) => (row.runnerStatus || "active") === "active").length >= 3
        ) {
          found = { cname, html: page.html };
          return;
        }
      } catch { /* not this suffix */ }
    }
  }));

  if (found) {
    await saveProbeState(db, group, { modeIndex: state.modeIndex, cursor: 0 });
    return { ...found, probed: values.length };
  }

  const cursor = state.cursor + values.length;
  if (cursor >= 256) {
    await saveProbeState(db, group, { modeIndex: (state.modeIndex + 1) % PROBE_MODES.length, cursor: 0 });
  } else {
    await saveProbeState(db, group, { modeIndex: state.modeIndex, cursor });
  }
  return null;
}

async function saveCname(db: D1Database, cname: string, expectedDates: Set<string>): Promise<string | null> {
  const page = await fetchOfficialEntry(cname);
  if (!page) return null;
  const canonical = canonicalEntryUrl(cname);
  const bundle = parseEntryPage(page.html, canonical);
  if (!expectedDates.has(bundle.race.raceDate)) return null;
  const active = bundle.runners.filter((row) => (row.runnerStatus || "active") === "active");
  if (active.length < 3) return null;
  const exists = await db.prepare("SELECT 1 AS found FROM rt_races WHERE race_id=? LIMIT 1")
    .bind(bundle.race.raceId).first<{ found: number }>();
  if (!exists?.found) return null;
  await saveEntryBundle(db, bundle);
  await upsertRaceSources(db, [canonical], toResultUrl);
  return bundle.race.raceId;
}

async function expandAndSave(db: D1Database, anchorCname: string, anchorHtml: string, now: Date): Promise<string[]> {
  const expectedDates = new Set([jstDate(now), jstDate(now, 1), jstDate(now, 2)]);
  const cnames = new Set<string>([anchorCname, ...cnameCandidates(anchorHtml)]);
  const saved = new Set<string>();
  let queue = [...cnames];
  let cursor = 0;

  // The entry page normally contains the 12 race links and venue/date navigation.
  // Crawl a bounded number of official entry pages so one anchor can populate the full weekend program.
  while (cursor < queue.length && cursor < 84) {
    const batch = queue.slice(cursor, cursor + FETCH_CONCURRENCY);
    cursor += batch.length;
    await Promise.all(batch.map(async (cname) => {
      try {
        const page = await fetchOfficialEntry(cname);
        if (!page) return;
        for (const child of cnameCandidates(page.html)) {
          if (!cnames.has(child)) { cnames.add(child); queue.push(child); }
        }
        const canonical = canonicalEntryUrl(cname);
        const bundle = parseEntryPage(page.html, canonical);
        if (!expectedDates.has(bundle.race.raceDate)) return;
        const active = bundle.runners.filter((row) => (row.runnerStatus || "active") === "active");
        if (active.length < 3) return;
        const exists = await db.prepare("SELECT 1 AS found FROM rt_races WHERE race_id=? LIMIT 1")
          .bind(bundle.race.raceId).first<{ found: number }>();
        if (!exists?.found) return;
        await saveEntryBundle(db, bundle);
        await upsertRaceSources(db, [canonical], toResultUrl);
        saved.add(bundle.race.raceId);
      } catch { /* continue other official links */ }
    }));
  }
  return [...saved].sort();
}

export async function runUpcomingEntryWorkerRepair(env: Env, now = new Date()): Promise<RepairAudit> {
  const audit: RepairAudit = {
    checkedAt: now.toISOString(), status: "idle", targetDate: null, targetVenue: null,
    probed: 0, anchorFound: false, savedRaceIds: [], errors: [],
  };
  try {
    const groups = await missingGroups(env.DB, now);
    if (!groups.length) {
      audit.status = "ready";
      await setState(env.DB, REPAIR_STATE_KEY, JSON.stringify(audit));
      return audit;
    }
    const group = groups[0];
    audit.targetDate = group.raceDate;
    audit.targetVenue = group.venue;

    // Reuse a verified official page already stored for the same venue/day first.
    // This is deterministic and lets us follow JRA's own page links instead of
    // brute-forcing race 1 again when race 7/8/etc. is already known.
    let anchor = await existingOfficialAnchor(env.DB, group);
    if (!anchor) anchor = await probeAnchor(env.DB, group);
    audit.probed = anchor?.probed ?? PROBE_BATCH;
    if (!anchor) {
      audit.status = "probing";
      await setState(env.DB, REPAIR_STATE_KEY, JSON.stringify(audit));
      return audit;
    }
    audit.anchorFound = true;
    audit.savedRaceIds = await expandAndSave(env.DB, anchor.cname, anchor.html, now);
    audit.status = audit.savedRaceIds.length ? "repaired" : "anchor_without_saved_entries";
  } catch (error) {
    audit.status = "error";
    audit.errors.push(errorText(error));
  }
  await setState(env.DB, REPAIR_STATE_KEY, JSON.stringify(audit));
  return audit;
}
