import type { PayoutRecord, RaceBundle, RaceRecord, ResultRecord, RunnerRecord } from "./types.js";
import { decodeEntities, htmlToLines, parseJapaneseDateTime, stripHtml } from "./utils.js";

const ALLOWED_HOSTS = new Set(["www.jra.go.jp", "jra.jp", "sp.jra.jp"]);
const MAX_BODY_BYTES = 3_000_000;
const FETCH_TIMEOUT_MS = 20_000;
const VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉";

export interface FetchPageResult {
  url: string;
  html: string;
  status: number;
  contentType: string | null;
}

interface ParsedRow {
  html: string;
  cells: string[];
}

function validateUrl(rawUrl: string): URL {
  const normalized = rawUrl.replace(/\\u0026/gi, "&").replace(/\\\//g, "/").replace(/&amp;/gi, "&");
  const url = new URL(normalized);
  if (url.protocol !== "https:") throw new Error("HTTPS_REQUIRED");
  if (!ALLOWED_HOSTS.has(url.hostname)) throw new Error("HOST_NOT_ALLOWED");
  return url;
}

function decodePage(buffer: ArrayBuffer, contentType: string | null): string {
  const declared = contentType?.match(/charset\s*=\s*([^;\s]+)/i)?.[1]?.replace(/["']/g, "") ?? null;
  const probe = new TextDecoder("windows-1252").decode(buffer.slice(0, Math.min(buffer.byteLength, 8192)));
  const meta = probe.match(/<meta[^>]+charset=["']?([^"'\s/>]+)/i)?.[1] ?? probe.match(/content=["'][^"']*charset=([^"';\s]+)/i)?.[1] ?? null;
  const candidates = [declared, meta, "shift_jis", "utf-8"].filter((value): value is string => Boolean(value));
  for (const charset of candidates) {
    try { return new TextDecoder(charset).decode(buffer); } catch { /* continue */ }
  }
  return new TextDecoder("utf-8").decode(buffer);
}

export async function fetchJraPage(rawUrl: string, fetchImpl: typeof fetch = fetch): Promise<FetchPageResult> {
  const initial = validateUrl(rawUrl);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetchImpl(initial.toString(), {
      redirect: "follow",
      signal: controller.signal,
      headers: {
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.7,en;q=0.5",
        "Cache-Control": "no-cache",
        Pragma: "no-cache",
        Referer: "https://www.jra.go.jp/",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
      }
    });
    const finalUrl = validateUrl(response.url || initial.toString());
    const declaredLength = Number(response.headers.get("content-length") ?? "0");
    if (declaredLength > MAX_BODY_BYTES) throw new Error("BODY_TOO_LARGE");
    const buffer = await response.arrayBuffer();
    if (buffer.byteLength > MAX_BODY_BYTES) throw new Error("BODY_TOO_LARGE");
    const contentType = response.headers.get("content-type");
    const html = decodePage(buffer, contentType);
    if (!response.ok) throw new Error(`HTTP_${response.status}`);
    if (/captcha|アクセスが集中|利用を制限|Forbidden|Access Denied|Service Unavailable/i.test(html)) throw new Error("BLOCKED_PAGE");
    return { url: finalUrl.toString(), html, status: response.status, contentType };
  } finally { clearTimeout(timer); }
}

function parsedRows(html: string): ParsedRow[] {
  const rows: ParsedRow[] = [];
  for (const rowMatch of html.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const rowHtml = rowMatch[0] ?? "";
    const cells: string[] = [];
    for (const cellMatch of (rowMatch[1] ?? "").matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)) cells.push(stripHtml(cellMatch[1] ?? "").replace(/\n+/g, " ").trim());
    if (cells.length > 0) rows.push({ html: rowHtml, cells });
  }
  return rows;
}

function allUrlCandidates(html: string): string[] {
  const candidates: string[] = [];
  for (const match of html.matchAll(/(?:href|data-url|data-href)\s*=\s*["']([^"']+)["']/gi)) candidates.push(match[1] ?? "");
  for (const match of html.matchAll(/(?:https?:\\?\/\\?\/[^"'\s<>]+|\/JRADB\/(?:accessD|accessS)\.html\?CNAME=[^"'\s<>]+)/gi)) candidates.push(match[0] ?? "");
  return candidates.map((value) => decodeEntities(value).replace(/\\u0026/gi, "&").replace(/\\\//g, "/"));
}

function extractJraDbLinks(html: string, baseUrl: string, kind: "entry" | "result"): string[] {
  const found = new Map<string, string>();
  const pathPattern = kind === "entry" ? /\/JRADB\/accessD\.html$/i : /\/JRADB\/accessS\.html$/i;
  const cnamePattern = kind === "entry" ? /(?:pw|sw)01dde/i : /(?:pw|sw)01sde/i;
  for (const candidate of allUrlCandidates(html)) {
    try {
      const url = new URL(candidate, baseUrl);
      if (!ALLOWED_HOSTS.has(url.hostname) || !pathPattern.test(url.pathname)) continue;
      const cname = decodeURIComponent(url.searchParams.get("CNAME") ?? "");
      if (!cnamePattern.test(cname)) continue;
      found.set(cname, url.toString());
    } catch { /* ignore */ }
  }
  return [...found.values()];
}

export function extractEntryLinks(html: string, baseUrl: string): string[] { return extractJraDbLinks(html, baseUrl, "entry"); }
export function extractResultLinks(html: string, baseUrl: string): string[] { return extractJraDbLinks(html, baseUrl, "result"); }
export function extractResultUrl(html: string, baseUrl: string): string | null { return extractResultLinks(html, baseUrl)[0] ?? null; }
function extractEntryUrl(html: string, baseUrl: string): string | null { return extractEntryLinks(html, baseUrl)[0] ?? null; }

export function toResultUrl(entryUrl: string): string {
  const url = validateUrl(entryUrl);
  url.pathname = url.pathname.replace(/accessD\.html$/i, "accessS.html");
  const cname = url.searchParams.get("CNAME");
  if (cname) url.searchParams.set("CNAME", cname.replace(/((?:pw|sw)01)dde/i, "$1sde"));
  return url.toString();
}

function venueSlug(venue: string): string {
  const map: Record<string, string> = { 札幌: "sapporo", 函館: "hakodate", 福島: "fukushima", 新潟: "niigata", 東京: "tokyo", 中山: "nakayama", 中京: "chukyo", 京都: "kyoto", 阪神: "hanshin", 小倉: "kokura" };
  return map[venue] ?? encodeURIComponent(venue);
}

function normalizeText(html: string): string {
  return stripHtml(html.replace(/<\/(?:td|th|tr|li|p|div|section|article|h[1-6]|dt|dd|ul|ol|table)>/gi, "\n").replace(/<\s*br\s*\/?>/gi, "\n"));
}

function headingTexts(html: string): string[] {
  const headings: string[] = [];
  for (const match of html.matchAll(/<h[1-6]\b[^>]*>([\s\S]*?)<\/h[1-6]>/gi)) {
    const text = stripHtml(match[1] ?? "").replace(/\s+/g, " ").trim();
    if (text) headings.push(text);
  }
  return headings;
}

function parseRaceName(html: string, raceNo: number): string {
  const explicitHtml = html.match(/<span\b[^>]*class=["'][^"']*\btitleRaceName\b[^"']*["'][^>]*>([\s\S]*?)<\/span>/i)?.[1];
  if (explicitHtml) {
    const explicitName = stripHtml(explicitHtml).replace(/\s+/g, " ").trim();
    if (explicitName) return explicitName;
  }
  for (const raw of headingTexts(html)) {
    const text = raw.replace(new RegExp(`^${raceNo}(?:R|レース)\\s*`), "").trim();
    if (!text || /^(?:出馬表|レース結果|払戻金|関連メニュー|コースレコード|勝馬の紹介)$/.test(text)) continue;
    if (/20\d{2}年|\d+回(?:札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)\d+日/.test(text)) continue;
    if (/^(?:\d+歳|障害|サラ系)/.test(text) && /(?:クラス|未勝利|新馬|オープン)/.test(text)) continue;
    return text;
  }
  const match = normalizeText(html).match(new RegExp(`${raceNo}(?:R|レース)\\s*([^\\n]+)`));
  return match?.[1]?.trim() || `${raceNo}レース`;
}

function parseHeader(html: string, pageUrl: string, isResult: boolean): RaceRecord {
  const text = normalizeText(html);
  const dateVenue = text.match(new RegExp(`(20\\d{2})年(\\d{1,2})月(\\d{1,2})日[^\\n]*?(\\d+)回(${VENUES})(\\d+)日`));
  if (!dateVenue) throw new Error("RACE_DATE_VENUE_NOT_FOUND");
  const year = Number(dateVenue[1]); const month = Number(dateVenue[2]); const day = Number(dateVenue[3]);
  const meetingNo = Number(dateVenue[4]); const venue = dateVenue[5] ?? ""; const meetingDay = Number(dateVenue[6]);
  const timeJapanese = text.match(/発走時刻\s*[：:]?\s*(\d{1,2})時(\d{2})分/); const timeColon = text.match(/発走\s*[：:]?\s*(\d{1,2}):(\d{2})/);
  const timeH = timeJapanese?.[1] ?? timeColon?.[1] ?? null; const timeM = timeJapanese?.[2] ?? timeColon?.[2] ?? null;
  const startTimeJst = timeH && timeM ? `${timeH.padStart(2, "0")}:${timeM}` : null;
  const raceMatches = [...text.matchAll(/(?:^|\s)(\d{1,2})(?:R|レース)(?:\s|$)/gm)].map((m) => Number(m[1])).filter((v) => v >= 1 && v <= 12);
  const decodedCname = decodeURIComponent(new URL(pageUrl).searchParams.get("CNAME") ?? "");
  const cnameRaceNo = Number(decodedCname.match(/(\d{2})20\d{6}\//i)?.[1] ?? 0);
  const raceNo = cnameRaceNo >= 1 && cnameRaceNo <= 12 ? cnameRaceNo : (raceMatches[0] ?? 0);
  if (!raceNo) throw new Error("RACE_NUMBER_NOT_FOUND");
  const raceName = parseRaceName(html, raceNo);
  const course = text.match(/コース\s*[：:]?\s*([0-9,]+)(?:メートル|m)\s*[（(]?\s*(芝|ダート|障害)(?:[・\s]*(右|左|直線|外|内|外内|内外))?/);
  const distanceM = course?.[1] ? Number(course[1].replace(/,/g, "")) : null; const surface = course?.[2] ?? null; const direction = course?.[3] ?? null;
  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean); const raceNameIndex = lines.findIndex((line) => line === raceName || line.endsWith(` ${raceName}`));
  const conditionLine = raceNameIndex >= 0 ? lines.slice(raceNameIndex + 1, raceNameIndex + 6).find((line) => /コース/.test(line)) ?? null : lines.find((line) => /コース\s*[：:]?\s*[0-9,]+/.test(line)) ?? null;
  const conditions = conditionLine?.replace(/\s*コース[\s\S]*$/, "").trim() || null;
  const weather = text.match(/天候\s*[：:]?\s*([^\s\n]+)/)?.[1] ?? null; const trackCondition = text.match(/(?:芝|ダート)\s*[：:]?\s*(良|稍重|重|不良)/)?.[1] ?? null;
  const raceDate = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const explicitEntry = isResult ? extractEntryUrl(html, pageUrl) : pageUrl;
  const entryUrl = explicitEntry ?? (isResult ? pageUrl.replace(/accessS\.html/i, "accessD.html").replace(/((?:pw|sw)01)sde/i, "$1dde") : pageUrl);
  const resultUrl = (isResult ? pageUrl : extractResultUrl(html, pageUrl)) ?? toResultUrl(entryUrl);
  return { raceId: `${raceDate}-${venueSlug(venue)}-${String(raceNo).padStart(2, "0")}`, raceDate, venue, meetingNo, meetingDay, raceNo, raceName, conditions, surface, distanceM, direction, startTimeJst, startTimeUtc: parseJapaneseDateTime(year, month, day, startTimeJst), weather, trackCondition, entryUrl, resultUrl, status: isResult ? "finished" : "scheduled" };
}

function lastStableMatch(text: string): { trainer: string; stable: string } | null {
  const matches = [...text.matchAll(/([A-Za-z.ぁ-んァ-ヶ一-龠々・ー]+(?:\s+[A-Za-z.ぁ-んァ-ヶ一-龠々・ー]+)?)\s*\((美浦|栗東|本会外)\)/gu)]; const match = matches.at(-1);
  return match?.[1] && match?.[2] ? { trainer: match[1].trim(), stable: match[2] } : null;
}

function parseHorseName(detail: string): string | null {
  const compact = detail.replace(/\s+/g, " ").trim(); const oddsIndex = compact.search(/\d+(?:\.\d+)?\s*\(\d+番人気\)/); if (oddsIndex > 0) return compact.slice(0, oddsIndex).trim();
  const statusIndex = compact.search(/(?:取消|除外)/); if (statusIndex > 0) return compact.slice(0, statusIndex).trim();
  const pedigreeIndex = compact.search(/(?:父[:：]|母[:：])/); const beforePedigree = pedigreeIndex > 0 ? compact.slice(0, pedigreeIndex).trim() : compact;
  const stable = [...beforePedigree.matchAll(/([A-Za-z.ぁ-んァ-ヶ一-龠々・ー]+(?:\s+[A-Za-z.ぁ-んァ-ヶ一-龠々・ー]+)?)\s*\((?:美浦|栗東|本会外)\)/gu)].at(-1);
  if (stable?.index !== undefined && stable.index > 0) { const prefix = beforePedigree.slice(0, stable.index).trim(); const token = prefix.split(/\s+/)[0]; return token && token.length >= 2 ? token : prefix || null; }
  const token = beforePedigree.split(/\s+/)[0]; return token && token.length >= 2 ? token : null;
}

function numbersBefore(cells: string[], end: number): number[] { return cells.slice(0, end).map((cell) => cell.match(/^\s*(\d{1,2})\s*$/)?.[1]).filter((v): v is string => Boolean(v)).map(Number); }

function parseEntryRows(html: string): RunnerRecord[] {
  const runners = new Map<number, RunnerRecord>();
  for (const row of parsedRows(html)) {
    const joined = row.cells.join(" ").replace(/\s+/g, " ").trim(); if (!/(?:番人気|初出走|kg|父[:：]|取消|除外|美浦|栗東)/.test(joined)) continue;
    const detailIndex = row.cells.findIndex((cell) => /(?:番人気|初出走|\d{3}kg|父[:：]|取消|除外|\((?:美浦|栗東|本会外)\))/.test(cell)); if (detailIndex < 0) continue;
    const nums = numbersBefore(row.cells, detailIndex).filter((v) => v >= 1 && v <= 18); const horseNo = nums.at(-1) ?? null; if (!horseNo) continue;
    const detail = row.cells[detailIndex] ?? ""; const horseName = parseHorseName(detail); if (!horseName) continue;
    const frameAlt = row.html.match(/alt=["'][^"']*枠(\d)[^"']*["']/i)?.[1]; const firstFrame = nums[0] ?? null; const frameNo = frameAlt ? Number(frameAlt) : (nums.length >= 2 && firstFrame !== null && firstFrame <= 8 ? firstFrame : null);
    const status: RunnerRecord["runnerStatus"] = /除外/.test(joined) ? "excluded" : /取消/.test(joined) ? "scratched" : "active";
    const odds = detail.match(/(\d+(?:\.\d+)?)\s*\((\d+)番人気\)/); const bodyWeight = detail.match(/(\d{3})\s*kg\s*\(([^)]*)\)/i); const weightChangeText = bodyWeight?.[2]?.replace(/初出走/g, "").trim() ?? "";
    const weightChange = /^[+＋-－]?\d+$/.test(weightChangeText) ? Number(weightChangeText.replace("＋", "+").replace("－", "-")) : null; const trainerInfo = lastStableMatch(detail) ?? lastStableMatch(joined);
    const infoCell = row.cells.slice(detailIndex + 1).find((cell) => /(?:牡|牝|せん|騸)\s*\d+|\d{2}(?:\.\d)?\s*kg/.test(cell)) ?? detail; const sex = infoCell.match(/(牡|牝|せん|騸)\s*(\d+)\s*(?:[/／]\s*([^\s]+))?/u); const assigned = infoCell.match(/(\d{2}(?:\.\d)?)\s*kg/i);
    let jockey: string | null = assigned?.index !== undefined ? infoCell.slice(assigned.index + assigned[0].length).replace(/^[\s▲△☆◇]+/u, "").trim() || null : null;
    if (!jockey) jockey = joined.match(/([▲△☆◇]?[A-Za-z.ぁ-んァ-ヶ一-龠々・ー]+(?:\s+[A-Za-z.ぁ-んァ-ヶ一-龠々・ー]+)?)\s*\((\d{2}(?:\.\d)?)\)/u)?.[1]?.replace(/^[▲△☆◇]/u, "") ?? null;
    runners.set(horseNo, { horseNo, frameNo, horseName, sexAge: sex ? `${sex[1]}${sex[2]}` : null, coatColor: sex?.[3] ?? null, horseWeight: bodyWeight ? Number(bodyWeight[1]) : null, weightChange, jockey, assignedWeight: assigned ? Number(assigned[1]) : null, trainer: trainerInfo?.trainer ?? null, stable: trainerInfo?.stable ?? null, winOdds: odds ? Number(odds[1]) : null, popularity: odds ? Number(odds[2]) : null, runnerStatus: status });
  }
  return [...runners.values()].sort((a, b) => a.horseNo - b.horseNo);
}

function parseResultRows(html: string): ResultRecord[] {
  const results = new Map<number, ResultRecord>();
  for (const row of parsedRows(html)) {
    const joined = row.cells.join(" ").replace(/\s+/g, " ").trim(); if (!/(?:\d+:\d{2}\.\d|除外|中止|失格|取消)/.test(joined)) continue;
    const finishCell = row.cells[0]?.trim() ?? ""; const finishPosition = /^\d{1,2}$/.test(finishCell) ? Number(finishCell) : null;
    const status = /除外/.test(joined) ? "excluded" : /取消/.test(joined) ? "scratched" : /中止/.test(joined) ? "dnf" : /失格/.test(joined) ? "disqualified" : "finished";
    const horseNo = row.cells.slice(1, 5).map((c) => c.match(/^\s*(\d{1,2})\s*$/)?.[1]).filter((v): v is string => Boolean(v)).map(Number).filter((v) => v >= 1 && v <= 18).at(-1) ?? null; if (!horseNo) continue;
    const timeIndex = row.cells.findIndex((c) => /\d+:\d{2}\.\d/.test(c)); const timeText = timeIndex >= 0 ? row.cells[timeIndex]?.match(/\d+:\d{2}\.\d/)?.[0] ?? null : null;
    const marginCandidate = timeIndex >= 0 ? (row.cells[timeIndex + 1] ?? "").trim() : ""; const marginText = marginCandidate && !/^\d+(?:\.\d+)?$/.test(marginCandidate) ? marginCandidate : null;
    const final3f = row.cells.slice(Math.max(0, timeIndex + 1)).flatMap((c) => [...c.matchAll(/(?:^|\s)(\d{2}\.\d)(?:\s|$)/g)].map((m) => Number(m[1]))).at(-1) ?? null;
    results.set(horseNo, { horseNo, finishPosition, resultStatus: status, timeText, marginText, final3f });
  }
  return [...results.values()].sort((a, b) => (a.finishPosition ?? 99) - (b.finishPosition ?? 99));
}

function normalizeBetType(value: string): string | null { const compact = value.replace(/\s+/g, "").replace(/３/g, "3"); return ["単勝", "複勝", "枠連", "馬連", "馬単", "ワイド", "3連複", "3連単"].find((type) => compact === type) ?? null; }
function normalizeCombination(value: string): string | null { const normalized = value.replace(/[‐‑–—−ー]/g, "-").replace(/[→、,]/g, "-").replace(/\s+/g, "").replace(/[^0-9-]/g, "").replace(/-+/g, "-").replace(/^-|-$/g, ""); return /^\d{1,2}(?:-\d{1,2}){0,2}$/.test(normalized) ? normalized : null; }

function parsePayoutRows(html: string): PayoutRecord[] {
  const payouts: PayoutRecord[] = []; let currentType: string | null = null;
  for (const row of parsedRows(html)) {
    const explicit = row.cells.map(normalizeBetType).find((v): v is string => Boolean(v)); if (explicit) currentType = explicit; if (!currentType) continue;
    const amounts = row.cells.map((cell, index) => ({ index, match: cell.match(/([0-9,]+)\s*円/) })).filter((x): x is { index: number; match: RegExpMatchArray } => Boolean(x.match));
    for (const amount of amounts) {
      let combination: string | null = null; for (let i = amount.index - 1; i >= 0; i -= 1) { combination = normalizeCombination(row.cells[i] ?? ""); if (combination || normalizeBetType(row.cells[i] ?? "")) break; }
      if (!combination) continue; const popularity = row.cells.slice(amount.index + 1).join(" ").match(/(\d+)番人気/)?.[1];
      payouts.push({ betType: currentType, combination, payoutYen: Number((amount.match[1] ?? "0").replace(/,/g, "")), popularity: popularity ? Number(popularity) : null });
    }
  }
  const unique = new Map<string, PayoutRecord>(); for (const payout of payouts) unique.set(`${payout.betType}:${payout.combination}`, payout); return [...unique.values()];
}

function parseRefunds(html: string): number[] { const match = normalizeText(html).match(/返還(?:馬番)?\s*[：:]?\s*([0-9、,\s]+)/); return match ? [...new Set(((match[1] ?? "").match(/\d{1,2}/g) ?? []).map(Number).filter((v) => v >= 1 && v <= 18))] : []; }

export function parseEntryPage(html: string, entryUrl: string): RaceBundle { const race = parseHeader(html, entryUrl, false); const runners = parseEntryRows(html); if (runners.length < 2) throw new Error(`RUNNERS_NOT_FOUND:${runners.length}`); return { race, runners, results: [], payouts: [], refundHorseNos: [] }; }
export function parseResultPage(html: string, resultUrl: string): RaceBundle { const race = parseHeader(html, resultUrl, true); const results = parseResultRows(html); const payouts = parsePayoutRows(html); if (results.length < 2) throw new Error(`RESULTS_NOT_FOUND:${results.length}`); return { race, runners: [], results, payouts, refundHorseNos: parseRefunds(html) }; }

function raceDateFromUrl(rawUrl: string): Date | null { try { const cname = decodeURIComponent(new URL(rawUrl).searchParams.get("CNAME") ?? ""); const value = [...cname.matchAll(/(20\d{6})/g)].map((m) => m[1] ?? "").at(-1); return value ? new Date(Date.UTC(Number(value.slice(0, 4)), Number(value.slice(4, 6)) - 1, Number(value.slice(6, 8)))) : null; } catch { return null; } }
function isNearCurrentWeekend(rawUrl: string, now = new Date()): boolean { const date = raceDateFromUrl(rawUrl); if (!date) return true; const jst = new Date(now.getTime() + 9 * 3600000); const today = Date.UTC(jst.getUTCFullYear(), jst.getUTCMonth(), jst.getUTCDate()); const delta = (date.getTime() - today) / 86400000; return delta >= -2 && delta <= 9; }
function meetingExpansionKey(rawUrl: string): string {
  try { const cname = decodeURIComponent(new URL(rawUrl).searchParams.get("CNAME") ?? ""); const match = cname.match(/^(.*?)(\d{2})(20\d{6})\//i); return match ? `${match[1]}:${match[3]}` : cname || rawUrl; } catch { return rawUrl; }
}

export async function discoverRaceUrls(homeUrl: string, seeds: string[], fetchImpl: typeof fetch = fetch): Promise<string[]> {
  const found = new Map<string, string>();
  const add = (link: string) => { try { const cname = decodeURIComponent(new URL(link).searchParams.get("CNAME") ?? ""); found.set(cname || link, link); } catch { found.set(link, link); } };
  for (const source of [homeUrl, "https://www.jra.go.jp/JRADB/accessD.html"]) {
    try { const page = await fetchJraPage(source, fetchImpl); for (const link of extractEntryLinks(page.html, page.url)) if (isNearCurrentWeekend(link)) add(link); } catch { /* continue */ }
  }
  for (const seed of seeds) { try { const normalized = validateUrl(seed).toString(); if (isNearCurrentWeekend(normalized)) add(normalized); } catch { /* ignore */ } }
  const initial = [...found.values()];
  for (const seed of initial.slice(0, 6)) { try { const page = await fetchJraPage(seed, fetchImpl); for (const link of extractEntryLinks(page.html, page.url)) if (isNearCurrentWeekend(link)) add(link); } catch { /* continue */ } }
  const representatives = new Map<string, string>(); for (const link of found.values()) if (!representatives.has(meetingExpansionKey(link))) representatives.set(meetingExpansionKey(link), link);
  for (const seed of [...representatives.values()].slice(0, 12)) { try { const page = await fetchJraPage(seed, fetchImpl); for (const link of extractEntryLinks(page.html, page.url)) if (isNearCurrentWeekend(link)) add(link); } catch { /* continue */ } }
  return [...found.values()];
}

export function pageLooksLikeEntry(html: string): boolean { const text = htmlToLines(html).join(" "); return /出馬表/.test(text) && (/<table\b/i.test(html) || /<tr\b/i.test(html)); }
export function pageLooksLikeResult(html: string): boolean { const text = htmlToLines(html).join(" "); return /レース結果/.test(text) && (/<table\b/i.test(html) || /<tr\b/i.test(html)); }
