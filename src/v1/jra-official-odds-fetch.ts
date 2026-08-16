import type { CompletedBetType, OfficialOddsRow } from "./completed-ticket-runtime.js";
import {
  crawlJraOfficialOddsForRace,
  decodeJraHtml,
  jraActionLinks,
  type JraOddsIdentity,
} from "./jra-official-odds.js";
import {
  JRA_FAST_TYPE_PREFIX,
  findFastJraTypeCnames,
  parseFastJraOddsIdentity,
  parseFastJraOfficialOddsRows,
  sameFastJraRaceLink,
} from "./jra-official-odds-fast.js";

export type { OfficialOddsRow } from "./completed-ticket-runtime.js";

const USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136 Safari/537.36";
const BET_ORDER: readonly CompletedBetType[] = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"];
const SECONDARY_TYPES = ["ワイド", "馬連", "馬単", "3連複", "3連単"] as const;
const TYPE_FETCH_CONCURRENCY = 2;
const JRA_HOSTS = ["sp.jra.jp", "www.jra.go.jp", "jra.jp"] as const;
const PAGE_TIMEOUT_MS = 4_500;
const PAGE_ATTEMPTS = 3;

export interface FastJraOddsPage {
  cname: string;
  betType: CompletedBetType;
  identity: JraOddsIdentity;
  rows: OfficialOddsRow[];
}

export interface FastJraOddsResult {
  rows: OfficialOddsRow[];
  pages: FastJraOddsPage[];
  entryCnameCount: number;
  fetchedPageCount: number;
  source: "jra-fast-official" | "jra-crawl-official";
  fallbackReason?: string;
  entryUrl?: string;
  oddsUrl?: string;
  sourceHost?: string;
  attemptedHosts?: string[];
}

function sameIdentity(a: JraOddsIdentity | null, b: JraOddsIdentity): boolean {
  return Boolean(a && a.raceDate === b.raceDate && a.venue === b.venue && a.raceNo === b.raceNo);
}

