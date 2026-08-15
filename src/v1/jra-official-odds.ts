import type { CompletedBetType, OfficialOddsRow } from "./completed-ticket-runtime";

export const JRA_ODDS_URL = "https://www.jra.go.jp/JRADB/accessO.html";
export const JRA_ODDS_HOME_CNAME = "pw15oli00/6D";
const USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136 Safari/537.36";
const BET_TYPES: readonly CompletedBetType[] = ["3連単", "3連複", "馬単", "馬連", "ワイド", "単勝"];
const BET_SET = new Set<string>(BET_TYPES);
const UNORDERED = new Set<CompletedBetType>(["ワイド", "馬連", "3連複"]);
const ARITY: Record<CompletedBetType, number> = { "単勝": 1, "ワイド": 2, "馬連": 2, "馬単": 2, "3連複": 3, "3連単": 3 };
const VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉";

export interface JraOddsIdentity {
  raceDate: string;
  venue: string;
  raceNo: number;
}

export interface JraActionLink {
  cname: string;
  context: string;
}

export interface JraOfficialOddsPage {
  cname: string;
  betType: CompletedBetType;
  identity: JraOddsIdentity;
  rows: OfficialOddsRow[];
  html: string;
}

export interface JraOfficialOddsCrawlResult {
  rows: OfficialOddsRow[];
  pages: Array<Omit<JraOfficialOddsPage, "html">>;
  fetchedCnames: string[];
  missingBetTypes: CompletedBetType[];
}

function decodeEntity(entity: string): string {
  if (entity === "nbsp") return " ";
  if (entity === "amp") return "&";
  if (entity === "lt") return "<";
  if (entity === "gt") return ">";
  if (entity === "quot") return '"';
  if (entity === "apos" || entity === "#39") return "'";
  if (entity.startsWith("#x") || entity.startsWith("#X")) {
    const value = Number.parseInt(entity.slice(2), 16);
    return Number.isFinite(value) ? String.fromCodePoint(value) : `&${entity};`;
  }
  if (entity.startsWith("#")) {
    const value = Number.parseInt(entity.slice(1), 10);
    return Number.isFinite(value) ? String.fromCodePoint(value) : `&${entity};`;
  }
  return `&${entity};`;
}

