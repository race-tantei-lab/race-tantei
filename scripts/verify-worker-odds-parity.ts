import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { detectJraBetType, jraActionLinks } from "../src/v1/jra-official-odds";
import {
  currentJraRaceNoFromCname,
  parseFastJraOddsIdentity,
  parseFastJraOfficialOddsRows,
} from "../src/v1/jra-official-odds-fast";
import type { CompletedBetType, OfficialOddsRow } from "../src/v1/completed-ticket-runtime";

type FixturePage = {
  cname: string;
  hint: string;
  depth: number;
  html: string;
  identity: { raceDate: string; venue: string; raceNo: number };
  betType: CompletedBetType;
  rows: OfficialOddsRow[];
};
type Fixture = {
  race: { raceId: string; raceDate: string; venue: string; raceNo: number };
  entryHtml: string;
  entryActionLinks: Array<{ cname: string; context: string }>;
  pagesFetched: number;
  maxFoundDepth: number;
  pages: FixturePage[];
};

for (const [cname, expected] of Object.entries({
  "pw15oren0101202601051120260808/AA": 11,
  "pw151ouS301202601061120260809Z/EA": 11,
  "pw151ouS301202601060920260809Z/40": 9,
  "pw157ouS301202601061120260809Z99/64": 11,
})) {
  const actual = currentJraRaceNoFromCname(cname);
  if (actual !== expected) throw new Error(`CURRENT_CNAME_RACE_NUMBER:${cname}:${actual}:${expected}`);
}

const fixture = JSON.parse(readFileSync(resolve(process.argv[2] ?? "worker-odds-parity.json"), "utf8")) as Fixture;
const expectedEntryCnames = fixture.entryActionLinks.map((row) => row.cname);
const actualEntryCnames = jraActionLinks(fixture.entryHtml).map((row) => row.cname);
if (JSON.stringify(actualEntryCnames) !== JSON.stringify(expectedEntryCnames)) {
  throw new Error(`ENTRY_ACTION_LINK_PARITY_FAILED expected=${JSON.stringify(expectedEntryCnames)} actual=${JSON.stringify(actualEntryCnames)}`);
}

let rowsChecked = 0;
let maxOddsError = 0;
for (const page of fixture.pages) {
  const identity = parseFastJraOddsIdentity(page.html, page.cname);
  if (JSON.stringify(identity) !== JSON.stringify(page.identity)) {
    throw new Error(`${page.betType}: identity mismatch expected=${JSON.stringify(page.identity)} actual=${JSON.stringify(identity)}`);
  }
  const betType = detectJraBetType(page.html, page.hint);
  if (betType !== page.betType) throw new Error(`${page.betType}: detected bet type mismatch actual=${betType}`);
  const actual = parseFastJraOfficialOddsRows(page.html, page.betType);
  if (actual.length !== page.rows.length) {
    throw new Error(`${page.betType}: row count mismatch expected=${page.rows.length} actual=${actual.length}`);
  }
  const actualByCombo = new Map(actual.map((row) => [row.combination, row]));
  for (const want of page.rows) {
    const got = actualByCombo.get(want.combination);
    if (!got || got.betType !== want.betType) {
      throw new Error(`${page.betType}: missing combination ${want.combination}`);
    }
    const lowError = Math.abs(got.oddsMin - want.oddsMin);
    const highError = Math.abs(got.oddsMax - want.oddsMax);
    maxOddsError = Math.max(maxOddsError, lowError, highError);
    if (lowError !== 0 || highError !== 0) {
      throw new Error(`${page.betType}:${got.combination}: odds mismatch expected=${want.oddsMin}-${want.oddsMax} actual=${got.oddsMin}-${got.oddsMax}`);
    }
    rowsChecked += 1;
  }
}

if (fixture.pages.length !== 6) throw new Error(`expected six JRA odds pages, got ${fixture.pages.length}`);
console.log(JSON.stringify({
  status: "WORKER_JRA_ODDS_FAST_PARSER_PARITY_OK",
  raceId: fixture.race.raceId,
  identity: [fixture.race.raceDate, fixture.race.venue, fixture.race.raceNo],
  entryActionLinks: actualEntryCnames.length,
  sourcePagesFetched: fixture.pagesFetched,
  maxFoundDepth: fixture.maxFoundDepth,
  betTypes: fixture.pages.map((page) => page.betType),
  rowsChecked,
  maxOddsError,
}));
