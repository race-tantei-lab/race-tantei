import { extractEntryLinks, fetchJraPage, pageLooksLikeEntry, parseEntryPage } from "../dist-test/src/v1/jra.js";
import { stripHtml } from "../dist-test/src/v1/utils.js";

const ACCESS_D = "https://www.jra.go.jp/JRADB/accessD.html";
const PAUSE_MS = Number(process.env.JRA_ANCHOR_PROBE_PAUSE_MS || 120);
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

function anchorPrefix(meeting, family = "pw01dde") {
  const compactDate = meeting.date.replaceAll("-", "");
  const year = meeting.date.slice(0, 4);
  return `${family}01${meeting.venueCode}${year}${String(meeting.meetingNo).padStart(2, "0")}${String(meeting.meetingDay).padStart(2, "0")}01${compactDate}`;
}

async function probeMeeting(meeting, errors) {
  for (const family of ["pw01dde", "sw01dde"]) {
    const prefix = anchorPrefix(meeting, family);
    for (let value = 0; value <= 255; value += 1) {
      const suffix = value.toString(16).toUpperCase().padStart(2, "0");
      const cname = `${prefix}/${suffix}`;
      const url = `${ACCESS_D}?CNAME=${encodeURIComponent(cname)}`;
      try {
        const page = await fetchJraPage(url);
        if (!pageLooksLikeEntry(page.html)) {
          await sleep(PAUSE_MS);
          continue;
        }
        const bundle = parseEntryPage(page.html, page.url);
        if (bundle.race.raceDate !== meeting.date || bundle.race.venue !== meeting.venue || bundle.race.raceNo !== 1) {
          await sleep(PAUSE_MS);
          continue;
        }
        return {
          found: true,
          suffix,
          family,
          prefix,
          anchorUrl: page.url,
          raceId: bundle.race.raceId,
          runnerCount: bundle.runners.length,
          discoveredLinks: extractEntryLinks(page.html, page.url),
          probes: value + 1,
        };
      } catch (error) {
        if (errors.length < 40) errors.push(`${meeting.date}:${meeting.venue}:${family}:${suffix}:${error?.name || "Error"}:${error?.message || String(error)}`);
      }
      await sleep(PAUSE_MS);
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

  for (const meeting of meetings) {
    const anchor = await probeMeeting(meeting, errors);
    if (!anchor) continue;
    return {
      ...anchor,
      targetDate: meeting.date,
      venue: meeting.venue,
      meetingNo: meeting.meetingNo,
      meetingDay: meeting.meetingDay,
      targetDates,
      calendarMeetings: meetings,
      errors,
    };
  }

  return {
    found: false,
    suffix: null,
    family: null,
    prefix: null,
    anchorUrl: null,
    raceId: null,
    runnerCount: 0,
    discoveredLinks: [],
    probes: 0,
    targetDate: null,
    venue: null,
    meetingNo: null,
    meetingDay: null,
    targetDates,
    calendarMeetings: meetings,
    errors,
  };
}
