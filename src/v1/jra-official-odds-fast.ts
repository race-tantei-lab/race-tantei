import type { CompletedBetType, OfficialOddsRow } from "./completed-ticket-runtime.js";
import { decodeHtmlEntities, jraActionLinks, jraPageText, parseJraOfficialOddsRows, stripJraTags, type JraOddsIdentity } from "./jra-official-odds.js";

const VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉";
const UNORDERED = new Set<CompletedBetType>(["ワイド", "馬連", "3連複"]);

export const JRA_FAST_TYPE_PREFIX: Record<CompletedBetType, string> = {
  "単勝": "pw151ou", "馬連": "pw154ou", "ワイド": "pw155ou",
  "馬単": "pw156ou", "3連複": "pw157ou", "3連単": "pw158ou",
};

function parseOddsValue(value: string): [number, number] | null {
  const compact = value.replaceAll(",", "").replaceAll("倍", "").trim();
  const match = compact.match(/^(\d+(?:\.\d+)?)\s*(?:[-－–〜～]\s*(\d+(?:\.\d+)?))?$/);
  if (!match) return null;
  const low = Number(match[1]);
  const high = Number(match[2] ?? match[1]);
  return Number.isFinite(low) && Number.isFinite(high) && low > 1 && high >= low && high <= 100000 ? [low, high] : null;
}

function normalizeCombination(betType: CompletedBetType, horses: number[]): string {
  return (UNORDERED.has(betType) ? [...horses].sort((a, b) => a - b) : horses).join("-");
}

function classTables(pageHtml: string, token: string): Array<{ body: string; start: number }> {
  const out: Array<{ body: string; start: number }> = [];
  const pattern = /<table\b([^>]*)>([\s\S]*?)<\/table>/gi;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(pageHtml)) !== null) {
    const classMatch = match[1].match(/\bclass\s*=\s*(['"])(.*?)\1/i);
    const classes = classMatch?.[2] ?? "";
    if (classes.split(/\s+/).includes(token) || classes.includes(token)) out.push({ body: match[2], start: match.index });
  }
  return out;
}

function captionNumbers(body: string): number[] {
  const match = body.match(/<caption\b[^>]*>([\s\S]*?)<\/caption>/i);
  if (!match) return [];
  return [...stripJraTags(match[1]).matchAll(/(?<!\d)(\d{1,2})(?!\d)/g)]
    .map((row) => Number(row[1])).filter((value) => value >= 1 && value <= 18);
}

function rowHorseAndOdds(rowHtml: string): [number, [number, number]] | null {
  const th = rowHtml.match(/<th\b[^>]*>([\s\S]*?)<\/th>/i);
  if (!th) return null;
  const horses = [...stripJraTags(th[1]).matchAll(/(?<!\d)(\d{1,2})(?!\d)/g)]
    .map((row) => Number(row[1])).filter((value) => value >= 1 && value <= 18);
  if (!horses.length) return null;
  const horse = horses[horses.length - 1];
  for (const cell of rowHtml.matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/gi)) {
    const odds = parseOddsValue(stripJraTags(cell[1]));
    if (odds) return [horse, odds];
  }
  return null;
}

function parseGrouped(pageHtml: string, betType: CompletedBetType, token: string, arity: number): OfficialOddsRow[] {
  const parsed = new Map<string, [number, number]>();
  for (const table of classTables(pageHtml, token)) {
    let prefix = captionNumbers(table.body);
    if (prefix.length < arity) continue;
    prefix = prefix.slice(-arity);
    for (const row of table.body.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
      const item = rowHorseAndOdds(row[1]);
      if (!item) continue;
      const [horse, odds] = item;
      const horses = [...prefix, horse];
      if (new Set(horses).size !== horses.length) continue;
      const combination = normalizeCombination(betType, horses);
      const previous = parsed.get(combination);
      if (!previous || odds[0] < previous[0]) parsed.set(combination, odds);
    }
  }
  return [...parsed.entries()].sort(([a], [b]) => a.localeCompare(b))
    .map(([combination, [oddsMin, oddsMax]]) => ({ betType, combination, oddsMin, oddsMax }));
}

function parseTrifecta(pageHtml: string): OfficialOddsRow[] {
  const parsed = new Map<string, [number, number]>();
  for (const table of classTables(pageHtml, "tan3")) {
    let before = pageHtml.slice(Math.max(0, table.start - 2600), table.start);
    const liStart = before.lastIndexOf("<li");
    if (liStart >= 0) before = before.slice(liStart);
    const firstMatch = before.match(/1着[\s\S]{0,600}?<div\b[^>]*class=(['"])[^'"]*\bnum\b[^'"]*\1[^>]*>\s*(\d{1,2})\s*<\/div>/i);
    const secondMatch = before.match(/2着[\s\S]{0,600}?<div\b[^>]*class=(['"])[^'"]*\bnum\b[^'"]*\1[^>]*>\s*(\d{1,2})\s*<\/div>/i);
    let first: number;
    let second: number;
    if (firstMatch && secondMatch) {
      first = Number(firstMatch[2]); second = Number(secondMatch[2]);
    } else {
      const values = [...before.matchAll(/<div\b[^>]*class=(?:['"])[^'"]*\bnum\b[^'"]*(?:['"])[^>]*>\s*(\d{1,2})\s*<\/div>/gi)].map((row) => Number(row[1]));
      if (values.length < 2) continue;
      first = values[values.length - 2]; second = values[values.length - 1];
    }
    if (first < 1 || first > 18 || second < 1 || second > 18 || first === second) continue;
    for (const row of table.body.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
      const item = rowHorseAndOdds(row[1]);
      if (!item) continue;
      const [third, odds] = item;
      if (third === first || third === second) continue;
      parsed.set(`${first}-${second}-${third}`, odds);
    }
  }
  return [...parsed.entries()].sort(([a], [b]) => a.localeCompare(b))
    .map(([combination, [oddsMin, oddsMax]]) => ({ betType: "3連単", combination, oddsMin, oddsMax }));
}

export function parseFastJraOfficialOddsRows(pageHtml: string, betType: CompletedBetType): OfficialOddsRow[] {
  if (betType === "単勝") return parseJraOfficialOddsRows(pageHtml, betType);
  if (betType === "馬連") return parseGrouped(pageHtml, betType, "umaren", 1);
  if (betType === "ワイド") return parseGrouped(pageHtml, betType, "wide", 1);
  if (betType === "馬単") return parseGrouped(pageHtml, betType, "umatan", 1);
  if (betType === "3連複") return parseGrouped(pageHtml, betType, "fuku3", 2);
  return parseTrifecta(pageHtml);
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
