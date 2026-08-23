import type { CompletedBetType, OfficialOddsRow } from "./completed-ticket-runtime.js";

export const JRA_ODDS_URL = "https://www.jra.go.jp/JRADB/accessO.html";
export const JRA_ODDS_HOME_CNAME = "pw15oli00/6D";
const USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136 Safari/537.36";
const BET_TYPES: readonly CompletedBetType[] = ["3連単", "3連複", "馬単", "馬連", "ワイド", "単勝"];
const UNORDERED = new Set<CompletedBetType>(["ワイド", "馬連", "3連複"]);
const VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉";
const CRAWL_PAGE_TIMEOUT_MS = 3_500;

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
  source: "jra_official";
}

type TableBlock = { attrs: string; body: string; start: number };

export function decodeJraHtml(buffer: ArrayBuffer, contentType: string | null): string {
  const declared = contentType?.match(/charset\s*=\s*([^;\s]+)/i)?.[1]?.replace(/["']/g, "") ?? null;
  const probe = new TextDecoder("windows-1252").decode(buffer.slice(0, Math.min(buffer.byteLength, 8192)));
  const meta = probe.match(/<meta[^>]+charset=["']?([^"'\s/>]+)/i)?.[1] ?? probe.match(/content=["'][^"']*charset=([^"';\s]+)/i)?.[1] ?? null;
  for (const charset of [declared, meta, "shift_jis", "utf-8"].filter(Boolean) as string[]) {
    try { return new TextDecoder(charset).decode(buffer); } catch { /* try next */ }
  }
  return new TextDecoder("utf-8").decode(buffer);
}

export function decodeHtmlEntities(value: string): string {
  return value
    .replace(/&amp;/gi, "&").replace(/&quot;/gi, '"').replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, "<").replace(/&gt;/gi, ">").replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)));
}

export function stripJraTags(value: string): string {
  return decodeHtmlEntities(value.replace(/<script\b[\s\S]*?<\/script>/gi, " ").replace(/<style\b[\s\S]*?<\/style>/gi, " ").replace(/<[^>]+>/g, " "))
    .replace(/[\s\u3000]+/g, " ").trim();
}

export function jraPageText(pageHtml: string): string {
  return stripJraTags(pageHtml.replace(/<\s*br\s*\/?>|<\/(?:tr|td|th|li|p|div|section|h[1-6])>/gi, "\n"));
}

