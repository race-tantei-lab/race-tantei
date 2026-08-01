import type { RaceBundle, RaceRecord, ResultRecord, RunnerRecord, PayoutRecord } from "./types.js";
import { decodeEntities, htmlToLines, parseJapaneseDateTime, stripHtml, tableRows } from "./utils.js";

const ALLOWED_HOSTS = new Set(["sp.jra.jp", "www.jra.go.jp", "jra.jp"]);
const MAX_BODY_BYTES = 2_500_000;
const FETCH_TIMEOUT_MS = 15_000;

export interface FetchPageResult {
  url: string;
  html: string;
  status: number;
  contentType: string | null;
}

function validateUrl(rawUrl: string): URL {
  const url = new URL(rawUrl);
  if (url.protocol !== "https:") throw new Error("HTTPS_REQUIRED");
  if (!ALLOWED_HOSTS.has(url.hostname)) throw new Error("HOST_NOT_ALLOWED");
  return url;
}

export async function fetchJraPage(rawUrl: string, fetchImpl: typeof fetch = fetch): Promise<FetchPageResult> {
  const initial = validateUrl(rawUrl);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetchImpl(initial, {
      redirect: "follow",
      signal: controller.signal,
      headers: {
        Accept: "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        "Accept-Language": "ja,en;q=0.5",
        "Cache-Control": "no-cache",
        "User-Agent": "race-tantei/1.0 (non-commercial prediction record; low-frequency fetch)"
      }
    });
    const finalUrl = validateUrl(response.url || initial.toString());
    const contentLength = Number(response.headers.get("content-length") ?? "0");
    if (contentLength > MAX_BODY_BYTES) throw new Error("BODY_TOO_LARGE");
    const buffer = await response.arrayBuffer();
    if (buffer.byteLength > MAX_BODY_BYTES) throw new Error("BODY_TOO_LARGE");
    const contentType = response.headers.get("content-type");
    const declared = contentType?.match(/charset\s*=\s*([^;\s]+)/i)?.[1]?.replace(/["']/g, "") ?? null;
    let charset = declared ?? "utf-8";
    if (!declared) {
      const ascii = new TextDecoder("windows-1252").decode(buffer.slice(0, Math.min(buffer.byteLength, 4096)));
      charset = ascii.match(/<meta[^>]+charset=["']?([^"'\s/>]+)/i)?.[1] ??
        ascii.match(/content=["'][^"']*charset=([^"';\s]+)/i)?.[1] ?? "utf-8";
    }
    let html: string;
    try {
      html = new TextDecoder(charset).decode(buffer);
    } catch {
      html = new TextDecoder("utf-8").decode(buffer);
    }
    if (!response.ok) throw new Error(`HTTP_${response.status}`);
    if (/captcha|アクセスが集中|利用を制限|Forbidden|Access Denied/i.test(html)) {
      throw new Error("BLOCKED_PAGE");
    }
    return {
      url: finalUrl.toString(),
      html,
      status: response.status,
      contentType
    };
  } finally {
    clearTimeout(timer);
  }
}

export function extractEntryLinks(html: string, baseUrl: string): string[] {
  const links = new Set<string>();
  for (const match of html.matchAll(/href\s*=\s*["']([^"']+)["']/gi)) {
    const href = decodeEntities(match[1] ?? "");
    try {
      const url = new URL(href, baseUrl);
      if (!ALLOWED_HOSTS.has(url.hostname)) continue;
      if (!/\/JRADB\/accessD\.html$/i.test(url.pathname)) continue;
      if (!/CNAME=sw01dde/i.test(url.search)) continue;
      links.add(url.toString());
    } catch {
      // Ignore malformed navigation links.
    }
  }
  return [...links];
}

export function toResultUrl(entryUrl: string): string {
  const url = validateUrl(entryUrl);
  url.pathname = url.pathname.replace(/accessD\.html$/i, "accessS.html");
  const cname = url.searchParams.get("CNAME");
  if (cname) url.searchParams.set("CNAME", cname.replace("sw01dde", "sw01sde"));
  return url.toString();
}

function venueSlug(venue: string): string {
  const map: Record<string, string> = {
    札幌: "sapporo",
    函館: "hakodate",
    福島: "fukushima",
    新潟: "niigata",
    東京: "tokyo",
    中山: "nakayama",
    中京: "chukyo",
    京都: "kyoto",
    阪神: "hanshin",
    小倉: "kokura"
  };
  return map[venue] ?? encodeURIComponent(venue);
}

function normalizeText(html: string): string {
  return stripHtml(
    html
      .replace(/<\/(?:td|th|tr|li|p|div|section|article|h[1-6]|dt|dd|ul|ol|table)>/gi, "\n")
      .replace(/<\s*br\s*\/?>/gi, "\n")
  );
}

function parseHeader(html: string, entryUrl: string, isResult: boolean): RaceRecord {
  const text = normalizeText(html);
  const dateVenue = text.match(/(20\d{2})年(\d{1,2})月(\d{1,2})日[^\n]*?(\d+)回(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)(\d+)日/);
  const raceLine = text.match(/(?:^|\n)\s*(\d{1,2})R\s+([^\n]+)/m);
  if (!dateVenue || !raceLine) throw new Error("RACE_HEADER_NOT_FOUND");

  const year = Number(dateVenue[1] ?? 0);
  const month = Number(dateVenue[2] ?? 0);
  const day = Number(dateVenue[3] ?? 0);
  const meetingNo = Number(dateVenue[4] ?? 0);
  const venue = dateVenue[5] ?? "";
  const meetingDay = Number(dateVenue[6] ?? 0);
  const raceNo = Number(raceLine[1] ?? 0);
  const raceName = (raceLine[2] ?? "").trim();
  const raceDate = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;

  const course = text.match(/コース\s*(\d+)m\s*(芝|ダート|障害)(?:・(右|左|直線))?\s*発走\s*(\d{1,2}:\d{2})/);
  const conditionsMatch = text.match(new RegExp(`${raceLine[1]}R\\s+[^\\n]+\\n([^\\n]+)`));
  const weather = text.match(/天候\s*[:：]\s*([^\s\n]+)/)?.[1] ?? null;
  const trackCondition = text.match(/(?:芝|ダート)\s*[:：]\s*([^\s\n]+)/)?.[1] ?? null;
  const startTimeJst = course?.[4] ?? null;
  const entry = isResult
    ? entryUrl.replace(/accessS\.html/i, "accessD.html").replace("sw01sde", "sw01dde")
    : entryUrl;

  return {
    raceId: `${raceDate}-${venueSlug(venue)}-${String(raceNo).padStart(2, "0")}`,
    raceDate,
    venue,
    meetingNo,
    meetingDay,
    raceNo,
    raceName,
    conditions: conditionsMatch?.[1]?.trim() ?? null,
    surface: course?.[2] ?? null,
    distanceM: course ? Number(course[1]) : null,
    direction: course?.[3] ?? null,
    startTimeJst,
    startTimeUtc: parseJapaneseDateTime(year, month, day, startTimeJst),
    weather,
    trackCondition,
    entryUrl: entry,
    resultUrl: toResultUrl(entry),
    status: isResult ? "finished" : "scheduled"
  };
}

function firstHorseName(text: string): string | null {
  const cleaned = text.replace(/前[４4]走[\s\S]*/u, "").trim();
  const match = cleaned.match(/^(.+?)(?=\s+(?:\d+(?:\.\d+)?\s*\(|除外|取消|牡\d|牝\d|せん\d|騸\d))/u);
  if (match?.[1]) return match[1].trim();
  const token = cleaned.split(/\s+/)[0];
  return token && token.length >= 2 ? token : null;
}

function numericCellsBefore(cells: string[], detailIndex: number): number[] {
  return cells.slice(0, detailIndex)
    .map((cell) => cell.match(/^\s*(\d{1,2})\s*$/)?.[1])
    .filter((value): value is string => Boolean(value))
    .map(Number);
}

function parseEntryRows(html: string): RunnerRecord[] {
  const runners = new Map<number, RunnerRecord>();
  const rows = tableRows(html);
  for (const cells of rows) {
    const joined = cells.join(" ");
    if (!/(?:番人気|初出走|kg|除外|取消)/.test(joined)) continue;
    const detailIndex = cells.findIndex((cell) => /(?:番人気|初出走|kg|除外|取消)/.test(cell));
    if (detailIndex < 0) continue;
    const nums = numericCellsBefore(cells, detailIndex);
    let horseNo = nums.at(-1) ?? null;
    const status: RunnerRecord["runnerStatus"] = /除外/.test(joined) ? "excluded" : /取消/.test(joined) ? "scratched" : "active";
    if (horseNo === null && status !== "active") {
      const fallback = joined.match(/(?:馬番\s*)?(\d{1,2})/);
      horseNo = fallback ? Number(fallback[1]) : null;
    }
    if (!horseNo || horseNo > 18) continue;
    const frameNo = nums.length >= 2 ? nums[0] : null;
    const horseName = firstHorseName(cells[detailIndex] ?? "") ?? firstHorseName(joined);
    if (!horseName) continue;
    const sexAge = joined.match(/(牡|牝|せん|騸)\s*(\d+)/u);
    const coat = joined.match(/(?:牡|牝|せん|騸)\s*\d+\s*[／/]\s*([^\s/]+)\s+/u);
    const weight = joined.match(/(\d{3})kg\s*\(([^)]*)\)/i);
    const odds = joined.match(/(\d+(?:\.\d+)?)\s*\((\d+)番人気\)/);
    const people = joined.match(/([▲△☆◇]?[ぁ-んァ-ヶ一-龠々・ー]+)\s*\((\d+(?:\.\d+)?)\)\s+([ぁ-んァ-ヶ一-龠々・ー]+)\s*\((美浦|栗東)\)/u);
    const weightChangeText = weight?.[2]?.replace(/初出走/g, "").trim() ?? "";
    const weightChange = /^[+-]?\d+$/.test(weightChangeText) ? Number(weightChangeText) : null;

    runners.set(horseNo, {
      horseNo,
      frameNo: frameNo ?? null,
      horseName,
      sexAge: sexAge ? `${sexAge[1]}${sexAge[2]}` : null,
      coatColor: coat?.[1] ?? null,
      horseWeight: weight ? Number(weight[1]) : null,
      weightChange,
      jockey: people?.[1]?.replace(/^[▲△☆◇]/u, "") ?? null,
      assignedWeight: people ? Number(people[2]) : null,
      trainer: people?.[3] ?? null,
      stable: people?.[4] ?? null,
      winOdds: odds ? Number(odds[1]) : null,
      popularity: odds ? Number(odds[2]) : null,
      runnerStatus: status
    });
  }
  return [...runners.values()].sort((a, b) => a.horseNo - b.horseNo);
}

function parseResultRows(html: string): ResultRecord[] {
  const results = new Map<number, ResultRecord>();
  for (const cells of tableRows(html)) {
    const joined = cells.join(" ");
    if (!/(?:\d+:\d{2}\.\d|除外|中止|失格|取消)/.test(joined)) continue;
    const first = cells[0]?.trim() ?? "";
    const finish = /^\d{1,2}$/.test(first) ? Number(first) : null;
    const detailIndex = cells.findIndex((cell) => /(?:番人気|kg|除外|中止|失格|取消)/.test(cell));
    if (detailIndex < 0) continue;
    const nums = numericCellsBefore(cells, detailIndex);
    const horseNo = nums.at(-1) ?? null;
    if (!horseNo || horseNo > 18) continue;
    const time = joined.match(/(\d+:\d{2}\.\d)/)?.[1] ?? null;
    const final3f = joined.match(/(?:\/|上り)\s*(\d{2}\.\d)(?:\s|$)/)?.[1] ?? null;
    const margin = time ? joined.match(new RegExp(`${time.replace(".", "\\.")}\\s*\\(([^)]+)\\)`))?.[1] ?? null : null;
    const status = /除外/.test(joined) ? "excluded" : /取消/.test(joined) ? "scratched" : /中止/.test(joined) ? "dnf" : /失格/.test(joined) ? "disqualified" : "finished";
    results.set(horseNo, {
      horseNo,
      finishPosition: finish,
      resultStatus: status,
      timeText: time,
      marginText: margin,
      final3f: final3f ? Number(final3f) : null
    });
  }
  return [...results.values()].sort((a, b) => (a.finishPosition ?? 99) - (b.finishPosition ?? 99));
}

function parsePayoutRows(html: string): PayoutRecord[] {
  const payouts: PayoutRecord[] = [];
  let currentType = "";
  for (const cells of tableRows(html)) {
    const joined = cells.join(" ");
    const yen = joined.match(/([0-9,]+)円/);
    if (!yen) continue;
    const explicitType = cells.find((cell) => /^(単勝|複勝|枠連|馬連|馬単|ワイド|3連複|3連単)$/.test(cell.trim()));
    if (explicitType) currentType = explicitType.trim();
    if (!currentType) continue;
    const payoutIndex = cells.findIndex((cell) => /[0-9,]+円/.test(cell));
    if (payoutIndex < 0) continue;
    const typeIndex = explicitType ? cells.indexOf(explicitType) : -1;
    const combinationCells = cells.slice(typeIndex + 1, payoutIndex).filter(Boolean);
    const combination = combinationCells.join("-").replace(/\s+/g, "").replace(/--+/g, "-");
    if (!combination) continue;
    const popularity = cells.slice(payoutIndex + 1).join(" ").match(/(\d+)番人気/)?.[1] ?? null;
    payouts.push({
      betType: currentType,
      combination,
      payoutYen: Number((yen[1] ?? "0").replace(/,/g, "")),
      popularity: popularity ? Number(popularity) : null
    });
  }
  return payouts;
}

function parseRefunds(html: string): number[] {
  const text = normalizeText(html);
  const match = text.match(/返還馬番\s*([0-9、,\s]+)/);
  if (!match) return [];
  return [...new Set(((match[1] ?? "").match(/\d{1,2}/g) ?? []).map(Number).filter((n) => n >= 1 && n <= 18))];
}

export function parseEntryPage(html: string, entryUrl: string): RaceBundle {
  const race = parseHeader(html, entryUrl, false);
  const runners = parseEntryRows(html);
  if (runners.length < 2) throw new Error("RUNNERS_NOT_FOUND");
  return { race, runners, results: [], payouts: [], refundHorseNos: [] };
}

export function parseResultPage(html: string, resultUrl: string): RaceBundle {
  const race = parseHeader(html, resultUrl, true);
  const results = parseResultRows(html);
  const payouts = parsePayoutRows(html);
  if (results.length < 2) throw new Error("RESULTS_NOT_FOUND");
  return { race, runners: [], results, payouts, refundHorseNos: parseRefunds(html) };
}

export async function discoverRaceUrls(homeUrl: string, seeds: string[], fetchImpl: typeof fetch = fetch): Promise<string[]> {
  const found = new Set<string>();
  const home = await fetchJraPage(homeUrl, fetchImpl);
  const firstLinks = extractEntryLinks(home.html, home.url);
  for (const seed of seeds) found.add(validateUrl(seed).toString());
  for (const link of firstLinks) found.add(link);

  const expansionSeeds = [...found].slice(0, 6);
  for (const seed of expansionSeeds) {
    try {
      const page = await fetchJraPage(seed, fetchImpl);
      for (const link of extractEntryLinks(page.html, page.url)) found.add(link);
    } catch {
      // Discovery remains useful even when an individual seed is temporarily unavailable.
    }
  }
  return [...found];
}

export function pageLooksLikeEntry(html: string): boolean {
  const lines = htmlToLines(html);
  return lines.includes("出馬表") && lines.some((line) => /馬名.*単勝オッズ/.test(line));
}

export function pageLooksLikeResult(html: string): boolean {
  const lines = htmlToLines(html);
  return lines.includes("レース結果") && lines.includes("払戻金");
}
