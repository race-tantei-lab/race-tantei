import { pageLooksLikeEntry, parseEntryPage } from "../dist-test/src/v1/jra.js";
import { stripHtml } from "../dist-test/src/v1/utils.js";

const WWW_ACCESS_D = "https://www.jra.go.jp/JRADB/accessD.html";
const APP_ACCESS_D = "https://app.jra.jp/JRADB/accessD.html";
const PAUSE_MS = Number(process.env.JRA_ANCHOR_PROBE_PAUSE_MS || 80);
const PROBE_CONCURRENCY = Math.max(4, Math.min(24, Number(process.env.JRA_ANCHOR_PROBE_CONCURRENCY || 16)));
const VENUE_CODES = {
  "札幌": "01", "函館": "02", "福島": "03", "新潟": "04", "東京": "05",
  "中山": "06", "中京": "07", "京都": "08", "阪神": "09", "小倉": "10",
};
const VENUE_PATTERN = Object.keys(VENUE_CODES).join("|");

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
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
function datesRequiringProbe(targetDates, now = new Date()) {
  const jst = new Date(now.getTime() + 9 * 3600_000);
  const day = jst.getUTCDay();
  if (day === 5) return targetDates.slice(0, 1); // Friday: Saturday entries are mandatory now.
  if (day === 6 || day === 0) return targetDates; // Saturday/Sunday: all remaining race days are mandatory.
  return targetDates.slice(0, 1); // Thursday discovery: prioritize the first race day.
}
function calendarUrl(date) {
  const [year, month, day] = date.split("-");
  return `https://www.jra.go.jp/keiba/calendar${year}/${year}/${Number(month)}/${month}${day}.html`;
}
function decodePage(buffer, contentType) {
  const declared = contentType?.match(/charset\s*=\s*([^;\s]+)/i)?.[1]?.replace(/["']/g, "") || null;
  for (const charset of [declared, "utf-8", "shift_jis"].filter(Boolean)) {
    try { return new TextDecoder(charset).decode(buffer); } catch { /* try next */ }
  }
  return new TextDecoder("utf-8").decode(buffer);
}
async function fetchOfficial(rawUrl) {
  const url = new URL(rawUrl);
  if (url.protocol !== "https:" || !["www.jra.go.jp", "jra.jp", "sp.jra.jp", "app.jra.jp"].includes(url.hostname)) throw new Error(`JRA_URL_NOT_ALLOWED:${rawUrl}`);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20_000);
  try {
    const response = await fetch(url, {
      redirect: "follow", signal: controller.signal,
      headers: {
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5", "Cache-Control": "no-cache", Pragma: "no-cache",
        Referer: "https://www.jra.go.jp/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
      },
    });
    if (!response.ok) throw new Error(`HTTP_${response.status}`);
    const html = decodePage(await response.arrayBuffer(), response.headers.get("content-type"));
    if (/captcha|アクセスが集中|利用を制限|Forbidden|Access Denied|Service Unavailable/i.test(html)) throw new Error("BLOCKED_PAGE");
    return { html, url: response.url || rawUrl };
  } finally { clearTimeout(timer); }
}
async function calendarMeetings(date) {
  const page = await fetchOfficial(calendarUrl(date));
  const text = stripHtml(page.html).replace(/\s+/g, " ");
  const meetings = [], seen = new Set();
  const pattern = new RegExp(`(\\d+)回(${VENUE_PATTERN})(\\d+)日`, "g");
  for (const match of text.matchAll(pattern)) {
    const meetingNo = Number(match[1]), venue = match[2], meetingDay = Number(match[3]), venueCode = VENUE_CODES[venue];
    if (!venueCode || !meetingNo || !meetingDay) continue;
    const key = `${date}:${venue}`; if (seen.has(key)) continue; seen.add(key);
    meetings.push({ date, venue, venueCode, meetingNo, meetingDay, calendarUrl: page.url });
  }
  return meetings;
}
function canonicalWwwUrl(cname) { return `${WWW_ACCESS_D}?CNAME=${encodeURIComponent(cname)}`; }
function appUrl(cname) { return `${APP_ACCESS_D}?CNAME=${encodeURIComponent(cname)}`; }
function cnameCandidates(html) {
  const decoded = html.replace(/&amp;/gi, "&").replace(/\\u0026/gi, "&").replace(/\\\//g, "/");
  const found = new Set();
  for (const match of decoded.matchAll(/((?:pw|sw)01(?:dde|ddd)[A-Za-z0-9/]+)/gi)) {
    const cname = String(match[1] || "").replace(/["'<>\s].*$/, ""); if (cname) found.add(cname);
  }
  return [...found];
}
function cnameRaceDate(cname) { return [...String(cname).matchAll(/(20\d{6})/g)].map((m) => m[1]).at(-1) || ""; }
function linksFromEntryHtml(html) { return cnameCandidates(html).filter((cname) => /(?:pw|sw)01dde/i.test(cname)).map(canonicalWwwUrl); }
async function validateCname(cname, meeting = null) {
  const canonicalUrl = canonicalWwwUrl(cname);
  const page = await fetchOfficial(appUrl(cname));
  if (!pageLooksLikeEntry(page.html)) return null;
  const bundle = parseEntryPage(page.html, canonicalUrl);
  if (meeting && (bundle.race.raceDate !== meeting.date || bundle.race.venue !== meeting.venue)) return null;
  return {
    found: true, targetDate: bundle.race.raceDate, venue: bundle.race.venue,
    meetingNo: bundle.race.meetingNo, meetingDay: bundle.race.meetingDay,
    suffix: String(cname).split("/").at(-1) || null, family: String(cname).slice(0, 7), viewMode: String(cname).slice(7, 9),
    prefix: String(cname).split("/")[0], anchorUrl: canonicalUrl, raceId: bundle.race.raceId,
    runnerCount: bundle.runners.length, discoveredLinks: linksFromEntryHtml(page.html), discoveryMode: "app-link",
  };
}
async function discoverPublishedAnchors(targetDates, errors) {
  const cnames = new Set();
  for (const url of [APP_ACCESS_D, "https://app.jra.jp/", WWW_ACCESS_D, "https://www.jra.go.jp/"]) {
    try { const page = await fetchOfficial(url); for (const cname of cnameCandidates(page.html)) cnames.add(cname); }
    catch (error) { if (errors.length < 80) errors.push(`LANDING:${url}:${error?.name || "Error"}:${error?.message || String(error)}`); }
  }
  const anchors = [];
  for (const date of targetDates) {
    const compact = date.replaceAll("-", "");
    for (const cname of [...cnames].filter((value) => cnameRaceDate(value) === compact)) {
      try { const found = await validateCname(cname); if (found?.targetDate === date) { anchors.push(found); break; } }
      catch (error) { if (errors.length < 80) errors.push(`${date}:LANDING_CNAME:${error?.name || "Error"}:${error?.message || String(error)}`); }
    }
  }
  return anchors;
}
function anchorPrefix(meeting, family = "sw01dde", viewMode = "01") {
  const compactDate = meeting.date.replaceAll("-", ""), year = meeting.date.slice(0, 4);
  return `${family}${viewMode}${meeting.venueCode}${year}${String(meeting.meetingNo).padStart(2, "0")}${String(meeting.meetingDay).padStart(2, "0")}01${compactDate}`;
}
async function probeMeeting(meeting, errors) {
  for (const { family, viewMode } of [
    { family: "sw01dde", viewMode: "01" }, { family: "sw01dde", viewMode: "10" },
    { family: "pw01dde", viewMode: "01" }, { family: "pw01dde", viewMode: "10" },
  ]) {
    const prefix = anchorPrefix(meeting, family, viewMode);
    for (let start = 0; start <= 255; start += PROBE_CONCURRENCY) {
      const values = Array.from({ length: Math.min(PROBE_CONCURRENCY, 256 - start) }, (_, index) => start + index);
      const results = await Promise.all(values.map(async (value) => {
        const suffix = value.toString(16).toUpperCase().padStart(2, "0"), cname = `${prefix}/${suffix}`;
        try {
          const result = await validateCname(cname, meeting);
          if (!result || result.raceId.split("-").at(-1) !== "01") return null;
          return { ...result, suffix, family, viewMode, prefix, probes: start + values.length, discoveryMode: "app-probe" };
        } catch (error) {
          if (errors.length < 80) errors.push(`${meeting.date}:${meeting.venue}:${family}:${viewMode}:${suffix}:${error?.name || "Error"}:${error?.message || String(error)}`);
          return null;
        }
      }));
      const found = results.find(Boolean); if (found) return found; if (PAUSE_MS > 0) await sleep(PAUSE_MS);
    }
  }
  return null;
}
export async function findCurrentEntryAnchor(now = new Date()) {
  const errors = [], targetDates = currentWeekendDates(now), meetings = [];
  for (const date of targetDates) {
    try { meetings.push(...await calendarMeetings(date)); }
    catch (error) { errors.push(`${date}:CALENDAR:${error?.name || "Error"}:${error?.message || String(error)}`); }
  }
  const anchors = await discoverPublishedAnchors(targetDates, errors), foundDates = new Set(anchors.map((row) => row.targetDate));
  const probeDates = new Set(datesRequiringProbe(targetDates, now));
  for (const date of targetDates) {
    if (foundDates.has(date) || !probeDates.has(date)) continue;
    let dateAnchor = null;
    for (const meeting of meetings.filter((row) => row.date === date)) { dateAnchor = await probeMeeting(meeting, errors); if (dateAnchor) break; }
    if (dateAnchor) { anchors.push(dateAnchor); foundDates.add(date); } else errors.push(`${date}:ENTRY_ANCHOR_NOT_FOUND`);
  }
  const discoveredLinks = [...new Set(anchors.flatMap((anchor) => anchor.discoveredLinks || []))], first = anchors[0] || null;
  return {
    found: [...probeDates].every((date) => foundDates.has(date)) && probeDates.size > 0,
    targetDates, requiredProbeDates: [...probeDates], calendarMeetings: meetings, anchors,
    anchorUrl: first?.anchorUrl ?? null, raceId: first?.raceId ?? null, targetDate: first?.targetDate ?? null,
    venue: first?.venue ?? null, meetingNo: first?.meetingNo ?? null, meetingDay: first?.meetingDay ?? null,
    family: first?.family ?? null, viewMode: first?.viewMode ?? null, prefix: first?.prefix ?? null, suffix: first?.suffix ?? null,
    runnerCount: first?.runnerCount ?? 0, probes: anchors.reduce((sum, anchor) => sum + Number(anchor.probes || 0), 0),
    discoveredLinks, errors,
  };
}
