import { fetchJraPage } from "./jra.js";
import { jstDateKey, officialCalendarUrl, parseOfficialCalendar } from "./jra-calendar.js";

type RaceDayGateResult = {
  raceDate: string;
  shouldRun: boolean;
  reason: "official_calendar" | "no_calendar" | "probe_failed_fail_open" | "unparsed_calendar_fail_open";
};

type CachedGate = RaceDayGateResult & { checkedAt: number };

const CACHE_MS = 6 * 60 * 60 * 1000;
let cachedGate: CachedGate | null = null;

function errorCode(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isDefiniteNoCalendar(error: unknown): boolean {
  return /(?:^|:)HTTP_(?:404|410)(?:$|:)/.test(errorCode(error)) || /^HTTP_(?:404|410)$/.test(errorCode(error));
}

export async function shouldRunOnJraRaceDay(now = new Date()): Promise<RaceDayGateResult> {
  const raceDate = jstDateKey(now);
  const nowMs = Date.now();
  if (cachedGate && cachedGate.raceDate === raceDate && nowMs - cachedGate.checkedAt < CACHE_MS) {
    return cachedGate;
  }

  const calendarUrl = officialCalendarUrl(raceDate);
  try {
    const page = await fetchJraPage(calendarUrl);
    const races = parseOfficialCalendar(page.html, raceDate, calendarUrl);
    if (races.length > 0) {
      cachedGate = { raceDate, shouldRun: true, reason: "official_calendar", checkedAt: nowMs };
      return cachedGate;
    }

    // A 200 response with no parsable races is ambiguous: JRA may have changed
    // markup. Never suppress a real race day because of a parser regression.
    console.warn("RACE_DAY_GATE_UNPARSED_CALENDAR_FAIL_OPEN", JSON.stringify({ raceDate, calendarUrl }));
    return { raceDate, shouldRun: true, reason: "unparsed_calendar_fail_open" };
  } catch (error) {
    if (isDefiniteNoCalendar(error)) {
      cachedGate = { raceDate, shouldRun: false, reason: "no_calendar", checkedAt: nowMs };
      return cachedGate;
    }

    // Network/JRA blocking failures must never disable race-day generation.
    console.warn("RACE_DAY_GATE_PROBE_FAILED_FAIL_OPEN", JSON.stringify({ raceDate, calendarUrl, error: errorCode(error) }));
    return { raceDate, shouldRun: true, reason: "probe_failed_fail_open" };
  }
}
