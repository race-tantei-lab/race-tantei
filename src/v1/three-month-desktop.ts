import type { PayoutRecord, RunnerRecord } from "./types.js";
import { clamp, decodeEntities, stripHtml } from "./utils.js";

const MARKET_TAKEOUT_FACTOR = 0.8;
const POPULARITY_POWER = 1.07;

function normalizedText(value: string): string {
  return decodeEntities(value)
    .replace(/<img\b[^>]*alt=["']([^"']*)["'][^>]*>/gi, " $1 ")
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/[０-９]/g, (char) => String(char.charCodeAt(0) - 0xfee0))
    .replace(/[－–—−]/g, "-")
    .replace(/\s+/g, " ")
    .trim();
}

function tableRows(html: string): string[][] {
  const rows: string[][] = [];
  for (const rowMatch of html.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const cells = [...(rowMatch[1] ?? "").matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)]
      .map((cell) => normalizedText(cell[1] ?? ""));
    if (cells.length >= 10 && (/^\d+$/.test(cells[2] ?? "") || cells.some((cell) => /取消|除外|中止|失格/.test(cell)))) {
      rows.push(cells);
    }
  }
  return rows;
}

function popularityOdds(runners: Array<{ horseNo: number; popularity: number | null; active: boolean }>): Map<number, number> {
  const active = runners.filter((runner) => runner.active);
  const fallbackStart = Math.max(active.length, ...active.map((runner) => runner.popularity ?? 0), 1);
  const weights = new Map<number, number>();
  let fallbackOffset = 0;
  for (const runner of active) {
    const rank = runner.popularity ?? fallbackStart + (++fallbackOffset);
    weights.set(runner.horseNo, Math.pow(Math.max(1, rank), -POPULARITY_POWER));
  }
  const total = [...weights.values()].reduce((sum, value) => sum + value, 0);
  const odds = new Map<number, number>();
  for (const runner of active) {
    const probability = total > 0
      ? (weights.get(runner.horseNo) ?? 0) / total
      : 1 / Math.max(1, active.length);
    const decimalOdds = clamp(MARKET_TAKEOUT_FACTOR / Math.max(0.0001, probability), 1.1, 999.9);
    odds.set(runner.horseNo, Math.floor(decimalOdds * 10) / 10);
  }
  return odds;
}

export function parseDesktopResultRunners(html: string): RunnerRecord[] {
  const parsed: RunnerRecord[] = [];
  for (const cells of tableRows(html)) {
    const horseNo = /^\d{1,2}$/.test(cells[2] ?? "") ? Number(cells[2]) : null;
    if (!horseNo || horseNo < 1 || horseNo > 18) continue;
    const joined = cells.join(" ");
    const runnerStatus: RunnerRecord["runnerStatus"] = /除外/.test(joined)
      ? "excluded"
      : /取消/.test(joined)
        ? "scratched"
        : "active";
    const frameMatch = (cells[1] ?? "").match(/(?:枠)?(\d{1,2})/);
    const sexAge = cells[4]?.match(/[牡牝騸セ]\d+/)?.[0] ?? null;
    const assignedWeight = cells[5]?.match(/\d+(?:\.\d+)?/)?.[0];
    const body = (cells[11] ?? joined).match(/(\d{3})\s*\(([+-]?\d+)\)/);
    const popularityCell = cells.at(-1) ?? "";
    const popularity = popularityCell.match(/^\d+$/)?.[0]
      ?? popularityCell.match(/(\d+)番人気/)?.[1]
      ?? null;
    const horseName = (cells[3] ?? "").replace(/ブリンカー着用/g, "").trim();
    if (!horseName) continue;
    parsed.push({
      horseNo,
      frameNo: frameMatch?.[1] ? Number(frameMatch[1]) : null,
      horseName,
      sexAge,
      coatColor: null,
      horseWeight: body?.[1] ? Number(body[1]) : null,
      weightChange: body?.[2] ? Number(body[2]) : null,
      jockey: cells[6]?.trim() || null,
      assignedWeight: assignedWeight ? Number(assignedWeight) : null,
      trainer: cells[12]?.trim() || null,
      stable: null,
      popularity: popularity ? Number(popularity) : null,
      runnerStatus,
      winOdds: null
    });
  }

  const unique = new Map<number, RunnerRecord>();
  for (const runner of parsed) unique.set(runner.horseNo, runner);
  const values = [...unique.values()].sort((a, b) => a.horseNo - b.horseNo);
  const odds = popularityOdds(values.map((runner) => ({
    horseNo: runner.horseNo,
    popularity: runner.popularity,
    active: runner.runnerStatus === "active"
  })));
  return values.map((runner) => ({
    ...runner,
    winOdds: runner.runnerStatus === "active" ? odds.get(runner.horseNo) ?? null : null
  }));
}

function normalizedPageText(html: string): string {
  return decodeEntities(html)
    .replace(/<script\b[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/[０-９]/g, (char) => String(char.charCodeAt(0) - 0xfee0))
    .replace(/[－–—−]/g, "-")
    .replace(/\s*-\s*/g, "-")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizePayoutText(html: string): string {
  const text = normalizedPageText(html);
  let start = text.lastIndexOf("払戻金 単勝");
  if (start < 0) {
    const trifecta = text.lastIndexOf("3連単");
    start = trifecta >= 0 ? text.lastIndexOf("払戻金", trifecta) : -1;
  }
  if (start < 0) return "";
  const endCandidates = [
    text.indexOf("勝馬の紹介", start),
    text.indexOf("レースや騎手等につく記号", start),
    text.indexOf("開催選択へ戻る", start)
  ].filter((index) => index > start).sort((a, b) => a - b);
  return text.slice(start, endCandidates[0] ?? text.length);
}

const PAYOUT_TYPES = ["単勝", "複勝", "枠連", "ワイド", "馬連", "馬単", "3連複", "3連単"] as const;

function sectionForType(text: string, type: string): string {
  const start = text.indexOf(type);
  if (start < 0) return "";
  const after = start + type.length;
  const next = PAYOUT_TYPES
    .map((candidate) => text.indexOf(candidate, after))
    .filter((index) => index >= 0)
    .sort((a, b) => a - b)[0];
  return text.slice(after, next ?? text.length);
}

function combinationPattern(type: string): string {
  if (type === "単勝" || type === "複勝") return "\\d{1,2}";
  if (type === "3連複" || type === "3連単") return "\\d{1,2}-\\d{1,2}-\\d{1,2}";
  return "\\d{1,2}-\\d{1,2}";
}

export function parseDesktopPayouts(html: string): PayoutRecord[] {
  const text = normalizePayoutText(html);
  const payouts: PayoutRecord[] = [];
  for (const type of PAYOUT_TYPES) {
    const section = sectionForType(text, type);
    if (!section) continue;
    const pattern = new RegExp(`(${combinationPattern(type)})\\s+([\\d,]+)\\s*円\\s+(\\d+)\\s*番人気`, "g");
    for (const match of section.matchAll(pattern)) {
      const payoutYen = Number((match[2] ?? "").replace(/,/g, ""));
      if (!Number.isFinite(payoutYen) || payoutYen <= 0 || !match[1]) continue;
      payouts.push({
        betType: type,
        combination: match[1],
        payoutYen,
        popularity: match[3] ? Number(match[3]) : null
      });
    }
  }
  return payouts;
}

export function desktopResultPlainText(html: string): string {
  return stripHtml(html).replace(/\s+/g, " ").trim();
}
