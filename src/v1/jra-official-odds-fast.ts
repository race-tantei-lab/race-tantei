import type { CompletedBetType, OfficialOddsRow } from "./completed-ticket-runtime.js";
import { decodeHtmlEntities, jraActionLinks, jraPageText, parseJraOfficialOddsRows, type JraOddsIdentity } from "./jra-official-odds.js";

const VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉";

export const JRA_FAST_TYPE_PREFIX: Record<CompletedBetType, string> = {
  "単勝": "pw151ou", "馬連": "pw154ou", "ワイド": "pw155ou",
  "馬単": "pw156ou", "3連複": "pw157ou", "3連単": "pw158ou",
};

// Fast and crawl paths deliberately share one canonical semantic parser. JRA's
// current markup identifies horse numbers and odds by their table/cell roles, so
// neither path is allowed to guess an odds value from arbitrary numeric cells.
export function parseFastJraOfficialOddsRows(pageHtml: string, betType: CompletedBetType): OfficialOddsRow[] {
  return parseJraOfficialOddsRows(pageHtml, betType);
}

export function currentJraRaceNoFromCname(cname: string): number | null {
  const decoded = decodeURIComponent(decodeHtmlEntities(cname));
  const values = [...decoded.matchAll(/(\d{2})(?=20\d{6}[A-Za-z0-9]*?(?:\/|$))/g)].map((row) => Number(row[1]));
  return [...values].reverse().find((value) => value >= 1 && value <= 12) ?? null;
}

export function sameFastJraRaceLink(cname: string, raceDateDigits: string, raceNo: number): boolean {
  return decodeURIComponent(decodeHtmlEntities(cname)).includes(raceDateDigits) && currentJraRaceNoFromCname(cname) === raceNo;
}

export function findFastJraTypeCnames(pageHtml: string, raceDateDigits: string, raceNo: number): Partial<Record<CompletedBetType, string>> {
  const actions = jraActionLinks(pageHtml).filter((link) => sameFastJraRaceLink(link.cname, raceDateDigits, raceNo));
  const result: Partial<Record<CompletedBetType, string>> = {};
  for (const [betType, prefix] of Object.entries(JRA_FAST_TYPE_PREFIX) as Array<[CompletedBetType, string]>) {
    const candidate = actions.find((link) => link.cname.startsWith(prefix));
    if (candidate) result[betType] = candidate.cname;
  }
  return result;
}

export function parseFastJraOddsIdentity(pageHtml: string, cname: string): JraOddsIdentity | null {
  const text = jraPageText(pageHtml);
  const heading = text.match(new RegExp(`(20\\d{2})年(\\d{1,2})月(\\d{1,2})日[^\\n]{0,150}?(?:\\d+回)?(${VENUES})(?:\\d+日)?`));
  const raceNo = currentJraRaceNoFromCname(cname);
  if (!heading || raceNo == null) return null;
  return {
    raceDate: `${heading[1]}-${String(Number(heading[2])).padStart(2, "0")}-${String(Number(heading[3])).padStart(2, "0")}`,
    venue: heading[4],
    raceNo,
  };
}
