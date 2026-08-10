import { decodeEntities, stripHtml } from "../dist-test/src/v1/utils.js";

const UI_HEADINGS = new Set([
  "検索ウィンドウ",
  "出馬表",
  "レース結果",
  "払戻金",
  "関連メニュー",
  "コースレコード",
  "勝馬の紹介",
  "開催お知らせ",
  "開催日程",
  "馬場情報",
  "今週の注目レース"
]);

function normalizeDigits(value) {
  return value
    .replace(/[０-９]/g, (char) => String(char.charCodeAt(0) - 0xfee0))
    .replace(/，/g, ",")
    .replace(/[：﹕]/g, ":")
    .replace(/[－–—−]/g, "-");
}

function flatText(html) {
  return normalizeDigits(stripHtml(html)).replace(/\s+/g, " ").trim();
}

function headingTexts(html) {
  const out = [];
  for (const match of html.matchAll(/<h[1-6]\b[^>]*>([\s\S]*?)<\/h[1-6]>/gi)) {
    const text = normalizeDigits(stripHtml(match[1] ?? "")).replace(/\s+/g, " ").trim();
    if (text) out.push(text);
  }
  return out;
}

function explicitRaceName(html) {
  const patterns = [
    /<span\b[^>]*class=["'][^"']*\btitleRaceName\b[^"']*["'][^>]*>([\s\S]*?)<\/span>/i,
    /<[^>]+class=["'][^"']*\brace_num\b[^"']*["'][^>]*>[\s\S]*?<\/[^>]+>\s*<h[1-6][^>]*>([\s\S]*?)<\/h[1-6]>/i
  ];
  for (const pattern of patterns) {
    const raw = html.match(pattern)?.[1];
    if (!raw) continue;
    const text = normalizeDigits(stripHtml(raw)).replace(/\s+/g, " ").trim();
    if (text) return text;
  }
  return null;
}

function plausibleRaceName(text, raceNo) {
  const value = text.replace(new RegExp(`^${raceNo}(?:R|レース)\\s*`), "").trim();
  if (!value || UI_HEADINGS.has(value)) return null;
  if (/検索|メニュー|レース選択|開催選択|ホーム|ここから本文/.test(value)) return null;
  if (/20\d{2}年|\d+回(?:札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)\d+日/.test(value)) return null;
  if (/^(?:\d+歳|障害|サラ系)/.test(value) && /(?:馬齢|定量|別定|ハンデ|コース)/.test(value)) return null;
  return value;
}

function parseRaceName(html, raceNo, flat) {
  const explicit = explicitRaceName(html);
  if (explicit) return explicit;
  for (const heading of headingTexts(html)) {
    const candidate = plausibleRaceName(heading, raceNo);
    if (candidate) return candidate;
  }
  const marker = new RegExp(`${raceNo}(?:R|レース)\\s+([^\\n]{2,80})`);
  const fallback = flat.match(marker)?.[1]?.trim();
  return fallback && !UI_HEADINGS.has(fallback) ? fallback : `${raceNo}レース`;
}

function parseCourse(flat) {
  const match = flat.match(/コース\s*:?\s*([0-9,]+)\s*(?:メートル|m)\s*[（(]?\s*(芝|ダート|障害)\s*(?:[・\s]*\s*(右|左|直線|外|内|外内|内外))?/);
  return {
    distanceM: match?.[1] ? Number(match[1].replace(/,/g, "")) : null,
    surface: match?.[2] ?? null,
    direction: match?.[3] ?? null
  };
}

function parseConditions(flat, raceName) {
  const courseMatch = flat.match(/コース\s*:?\s*[0-9,]+\s*(?:メートル|m)/);
  if (!courseMatch || courseMatch.index == null) return null;
  const before = flat.slice(Math.max(0, courseMatch.index - 320), courseMatch.index).trim();
  const raceNameIndex = raceName ? before.lastIndexOf(raceName) : -1;
  let candidate = raceNameIndex >= 0 ? before.slice(raceNameIndex + raceName.length).trim() : before;
  candidate = candidate
    .replace(/^.*?(?:天候\s*\S+\s*)?(?:芝|ダート)\s*(?:良|稍重|重|不良)\s*/u, "")
    .replace(/^.*?\d{1,2}レース\s*/u, "")
    .trim();
  if (candidate.length > 220) candidate = candidate.slice(-220).trim();
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