export function decodeHtmlEntities(value: string): string {
  return value.replace(/&([a-zA-Z]+|#\d+|#x[0-9a-fA-F]+);/g, (_match, entity: string) => decodeEntity(entity));
}

export function stripJraTags(value: string): string {
  return decodeHtmlEntities(
    value
      .replace(/<script\b[\s\S]*?<\/script>/gi, " ")
      .replace(/<style\b[\s\S]*?<\/style>/gi, " ")
      .replace(/<[^>]+>/g, " "),
  ).replace(/\s+/g, " ").trim();
}

export function jraActionLinks(pageHtml: string): JraActionLink[] {
  const output: JraActionLink[] = [];
  const pattern = /doAction\(\s*['"]\/JRADB\/accessO\.html['"]\s*,\s*['"]([^'"]+)['"]\s*\)/gi;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(pageHtml)) !== null) {
    const begin = Math.max(0, match.index - 1000);
    const start = pageHtml.lastIndexOf("<a", match.index);
    const safeStart = start >= begin ? start : -1;
    const end = pageHtml.indexOf("</a>", match.index + match[0].length);
    const safeEnd = end >= 0 && end <= match.index + match[0].length + 1500 ? end + 4 : -1;
    const contextHtml = safeStart >= 0 && safeEnd >= 0
      ? pageHtml.slice(safeStart, safeEnd)
      : pageHtml.slice(Math.max(0, match.index - 250), Math.min(pageHtml.length, match.index + match[0].length + 250));
    output.push({ cname: decodeHtmlEntities(match[1]), context: stripJraTags(contextHtml) });
  }
  return output;
}

export function jraPageText(pageHtml: string): string {
  const normalized = pageHtml.replace(/<\s*br\s*\/?>|<\/(?:tr|td|th|li|p|div|section|h[1-6])>/gi, "\n");
  const withoutScripts = normalized
    .replace(/<script\b[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ");
  return decodeHtmlEntities(withoutScripts)
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join("\n");
}

function headingText(pageHtml: string): string {
  const values: string[] = [];
  for (const pattern of [/<title[^>]*>([\s\S]*?)<\/title>/gi, /<h[1-4][^>]*>([\s\S]*?)<\/h[1-4]>/gi]) {
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(pageHtml)) !== null) {
      const value = stripJraTags(match[1]);
      if (value) values.push(value);
    }
  }
  return values.join(" | ");
}

export function detectJraBetType(pageHtml: string, hint = ""): CompletedBetType | null {
  const target = `${headingText(pageHtml)} | ${hint}`;
  for (const betType of BET_TYPES) {
    if (target.includes(betType) && target.includes("オッズ")) return betType;
  }
  const compact = jraPageText(pageHtml).slice(0, 3500);
  for (const betType of BET_TYPES) {
    if (new RegExp(`${betType.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*オッズ`).test(compact)) return betType;
  }
  return null;
}

export function parseJraOddsIdentity(pageHtml: string): JraOddsIdentity | null {
  const text = jraPageText(pageHtml);
  const dateMatch = text.match(/(20\d{2})年(\d{1,2})月(\d{1,2})日/);
  const venueMatch = text.match(new RegExp(`\\d+回(${VENUES})\\d+日`));
  const raceMatches = [...text.matchAll(/(?:^|\s)(\d{1,2})(?:レース|R)(?:\s|$)/g)]
    .map((match) => Number.parseInt(match[1], 10));
  const raceNo = raceMatches.find((value) => value >= 1 && value <= 12);
  if (!dateMatch || !venueMatch || raceNo == null) return null;
  return {
    raceDate: `${Number.parseInt(dateMatch[1], 10).toString().padStart(4, "0")}-${Number.parseInt(dateMatch[2], 10).toString().padStart(2, "0")}-${Number.parseInt(dateMatch[3], 10).toString().padStart(2, "0")}`,
    venue: venueMatch[1],
    raceNo,
  };
}

function normalizeCombination(betType: CompletedBetType, horses: number[]): string {
  const values = UNORDERED.has(betType) ? [...horses].sort((a, b) => a - b) : horses;
  return values.join("-");
}

function parseOddsValue(value: string): [number, number] | null {
  const compact = value.replaceAll(",", "").replaceAll("倍", "").trim();
  const match = compact.match(/^(\d+(?:\.\d+)?)\s*(?:[-－–〜～]\s*(\d+(?:\.\d+)?))?$/);
  if (!match) return null;
  const low = Number(match[1]);
  const high = Number(match[2] ?? match[1]);
  if (!Number.isFinite(low) || !Number.isFinite(high) || low <= 1 || high < low || high > 100000) return null;
  return [low, high];
}

function parsedTableRows(pageHtml: string): string[][] {
  const output: string[][] = [];
  for (const row of pageHtml.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const cells = [...row[1].matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)].map((cell) => stripJraTags(cell[1]));
    if (cells.length) output.push(cells);
  }
  return output;
}

export function parseJraOfficialOddsRows(pageHtml: string, betType: CompletedBetType): OfficialOddsRow[] {
  const arity = ARITY[betType];
  const parsed = new Map<string, [number, number]>();
  for (const cells of parsedTableRows(pageHtml)) {
    for (let oddsIndex = 0; oddsIndex < cells.length; oddsIndex += 1) {
      const value = parseOddsValue(cells[oddsIndex]);
      if (!value) continue;
      const before = cells.slice(0, oddsIndex).join(" ");
      const horses = [...before.matchAll(/(?<![.\d])(\d{1,2})(?![.\d])/g)]
        .map((match) => Number.parseInt(match[1], 10))
        .filter((number) => number >= 1 && number <= 18);
      if (horses.length < arity) {
        horses.push(...[...cells[oddsIndex].matchAll(/(?<![.\d])(\d{1,2})(?![.\d])/g)]
          .map((match) => Number.parseInt(match[1], 10))
          .filter((number) => number >= 1 && number <= 18));
      }
      if (horses.length < arity) continue;
      const combinationHorses = horses.slice(-arity);
      if (new Set(combinationHorses).size !== arity) continue;
      const combination = normalizeCombination(betType, combinationHorses);
      const previous = parsed.get(combination);
      if (!previous || value[0] < previous[0]) parsed.set(combination, value);
    }
  }
  return [...parsed.entries()]
    .sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
    .map(([combination, [oddsMin, oddsMax]]) => ({ betType, combination, oddsMin, oddsMax }));
}

function charsetFromContentType(contentType: string | null): string | null {
  const match = contentType?.match(/charset\s*=\s*([^;\s]+)/i);
  return match?.[1]?.replace(/["']/g, "") ?? null;
}

export function decodeJraHtml(bytes: ArrayBuffer, contentType: string | null): string {
  const declared = charsetFromContentType(contentType);
  const candidates = [declared, "shift_jis", "windows-31j", "utf-8"].filter((value, index, self): value is string => Boolean(value) && self.indexOf(value) === index);
  for (const charset of candidates) {
    try {
      return new TextDecoder(charset, { fatal: true }).decode(bytes);
    } catch {
      // Try the next encoding label.
    }
  }
  return new TextDecoder("utf-8").decode(bytes);
}

function blocked(pageHtml: string): boolean {
  return /captcha|アクセスが集中|利用を制限|Access Denied|Forbidden|Service Unavailable/i.test(pageHtml);
}

async function fetchJraHtml(url: string, cname?: string): Promise<string> {
  const headers = new Headers({
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.jra.go.jp/",
  });
  let body: string | undefined;
  let method = "GET";
  if (cname != null) {
    method = "POST";
    body = new URLSearchParams({ cname }).toString();
    headers.set("Content-Type", "application/x-www-form-urlencoded");
  }
  const response = await fetch(url, { method, headers, body, redirect: "follow" });
  if (!response.ok) throw new Error(`JRA_ODDS_HTTP_${response.status}`);
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength > 4_000_000) throw new Error("JRA_ODDS_BODY_TOO_LARGE");
  const pageHtml = decodeJraHtml(bytes, response.headers.get("content-type"));
  if (blocked(pageHtml)) throw new Error("JRA_ODDS_PAGE_BLOCKED");
  return pageHtml;
}

function sameIdentity(a: JraOddsIdentity, b: JraOddsIdentity): boolean {
  return a.raceDate === b.raceDate && a.venue === b.venue && a.raceNo === b.raceNo;
}

export async function crawlJraOfficialOddsForRace(
  entryUrl: string,
  target: JraOddsIdentity,
  options: { maxPages?: number; maxDepth?: number } = {},
): Promise<JraOfficialOddsCrawlResult> {
  const maxPages = options.maxPages ?? 24;
  const maxDepth = options.maxDepth ?? 3;
  const entryHtml = await fetchJraHtml(entryUrl);
  const queue: Array<{ cname: string; hint: string; depth: number }> = [];
  const queued = new Set<string>();
  for (const link of jraActionLinks(entryHtml)) {
    if (!queued.has(link.cname)) {
      queued.add(link.cname);
      queue.push({ cname: link.cname, hint: link.context, depth: 0 });
    }
  }
  if (!queue.length) {
    queued.add(JRA_ODDS_HOME_CNAME);
    queue.push({ cname: JRA_ODDS_HOME_CNAME, hint: "今週のオッズ", depth: 0 });
  }

  const seen = new Set<string>();
  const pages: Array<Omit<JraOfficialOddsPage, "html">> = [];
  const rowsByKey = new Map<string, OfficialOddsRow>();
  const covered = new Set<CompletedBetType>();

  while (queue.length && seen.size < maxPages && covered.size < BET_TYPES.length) {
    const current = queue.shift()!;
    if (seen.has(current.cname)) continue;
    seen.add(current.cname);
    const pageHtml = await fetchJraHtml(JRA_ODDS_URL, current.cname);
    const identity = parseJraOddsIdentity(pageHtml);
    const betType = detectJraBetType(pageHtml, current.hint);
    if (identity && betType && BET_SET.has(betType) && sameIdentity(identity, target)) {
      const rows = parseJraOfficialOddsRows(pageHtml, betType);
      if (rows.length) {
        covered.add(betType);
        pages.push({ cname: current.cname, betType, identity, rows });
        for (const row of rows) rowsByKey.set(`${row.betType}\u0001${row.combination}`, row);
      }
    }
    if (current.depth < maxDepth) {
      for (const link of jraActionLinks(pageHtml)) {
        if (!seen.has(link.cname) && !queued.has(link.cname)) {
          queued.add(link.cname);
          queue.push({ cname: link.cname, hint: link.context, depth: current.depth + 1 });
        }
      }
    }
  }

  return {
    rows: [...rowsByKey.values()],
    pages,
    fetchedCnames: [...seen],
    missingBetTypes: BET_TYPES.filter((betType) => !covered.has(betType)),
  };
}
