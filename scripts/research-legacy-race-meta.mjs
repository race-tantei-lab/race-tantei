import { stripHtml } from "../dist-test/src/v1/utils.js";

const UI_HEADING_PATTERN = /検索|緊急情報|お知らせ|メニュー|レース選択|開催選択|ホーム|ここから本文|出馬表|レース結果|払戻金|コースレコード|勝馬の紹介|馬場情報|今週の注目レース/;
const VENUE_PATTERN = /(?:札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)/;

function normalizeDigits(value) {
  return value
    .replace(/[０-９]/g, (char) => String(char.charCodeAt(0) - 0xfee0))
    .replace(/，/g, ",")
    .replace(/[：﹕]/g, ":")
    .replace(/[－–—−]/g, "-");
}

function normalizeText(value) {
  return normalizeDigits(stripHtml(value)).replace(/\s+/g, " ").trim();
}

function flatText(html) {
  return normalizeText(html);
}

function headingRecords(html) {
  const records = [];
  for (const match of html.matchAll(/<h[1-6]\b[^>]*>([\s\S]*?)<\/h[1-6]>/gi)) {
    const text = normalizeText(match[1] ?? "");
    if (!text) continue;
    records.push({ text, index: match.index ?? 0 });
  }
  return records;
}

function explicitRaceName(html) {
  const patterns = [
    /<span\b[^>]*class=["'][^"']*\btitleRaceName\b[^"']*["'][^>]*>([\s\S]*?)<\/span>/i,
    /<[^>]+class=["'][^"']*\brace_name\b[^"']*["'][^>]*>([\s\S]*?)<\/[^>]+>/i
  ];
  for (const pattern of patterns) {
    const raw = html.match(pattern)?.[1];
    if (!raw) continue;
    const text = normalizeText(raw);
    if (text) return text;
  }
  return null;
}

function plausibleRaceName(text, raceNo) {
  const value = text.replace(new RegExp(`^${raceNo}(?:R|レース)\\s*`), "").trim();
  if (!value || UI_HEADING_PATTERN.test(value)) return null;
  if (/20\d{2}年/.test(value) || new RegExp(`\\d+回${VENUE_PATTERN.source}\\d+日`).test(value)) return null;
  if (/^(?:\d+歳|障害|サラ系)/.test(value) && /(?:\[指定\]|\[特指\]|馬齢|定量|別定|ハンデ|負担重量|コース)/.test(value)) return null;
  if (/^(?:天候|芝|ダート|発走|コース)\b/.test(value)) return null;
  return value;
}

function raceBodyStartIndex(html) {
  const markers = ["発走時刻", "ここから本文", "ここから本文です"];
  let best = -1;
  for (const marker of markers) {
    const index = html.indexOf(marker);
    if (index > best) best = index;
  }
  return best;
}

function parseRaceName(html, raceNo, flat) {
  const explicit = explicitRaceName(html);
  const explicitCandidate = explicit ? plausibleRaceName(explicit, raceNo) : null;
  if (explicitCandidate) return explicitCandidate;

  const bodyStart = raceBodyStartIndex(html);
  const bodyCandidates = headingRecords(html)
    .filter((record) => bodyStart < 0 || record.index > bodyStart)
    .map((record) => plausibleRaceName(record.text, raceNo))
    .filter(Boolean);

  // On legacy JRA result pages the first meaningful heading after the race-body
  // boundary (発走時刻/ここから本文) is the race title. Page chrome is before it.
  if (bodyCandidates[0]) return bodyCandidates[0];

  const fallbackPatterns = [
    new RegExp(`(?:発走時刻[^\\n]{0,80})?${raceNo}(?:R|レース)\\s+([^\\n]{2,100}?)\\s+(?=(?:サラ系|障害|\\d+歳|コース))`),
    new RegExp(`${raceNo}(?:R|レース)\\s+([^\\n]{2,80})`)
  ];
  for (const pattern of fallbackPatterns) {
    const raw = flat.match(pattern)?.[1]?.trim();
    const candidate = raw ? plausibleRaceName(raw, raceNo) : null;
    if (candidate) return candidate;
  }
  return `${raceNo}レース`;
}

function parseCourse(flat) {
  const patterns = [
    /コース\s*:?\s*([0-9,]+)\s*(?:メートル|m)\s*[（(]?\s*(芝|ダート|障害)\s*(?:[・／/\s]*\s*(右|左|直線|外|内|外内|内外))?/,
    /(芝|ダート|障害)\s*([0-9,]+)\s*(?:メートル|m)\s*[（(]?\s*(右|左|直線|外|内|外内|内外)?/
  ];
  for (const [index, pattern] of patterns.entries()) {
    const match = flat.match(pattern);
    if (!match) continue;
    if (index === 0) {
      return {
        distanceM: match[1] ? Number(match[1].replace(/,/g, "")) : null,
        surface: match[2] ?? null,
        direction: match[3] ?? null
      };
    }
    return {
      distanceM: match[2] ? Number(match[2].replace(/,/g, "")) : null,
      surface: match[1] ?? null,
      direction: match[3] ?? null
    };
  }
  return { distanceM: null, surface: null, direction: null };
}

function parseConditions(flat, raceName) {
  const courseMatch = flat.match(/コース\s*:?\s*[0-9,]+\s*(?:メートル|m)/)
    ?? flat.match(/(?:芝|ダート|障害)\s*[0-9,]+\s*(?:メートル|m)/);
  if (!courseMatch || courseMatch.index == null) return null;
  const before = flat.slice(Math.max(0, courseMatch.index - 420), courseMatch.index).trim();
  const raceNameIndex = raceName ? before.lastIndexOf(raceName) : -1;
  let candidate = raceNameIndex >= 0 ? before.slice(raceNameIndex + raceName.length).trim() : before;

  candidate = candidate
    .replace(/^.*?(?:発走時刻\s*:?\s*\d{1,2}時\d{2}分|発走\s*:?\s*\d{1,2}:\d{2})\s*/u, "")
    .replace(/^.*?(?:天候\s*:?\s*\S+\s*)?(?:芝|ダート)\s*:?\s*(?:良|稍重|重|不良)\s*/u, "")
    .replace(/^.*?\d{1,2}(?:R|レース)\s*/u, "")
    .trim();

  if (candidate.length > 240) candidate = candidate.slice(-240).trim();
  return candidate || null;
}

export function parseLegacyRaceMeta(html, pageUrl) {
  const flat = flatText(html);
  const cname = decodeURIComponent(new URL(pageUrl).searchParams.get("CNAME") ?? "");
  const raceNo = Number(cname.match(/(\d{2})20\d{6}\//i)?.[1] ?? 0)
    || Number(flat.match(/(?:^|\s)(\d{1,2})(?:R|レース)(?:\s|$)/)?.[1] ?? 0);
  if (!raceNo || raceNo < 1 || raceNo > 12) throw new Error("LEGACY_RACE_NUMBER_NOT_FOUND");

  const raceName = parseRaceName(html, raceNo, flat);
  const course = parseCourse(flat);
  const conditions = parseConditions(flat, raceName);
  const weather = flat.match(/天候\s*:?\s*([^\s]+)/)?.[1] ?? null;
  const trackCondition = flat.match(/(?:芝|ダート)\s*:?\s*(良|稍重|重|不良)/)?.[1] ?? null;

  return {
    raceNo,
    raceName,
    conditions,
    ...course,
    weather,
    trackCondition,
    provenance: "jra_legacy_result_meta_research_only"
  };
}
