import { saveEntryBundle, setState, upsertRaceSources } from "./db.js";
import {
  canonicalPublishedEntryUrl,
  discoverPublishedEntryAnchor,
  extractPublishedEntryCnames,
  fetchPublishedEntryByCname,
} from "./jra-entry-anchor-discovery.js";
import { parseEntryPage, toResultUrl } from "./jra.js";
import type { Env } from "./types.js";

const STATE_KEY = "worker_published_entry_maintenance";
const MAX_CNAME_PAGES = 18;
const FETCH_CONCURRENCY = 6;

type MissingGroup = {
  raceDate: string;
  venue: string;
  meetingNo: number;
  meetingDay: number;
  storedRaces: number;
  readyRaces: number;
};

export type PublishedEntryMaintenanceAudit = {
  checkedAt: string;
  status: "idle" | "ready" | "anchor_not_published" | "repaired" | "error";
  targetDate: string | null;
  targetVenue: string | null;
  missingGroups: number;
  anchorFound: boolean;
  savedRaceIds: string[];
  error: string | null;
};

function jstDate(now = new Date(), offsetDays = 0): string {
  return new Date(now.getTime() + 9 * 3600_000 + offsetDays * 86400_000).toISOString().slice(0, 10);
}

function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}:${error.message}` : String(error);
}

async function missingGroups(db: D1Database, now: Date): Promise<MissingGroup[]> {
  const today = jstDate(now);
  const maxDate = jstDate(now, 2);
  const result = await db.prepare(`
    WITH per_race AS (
      SELECT r.race_id,r.race_date,r.venue,r.meeting_no,r.meeting_day,r.race_no,
             SUM(CASE WHEN rr.race_id IS NOT NULL AND COALESCE(rr.runner_status,'active')='active' THEN 1 ELSE 0 END) AS activeRunners
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
  return (result.results ?? []).map((row) => ({
    raceDate: String(row.raceDate),
    venue: String(row.venue),
    meetingNo: Number(row.meetingNo),
    meetingDay: Number(row.meetingDay),
    storedRaces: Number(row.storedRaces),
    readyRaces: Number(row.readyRaces),
  }));
}

async function saveCname(db: D1Database, cname: string, group: MissingGroup): Promise<string | null> {
  const page = await fetchPublishedEntryByCname(cname);
  if (!page) return null;
  try {
    const canonical = canonicalPublishedEntryUrl(cname);
    const bundle = parseEntryPage(page.html, canonical);
    if (bundle.race.raceDate !== group.raceDate || bundle.race.venue !== group.venue) return null;
    const active = bundle.runners.filter((runner) => (runner.runnerStatus || "active") === "active");
    if (active.length < 3) return null;
    const exists = await db.prepare("SELECT 1 AS found FROM rt_races WHERE race_id=? LIMIT 1")
      .bind(bundle.race.raceId).first<{ found: number }>();
    if (!exists?.found) return null;
    await saveEntryBundle(db, bundle);
    await upsertRaceSources(db, [canonical], toResultUrl);
    return bundle.race.raceId;
  } catch {
    return null;
  }
}

async function expandAnchor(db: D1Database, group: MissingGroup, anchorCname: string, anchorHtml: string): Promise<string[]> {
  const all = [anchorCname, ...extractPublishedEntryCnames(anchorHtml)];
  const cnames = [...new Set(all)].slice(0, MAX_CNAME_PAGES);
  const saved = new Set<string>();
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(FETCH_CONCURRENCY, cnames.length) }, async () => {
    while (true) {
      const index = cursor++;
      if (index >= cnames.length) return;
      const raceId = await saveCname(db, cnames[index]!, group);
      if (raceId) saved.add(raceId);
    }
  }));
  return [...saved].sort();
}

export async function runPublishedEntryMaintenance(env: Env, now = new Date()): Promise<PublishedEntryMaintenanceAudit> {
  const audit: PublishedEntryMaintenanceAudit = {
    checkedAt: now.toISOString(),
    status: "idle",
    targetDate: null,
    targetVenue: null,
    missingGroups: 0,
    anchorFound: false,
    savedRaceIds: [],
    error: null,
  };
  try {
    const groups = await missingGroups(env.DB, now);
    audit.missingGroups = groups.length;
    if (!groups.length) {
      audit.status = "ready";
      await setState(env.DB, STATE_KEY, JSON.stringify(audit));
      return audit;
    }

    // Rotate incomplete venues so one unpublished/blocked venue cannot starve the others.
    const minuteSlot = Math.floor(now.getTime() / 60_000);
    const group = groups[minuteSlot % groups.length]!;
    audit.targetDate = group.raceDate;
    audit.targetVenue = group.venue;

    const anchor = await discoverPublishedEntryAnchor(group);
    if (!anchor) {
      audit.status = "anchor_not_published";
      await setState(env.DB, STATE_KEY, JSON.stringify(audit));
      return audit;
    }

    audit.anchorFound = true;
    audit.savedRaceIds = await expandAnchor(env.DB, group, anchor.cname, anchor.html);
    audit.status = audit.savedRaceIds.length ? "repaired" : "anchor_not_published";
  } catch (error) {
    audit.status = "error";
    audit.error = errorText(error);
  }
  await setState(env.DB, STATE_KEY, JSON.stringify(audit));
  return audit;
}
