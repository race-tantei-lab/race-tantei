import type { PayoutRecord } from "./types.js";

const SUPPORTED = new Set(["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"]);
const ALL_HEADERS = new Set(["単勝", "複勝", "枠連", "ワイド", "馬連", "馬単", "3連複", "3連単"]);

function decodeEntities(value: string): string {
  return value
    .replace(/&nbsp;|&#160;/gi, " ")
    .replace(/&yen;|&#165;/gi, "¥")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&#(\d+);/g, (_match, code: string) => String.fromCodePoint(Number(code)))
    .replace(/&#x([0-9a-f]+);/gi, (_match, code: string) => String.fromCodePoint(Number.parseInt(code, 16)));
}

function normalizeHeader(value: string): string {
  return value
    .replace(/３/g, "3")
    .replace(/−|－|–|—/g, "-")
    .replace(/\s+/g, "")
    .trim();
}

function textLines(html: string): string[] {
  const withoutScripts = html
    .replace(/<script\b[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[\s\S]*?<\/style>/gi, " ")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/\s*(?:div|li|p|tr|td|th|section|h[1-6]|dd|dt|ul|ol)\s*>/gi, "\n")
    .replace(/<[^>]+>/g, " ");
  return decodeEntities(withoutScripts)
    .split(/\r?\n/)
    .map((line) => line.replace(/[\t\f\v ]+/g, " ").trim())
    .filter(Boolean);
}

function arity(betType: string): number {
  if (betType === "単勝") return 1;
  if (betType === "ワイド" || betType === "馬連" || betType === "馬単") return 2;
  return 3;
}

function parseCombination(betType: string, line: string): string | null {
  const normalized = line.replace(/３/g, "3").replace(/[－–—−]/g, "-").replace(/\s+/g, "").trim();
  const count = arity(betType);
  if (count === 1) {
    const match = normalized.match(/^(\d{1,2})$/);
    if (!match) return null;
    const value = Number(match[1]);
    return value >= 1 && value <= 18 ? String(value) : null;
  }
  const pattern = count === 2 ? /^(\d{1,2})-(\d{1,2})$/ : /^(\d{1,2})-(\d{1,2})-(\d{1,2})$/;
  const match = normalized.match(pattern);
  if (!match) return null;
  const numbers = match.slice(1).map(Number);
  if (numbers.some((value) => value < 1 || value > 18) || new Set(numbers).size !== count) return null;
  if (["ワイド", "馬連", "3連複"].includes(betType)) numbers.sort((a, b) => a - b);
  return numbers.join("-");
}

function parseYen(line: string): number | null {
  const normalized = line.replace(/\s+/g, "").replace(/¥/g, "円");
  const match = normalized.match(/^([\d,]+)円$/);
  if (!match) return null;
  const value = Number(match[1].replace(/,/g, ""));
  return Number.isFinite(value) && value >= 0 ? value : null;
}

function parsePopularity(line: string): number | null {
  const normalized = line.replace(/\s+/g, "");
  const match = normalized.match(/^(\d{1,3})番人気$/);
  return match ? Number(match[1]) : null;
}

export function parseJraPayoutsFromHtml(html: string): PayoutRecord[] {
  const lines = textLines(html);
  const payoutStarts = lines
    .map((line, index) => ({ line: normalizeHeader(line), index }))
    .filter((row) => row.line === "払戻金" || row.line === "払戻し" || row.line === "払戻");
  const start = payoutStarts.find((candidate) => lines.slice(candidate.index + 1, candidate.index + 120).some((line) => /[\d,]+\s*(?:円|¥)/.test(line)))?.index;
  if (start === undefined) return [];

  const rows: PayoutRecord[] = [];
  let currentType: string | null = null;
  let pendingCombination: string | null = null;
  let lastRowIndex = -1;

  for (let i = start + 1; i < lines.length; i += 1) {
    const raw = lines[i];
    const normalized = normalizeHeader(raw);
    if (/^(?:勝馬の紹介|レース映像|開催選択へ戻る|ページトップへ戻る)/.test(normalized)) break;

    if (ALL_HEADERS.has(normalized)) {
      currentType = SUPPORTED.has(normalized) ? normalized : null;
      pendingCombination = null;
      lastRowIndex = -1;
      continue;
    }
    if (!currentType) continue;

    const combination = parseCombination(currentType, raw);
    if (combination !== null) {
      pendingCombination = combination;
      lastRowIndex = -1;
      continue;
    }

    const payoutYen = parseYen(raw);
    if (payoutYen !== null && pendingCombination !== null) {
      rows.push({ betType: currentType, combination: pendingCombination, payoutYen, popularity: null });
      lastRowIndex = rows.length - 1;
      pendingCombination = null;
      continue;
    }

    const popularity = parsePopularity(raw);
    if (popularity !== null && lastRowIndex >= 0) {
      rows[lastRowIndex] = { ...rows[lastRowIndex], popularity };
      lastRowIndex = -1;
    }
  }

  const deduped = new Map<string, PayoutRecord>();
  for (const row of rows) deduped.set(`${row.betType}:${row.combination}`, row);
  return [...deduped.values()];
}
