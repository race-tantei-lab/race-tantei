import fs from "node:fs";
import { extractEntryLinks, fetchJraPage, pageLooksLikeEntry, parseEntryPage, toResultUrl } from "../dist-test/src/v1/jra.js";

const accountId = process.env.CLOUDFLARE_ACCOUNT_ID;
const databaseId = process.env.CLOUDFLARE_D1_DATABASE_ID;
const token = process.env.CLOUDFLARE_API_TOKEN;
const apiUrl = `https://api.cloudflare.com/client/v4/accounts/${accountId}/d1/database/${databaseId}/query`;
const reportPath = "analysis-results/jra-entry-anchor-discovery.json";
const targetDate = process.env.REPAIR_RACE_DATE || "2026-08-16";
const targetDigits = targetDate.replaceAll("-", "");

if (!accountId || !databaseId || !token) throw new Error("CLOUDFLARE_D1_ENV_MISSING");
if (!fs.existsSync(reportPath)) throw new Error("ENTRY_ANCHOR_REPORT_MISSING");

async function d1(sql, params = []) {
  const response = await fetch(apiUrl, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ sql, params })
  });
  const body = await response.json();
  if (!response.ok || body?.success !== true) throw new Error(`D1_HTTP_${response.status}:${JSON.stringify(body?.errors || [])}`);
  const result = Array.isArray(body.result) ? body.result[0] : null;
  if (result?.success === false) throw new Error(`D1_QUERY_FAILED:${JSON.stringify(result)}`);
  return result?.results || [];
}

function canonicalEntryUrl(rawUrl) {
  const url = new URL(String(rawUrl || ""));
  if (!/\/JRADB\/accessD\.html$/i.test(url.pathname)) throw new Error(`ENTRY_PATH_INVALID:${rawUrl}`);
  const cname = decodeURIComponent(url.searchParams.get("CNAME") || "").replace(/&amp;/gi, "&").trim();
  if (!/(?:pw|sw)01dde/i.test(cname) || !cname.includes(targetDigits)) throw new Error(`ENTRY_CNAME_INVALID:${rawUrl}`);
  return `https://www.jra.go.jp/JRADB/accessD.html?CNAME=${encodeURIComponent(cname)}`;
}

async function poolMap(values, limit, fn) {
  const output = [];
  let index = 0;
  async function worker() {
    while (index < values.length) {
      const current = values[index++];
      output.push(await fn(current));
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, values.length) }, () => worker()));
  return output;
}

const anchor = JSON.parse(fs.readFileSync(reportPath, "utf8"));
const initial = new Map();
for (const raw of anchor.discoveredLinks || []) {
  try {
    const url = canonicalEntryUrl(raw);
    const cname = decodeURIComponent(new URL(url).searchParams.get("CNAME") || "");
    initial.set(cname, url);
  } catch { /* ignore other days/non-entry links */ }
}
if (initial.size < 3) throw new Error(`INITIAL_ENTRY_LINKS_TOO_FEW:${initial.size}`);

// The saved anchor page exposes all races at its venue and race 1 links for the
// other venues. Fetch those canonical race pages once; their navigation exposes
// the remaining same-day race-specific accessD links.
const expanded = new Map(initial);
await poolMap([...initial.values()], 6, async (requestedUrl) => {
  const page = await fetchJraPage(requestedUrl);
  if (!pageLooksLikeEntry(page.html)) return;
  for (const raw of extractEntryLinks(page.html, requestedUrl)) {
    try {
      const url = canonicalEntryUrl(raw);
      const cname = decodeURIComponent(new URL(url).searchParams.get("CNAME") || "");
      expanded.set(cname, url);
    } catch { /* ignore */ }
  }
});

const parsed = await poolMap([...expanded.values()], 8, async (requestedUrl) => {
  const page = await fetchJraPage(requestedUrl);
  if (!pageLooksLikeEntry(page.html)) return null;
  const bundle = parseEntryPage(page.html, requestedUrl);
  if (bundle.race.raceDate !== targetDate) return null;
  if (bundle.race.entryUrl !== requestedUrl) throw new Error(`ENTRY_PARSE_DRIFT:${bundle.race.raceId}`);
  return { race: bundle.race, responseUrl: page.url };
});

const byRace = new Map();
for (const row of parsed.filter(Boolean)) byRace.set(row.race.raceId, row);
const venues = new Map();
for (const { race } of byRace.values()) venues.set(race.venue, (venues.get(race.venue) || 0) + 1);
if (byRace.size !== 36 || venues.size !== 3 || [...venues.values()].some((count) => count !== 12)) {
  throw new Error(`TODAY_ENTRY_SET_INCOMPLETE:${byRace.size}:${JSON.stringify(Object.fromEntries(venues))}`);
}

for (const { race } of byRace.values()) {
  if (/\/keiba\/calendar/i.test(race.entryUrl)) throw new Error(`CALENDAR_ENTRY_REFUSED:${race.raceId}`);
  await d1(
    `UPDATE rt_races SET entry_url=?,result_url=?,entry_updated_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE race_id=? AND race_date=?`,
    [race.entryUrl, toResultUrl(race.entryUrl), race.raceId, targetDate]
  );
}

const verification = await d1(`
  SELECT COUNT(*) AS total,
         SUM(CASE WHEN entry_url LIKE '%/keiba/calendar%' THEN 1 ELSE 0 END) AS calendarUrls,
         SUM(CASE WHEN entry_url LIKE '%/JRADB/accessD.html?CNAME=%' THEN 1 ELSE 0 END) AS specificUrls,
         SUM(CASE WHEN result_url LIKE '%/JRADB/accessS.html?CNAME=%' THEN 1 ELSE 0 END) AS resultSpecificUrls
  FROM rt_races WHERE race_date=?
`, [targetDate]);
const check = verification[0] || {};
if (Number(check.total) !== 36 || Number(check.calendarUrls || 0) !== 0 || Number(check.specificUrls || 0) !== 36 || Number(check.resultSpecificUrls || 0) !== 36) {
  throw new Error(`D1_ENTRY_URL_REPAIR_VERIFY_FAILED:${JSON.stringify(check)}`);
}

const output = {
  status: "repaired",
  targetDate,
  races: byRace.size,
  venues: Object.fromEntries(venues),
  d1: check,
  responseUrlDriftCount: [...byRace.values()].filter((row) => row.responseUrl !== row.race.entryUrl).length,
};
fs.mkdirSync("analysis-results", { recursive: true });
fs.writeFileSync("analysis-results/today-entry-url-repair.json", JSON.stringify(output, null, 2) + "\n");
console.log(JSON.stringify(output));
