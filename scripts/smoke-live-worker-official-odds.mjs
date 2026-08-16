import fs from "node:fs";
import { fetchFastJraOfficialOddsForRace } from "../dist-test/src/v1/jra-official-odds-fetch.js";

const accountId = process.env.CLOUDFLARE_ACCOUNT_ID;
const databaseId = process.env.CLOUDFLARE_D1_DATABASE_ID;
const token = process.env.CLOUDFLARE_API_TOKEN;
const apiUrl = `https://api.cloudflare.com/client/v4/accounts/${accountId}/d1/database/${databaseId}/query`;
if (!accountId || !databaseId || !token) throw new Error("CLOUDFLARE_D1_ENV_MISSING");

async function d1(sql, params = []) {
  const response = await fetch(apiUrl, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ sql, params })
  });
  const body = await response.json();
  if (!response.ok || body?.success !== true) throw new Error(`D1_HTTP_${response.status}:${JSON.stringify(body?.errors || [])}`);
  return (Array.isArray(body.result) ? body.result[0]?.results : []) || [];
}

function jstDate() {
  const d = new Date(Date.now() + 9 * 3600_000);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

const date = process.env.SMOKE_RACE_DATE || jstDate();
const selectionRows = await d1("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1", [`final_daily_selection:${date}`]);
if (!selectionRows.length) throw new Error(`SMOKE_SELECTION_MISSING:${date}`);
const selection = JSON.parse(selectionRows[0].value || "{}");
const ids = [...new Set((selection.selected || []).map((row) => String(row.raceId || "")).filter(Boolean))];
if (!ids.length) throw new Error("SMOKE_SELECTION_EMPTY");
const placeholders = ids.map(() => "?").join(",");
const races = await d1(`
  SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,start_time_utc AS startTimeUtc,entry_url AS entryUrl
  FROM rt_races
  WHERE race_id IN (${placeholders}) AND datetime(start_time_utc)>datetime('now')
  ORDER BY datetime(start_time_utc),race_id
`, ids);
if (!races.length) throw new Error("SMOKE_NO_FUTURE_SELECTED_RACE");
const race = races[0];
if (!/\/JRADB\/accessD\.html\?CNAME=/i.test(String(race.entryUrl || ""))) throw new Error(`SMOKE_ENTRY_URL_INVALID:${race.raceId}:${race.entryUrl}`);

const fetched = await fetchFastJraOfficialOddsForRace(race.entryUrl, {
  raceDate: race.raceDate,
  venue: race.venue,
  raceNo: Number(race.raceNo),
});
const types = [...new Set(fetched.pages.map((page) => page.betType))].sort();
const expected = ["3連単", "3連複", "ワイド", "単勝", "馬単", "馬連"].sort();
if (fetched.pages.length !== 6 || JSON.stringify(types) !== JSON.stringify(expected) || fetched.rows.length < 6) {
  throw new Error(`SMOKE_SIX_TYPE_FAILED:${race.raceId}:${JSON.stringify(types)}:${fetched.rows.length}`);
}
const output = {
  status: "ok",
  checkedAt: new Date().toISOString(),
  raceId: race.raceId,
  startTimeUtc: race.startTimeUtc,
  entryUrl: race.entryUrl,
  types,
  pages: fetched.pages.length,
  rows: fetched.rows.length,
  entryCnameCount: fetched.entryCnameCount,
};
fs.mkdirSync("analysis-results", { recursive: true });
fs.writeFileSync("analysis-results/live-worker-six-type-odds-smoke.json", JSON.stringify(output, null, 2) + "\n");
console.log(JSON.stringify(output));
