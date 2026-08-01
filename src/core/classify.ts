import { extractTitle, htmlToNormalizedText, looksLikeHtml } from "./normalize.js";
import type { PageKind, ProbeEvidence } from "./types.js";

const BLOCK_MARKERS = ["Access Denied", "Forbidden", "Too Many Requests", "captcha", "CAPTCHA", "アクセスが集中", "ご利用いただけません", "不正なアクセス"];
const RESULT_MARKERS = ["レース結果", "発走時刻", "着順", "馬名"];
const RESULT_OPTIONAL_MARKERS = ["払戻金", "単勝", "人気", "騎手名"];
const ENTRY_MARKERS = ["出馬表", "発走時刻", "馬名"];
const ENTRY_OPTIONAL_MARKERS = ["枠", "馬番", "騎手", "単勝", "オッズ"];

function foundMarkers(text: string, markers: readonly string[]): string[] {
  return markers.filter((marker) => text.includes(marker));
}

function missingMarkers(text: string, markers: readonly string[]): string[] {
  return markers.filter((marker) => !text.includes(marker));
}

function score(foundRequired: number, totalRequired: number, foundOptional: number, totalOptional: number): number {
  const requiredScore = totalRequired === 0 ? 0 : foundRequired / totalRequired;
  const optionalScore = totalOptional === 0 ? 0 : foundOptional / totalOptional;
  return Math.round((requiredScore * 0.8 + optionalScore * 0.2) * 100) / 100;
}

export function classifyHtml(html: string, contentType: string | null = "text/html"): ProbeEvidence {
  const text = htmlToNormalizedText(html);
  const blocked = foundMarkers(text, BLOCK_MARKERS);
  const htmlLike = looksLikeHtml(html) || Boolean(contentType?.includes("html"));

  if (blocked.length > 0) {
    return { pageKind: "blocked", confidence: 1, markersFound: blocked, markersMissing: [], title: extractTitle(html), normalizedTextLength: text.length, looksLikeHtml: htmlLike, blockedReason: blocked.join(", ") };
  }

  if (contentType?.includes("text/plain") && /User-agent\s*:/i.test(text)) {
    return { pageKind: "robots", confidence: 1, markersFound: ["User-agent"], markersMissing: [], title: null, normalizedTextLength: text.length, looksLikeHtml: false, blockedReason: null };
  }

  const resultRequired = foundMarkers(text, RESULT_MARKERS);
  const resultOptional = foundMarkers(text, RESULT_OPTIONAL_MARKERS);
  const resultScore = score(resultRequired.length, RESULT_MARKERS.length, resultOptional.length, RESULT_OPTIONAL_MARKERS.length);
  const entryRequired = foundMarkers(text, ENTRY_MARKERS);
  const entryOptional = foundMarkers(text, ENTRY_OPTIONAL_MARKERS);
  const entryScore = score(entryRequired.length, ENTRY_MARKERS.length, entryOptional.length, ENTRY_OPTIONAL_MARKERS.length);

  let pageKind: PageKind = "unknown";
  let confidence = Math.max(resultScore, entryScore);
  let requiredMarkers: readonly string[] = [];
  let optionalMarkers: readonly string[] = [];

  if (resultScore >= 0.65 && resultScore >= entryScore) {
    pageKind = "race-result";
    requiredMarkers = RESULT_MARKERS;
    optionalMarkers = RESULT_OPTIONAL_MARKERS;
  } else if (entryScore >= 0.65) {
    pageKind = "race-entry";
    requiredMarkers = ENTRY_MARKERS;
    optionalMarkers = ENTRY_OPTIONAL_MARKERS;
  }

  const allExpected = [...requiredMarkers, ...optionalMarkers];
  return { pageKind, confidence, markersFound: foundMarkers(text, allExpected), markersMissing: missingMarkers(text, requiredMarkers), title: extractTitle(html), normalizedTextLength: text.length, looksLikeHtml: htmlLike, blockedReason: null };
}
