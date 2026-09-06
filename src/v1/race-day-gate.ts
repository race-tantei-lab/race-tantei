import { fetchJraPage, type FetchPageResult } from "./jra.js";
import { jstDateKey, officialCalendarUrl, parseOfficialCalendar } from "./jra-calendar.js";

type RaceDayGateResult = {
  raceDate: string;
  shouldRun: boolean;
  reason:
    | "official_calendar"
    | "no_calendar"
    | "not_listed_in_official_month_calendar"
    | "probe_failed_fail_open"
    | "unparsed_calendar_fail_open";
};

type CachedGate = RaceDayGateResult & { checkedAt: number };
type JraPageFetcher = (url: string) => Promise<FetchPageResult>;

const CACHE_MS = 6 * 60 * 60 * 1000;
const MONTH_SLUGS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"] as const;
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
      const result: CachedGate = { raceDate, shouldRun: true, reason: "official_calendar", checkedAt: nowMs };
      if (mayUseProcessCache) cachedGate = result;
      return result;
    }

    // A daily URL can theoretically return a generic 200 page. Resolve that
    // ambiguity from JRA's official month calendar before touching D1.
    try {
      const monthUrl = officialMonthCalendarUrl(raceDate);
      const monthPage = await fetchPage(monthUrl);
      if (!monthCalendarListsDay(monthPage.html, raceDate)) {
        const result: CachedGate = { raceDate, shouldRun: false, reason: "not_listed_in_official_month_calendar", checkedAt: nowMs };
        if (mayUseProcessCache) cachedGate = result;
        return result;
      }
    } catch (monthError) {
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
      const result: CachedGate = { raceDate, shouldRun: false, reason: "no_calendar", checkedAt: nowMs };
      if (mayUseProcessCache) cachedGate = result;
      return result;
    }

    // Network/JRA blocking failures must never disable race-day generation.
    console.warn("RACE_DAY_GATE_PROBE_FAILED_FAIL_OPEN", JSON.stringify({ raceDate, calendarUrl, error: errorCode(error) }));
    return { raceDate, shouldRun: true, reason: "probe_failed_fail_open" };
  }
}