function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}:${error.message}` : String(error);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function candidateJraEntryUrls(rawUrl: string): string[] {
  const urls: string[] = [];
  const add = (value: string) => { if (value && !urls.includes(value)) urls.push(value); };
  add(rawUrl);
  try {
    const parsed = new URL(rawUrl);
    for (const host of JRA_HOSTS) {
      const candidate = new URL(parsed.toString());
      candidate.hostname = host;
      add(candidate.toString());
    }
  } catch {
    // Keep the original value so the caller gets a useful URL/fetch error.
  }
  return urls;
}

export function jraOddsUrlForEntry(entryUrl: string): string {
  const parsed = new URL(entryUrl);
  return new URL("/JRADB/accessO.html", parsed.origin).toString();
}

class JraFetchSession {
  private cookies = new Map<string, string>();

  private cookieHeader(): string {
    return [...this.cookies.entries()].map(([key, value]) => `${key}=${value}`).join("; ");
  }

  private rememberCookies(response: Response): void {
    const setCookie = response.headers.get("set-cookie");
    if (!setCookie) return;
    for (const segment of setCookie.split(/,(?=[^;,]+=)/)) {
      const pair = segment.split(";", 1)[0];
      const index = pair.indexOf("=");
      if (index > 0) this.cookies.set(pair.slice(0, index).trim(), pair.slice(index + 1).trim());
    }
  }

  async html(url: string, options: { cname?: string; referer?: string } = {}): Promise<string> {
    const body = options.cname == null ? undefined : new URLSearchParams({ cname: options.cname }).toString();
    let lastError = "unknown";
    for (let attempt = 0; attempt < PAGE_ATTEMPTS; attempt += 1) {
      const headers = new Headers({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": options.referer ?? new URL(url).origin,
        "Upgrade-Insecure-Requests": "1",
      });
      const cookie = this.cookieHeader();
      if (cookie) headers.set("Cookie", cookie);
      if (body != null) headers.set("Content-Type", "application/x-www-form-urlencoded");
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), PAGE_TIMEOUT_MS);
      try {
        const response = await fetch(url, { method: body == null ? "GET" : "POST", headers, body, redirect: "follow", signal: controller.signal });
        this.rememberCookies(response);
        if (!response.ok) {
          const retryable = [408, 425, 429, 500, 502, 503, 504].includes(response.status);
          if (!retryable) throw new Error(`JRA_ODDS_HTTP_${response.status}`);
          throw new Error(`JRA_ODDS_RETRYABLE_HTTP_${response.status}`);
        }
        const bytes = await response.arrayBuffer();
        if (bytes.byteLength > 4_000_000) throw new Error("JRA_ODDS_BODY_TOO_LARGE");
        const html = decodeJraHtml(bytes, response.headers.get("content-type"));
        if (/captcha|アクセスが集中|利用を制限|Access Denied|Forbidden|Service Unavailable/i.test(html)) throw new Error("JRA_ODDS_PAGE_BLOCKED");
        return html;
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error);
        if (lastError.startsWith("JRA_ODDS_HTTP_") || lastError === "JRA_ODDS_BODY_TOO_LARGE" || lastError === "JRA_ODDS_PAGE_BLOCKED") throw error;
        if (attempt < PAGE_ATTEMPTS - 1) await sleep(250 * (attempt + 1) * (attempt + 1));
      } finally {
        clearTimeout(timer);
      }
    }
    throw new Error(`JRA_ODDS_FETCH_FAILED:${lastError}`);
  }
}

function completePages(pages: FastJraOddsPage[]): void {
  if (pages.length !== 6 || BET_ORDER.some((betType) => !pages.some((page) => page.betType === betType))) {
    throw new Error(`JRA_SIX_TYPE_INCOMPLETE:${pages.map((page) => page.betType).join(",")}`);
  }
}

async function fetchFastDirect(entryUrl: string, target: JraOddsIdentity): Promise<FastJraOddsResult> {
  const session = new JraFetchSession();
  const dateDigits = target.raceDate.replaceAll("-", "");
  const oddsUrl = jraOddsUrlForEntry(entryUrl);
  const entryHtml = await session.html(entryUrl);
  const entryLinks = jraActionLinks(entryHtml).filter((link) => sameFastJraRaceLink(link.cname, dateDigits, target.raceNo));
  const entryCnames = findFastJraTypeCnames(entryHtml, dateDigits, target.raceNo);
  const winCname = entryCnames["単勝"] ?? entryLinks.find((link) => link.cname.startsWith(JRA_FAST_TYPE_PREFIX["単勝"]))?.cname;
  if (!winCname) throw new Error("WIN_CNAME_NOT_FOUND");

  const winPage = await session.html(oddsUrl, { cname: winCname, referer: entryUrl });
  const winIdentity = parseFastJraOddsIdentity(winPage, winCname);
  if (!sameIdentity(winIdentity, target)) throw new Error(`WIN_IDENTITY_MISMATCH:${JSON.stringify(winIdentity)}`);
  const winRows = parseFastJraOfficialOddsRows(winPage, "単勝");
  if (winRows.length < 2) throw new Error(`WIN_HORSES_TOO_FEW:${winRows.length}`);
  const pages: FastJraOddsPage[] = [{ cname: winCname, betType: "単勝", identity: winIdentity!, rows: winRows }];

  // Do not depend on a single page containing every navigation CNAME. Merge
  // discovery from both the entry page and the first odds page.
  const winPageCnames = findFastJraTypeCnames(winPage, dateDigits, target.raceNo);
  const cnames: Partial<Record<CompletedBetType, string>> = { ...entryCnames, ...winPageCnames, "単勝": winCname };

  // Keep bounded concurrency: faster than fully serial requests without firing
  // all five secondary pages at JRA simultaneously.
  let nextIndex = 0;
  const fetched = new Map<CompletedBetType, FastJraOddsPage>();
  await Promise.all(Array.from({ length: TYPE_FETCH_CONCURRENCY }, async () => {
    while (true) {
      const index = nextIndex;
      nextIndex += 1;
      if (index >= SECONDARY_TYPES.length) return;
      const betType = SECONDARY_TYPES[index];
      const cname = cnames[betType];
      if (!cname) throw new Error(`${betType}_CNAME_NOT_FOUND`);
      const page = await session.html(oddsUrl, { cname, referer: oddsUrl });
      const identity = parseFastJraOddsIdentity(page, cname);
      if (!sameIdentity(identity, target)) throw new Error(`${betType}_IDENTITY_MISMATCH:${JSON.stringify(identity)}`);
      const rows = parseFastJraOfficialOddsRows(page, betType);
      if (!rows.length) throw new Error(`${betType}_NO_PARSED_ROWS`);
      fetched.set(betType, { cname, betType, identity: identity!, rows });
    }
  }));
  for (const betType of SECONDARY_TYPES) {
    const page = fetched.get(betType);
    if (!page) throw new Error(`${betType}_FETCH_RESULT_MISSING`);
    pages.push(page);
  }

  completePages(pages);
  return {
    rows: pages.flatMap((page) => page.rows),
    pages,
    entryCnameCount: entryLinks.length,
    fetchedPageCount: 7,
    source: "jra-fast-official",
    entryUrl,
    oddsUrl,
    sourceHost: new URL(oddsUrl).hostname,
  };
}

async function fetchOfficialCrawlFallback(entryUrl: string, target: JraOddsIdentity, fastError: unknown): Promise<FastJraOddsResult> {
  const crawl = await crawlJraOfficialOddsForRace(entryUrl, target);
  if (crawl.missingBetTypes.length) {
    throw new Error(`JRA_OFFICIAL_ALL_PATHS_FAILED:fast=${errorText(fastError)};crawl_missing=${crawl.missingBetTypes.join(",")}`);
  }
  const pages: FastJraOddsPage[] = [];
  for (const betType of BET_ORDER) {
    const page = crawl.pages.find((row) => row.betType === betType);
    if (!page || !page.rows.length || !sameIdentity(page.identity, target)) {
      throw new Error(`JRA_OFFICIAL_ALL_PATHS_FAILED:fast=${errorText(fastError)};crawl_invalid=${betType}`);
    }
    pages.push({ cname: page.cname, betType, identity: page.identity, rows: page.rows });
  }
  completePages(pages);
  return {
    rows: pages.flatMap((page) => page.rows),
    pages,
    entryCnameCount: 0,
    fetchedPageCount: crawl.fetchedCnames.length + 1,
    source: "jra-crawl-official",
    fallbackReason: errorText(fastError),
  };
}

export async function fetchFastJraOfficialOddsForRace(entryUrl: string, target: JraOddsIdentity): Promise<FastJraOddsResult> {
  const candidates = candidateJraEntryUrls(entryUrl);
  const attemptedHosts: string[] = [];
  const fastErrors: string[] = [];

  for (const candidate of candidates) {
    let host = candidate;
    try { host = new URL(candidate).hostname; } catch { /* keep raw value */ }
    if (!attemptedHosts.includes(host)) attemptedHosts.push(host);
    try {
      const result = await fetchFastDirect(candidate, target);
      return { ...result, attemptedHosts };
    } catch (error) {
      fastErrors.push(`${host}:${errorText(error)}`);
    }
  }

  const aggregateFastError = new Error(`JRA_ODDS_FAST_ALL_HOSTS_FAILED:${fastErrors.join("|")}`);
  try {
    const crawl = await fetchOfficialCrawlFallback(entryUrl, target, aggregateFastError);
    return { ...crawl, attemptedHosts };
  } catch (crawlError) {
    throw new Error(`JRA_ODDS_ALL_PATHS_FAILED:fast=${fastErrors.join("|")};crawl=${errorText(crawlError)}`);
  }
}
