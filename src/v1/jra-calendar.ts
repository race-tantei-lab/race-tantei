import type { RaceRecord } from "./types.js";
import { fetchJraPage } from "./jra.js";
import { htmlToLines, parseJapaneseDateTime } from "./utils.js";

const VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉";

function venueSlug(venue: string): string {
  const map: Record<string, string> = {
    札幌: "sapporo", 函館: "hakodate", 福島: "fukushima", 新潟: "niigata", 東京: "tokyo",
    中山: "nakayama", 中京: "chukyo", 京都: "kyoto", 阪神: "hanshin", 小倉: "kokura"
  };
  return map[venue] ?? encodeURIComponent(venue);
}

export function jstDateKey(date = new Date(), offsetDays = 0): string {
  const jst = new Date(date.getTime() + 9 * 60 * 60 * 1000 + offsetDays * 24 * 60 * 60 * 1000);
  return `${jst.getUTCFullYear()}-${String(jst.getUTCMonth() + 1).padStart(2, "0")}-${String(jst.getUTCDate()).padStart(2, "0")}`;
}

export function officialCalendarUrl(raceDate: string): string {
  const [year, month, day] = raceDate.split("-");
  if (!year || !month || !day) throw new Error("INVALID_RACE_DATE");
  return `https://www.jra.go.jp/keiba/calendar${year}/${year}/${Number(month)}/${month}${day}.html`;
}

function descriptorParts(descriptor: string, raceNo: number): {
  raceName: string; conditions: string; surface: string | null; distanceM: number | null; direction: string | null;
} {
  const clean = descriptor.replace(/\s+/g, " ").trim();
  const distance = clean.match(/([0-9,]{3,5})\s*[（(]([^）)]+)[）)]/);
  const inside = distance?.[2] ?? "";
  const distanceM = distance?.[1] ? Number(distance[1].replace(/,/g, "")) : null;
  const surface = /^ダ/.test(inside) ? "ダート" : /^芝/.test(inside) ? (/^障害/.test(clean) ? "障害" : "芝") : /^障害/.test(clean) ? "障害" : null;
  const direction = /直/.test(inside) ? "直線" : /右/.test(inside) ? "右" : /左/.test(inside) ? "左" : /外/.test(inside) ? "外" : /内/.test(inside) ? "内" : null;
  const classStart = clean.search(/(?:障害)?(?:2歳|3歳|4歳|3歳以上|4歳以上)(?:\s|　)*(?:未勝利|新馬|1勝クラス|2勝クラス|3勝クラス|オープン)/);
  let raceName = "";
  if (classStart > 0) raceName = clean.slice(0, classStart).trim();
  if (!raceName) {
    raceName = clean.match(/^(?:障害)?(?:2歳|3歳|4歳|3歳以上|4歳以上)(?:\s|　)*(?:未勝利|新馬|1勝クラス|2勝クラス|3勝クラス|オープン)/)?.[0]?.replace(/\s+/g, "") ?? `${raceNo}レース`;
  }
  return { raceName, conditions: clean, surface, distanceM, direction };
}