export function jraActionLinks(pageHtml: string): JraActionLink[] {
  const result: JraActionLink[] = [];
  const pattern = /doAction\(\s*['"]\/JRADB\/accessO\.html['"]\s*,\s*['"]([^'"]+)['"]\s*\)/gi;
  for (const match of pageHtml.matchAll(pattern)) {
    const start = Math.max(0, (match.index ?? 0) - 1000);
    const end = Math.min(pageHtml.length, (match.index ?? 0) + match[0].length + 1500);
    result.push({ cname: decodeHtmlEntities(match[1] ?? "").trim(), context: stripJraTags(pageHtml.slice(start, end)) });
  }
  return result;
}

function raceNoFromCname(cname: string): number | null {
  const decoded = decodeURIComponent(decodeHtmlEntities(cname));
  const values = [...decoded.matchAll(/(\d{2})(?=20\d{6}[A-Za-z0-9]*?(?:\/|$))/g)].map((row) => Number(row[1]));
  return [...values].reverse().find((value) => value >= 1 && value <= 12) ?? null;
}

export function parseJraOddsIdentity(pageHtml: string, cname: string): JraOddsIdentity | null {
  const text = jraPageText(pageHtml);
  const heading = text.match(new RegExp(`(20\\d{2})年(\\d{1,2})月(\\d{1,2})日[^\\n]{0,150}?(?:\\d+回)?(${VENUES})(?:\\d+日)?`));
  const raceNo = raceNoFromCname(cname);
  if (!heading || raceNo == null) return null;
  return {
    raceDate: `${heading[1]}-${String(Number(heading[2])).padStart(2, "0")}-${String(Number(heading[3])).padStart(2, "0")}`,
    venue: heading[4],
    raceNo,
  };
}

function classValue(attrs: string): string {
  return attrs.match(/\bclass\s*=\s*(['"])(.*?)\1/i)?.[2] ?? "";
}

function hasClass(attrs: string, token: string): boolean {
  return classValue(attrs).split(/\s+/).includes(token);
}

function tablesByClass(pageHtml: string, token: string): TableBlock[] {
  const out: TableBlock[] = [];
  const pattern = /<table\b([^>]*)>([\s\S]*?)<\/table>/gi;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(pageHtml)) !== null) {
    if (hasClass(match[1] ?? "", token)) out.push({ attrs: match[1] ?? "", body: match[2] ?? "", start: match.index });
  }
  return out;
}

function elementBodies(html: string, tag: "td" | "th" | "span"): Array<{ attrs: string; body: string }> {
  const result: Array<{ attrs: string; body: string }> = [];
  const pattern = new RegExp(`<${tag}\\b([^>]*)>([\\s\\S]*?)<\\/${tag}>`, "gi");
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(html)) !== null) result.push({ attrs: match[1] ?? "", body: match[2] ?? "" });
  return result;
}

function bodyByClass(html: string, tag: "td" | "th" | "span", token: string): string | null {
  return elementBodies(html, tag).find((element) => hasClass(element.attrs, token))?.body ?? null;
}

function horseNumber(text: string): number | null {
  const clean = stripJraTags(text).trim();
  if (!/^\d{1,2}$/.test(clean)) return null;
  const value = Number(clean);
  return Number.isInteger(value) && value >= 1 && value <= 18 ? value : null;
}

function exactOdds(text: string): [number, number] | null {
  const clean = stripJraTags(text).replaceAll(",", "").replaceAll("倍", "").trim();
  const match = clean.match(/^(\d+\.\d+)$/);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isFinite(value) && value >= 1 ? [value, value] : null;
}

function nestedElementBodyByClass(html: string, tag: "span", token: string): string | null {
  const opening = new RegExp(`<${tag}\\b([^>]*)>`, "gi");
  let match: RegExpExecArray | null;
  while ((match = opening.exec(html)) !== null) {
    if (!hasClass(match[1] ?? "", token)) continue;
    const close = html.indexOf(`</${tag}>`, opening.lastIndex);
    if (close < 0) return null;
    return html.slice(opening.lastIndex, close);
  }
  return null;
}

function wideOdds(cellBody: string): [number, number] | null {
  const minBody = nestedElementBodyByClass(cellBody, "span", "min");
  const maxBody = nestedElementBodyByClass(cellBody, "span", "max");
  if (minBody == null || maxBody == null) return null;
  const low = Number(stripJraTags(minBody).replaceAll(",", ""));
  const high = Number(stripJraTags(maxBody).replaceAll(",", ""));
  return Number.isFinite(low) && Number.isFinite(high) && low >= 1 && high >= low ? [low, high] : null;
}

function normalizeCombination(betType: CompletedBetType, horses: number[]): string {
  return (UNORDERED.has(betType) ? [...horses].sort((a, b) => a - b) : horses).join("-");
}

function captionHorses(tableBody: string, expected: number): number[] | null {
  const caption = tableBody.match(/<caption\b[^>]*>([\s\S]*?)<\/caption>/i)?.[1];
  if (caption == null) return null;
  const values = [...stripJraTags(caption).matchAll(/(?<!\d)(\d{1,2})(?!\d)/g)]
    .map((row) => Number(row[1])).filter((value) => value >= 1 && value <= 18);
  if (values.length !== expected || new Set(values).size !== values.length) return null;
  return values;
}

function rowHorseFromScope(rowHtml: string): number | null {
  for (const th of elementBodies(rowHtml, "th")) {
    const scope = th.attrs.match(/\bscope\s*=\s*(['"])(.*?)\1/i)?.[2]?.trim().toLowerCase();
    if (scope === "row") return horseNumber(th.body);
  }
  return null;
}

function exactRowOdds(rowHtml: string): [number, number] | null {
  const cells = elementBodies(rowHtml, "td");
  if (cells.length !== 1) return null;
  return exactOdds(cells[0].body);
}

function parseWinRows(pageHtml: string): OfficialOddsRow[] {
  const rows = new Map<string, [number, number]>();
  for (const table of tablesByClass(pageHtml, "tanpuku")) {
    for (const row of table.body.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
      const rowHtml = row[0] ?? "";
      const numberBody = bodyByClass(rowHtml, "td", "num");
      const oddsBody = bodyByClass(rowHtml, "td", "odds_tan");
      if (numberBody == null || oddsBody == null) continue;
      const number = horseNumber(numberBody);
      const odds = exactOdds(oddsBody);
      if (number == null || odds == null) continue;
      rows.set(String(number), odds);
    }
  }
  return [...rows.entries()].sort(([a], [b]) => Number(a) - Number(b))
    .map(([combination, [oddsMin, oddsMax]]) => ({ betType: "単勝", combination, oddsMin, oddsMax }));
}

function parseGroupedRows(pageHtml: string, betType: Exclude<CompletedBetType, "単勝" | "3連単">, token: string, prefixCount: number): OfficialOddsRow[] {
  const parsed = new Map<string, [number, number]>();
  for (const table of tablesByClass(pageHtml, token)) {
    const prefix = captionHorses(table.body, prefixCount);
    if (!prefix) continue;
    for (const row of table.body.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
      const rowHtml = row[0] ?? "";
      const lastHorse = rowHorseFromScope(rowHtml);
      if (lastHorse == null) continue;
      const horses = [...prefix, lastHorse];
      if (new Set(horses).size !== horses.length) continue;
      let odds: [number, number] | null;
      if (betType === "ワイド") {
        const oddsBody = bodyByClass(rowHtml, "td", "odds");
        odds = oddsBody == null ? null : wideOdds(oddsBody);
      } else {
        odds = exactRowOdds(rowHtml);
      }
      if (!odds) continue;
      const combination = normalizeCombination(betType, horses);
      parsed.set(combination, odds);
    }
  }
  return [...parsed.entries()].sort(([a], [b]) => a.localeCompare(b, "en", { numeric: true }))
    .map(([combination, [oddsMin, oddsMax]]) => ({ betType, combination, oddsMin, oddsMax }));
}

function positionedHorse(context: string, label: "1着" | "2着"): number | null {
  const pattern = new RegExp(`${label}[\\s\\S]{0,500}?<div\\b([^>]*)>([\\s\\S]*?)<\\/div>`, "i");
  const match = pattern.exec(context);
  if (!match || !hasClass(match[1] ?? "", "num")) return null;
  return horseNumber(match[2] ?? "");
}

function parseTrifectaRows(pageHtml: string): OfficialOddsRow[] {
  const parsed = new Map<string, [number, number]>();
  for (const unit of pageHtml.matchAll(/<li\b[^>]*>([\s\S]*?)<\/li>/gi)) {
    const unitHtml = unit[1] ?? "";
    const tables = tablesByClass(unitHtml, "tan3");
    if (tables.length !== 1) continue;
    const table = tables[0];
    const context = unitHtml.slice(0, table.start);
    const first = positionedHorse(context, "1着");
    const second = positionedHorse(context, "2着");
    if (first == null || second == null || first === second) continue;
    for (const row of table.body.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
      const rowHtml = row[0] ?? "";
      const third = rowHorseFromScope(rowHtml);
      const odds = exactRowOdds(rowHtml);
      if (third == null || odds == null || third === first || third === second) continue;
      const combination = `${first}-${second}-${third}`;
      if (parsed.has(combination)) throw new Error(`JRA_TAN3_DUPLICATE_COMBINATION:${combination}`);
      parsed.set(combination, odds);
    }
  }
  return [...parsed.entries()].sort(([a], [b]) => a.localeCompare(b, "en", { numeric: true }))
    .map(([combination, [oddsMin, oddsMax]]) => ({ betType: "3連単", combination, oddsMin, oddsMax }));
}

export function parseJraOfficialOddsRows(pageHtml: string, betType: CompletedBetType): OfficialOddsRow[] {
  if (betType === "単勝") return parseWinRows(pageHtml);
  if (betType === "馬連") return parseGroupedRows(pageHtml, betType, "umaren", 1);
  if (betType === "ワイド") return parseGroupedRows(pageHtml, betType, "wide", 1);
  if (betType === "馬単") return parseGroupedRows(pageHtml, betType, "umatan", 1);
  if (betType === "3連複") return parseGroupedRows(pageHtml, betType, "fuku3", 2);
  return parseTrifectaRows(pageHtml);
}

function guessedBetType(context: string, cname: string): CompletedBetType | null {
  const compact = context.replace(/\s+/g, "");
  for (const betType of BET_TYPES) if (compact.includes(betType)) return betType;
  const prefixes: Array<[string, CompletedBetType]> = [
    ["pw151ou", "単勝"], ["pw154ou", "馬連"], ["pw155ou", "ワイド"], ["pw156ou", "馬単"], ["pw157ou", "3連複"], ["pw158ou", "3連単"],
  ];
  return prefixes.find(([prefix]) => cname.startsWith(prefix))?.[1] ?? null;
}

async function fetchHtml(url: string, cname?: string, referer = "https://www.jra.go.jp/", deadlineMs = Number.POSITIVE_INFINITY): Promise<string> {
  const headers: Record<string, string> = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Cache-Control": "no-cache", Pragma: "no-cache", Referer: referer,
  };
  let body: string | undefined;
  if (cname != null) { body = new URLSearchParams({ cname }).toString(); headers["Content-Type"] = "application/x-www-form-urlencoded"; }
  const remainingBudgetMs = deadlineMs - Date.now();
  if (remainingBudgetMs <= 0) throw new Error("JRA_ODDS_CRAWL_BUDGET_EXHAUSTED");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(1, Math.min(CRAWL_PAGE_TIMEOUT_MS, remainingBudgetMs)));
  let response: Response;
  try {
    response = await fetch(url, { method: body ? "POST" : "GET", headers, body, redirect: "follow", signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) throw new Error(`JRA_ODDS_HTTP_${response.status}`);
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength > 4_000_000) throw new Error("JRA_ODDS_BODY_TOO_LARGE");
  const html = decodeJraHtml(bytes, response.headers.get("content-type"));
  if (/captcha|アクセスが集中|利用を制限|Access Denied|Forbidden|Service Unavailable/i.test(html)) throw new Error("JRA_ODDS_PAGE_BLOCKED");
  return html;
}

export async function crawlJraOfficialOddsForRace(entryUrl: string, target: JraOddsIdentity, deadlineMs = Number.POSITIVE_INFINITY): Promise<JraOfficialOddsCrawlResult> {
  const entryHtml = await fetchHtml(entryUrl, undefined, "https://www.jra.go.jp/", deadlineMs);
  const queue = jraActionLinks(entryHtml).map((link) => link.cname);
  const seen = new Set<string>(); const pages: JraOfficialOddsPage[] = [];
  while (queue.length && seen.size < 40 && Date.now() < deadlineMs) {
    const cname = queue.shift()!;
    if (seen.has(cname)) continue;
    seen.add(cname);
    try {
      const page = await fetchHtml(JRA_ODDS_URL, cname, JRA_ODDS_URL, deadlineMs);
      const identity = parseJraOddsIdentity(page, cname);
      if (!identity || identity.raceDate !== target.raceDate || identity.venue !== target.venue || identity.raceNo !== target.raceNo) continue;
      const links = jraActionLinks(page);
      for (const link of links) if (!seen.has(link.cname)) queue.push(link.cname);
      const betType = guessedBetType(links.map((link) => link.context).join(" ") + " " + jraPageText(page).slice(0, 5000), cname);
      if (!betType) continue;
      const rows = parseJraOfficialOddsRows(page, betType);
      if (rows.length) pages.push({ cname, betType, identity, rows, html: page });
    } catch { /* crawl continues */ }
  }
  const best = new Map<CompletedBetType, JraOfficialOddsPage>();
  for (const page of pages) if (!best.has(page.betType) || page.rows.length > best.get(page.betType)!.rows.length) best.set(page.betType, page);
  const selected = [...best.values()];
  return {
    rows: selected.flatMap((page) => page.rows),
    pages: selected.map(({ html: _html, ...page }) => page),
    fetchedCnames: [...seen],
    missingBetTypes: BET_TYPES.filter((betType) => !best.has(betType)),
    source: "jra_official",
  };
}
