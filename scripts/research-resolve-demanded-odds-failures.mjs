import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { getArchiveResultUrls } from "../dist-test/src/v1/three-month-archive.js";

function arg(name, fallback = null) {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const DEMAND = path.resolve(arg("--demand"));
const META_DIR = path.resolve(arg("--meta-dir"));
const CORPUS = path.resolve(arg("--corpus"));
const OUT = path.resolve(arg("--out"));
const META = path.resolve(arg("--meta"));

if (!DEMAND || !META_DIR || !CORPUS || !OUT || !META) {
  throw new Error("--demand, --meta-dir, --corpus, --out and --meta are required");
}

const VENUE_CODE = {
  "札幌": "01", "函館": "02", "福島": "03", "新潟": "04", "東京": "05",
  "中山": "06", "中京": "07", "京都": "08", "阪神": "09", "小倉": "10"
};
const pad2 = (value) => String(value ?? 0).padStart(2, "0");
function parseJsonl(text) { return text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line)); }
function cnameFromUrl(url) {
  try { return decodeURIComponent(new URL(url).searchParams.get("CNAME") ?? ""); }
  catch { return ""; }
}
function normalizedCname(url) { return cnameFromUrl(url).toLowerCase().replace(/^sw/, "pw"); }
function expectedIdentity(race) {
  const venueCode = VENUE_CODE[race.venue];
  if (!venueCode) throw new Error(`VENUE_CODE_NOT_FOUND:${race.venue}`);
  if (race.meetingNo == null || race.meetingDay == null) throw new Error(`MEETING_INFO_MISSING:${race.raceId}`);
  const compactDate = String(race.raceDate).replace(/-/g, "");
  const year = String(race.raceDate).slice(0, 4);
  return `${venueCode}${year}${pad2(race.meetingNo)}${pad2(race.meetingDay)}${pad2(race.raceNo)}${compactDate}`.toLowerCase();
}
function expectedArchivePrefix(race) { return `pw01sde10${expectedIdentity(race)}`; }
function validateAndNormalizeDirectResultUrl(url, race) {
  const cname = cnameFromUrl(url);
  const match = cname.match(/^(?:pw|sw)01sde(?:01|10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})(?:\/([0-9a-f]{2}))?$/i);
  if (!match) throw new Error(`DIRECT_RESULT_CNAME_INVALID:${race.raceId}:${cname}`);
  const [, venue, year, meeting, day, raceNo, ymd] = match;
  const actualIdentity = `${venue}${year}${meeting}${day}${raceNo}${ymd}`.toLowerCase();
  const wanted = expectedIdentity(race);
  if (actualIdentity !== wanted) throw new Error(`DIRECT_RESULT_IDENTITY_MISMATCH:${race.raceId}:${actualIdentity}:${wanted}`);
  const desktopCname = cname.replace(/^sw/i, "pw");
  return `https://www.jra.go.jp/JRADB/accessS.html?CNAME=${encodeURIComponent(desktopCname)}`;
}
async function findMetaFiles(dir) {
  const { readdir } = await import("node:fs/promises");
  const out = [];
  async function walk(current) {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (/research-demanded-odds-\d{4}-meta\.json$/.test(entry.name)) out.push(full);
    }
  }
  await walk(dir);
  return out.sort();
}

async function main() {
  const demandRows = parseJsonl(await readFile(DEMAND, "utf8"));
  const demandById = new Map(demandRows.map((row) => [String(row.raceId), row]));
  const corpusRows = parseJsonl(await readFile(CORPUS, "utf8"));
  const raceById = new Map(corpusRows.map((row) => [String(row?.race?.raceId), row?.race]));
  const metaFiles = await findMetaFiles(META_DIR);
  if (metaFiles.length !== 11) throw new Error(`ODDS_META_COUNT_INVALID:${metaFiles.length}`);
  const failures = new Map();
  for (const file of metaFiles) {
    const meta = JSON.parse(await readFile(file, "utf8"));
    for (const failure of meta.failures ?? []) {
      const rid = String(failure.raceId ?? "");
      if (rid) failures.set(rid, failure);
    }
  }
  const monthCache = new Map();
  async function monthUrls(month) {
    if (!monthCache.has(month)) monthCache.set(month, getArchiveResultUrls(month));
    return monthCache.get(month);
  }
  const resolved = [], unresolved = [];
  let archiveResolved = 0, currentDirectResolved = 0;
  for (const rid of [...failures.keys()].sort()) {
    try {
      const demand = demandById.get(rid), race = raceById.get(rid);
      if (!demand) throw new Error(`DEMAND_ROW_MISSING:${rid}`);
      if (!race) throw new Error(`CORPUS_RACE_MISSING:${rid}`);
      const month = String(race.raceDate).slice(0, 7).replace("-", "");
      let resolvedUrl = null, resolutionMethod = null;
      try {
        const urls = await monthUrls(month);
        const prefix = expectedArchivePrefix(race);
        const matches = urls.filter((url) => normalizedCname(url).startsWith(prefix));
        if (matches.length !== 1) throw new Error(`ARCHIVE_RACE_URL_MATCH:${rid}:count=${matches.length}:prefix=${prefix}`);
        resolvedUrl = matches[0]; resolutionMethod = "jra_month_archive"; archiveResolved += 1;
      } catch (archiveError) {
        resolvedUrl = validateAndNormalizeDirectResultUrl(demand.resultUrl ?? "", race);
        resolutionMethod = "validated_current_direct_desktop"; currentDirectResolved += 1;
      }
      const entryUrl = race.entryUrl ?? demand.entryUrl ?? null;
      if (resolutionMethod === "validated_current_direct_desktop" && !entryUrl) throw new Error(`CURRENT_ENTRY_URL_MISSING:${rid}`);
      resolved.push({
        ...demand,
        resultUrl: resolvedUrl,
        entryUrl,
        resultUrlResolutionMethod: resolutionMethod,
        originalResultUrl: demand.resultUrl ?? null,
        syntheticOddsUsed: false,
        productionDatabaseWritten: false,
        productionModelChanged: false
      });
    } catch (error) {
      unresolved.push({ raceId: rid, error: error instanceof Error ? `${error.name}:${error.message}` : String(error) });
    }
  }
  resolved.sort((a, b) => String(a.raceId).localeCompare(String(b.raceId)));
  await mkdir(path.dirname(OUT), { recursive: true });
  await writeFile(OUT, resolved.map((row) => JSON.stringify(row)).join("\n") + (resolved.length ? "\n" : ""));
  const meta = {
    purpose: "research_only_resolve_failed_odds_urls_via_jra_official_sources",
    initialFailureCount: failures.size,
    resolvedCount: resolved.length,
    archiveResolvedCount: archiveResolved,
    currentDirectResolvedCount: currentDirectResolved,
    unresolvedCount: unresolved.length,
    unresolved,
    archiveMonthsAttempted: [...monthCache.keys()].sort(),
    syntheticOddsUsed: false,
    productionDatabaseWritten: false,
    productionModelChanged: false
  };
  await writeFile(META, JSON.stringify(meta, null, 2) + "\n");
  console.log(JSON.stringify(meta));
  if (unresolved.length || resolved.length !== failures.size) process.exitCode = 2;
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
