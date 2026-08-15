import type { CompletedBetType, OfficialOddsRow } from "./completed-ticket-runtime";
import { JRA_ODDS_URL, decodeJraHtml, jraActionLinks, type JraOddsIdentity } from "./jra-official-odds";
import {
  JRA_FAST_TYPE_PREFIX,
  findFastJraTypeCnames,
  parseFastJraOddsIdentity,
  parseFastJraOfficialOddsRows,
  sameFastJraRaceLink,
} from "./jra-official-odds-fast";

export type { OfficialOddsRow } from "./completed-ticket-runtime";

const USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136 Safari/537.36";
const BET_ORDER: readonly CompletedBetType[] = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"];

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
  source: "jra-fast-official";
}

function sameIdentity(a: JraOddsIdentity | null, b: JraOddsIdentity): boolean {
  return Boolean(a && a.raceDate === b.raceDate && a.venue === b.venue && a.raceNo === b.raceNo);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const headers = new Headers({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": options.referer ?? "https://www.jra.go.jp/",
        "Upgrade-Insecure-Requests": "1",
      });
      const cookie = this.cookieHeader();
      if (cookie) headers.set("Cookie", cookie);
      if (body != null) headers.set("Content-Type", "application/x-www-form-urlencoded");
      try {
        const response = await fetch(url, { method: body == null ? "GET" : "POST", headers, body, redirect: "follow" });
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
        if (lastError.startsWith("JRA_ODDS_HTTP_") || lastError === "JRA_ODDS_BODY_TOO_LARGE") throw error;
        if (attempt < 4) await sleep(350 * (attempt + 1));
      }
    }
    throw new Error(`JRA_ODDS_FETCH_FAILED:${lastError}`);
  }
}

export async function fetchFastJraOfficialOddsForRace(entryUrl: string, target: JraOddsIdentity): Promise<FastJraOddsResult> {
  const session = new JraFetchSession();
  const dateDigits = target.raceDate.replaceAll("-", "");
  const entryHtml = await session.html(entryUrl);
  const entryLinks = jraActionLinks(entryHtml).filter((link) => sameFastJraRaceLink(link.cname, dateDigits, target.raceNo));
  const win = entryLinks.find((link) => link.cname.startsWith(JRA_FAST_TYPE_PREFIX["単勝"]));
  if (!win) throw new Error("WIN_CNAME_NOT_FOUND");

  const winPage = await session.html(JRA_ODDS_URL, { cname: win.cname, referer: entryUrl });
  const winIdentity = parseFastJraOddsIdentity(winPage, win.cname);
  if (!sameIdentity(winIdentity, target)) throw new Error(`WIN_IDENTITY_MISMATCH:${JSON.stringify(winIdentity)}`);
  const winRows = parseFastJraOfficialOddsRows(winPage, "単勝");
  if (winRows.length < 2) throw new Error(`WIN_HORSES_TOO_FEW:${winRows.length}`);
  const pages: FastJraOddsPage[] = [{ cname: win.cname, betType: "単勝", identity: winIdentity!, rows: winRows }];

  const cnames = findFastJraTypeCnames(winPage, dateDigits, target.raceNo);
  for (const betType of ["ワイド", "馬連", "馬単", "3連複", "3連単"] as const) {
    const cname = cnames[betType];
    if (!cname) throw new Error(`${betType}_CNAME_NOT_FOUND`);
    const page = await session.html(JRA_ODDS_URL, { cname, referer: JRA_ODDS_URL });
    const identity = parseFastJraOddsIdentity(page, cname);
    if (!sameIdentity(identity, target)) throw new Error(`${betType}_IDENTITY_MISMATCH:${JSON.stringify(identity)}`);
    const rows = parseFastJraOfficialOddsRows(page, betType);
    if (!rows.length) throw new Error(`${betType}_NO_PARSED_ROWS`);
    pages.push({ cname, betType, identity: identity!, rows });
  }

  if (pages.length !== 6 || BET_ORDER.some((betType) => !pages.some((page) => page.betType === betType))) {
    throw new Error(`JRA_SIX_TYPE_INCOMPLETE:${pages.map((page) => page.betType).join(",")}`);
  }
  return {
    rows: pages.flatMap((page) => page.rows),
    pages,
    entryCnameCount: entryLinks.length,
    fetchedPageCount: 7,
    source: "jra-fast-official",
  };
}
