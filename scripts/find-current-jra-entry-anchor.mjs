import { extractEntryLinks, fetchJraPage, pageLooksLikeEntry, parseEntryPage } from "../dist-test/src/v1/jra.js";
import { stripHtml } from "../dist-test/src/v1/utils.js";

const ACCESS_D = "https://www.jra.go.jp/JRADB/accessD.html";
const PAUSE_MS = Number(process.env.JRA_ANCHOR_PROBE_PAUSE_MS || 120);
const PROBE_CONCURRENCY = Math.max(1, Math.min(12, Number(process.env.JRA_ANCHOR_PROBE_CONCURRENCY || 8)));
const VENUE_CODES = {
  "札幌": "01",
  "函館": "02",
  "福島": "03",
  "新潟": "04",
  "東京": "05",
  "中山": "06",
  "中京": "07",
  "京都": "08",
  "阪神": "09",
  "小倉": "10",
};
const VENUE_PATTERN = Object.keys(VENUE_CODES).join("|");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatDateUtc(ms) {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

function currentWeekendDates(now = new Date()) {
  const jst = new Date(now.getTime() + 9 * 3600_000);
  const base = Date.UTC(jst.getUTCFullYear(), jst.getUTCMonth(), jst.getUTCDate());
  const day = jst.getUTCDay();
  if (day === 0) return [formatDateUtc(base)];
  const daysToSaturday = (6 - day + 7) % 7;
  const saturday = base + daysToSaturday * 86400_000;
  return [formatDateUtc(saturday), formatDateUtc(saturday + 86400_000)];
}

function calendarUrl(date) {
  const [year, month, day] = date.split("-");
  return `https://www.jra.go.jp/keiba/calendar${year}/${year}/${Number(month)}/${month}${day}.html`;
}

async function calendarMeetings(date) {
  const page = await fetchJraPage(calendarUrl(date));
  const text = stripHtml(page.html).replace(/\s+/g, " ");
  const meetings = [];
  const seen = new Set();
  const pattern = new RegExp(`(\\d+)回(${VENUE_PATTERN})(\\d+)日`, "g");
  for (const match of text.matchAll(pattern)) {
    const meetingNo = Number(match[1]);
    const venue = match[2];
    const meetingDay = Number(match[3]);
    const venueCode = VENUE_CODES[venue];
    if (!venueCode || !meetingNo || !meetingDay) continue;
    const key = `${date}:${venue}`;
    if (seen.has(key)) continue;
    seen.add(key);
    meetings.push({ date, venue, venueCode, meetingNo, meetingDay, calendarUrl: page.url });
  }
  return meetings;
}

function anchorPrefix(meeting, family = "pw01dde", viewMode = "01") {
  const compactDate = meeting.date.replaceAll("-", "");
  const year = meeting.date.slice(0, 4);
  return `${family}${viewMode}${meeting.venueCode}${year}${String(meeting.meetingNo).padStart(2, "0")}${String(meeting.meetingDay).padStart(2, "0")}01${compactDate}`;
}

async function probeCandidate(meeting, family, viewMode, prefix, value, errors) {
  const suffix = value.toString(16).toUpperCase().padStart(2, "0");
  const cname = `${prefix}/${suffix}`;
  const url = `${ACCESS_D}?CNAME=${encodeURIComponent(cname)}`;
  try {
    const page = await fetchJraPage(url);
    if (!pageLooksLikeEntry(page.html)) return null;
    const bundle = parseEntryPage(page.html, page.url);
    if (bundle.race.raceDate !== meeting.date || bundle.race.venue !== meeting.venue || bundle.race.raceNo !== 1) return null;
    return {
      found: true,
      targetDate: meeting.date,
      venue: meeting.venue,
      meetingNo: meeting.meetingNo,
      meetingDay: meeting.meetingDay,
      suffix,
      family,
      viewMode,
      prefix,
      anchorUrl: page.url,
      raceId: bundle.race.raceId,
      runnerCount: bundle.runners.length,
      discoveredLinks: extractEntryLinks(page.html, page.url),
    };
  } catch (error) {
    if (errors.length < 80) errors.push(`${meeting.date}:${meeting.venue}:${family}:${viewMode}:${suffix}:${error?.name || "Error"}:${error?.message || String(error)}`);
    return null;
  }
}

async function probeMeeting(meeting, errors) {
  // JRA uses multiple display modes for the same race. The 01 mode is common for
  // Saturday/current-day tables, while Sunday detailed tables can be exposed as 10.
  // Try both dynamically instead of assuming the day from a hard-coded URL.
  for (const { family, viewMode } of [
    { family: "pw01dde", viewMode: "01" },
    { family: "pw01dde", viewMode: "10" },
    { family: "sw01dde", viewMode: "01" },
    { family: "sw01dde", viewMode: "10" },
  ]) {
    const prefix = anchorPrefix(meeting, family, viewMode);
    for (let start = 0; start <= 255; start += PROBE_CONCURRENCY) {
      const values = Array.from({ length: Math.min(PROBE_CONCURRENCY, 256 - start) }, (_, index) => start + index);
      const results = await Promise.all(values.map((value) => probeCandidate(meeting, family, viewMode, prefix, value, errors)));
      const found = results.find(Boolean);
      if (found) return { ...found, probes: start + values.length };
      if (PAUSE_MS > 0) await sleep(PAUSE_MS);
    }
  }
  return null;
}

export async function findCurrentEntryAnchor(now = new Date()) {
  const errors = [];
  const targetDates = currentWeekendDates(now);
  const meetings = [];
  for (const date of targetDates) {
    try {
      meetings.push(...await calendarMeetings(date));
    } catch (error) {
      errors.push(`${date}:CALENDAR:${error?.name || "Error"}:${error?.message || String(error)}`);
    }
  }

  const anchors = [];
  for (const date of targetDates) {
    const dateMeetings = meetings.filter((meeting) => meeting.date === date);
    let dateAnchor = null;
    for (const meeting of dateMeetings) {
      dateAnchor = await probeMeeting(meeting, errors);
      if (dateAnchor) break;
    }
    if (dateAnchor) anchors.push(dateAnchor);
    else errors.push(`${date}:ENTRY_ANCHOR_NOT_FOUND`);
  }

  const discoveredLinks = [...new Set(anchors.flatMap((anchor) => anchor.discoveredLinks || []))];
  const first = anchors[0] || null;
  return {
    found: anchors.length === targetDates.length && targetDates.length > 0,
    targetDates,
    calendarMeetings: meetings,
    anchors,
    anchorUrl: first?.anchorUrl ?? null,
    raceId: first?.raceId ?? null,
    targetDate: first?.targetDate ?? null,
    venue: first?.venue ?? null,
    meetingNo: first?.meetingNo ?? null,
    meetingDay: first?.meetingDay ?? null,
    family: first?.family ?? null,
    viewMode: first?.viewMode ?? null,
    prefix: first?.prefix ?? null,
    suffix: first?.suffix ?? null,
    runnerCount: first?.runnerCount ?? 0,
    probes: anchors.reduce((sum, anchor) => sum + Number(anchor.probes || 0), 0),
    discoveredLinks,
    errors,
  };
}