export function parseOfficialCalendar(html: string, raceDate: string, calendarUrl: string): RaceRecord[] {
  const [yearText, monthText, dayText] = raceDate.split("-");
  const year = Number(yearText), month = Number(monthText), day = Number(dayText);
  if (!year || !month || !day) throw new Error("INVALID_RACE_DATE");

  const lines = htmlToLines(html).map((line) => line.replace(/\s+/g, " ").trim()).filter(Boolean);
  const races: RaceRecord[] = [];
  let meeting: { venue: string; meetingNo: number; meetingDay: number } | null = null;

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i] ?? "";
    const heading = line.match(new RegExp(`^(\\d+)回(${VENUES})(\\d+)日$`));
    if (heading) {
      meeting = { venue: heading[2] ?? "", meetingNo: Number(heading[1]), meetingDay: Number(heading[3]) };
      continue;
    }
    if (!meeting) continue;

    let raceNo = 0;
    let descriptor = "";
    let hour = 0;
    let minute = 0;

    const full = line.match(/^(\d{1,2})\s*レース\s+(.+?)\s+(\d{1,2})時(\d{2})分$/);
    if (full) {
      raceNo = Number(full[1]); descriptor = full[2] ?? ""; hour = Number(full[3]); minute = Number(full[4]);
    } else {
      const raceOnly = line.match(/^(\d{1,2})\s*レース$/);
      if (!raceOnly) continue;
      raceNo = Number(raceOnly[1]);
      const pieces: string[] = [];
      for (let j = i + 1; j < Math.min(lines.length, i + 8); j += 1) {
        const next = lines[j] ?? "";
        if (new RegExp(`^\\d+回(${VENUES})\\d+日$`).test(next) || /^\d{1,2}\s*レース$/.test(next)) break;
        const time = next.match(/^(\d{1,2})時(\d{2})分$/);
        if (time) { hour = Number(time[1]); minute = Number(time[2]); i = j; break; }
        if (!/^(?:レース\s*番号|レース名・条件|発走時刻|---|\|)/.test(next)) pieces.push(next);
      }
      descriptor = pieces.join(" ").trim();
    }

    if (raceNo < 1 || raceNo > 12 || !descriptor || hour < 1 || minute < 0 || minute > 59) continue;
    const parsed = descriptorParts(descriptor, raceNo);
    const startTimeJst = `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
    const raceId = `${raceDate}-${venueSlug(meeting.venue)}-${String(raceNo).padStart(2,"0")}`;
    races.push({
      raceId, raceDate, venue: meeting.venue, meetingNo: meeting.meetingNo, meetingDay: meeting.meetingDay,
      raceNo, raceName: parsed.raceName, conditions: parsed.conditions, surface: parsed.surface,
      distanceM: parsed.distanceM, direction: parsed.direction, startTimeJst,
      startTimeUtc: parseJapaneseDateTime(year, month, day, startTimeJst), weather: null, trackCondition: null,
      entryUrl: calendarUrl, resultUrl: calendarUrl, status: "scheduled"
    });
  }

  return races;
}

async function upsertCalendarRaces(db: D1Database, races: RaceRecord[]): Promise<void> {
  if (!races.length) return;
  const statements = races.map((race) => db.prepare(`
    INSERT INTO rt_races (
      race_id,race_date,venue,meeting_no,meeting_day,race_no,race_name,conditions,surface,distance_m,direction,
      start_time_jst,start_time_utc,weather,track_condition,entry_url,result_url,status,entry_updated_at,updated_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
    ON CONFLICT(race_id) DO UPDATE SET
      race_date=excluded.race_date, venue=excluded.venue, meeting_no=excluded.meeting_no, meeting_day=excluded.meeting_day,
      race_no=excluded.race_no,
      race_name=CASE WHEN rt_races.race_name GLOB '[0-9]*レース' OR rt_races.race_name IN ('検索ウィンドウ','検索','出馬表','レース','') OR rt_races.entry_url LIKE '%/keiba/calendar%' THEN excluded.race_name ELSE rt_races.race_name END,
      conditions=COALESCE(rt_races.conditions,excluded.conditions), surface=COALESCE(rt_races.surface,excluded.surface),
      distance_m=COALESCE(rt_races.distance_m,excluded.distance_m), direction=COALESCE(rt_races.direction,excluded.direction),
      start_time_jst=COALESCE(rt_races.start_time_jst,excluded.start_time_jst), start_time_utc=COALESCE(rt_races.start_time_utc,excluded.start_time_utc),
      entry_url=CASE WHEN rt_races.entry_url LIKE '%/keiba/calendar%' THEN excluded.entry_url ELSE rt_races.entry_url END,
      result_url=CASE WHEN rt_races.result_url LIKE '%/keiba/calendar%' THEN excluded.result_url ELSE rt_races.result_url END,
      status=CASE WHEN rt_races.status='finished' THEN 'finished' ELSE rt_races.status END,
      updated_at=CURRENT_TIMESTAMP
  `).bind(
    race.raceId,race.raceDate,race.venue,race.meetingNo,race.meetingDay,race.raceNo,race.raceName,race.conditions,
    race.surface,race.distanceM,race.direction,race.startTimeJst,race.startTimeUtc,race.weather,race.trackCondition,
    race.entryUrl,race.resultUrl,race.status
  ));
  await db.batch(statements);
}

export async function syncOfficialCalendarDay(db: D1Database, raceDate: string): Promise<{ raceDate: string; races: number; venues: number }> {
  const url = officialCalendarUrl(raceDate);
  const page = await fetchJraPage(url);
  const races = parseOfficialCalendar(page.html, raceDate, url);
  if (!races.length) throw new Error(`CALENDAR_RACES_NOT_FOUND:${raceDate}`);
  await upsertCalendarRaces(db, races);
  return { raceDate, races: races.length, venues: new Set(races.map((race) => race.venue)).size };
}
