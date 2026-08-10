import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { getArchiveResultUrls } from "../src/v1/three-month-archive.js";
import { parseDesktopPayouts, parseDesktopResultRunners } from "../src/v1/three-month-desktop.js";
import { decodeEntities } from "../src/v1/utils.js";

const YEAR_MONTH = process.argv[2] ?? "201608";
const OUTPUT = resolve(process.argv[3] ?? `analysis-results/research-result-pilot-${YEAR_MONTH}.json`);
const USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/136 Safari/537.36";
const VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉";

function decodePage(buffer: ArrayBuffer, contentType: string | null): string {
  const declared = contentType?.match(/charset\s*=\s*([^;\s]+)/i)?.[1]?.replace(/["']/g, "") ?? null;
  const probe = new TextDecoder("windows-1252").decode(buffer.slice(0, Math.min(buffer.byteLength, 8192)));
  const meta = probe.match(/<meta[^>]+charset=["']?([^"'\s/>]+)/i)?.[1]
    ?? probe.match(/content=["'][^"']*charset=([^"';\s]+)/i)?.[1]
    ?? null;
  for (const charset of [declared, meta, "shift_jis", "utf-8"].filter((value): value is string => Boolean(value))) {
    try { return new TextDecoder(charset).decode(buffer); } catch { /* next */ }
  }
  return new TextDecoder("utf-8").decode(buffer);
}

async function fetchHtml(url: string): Promise<string> {
  let lastError: unknown = null;
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: { "User-Agent": USER_AGENT, "Accept-Language": "ja-JP,ja;q=0.9", Referer: "https://www.jra.go.jp/" },
        redirect: "follow"
      });
      if (!response.ok) throw new Error(`HTTP_${response.status}`);
      const buffer = await response.arrayBuffer();
      if (buffer.byteLength > 3_000_000) throw new Error("BODY_TOO_LARGE");
      const html = decodePage(buffer, response.headers.get("content-type"));
      if (/captcha|アクセスが集中|利用を制限|Forbidden|Access Denied|Service Unavailable/i.test(html)) {
        throw new Error("BLOCKED_PAGE");
      }
      return html;
    } catch (error) {
      lastError = error;
      await new Promise((resolveDelay) => setTimeout(resolveDelay, attempt * 800));
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

function plainText(html: string): string {
  return decodeEntities(html)
    .replace(/<script\b[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/[０-９]/g, (char) => String(char.charCodeAt(0) - 0xfee0))
    .replace(/[－–—−]/g, "-")
    .replace(/\s+/g, " ")
    .trim();
}

function urlCname(url: string): string {
  const parsed = new URL(url);
  return decodeURIComponent(parsed.searchParams.get("CNAME") ?? parsed.searchParams.get("cname") ?? "");
}

function identity(html: string, url: string): { raceDate: string; venue: string; raceNo: number } | null {
  const text = plainText(html);
  const date = text.match(/(20\d{2})年(\d{1,2})月(\d{1,2})日/);
  const venue = text.match(new RegExp(`\\d+回(${VENUES})\\d+日`));
  const cname = urlCname(url);
  const cnameDates = [...cname.matchAll(/20\d{6}/g)].map((match) => match[0]);
  const raceMatches = [...cname.matchAll(/(\d{2})(?=20\d{6}[A-Za-z0-9]*?(?:\/|$))/g)]
    .map((match) => Number(match[1]))
    .filter((value) => value >= 1 && value <= 12);
  const raceText = [...text.matchAll(/(?:^|\s)(\d{1,2})(?:レース|R)(?:\s|$)/g)]
    .map((match) => Number(match[1]))
    .find((value) => value >= 1 && value <= 12);
  const raceNo = raceText ?? raceMatches.at(-1) ?? null;
  const raceDate = date
    ? `${date[1]}-${String(Number(date[2])).padStart(2, "0")}-${String(Number(date[3])).padStart(2, "0")}`
    : cnameDates.length
      ? `${cnameDates.at(-1)!.slice(0, 4)}-${cnameDates.at(-1)!.slice(4, 6)}-${cnameDates.at(-1)!.slice(6, 8)}`
      : null;
  if (!raceDate || !venue?.[1] || !raceNo) return null;
  return { raceDate, venue: venue[1], raceNo };
}

function normalizedCell(value: string): string {
  return decodeEntities(value)
    .replace(/<img\b[^>]*alt=["']([^"']*)["'][^>]*>/gi, " $1 ")
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/[０-９]/g, (char) => String(char.charCodeAt(0) - 0xfee0))
    .replace(/\s+/g, " ")
    .trim();
}

function results(html: string): Array<{ horseNo: number; finishPosition: number | null; final3f: number | null }> {
  const rows: Array<{ horseNo: number; finishPosition: number | null; final3f: number | null }> = [];
  for (const tr of html.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const cells = [...(tr[1] ?? "").matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)].map((cell) => normalizedCell(cell[1] ?? ""));
    if (cells.length < 11 || !/^\d{1,2}$/.test(cells[2] ?? "")) continue;
    const horseNo = Number(cells[2]);
    const finish = (cells[0] ?? "").match(/^\d{1,2}$/) ? Number(cells[0]) : null;
    const final3fText = (cells[10] ?? "").match(/\d{2}\.\d/);
    rows.push({ horseNo, finishPosition: finish, final3f: final3fText ? Number(final3fText[0]) : null });
  }
  return [...new Map(rows.map((row) => [row.horseNo, row])).values()].sort((a, b) => a.horseNo - b.horseNo);
}

function resultKey(row: { raceDate: string; venue: string; raceNo: number }): string {
  return `${row.raceDate}-${row.venue}-${String(row.raceNo).padStart(2, "0")}`;
}

async function main(): Promise<void> {
  if (!/^20\d{4}$/.test(YEAR_MONTH)) throw new Error(`INVALID_YEAR_MONTH:${YEAR_MONTH}`);
  const urls = await getArchiveResultUrls(YEAR_MONTH);
  const races: unknown[] = [];
  const errors: string[] = [];
  const seen = new Set<string>();

  for (let index = 0; index < urls.length; index += 1) {
    const url = urls[index]!;
    try {
      const html = await fetchHtml(url);
      const id = identity(html, url);
      if (!id) throw new Error("IDENTITY_NOT_FOUND");
      if (!id.raceDate.startsWith(`${YEAR_MONTH.slice(0, 4)}-${YEAR_MONTH.slice(4, 6)}`)) continue;
      const key = resultKey(id);
      if (seen.has(key)) continue;
      seen.add(key);

      const parsedRunners = parseDesktopResultRunners(html).map((runner) => ({
        ...runner,
        // Research rule: never treat popularity-derived synthetic odds as official historical odds.
        winOdds: null
      }));
      const parsedResults = results(html);
      const payouts = parseDesktopPayouts(html);
      const activeRunners = parsedRunners.filter((runner) => runner.runnerStatus === "active");
      if (activeRunners.length < 2) throw new Error(`ACTIVE_RUNNERS_TOO_FEW:${activeRunners.length}`);
      if (parsedResults.filter((row) => row.finishPosition !== null).length < 2) {
        throw new Error(`RESULT_ROWS_TOO_FEW:${parsedResults.length}`);
      }
      if (!payouts.some((row) => row.betType === "単勝") || !payouts.some((row) => row.betType === "3連単")) {
        throw new Error(`PAYOUT_TYPES_INCOMPLETE:${[...new Set(payouts.map((row) => row.betType))].join(",")}`);
      }
      races.push({ ...id, raceKey: key, sourceUrl: url, runners: parsedRunners, results: parsedResults, payouts });
      if ((races.length % 50) === 0) console.log(JSON.stringify({ progress: races.length, totalUrls: urls.length }));
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 180));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      errors.push(`${url}:${message}`);
    }
  }

  const byDateVenue = new Map<string, number>();
  for (const raw of races as Array<{ raceDate: string; venue: string }>) {
    const key = `${raw.raceDate}|${raw.venue}`;
    byDateVenue.set(key, (byDateVenue.get(key) ?? 0) + 1);
  }
  const incompleteVenueDays = [...byDateVenue.entries()].filter(([, count]) => count !== 12);
  const report = {
    generatedAtUtc: new Date().toISOString(),
    mode: "research_only_official_result_pages",
    yearMonth: YEAR_MONTH,
    archiveResultUrlCount: urls.length,
    uniqueRaceCount: races.length,
    errorCount: errors.length,
    errors: errors.slice(0, 100),
    venueDayCount: byDateVenue.size,
    incompleteVenueDays,
    syntheticWinOddsStored: false,
    runnerPopularityStored: true,
    officialOddsStored: false,
    races
  };
  await mkdir(dirname(OUTPUT), { recursive: true });
  await writeFile(OUTPUT, `${JSON.stringify(report)}\n`, "utf8");
  console.log(JSON.stringify({
    yearMonth: YEAR_MONTH,
    urls: urls.length,
    races: races.length,
    errors: errors.length,
    venueDays: byDateVenue.size,
    incompleteVenueDays: incompleteVenueDays.length,
    syntheticWinOddsStored: false
  }));
  if (errors.length || incompleteVenueDays.length || races.length < 100) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
