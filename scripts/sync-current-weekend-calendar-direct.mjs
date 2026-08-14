import { fetchJraPage } from "../dist-test/src/v1/jra.js";
import { officialCalendarUrl, parseOfficialCalendar } from "../dist-test/src/v1/jra-calendar.js";

const accountId = process.env.CLOUDFLARE_ACCOUNT_ID;
const databaseId = process.env.CLOUDFLARE_D1_DATABASE_ID;
const token = process.env.CLOUDFLARE_API_TOKEN;
const apiUrl = `https://api.cloudflare.com/client/v4/accounts/${accountId}/d1/database/${databaseId}/query`;

if (!accountId || !databaseId || !token) throw new Error("CLOUDFLARE_D1_ENV_MISSING");

function dateKey(ms) {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

export function currentWeekendDates(now = new Date()) {
  const jst = new Date(now.getTime() + 9 * 3600_000);
  const base = Date.UTC(jst.getUTCFullYear(), jst.getUTCMonth(), jst.getUTCDate());
  const day = jst.getUTCDay();
  if (day === 0) return [dateKey(base)];
  const toSat = (6 - day + 7) % 7;
  const sat = base + toSat * 86400_000;
  return [dateKey(sat), dateKey(sat + 86400_000)];
}

async function d1(sql, params = []) {
  const response = await fetch(apiUrl, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ sql, params })
  });
  const body = await response.json();
  if (!response.ok || body?.success !== true) throw new Error(`D1_HTTP_${response.status}`);
  const result = Array.isArray(body.result) ? body.result[0] : null;
  if (result?.success === false) throw new Error("D1_QUERY_FAILED");
  return result?.results || [];
}

async function saveRace(race) {
  await d1(`INSERT INTO rt_races (
    race_id,race_date,venue,meeting_no,meeting_day,race_no,race_name,conditions,surface,distance_m,direction,
    start_time_jst,start_time_utc,weather,track_condition,entry_url,result_url,status,entry_updated_at,updated_at
  ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
  ON CONFLICT(race_id) DO UPDATE SET
    race_date=excluded.race_date,venue=excluded.venue,meeting_no=excluded.meeting_no,meeting_day=excluded.meeting_day,
    race_no=excluded.race_no,
    race_name=CASE WHEN rt_races.race_name IS NULL OR trim(rt_races.race_name)='' OR rt_races.race_name GLOB '[0-9]*レース' OR rt_races.race_name GLOB '[0-9]*R' OR rt_races.entry_url LIKE '%/keiba/calendar%' THEN excluded.race_name ELSE rt_races.race_name END,
    conditions=COALESCE(rt_races.conditions,excluded.conditions),surface=COALESCE(rt_races.surface,excluded.surface),
    distance_m=COALESCE(rt_races.distance_m,excluded.distance_m),direction=COALESCE(rt_races.direction,excluded.direction),
    start_time_jst=COALESCE(rt_races.start_time_jst,excluded.start_time_jst),start_time_utc=COALESCE(rt_races.start_time_utc,excluded.start_time_utc),
    entry_url=CASE WHEN rt_races.entry_url IS NULL OR rt_races.entry_url LIKE '%/keiba/calendar%' THEN excluded.entry_url ELSE rt_races.entry_url END,
    result_url=CASE WHEN rt_races.result_url IS NULL OR rt_races.result_url LIKE '%/keiba/calendar%' THEN excluded.result_url ELSE rt_races.result_url END,
    status=CASE WHEN rt_races.status='finished' THEN 'finished' ELSE 'scheduled' END,updated_at=CURRENT_TIMESTAMP`, [
    race.raceId,race.raceDate,race.venue,race.meetingNo,race.meetingDay,race.raceNo,race.raceName,race.conditions,
    race.surface,race.distanceM,race.direction,race.startTimeJst,race.startTimeUtc,race.weather,race.trackCondition,
    race.entryUrl,race.resultUrl,race.status
  ]);
}

export async function syncCurrentWeekendCalendarDirect(now = new Date()) {
  const dates = currentWeekendDates(now);
  const days = [];
  for (const raceDate of dates) {
    const page = await fetchJraPage(officialCalendarUrl(raceDate));
    const races = parseOfficialCalendar(page.html, raceDate, page.url);
    const venues = new Set(races.map((race) => race.venue));
    if (!races.length || races.length !== venues.size * 12) throw new Error(`JRA_CALENDAR_INCOMPLETE:${raceDate}:${races.length}:${venues.size}`);
    for (const race of races) await saveRace(race);
    days.push({ raceDate, races: races.length, venues: venues.size });
  }
  const report = { generatedAtUtc: new Date().toISOString(), dates, days };
  await globalThis.Bun?.write?.("current-weekend-calendar-sync.json", JSON.stringify(report, null, 2));
  return report;
}
