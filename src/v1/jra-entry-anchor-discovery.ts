import { pageLooksLikeEntry, parseEntryPage } from "./jra.js";

const ALLOWED_HOSTS = new Set(["www.jra.go.jp", "jra.jp", "sp.jra.jp", "app.jra.jp"]);
const LANDING_URLS = [
  "https://www.jra.go.jp/JRADB/accessD.html",
  "https://www.jra.go.jp/",
  "https://sp.jra.jp/JRADB/accessD.html",
  "https://app.jra.jp/JRADB/accessD.html",
  "https://app.jra.jp/",
] as const;
const VENUE_CODES: Record<string, string> = {
  札幌: "01", 函館: "02", 福島: "03", 新潟: "04", 東京: "05",
  中山: "06", 中京: "07", 京都: "08", 阪神: "09", 小倉: "10",
};
const FETCH_TIMEOUT_MS = 6_000;
const MAX_VALIDATE = 32;
const VALIDATE_CONCURRENCY = 8;

type Meeting = {
  raceDate: string;
  venue: string;
  meetingNo: number;
  meetingDay: number;
};

export type PublishedEntryAnchor = {
  cname: string;
  html: string;
  sourceUrl: string;
};

function canonicalUrl(cname: string): string {
  return `https://www.jra.go.jp/JRADB/accessD.html?CNAME=${encodeURIComponent(cname)}`;
}

function appUrl(cname: string): string {
  return `https://app.jra.jp/JRADB/accessD.html?CNAME=${encodeURIComponent(cname)}`;
}

function decodeOfficialPage(bytes: ArrayBuffer, contentType: string | null): string {
  const declared = contentType?.match(/charset\s*=\s*([^;\s]+)/i)?.[1]?.replace(/["']/g, "") ?? null;
  const probe = new TextDecoder("windows-1252").decode(bytes.slice(0, Math.min(bytes.byteLength, 8192)));
  const meta = probe.match(/<meta[^>]+charset=["']?([^"'\s/>]+)/i)?.[1]
    ?? probe.match(/content=["'][^"']*charset=([^"';\s]+)/i)?.[1]
    ?? null;
  for (const charset of [declared, meta, "shift_jis", "utf-8"].filter((value): value is string => Boolean(value))) {
    try { return new TextDecoder(charset).decode(bytes); } catch { /* continue */ }
  }
  return new TextDecoder("utf-8").decode(bytes);
}

async function fetchOfficial(rawUrl: string): Promise<{ html: string; url: string } | null> {
  const initial = new URL(rawUrl);
  if (initial.protocol !== "https:" || !ALLOWED_HOSTS.has(initial.hostname)) return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(initial.toString(), {
      redirect: "follow",
      signal: controller.signal,
      headers: {
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
        "Cache-Control": "no-cache",
        Pragma: "no-cache",
        Referer: "https://www.jra.go.jp/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
      },
    });
    if (!response.ok) return null;
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength > 4_000_000) return null;
    const html = decodeOfficialPage(bytes, response.headers.get("content-type"));
    if (/captcha|アクセスが集中|利用を制限|Access Denied|Forbidden|Service Unavailable/i.test(html)) return null;
    return { html, url: response.url || initial.toString() };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function cnameCandidates(html: string): string[] {
  const normalized = html.replace(/&amp;/gi, "&").replace(/\\u0026/gi, "&").replace(/\\\//g, "/");
  const found = new Set<string>();
  for (const match of normalized.matchAll(/((?:pw|sw)01(?:dde|ddd)[A-Za-z0-9%/]+)/gi)) {
    let cname = String(match[1] ?? "").replace(/["'<>\s].*$/, "");
    try { cname = decodeURIComponent(cname); } catch { /* keep raw */ }
    if (/(?:pw|sw)01dde/i.test(cname)) found.add(cname);
  }
  return [...found];
}

function candidateMatchesMeeting(cname: string, meeting: Meeting): boolean {
  const venueCode = VENUE_CODES[meeting.venue];
  if (!venueCode) return false;
  const compactDate = meeting.raceDate.replaceAll("-", "");
  const year = meeting.raceDate.slice(0, 4);
  const normalized = cname.toLowerCase();
  if (!normalized.includes(compactDate)) return false;
  const expectedCore = `${venueCode}${year}${String(meeting.meetingNo).padStart(2, "0")}${String(meeting.meetingDay).padStart(2, "0")}`;
  return normalized.includes(expectedCore.toLowerCase());
}

async function validateCandidate(cname: string, meeting: Meeting): Promise<PublishedEntryAnchor | null> {
  for (const url of [canonicalUrl(cname), appUrl(cname)]) {
    const page = await fetchOfficial(url);
    if (!page || !pageLooksLikeEntry(page.html)) continue;
    try {
      const bundle = parseEntryPage(page.html, canonicalUrl(cname));
      const active = bundle.runners.filter((runner) => (runner.runnerStatus || "active") === "active");
      if (bundle.race.raceDate !== meeting.raceDate || bundle.race.venue !== meeting.venue || active.length < 3) continue;
      return { cname, html: page.html, sourceUrl: page.url };
    } catch {
      // Try the alternate official host/candidate.
    }
  }
  return null;
}

export async function discoverPublishedEntryAnchor(meeting: Meeting): Promise<PublishedEntryAnchor | null> {
  const landingPages = await Promise.all(LANDING_URLS.map((url) => fetchOfficial(url)));
  const candidates = [...new Set(landingPages.flatMap((page) => page ? cnameCandidates(page.html) : []))]
    .filter((cname) => candidateMatchesMeeting(cname, meeting))
    .slice(0, MAX_VALIDATE);
  if (!candidates.length) return null;

  let cursor = 0;
  let found: PublishedEntryAnchor | null = null;
  await Promise.all(Array.from({ length: Math.min(VALIDATE_CONCURRENCY, candidates.length) }, async () => {
    while (!found) {
      const index = cursor++;
      if (index >= candidates.length) return;
      const valid = await validateCandidate(candidates[index]!, meeting);
      if (valid) {
        found = valid;
        return;
      }
    }
  }));
  return found;
}
