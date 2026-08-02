import { decodeEntities } from "./utils.js";

const ARCHIVE_ENDPOINT = "https://www.jra.go.jp/JRADB/accessS.html";
const ARCHIVE_INDEX_CNAME = "pw01skl00999999/B3";
const MAX_BODY_BYTES = 3_000_000;
const FETCH_TIMEOUT_MS = 25_000;

export interface ArchivePage {
  url: string;
  html: string;
  status: number;
}

function decodePage(buffer: ArrayBuffer, contentType: string | null): string {
  const declared = contentType?.match(/charset\s*=\s*([^;\s]+)/i)?.[1]?.replace(/["']/g, "") ?? null;
  const probe = new TextDecoder("windows-1252").decode(buffer.slice(0, Math.min(buffer.byteLength, 8192)));
  const meta = probe.match(/<meta[^>]+charset=["']?([^"'\s/>]+)/i)?.[1]
    ?? probe.match(/content=["'][^"']*charset=([^"';\s]+)/i)?.[1]
    ?? null;
  const candidates = [declared, meta, "shift_jis", "utf-8"].filter((value): value is string => Boolean(value));
  for (const charset of candidates) {
    try {
      return new TextDecoder(charset).decode(buffer);
    } catch {
      // Try the next declared or fallback charset.
    }
  }
  return new TextDecoder("utf-8").decode(buffer);
}

export async function fetchJraArchivePage(
  cname: string,
  fetchImpl: typeof fetch = fetch
): Promise<ArchivePage> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetchImpl(ARCHIVE_ENDPOINT, {
      method: "POST",
      redirect: "follow",
      signal: controller.signal,
      headers: {
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded",
        Referer: "https://www.jra.go.jp/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/136 Safari/537.36"
      },
      body: `cname=${encodeURIComponent(cname)}`
    });
    const declaredLength = Number(response.headers.get("content-length") ?? "0");
    if (declaredLength > MAX_BODY_BYTES) throw new Error("ARCHIVE_BODY_TOO_LARGE");
    const buffer = await response.arrayBuffer();
    if (buffer.byteLength > MAX_BODY_BYTES) throw new Error("ARCHIVE_BODY_TOO_LARGE");
    const html = decodePage(buffer, response.headers.get("content-type"));
    if (!response.ok) throw new Error(`ARCHIVE_HTTP_${response.status}`);
    if (/captcha|アクセスが集中|利用を制限|Forbidden|Access Denied|Service Unavailable/i.test(html)) {
      throw new Error("ARCHIVE_BLOCKED_PAGE");
    }
    return {
      url: response.url || ARCHIVE_ENDPOINT,
      html,
      status: response.status
    };
  } finally {
    clearTimeout(timer);
  }
}

function normalizedHtml(html: string): string {
  return decodeEntities(html)
    .replace(/\\u0026/gi, "&")
    .replace(/\\\//g, "/")
    .replace(/&amp;/gi, "&");
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

export function parseArchiveMonthChecksums(html: string): Map<string, string> {
  const text = normalizedHtml(html);
  const values = new Map<string, string>();
  for (const match of text.matchAll(/objParam\s*\[\s*["'](\d{4})["']\s*\]\s*=\s*["']([0-9A-F]{2})["']/gi)) {
    if (match[1] && match[2]) values.set(match[1], match[2].toUpperCase());
  }
  return values;
}

function extractCnames(html: string, marker: RegExp): string[] {
  const text = normalizedHtml(html);
  const candidates: string[] = [];
  for (const match of text.matchAll(/(?:CNAME=|cname=)([^"'&<>\s)]+)/gi)) {
    candidates.push(decodeURIComponent(match[1] ?? ""));
  }
  for (const match of text.matchAll(/(?:pw|sw)01[a-zA-Z0-9]+[^"'<>\s,)]+\/[0-9A-F]{2}/gi)) {
    candidates.push(match[0] ?? "");
  }
  return unique(candidates.map((value) => value.replace(/^cname=/i, "").trim()))
    .filter((value) => marker.test(value));
}

export function parseArchiveMeetingCnames(html: string): string[] {
  return extractCnames(html, /^(?:pw|sw)01srl/i);
}

export function parseArchiveResultCnames(html: string): string[] {
  return extractCnames(html, /^(?:pw|sw)01sde/i);
}

export function archiveResultUrl(cname: string): string {
  return `${ARCHIVE_ENDPOINT}?CNAME=${encodeURIComponent(cname)}`;
}

export async function getArchiveMonthChecksum(
  yearMonth: string,
  fetchImpl: typeof fetch = fetch
): Promise<string> {
  if (!/^\d{6}$/.test(yearMonth)) throw new Error(`INVALID_ARCHIVE_MONTH:${yearMonth}`);
  const page = await fetchJraArchivePage(ARCHIVE_INDEX_CNAME, fetchImpl);
  const checksum = parseArchiveMonthChecksums(page.html).get(yearMonth.slice(2));
  if (!checksum) throw new Error(`ARCHIVE_MONTH_CHECKSUM_NOT_FOUND:${yearMonth}`);
  return checksum;
}

export async function getArchiveMeetingCnames(
  yearMonth: string,
  fetchImpl: typeof fetch = fetch
): Promise<string[]> {
  const checksum = await getArchiveMonthChecksum(yearMonth, fetchImpl);
  const page = await fetchJraArchivePage(`pw01skl10${yearMonth}/${checksum}`, fetchImpl);
  const meetings = parseArchiveMeetingCnames(page.html);
  if (meetings.length === 0) throw new Error(`ARCHIVE_MEETINGS_NOT_FOUND:${yearMonth}`);
  return meetings;
}

async function mapWithConcurrency<T, R>(
  values: readonly T[],
  concurrency: number,
  mapper: (value: T, index: number) => Promise<R>
): Promise<R[]> {
  const results = new Array<R>(values.length);
  let cursor = 0;
  async function worker(): Promise<void> {
    while (cursor < values.length) {
      const index = cursor++;
      results[index] = await mapper(values[index]!, index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, values.length) }, () => worker()));
  return results;
}

export async function getArchiveResultUrls(
  yearMonth: string,
  fetchImpl: typeof fetch = fetch
): Promise<string[]> {
  const meetings = await getArchiveMeetingCnames(yearMonth, fetchImpl);
  const resultGroups = await mapWithConcurrency(meetings, 6, async (meeting) => {
    const page = await fetchJraArchivePage(meeting, fetchImpl);
    return parseArchiveResultCnames(page.html);
  });
  const cnames = unique(resultGroups.flat());
  if (cnames.length === 0) throw new Error(`ARCHIVE_RESULTS_NOT_FOUND:${yearMonth}`);
  return cnames.map(archiveResultUrl);
}
