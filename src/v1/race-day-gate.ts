import { fetchJraPage, type FetchPageResult } from "./jra.js";
import { jstDateKey, officialCalendarUrl, parseOfficialCalendar } from "./jra-calendar.js";

type RaceDayGateResult = {
  raceDate: string;
  shouldRun: boolean;
  reason:
    | "official_calendar"
    | "no_calendar"
    | "not_listed_in_official_month_calendar"
    | "official_annual_schedule_fallback"
    | "probe_failed_fail_open"
    | "unparsed_calendar_fail_open";
};

type CachedGate = RaceDayGateResult & { checkedAt: number };
type JraPageFetcher = (url: string) => Promise<FetchPageResult>;

const CACHE_MS = 6 * 60 * 60 * 1000;
const MONTH_SLUGS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"] as const;
const JRA_2026_SPECIAL_MONDAYS = new Set(["2026-01-12", "2026-09-21", "2026-10-12", "2026-11-23"]);
let cachedGate: CachedGate | null = null;

function errorCode(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isDefiniteNoCalendar(error: unknown): boolean {
  return /(?:^|:)HTTP_(?:404|410)(?:$|:)/.test(errorCode(error)) || /^HTTP_(?:404|410)$/.test(errorCode(error));
}

function officialMonthCalendarUrl(raceDate: string): string {
  const [year, monthText] = raceDate.split("-");
  const month = Number(monthText);
  const slug = MONTH_SLUGS[month - 1];
  if (!year || !slug) throw new Error("INVALID_RACE_DATE");
  return `https://www.jra.go.jp/keiba/calendar${year}/${slug}.html`;
}

function monthCalendarListsDay(html: string, raceDate: string): boolean {
  const [, monthText, dayText] = raceDate.split("-");
  if (!monthText || !dayText) return false;
  const file = `${monthText}${dayText}.html`;
  const monthNumber = String(Number(monthText));
  return html.includes(file) || html.includes(`/${monthNumber}/${file}`);
}

// JRA's published 2026 annual program starts Sun Jan 4, ends Sun Dec 27,
// and adds four holiday Mondays (Jan 12, Sep 21, Oct 12, Nov 23). Within
// those bounds central racing is scheduled every Saturday/Sunday. This is a
// local fallback only for 2026 so JRA-side 403/temporary blocking cannot make
// non-race weekdays burn D1 quota. Unknown years still fail open.
function officialAnnualScheduleFallback(raceDate: string): boolean | null {
  if (!raceDate.startsWith("2026-")) return null;
  if (raceDate < "2026-01-04" || raceDate > "2026-12-27") return false;
  if (JRA_2026_SPECIAL_MONDAYS.has(raceDate)) return true;
  const [yearText, monthText, dayText] = raceDate.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return null;
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  return weekday === 0 || weekday === 6;
}

function cacheResult(result: RaceDayGateResult, checkedAt: number, mayUseProcessCache: boolean): RaceDayGateResult {
  if (mayUseProcessCache) cachedGate = { ...result, checkedAt };
  return result;
}

function fallbackForProbeFailure(raceDate: string, nowMs: number, mayUseProcessCache: boolean): RaceDayGateResult | null {
  const known = officialAnnualScheduleFallback(raceDate);
  if (known === null) return null;
  return cacheResult({ raceDate, shouldRun: known, reason: "official_annual_schedule_fallback" }, nowMs, mayUseProcessCache);
}

export async function shouldRunOnJraRaceDay(
  now = new Date(),
  fetchPage: JraPageFetcher = fetchJraPage,
): Promise<RaceDayGateResult> {
  const raceDate = jstDateKey(now);
  const nowMs = Date.now();
  const mayUseProcessCache = fetchPage === fetchJraPage;
  if (mayUseProcessCache && cachedGate && cachedGate.raceDate === raceDate && nowMs - cachedGate.checkedAt < CACHE_MS) {
    return cachedGate;
  }

  const calendarUrl = officialCalendarUrl(raceDate);
  try {
    const page = await fetchPage(calendarUrl);
    const races = parseOfficialCalendar(page.html, raceDate, calendarUrl);
    if (races.length > 0) {
      return cacheResult({ raceDate, shouldRun: true, reason: "official_calendar" }, nowMs, mayUseProcessCache);
    }

    // A daily URL can theoretically return a generic 200 page. Resolve that
    // ambiguity from JRA's official month calendar before touching D1.
    try {
      const monthUrl = officialMonthCalendarUrl(raceDate);
      const monthPage = await fetchPage(monthUrl);
      if (!monthCalendarListsDay(monthPage.html, raceDate)) {
        return cacheResult({ raceDate, shouldRun: false, reason: "not_listed_in_official_month_calendar" }, nowMs, mayUseProcessCache);
      }
    } catch (monthError) {
      const fallback = fallbackForProbeFailure(raceDate, nowMs, mayUseProcessCache);
      if (fallback) return fallback;
      console.warn("RACE_DAY_GATE_MONTH_PROBE_FAILED_FAIL_OPEN", JSON.stringify({ raceDate, error: errorCode(monthError) }));
      return { raceDate, shouldRun: true, reason: "probe_failed_fail_open" };
    }

    // The official month calendar says racing exists but the daily page could
    // not be parsed. Fail open so a JRA markup change cannot suppress a real
    // race day; CI separately protects the parser contract.
    console.warn("RACE_DAY_GATE_UNPARSED_CALENDAR_FAIL_OPEN", JSON.stringify({ raceDate, calendarUrl }));
    return { raceDate, shouldRun: true, reason: "unparsed_calendar_fail_open" };
  } catch (error) {
    if (isDefiniteNoCalendar(error)) {
      return cacheResult({ raceDate, shouldRun: false, reason: "no_calendar" }, nowMs, mayUseProcessCache);
    }

    const fallback = fallbackForProbeFailure(raceDate, nowMs, mayUseProcessCache);
    if (fallback) return fallback;

    // Unknown-year network/JRA blocking failures must never disable race-day generation.
    console.warn("RACE_DAY_GATE_PROBE_FAILED_FAIL_OPEN", JSON.stringify({ raceDate, calendarUrl, error: errorCode(error) }));
    return { raceDate, shouldRun: true, reason: "probe_failed_fail_open" };
  }
}
