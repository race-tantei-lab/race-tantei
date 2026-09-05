import { setState } from "./db.js";
import { syncOfficialCalendarDay } from "./jra-calendar.js";
import type { Env } from "./types.js";

const STATE_KEY = "worker_upcoming_calendar_repair";
const DATE_STATE_PREFIX = "worker_upcoming_calendar_day:";
const REFRESH_MS = 90 * 60 * 1000;

type DayAudit = {
  raceDate: string;
  status: "synced" | "recent" | "error";
  storedBefore: number;
  storedAfter: number;
  races: number | null;
  venues: number | null;
  error: string | null;
};

export type UpcomingCalendarAudit = {
  checkedAt: string;
  status: "idle" | "ready" | "partial" | "error";
  days: DayAudit[];
};

function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}:${error.message}` : String(error);
}

function jstDate(now: Date, offsetDays: number): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000 + offsetDays * 86400_000).toISOString().slice(0, 10);
}

function jstWeekday(now: Date): number {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).getUTCDay();
}

function targetDates(now: Date): string[] {
  const weekday = jstWeekday(now); // Sun=0 ... Sat=6
  if (weekday === 4) return [jstDate(now, 2), jstDate(now, 3)]; // Thu -> Sat/Sun
  if (weekday === 5) return [jstDate(now, 1), jstDate(now, 2)]; // Fri -> Sat/Sun
  if (weekday === 6) return [jstDate(now, 0), jstDate(now, 1), jstDate(now, 2)]; // Sat -> Sat/Sun/Mon holiday
  if (weekday === 0) return [jstDate(now, 0), jstDate(now, 1)]; // Sun -> Sun/Mon holiday
  if (weekday === 1) return [jstDate(now, 0)]; // Mon -> holiday Monday when applicable
  return [];
}

async function storedRaceCount(db: D1Database, raceDate: string): Promise<number> {
  const row = await db.prepare("SELECT COUNT(*) AS count FROM rt_races WHERE race_date=?").bind(raceDate).first<{ count: number }>();
  return Number(row?.count ?? 0);
}

async function recentSuccess(db: D1Database, raceDate: string, now: Date): Promise<boolean> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`${DATE_STATE_PREFIX}${raceDate}`).first<{ value: string }>();
  if (!row?.value) return false;
  try {
    const parsed = JSON.parse(row.value) as { checkedAt?: string; status?: string };
    const checked = Date.parse(String(parsed.checkedAt ?? ""));
    return parsed.status === "synced" && Number.isFinite(checked) && now.getTime() - checked < REFRESH_MS;
  } catch {
    return false;
  }
}

export async function runUpcomingCalendarRepair(env: Env, now = new Date()): Promise<UpcomingCalendarAudit> {
  const dates = targetDates(now);
  const audit: UpcomingCalendarAudit = { checkedAt: now.toISOString(), status: dates.length ? "ready" : "idle", days: [] };
  for (const raceDate of dates) {
    const storedBefore = await storedRaceCount(env.DB, raceDate);
    if (await recentSuccess(env.DB, raceDate, now)) {
      audit.days.push({ raceDate, status: "recent", storedBefore, storedAfter: storedBefore, races: null, venues: null, error: null });
      continue;
    }
    try {
      const result = await syncOfficialCalendarDay(env.DB, raceDate);
      const storedAfter = await storedRaceCount(env.DB, raceDate);
      const day: DayAudit = {
        raceDate,
        status: "synced",
        storedBefore,
        storedAfter,
        races: result.races,
        venues: result.venues,
        error: null,
      };
      audit.days.push(day);
      await setState(env.DB, `${DATE_STATE_PREFIX}${raceDate}`, JSON.stringify({ checkedAt: now.toISOString(), ...day }));
    } catch (error) {
      const storedAfter = await storedRaceCount(env.DB, raceDate);
      const day: DayAudit = {
        raceDate,
        status: "error",
        storedBefore,
        storedAfter,
        races: null,
        venues: null,
        error: errorText(error),
      };
      audit.days.push(day);
      await setState(env.DB, `${DATE_STATE_PREFIX}${raceDate}`, JSON.stringify({ checkedAt: now.toISOString(), ...day }));
    }
  }
  const errors = audit.days.filter((day) => day.status === "error").length;
  if (errors === audit.days.length && errors > 0) audit.status = "error";
  else if (errors > 0) audit.status = "partial";
  else if (audit.days.length) audit.status = "ready";
  await setState(env.DB, STATE_KEY, JSON.stringify(audit));
  return audit;
}
