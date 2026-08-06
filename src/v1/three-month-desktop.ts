import type { PayoutRecord, RunnerRecord } from "./types.js";
import { clamp, decodeEntities, stripHtml } from "./utils.js";

const MARKET_TAKEOUT_FACTOR = 0.8;
const POPULARITY_POWER = 1.07;
const RESULT_COLUMN_COUNT = 14;
const RESULT_COLUMN = {
  finish: 0,
  frameNo: 1,
  horseNo: 2,
  horseName: 3,
  sexAge: 4,
  assignedWeight: 5,
  jockey: 6,
  time: 7,
  margin: 8,
  passingOrder: 9,
  final3f: 10,
  horseWeight: 11,
  trainer: 12,
  popularity: 13
} as const;

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
    const horseNo = cells[RESULT_COLUMN.horseNo] ?? "";
    const statusRow = cells.some((cell) => /取消|除外|中止|失格/.test(cell));
    if (/^\d{1,2}$/.test(horseNo) && (cells.length >= RESULT_COLUMN_COUNT || statusRow)) {
      rows.push(cells);
    }
  }
  return rows;
}

function completePopularity(
  runners: Array<{ horseNo: number; popularity: number | null; active: boolean }>
): boolean {
  const active = runners.filter((runner) => runner.active);
  if (active.length < 2 || active.length > 18) return false;
  const ranks = active.map((runner) => runner.popularity);
  if (ranks.some((rank) => rank === null || !Number.isInteger(rank))) return false;
  const values = ranks as number[];
  return values.every((rank) => rank >= 1 && rank <= active.length)
    && new Set(values).size === active.length;
}

function popularityOdds(
  runners: Array<{ horseNo: number; popularity: number | null; active: boolean }>
): Map<number, number> {
  const active = runners.filter((runner) => runner.active);
  if (!completePopularity(runners)) return new Map();

  const weights = new Map<number, number>();
  for (const runner of active) {
    const rank = runner.popularity as number;
    weights.set(runner.horseNo, Math.pow(rank, -POPULARITY_POWER));
  }
  const total = [...weights.values()].reduce((sum, value) => sum + value, 0);
  const odds = new Map<number, number>();
  for (const runner of active) {
    const probability = total > 0
      ? (weights.get(runner.horseNo) ?? 0) / total
      : 0;
    const decimalOdds = clamp(MARKET_TAKEOUT_FACTOR / Math.max(0.0001, probability), 1.1, 999.9);
    odds.set(runner.horseNo, Math.floor(decimalOdds * 10) / 10);
  }
  return odds;
}

function resultPopularity(value: string | undefined): number | null {
  const text = (value ?? "").trim();
  if (!/^\d{1,2}$/.test(text)) return null;
  const parsed = Number(text);
  return parsed >= 1 && parsed <= 18 ? parsed : null;
}

function trainerDetails(value: string | undefined): {
  trainer: string | null;
  stable: string | null;
} {
  const text = (value ?? "").trim();
  if (!text) return { trainer: null, stable: null };
  const match = text.match(/^(?:\[|\(|（)?(美浦|栗東|本会外)(?:\]|\)|）|[・\s]+)\s*(.+)$/);
  if (!match) return { trainer: text, stable: null };
  return {
    trainer: match[2]?.trim() || null,
    stable: match[1] ?? null
  };
}

export function parseDesktopResultRunners(html: string): RunnerRecord[] {
  const parsed: RunnerRecord[] = [];
  for (const cells of tableRows(html)) {
    const horseNo = /^\d{1,2}$/.test(cells[RESULT_COLUMN.horseNo] ?? "")
      ? Number(cells[RESULT_COLUMN.horseNo])
      : null;
    if (!horseNo || horseNo < 1 || horseNo > 18) continue;

    const joined = cells.join(" ");
    const runnerStatus: RunnerRecord["runnerStatus"] = /除外/.test(joined)
      ? "excluded"
      : /取消/.test(joined)
        ? "scratched"
        : "active";
    const frameMatch = (cells[RESULT_COLUMN.frameNo] ?? "").match(/(?:枠)?(\d{1,2})/);
    const sexAge = cells[RESULT_COLUMN.sexAge]?.match(/[牡牝騸セ]\d+/)?.[0] ?? null;
    const assignedWeight = cells[RESULT_COLUMN.assignedWeight]?.match(/\d+(?:\.\d+)?/)?.[0];
    const body = (cells[RESULT_COLUMN.horseWeight] ?? "")
      .match(/(\d{3})(?:kg)?\s*\((?:([+-]?\d+)|初出走)\)/i);
    const trainer = trainerDetails(cells[RESULT_COLUMN.trainer]);
    const popularity = runnerStatus === "active"
      ? resultPopularity(cells[RESULT_COLUMN.popularity])
      : null;
    const horseName = (cells[RESULT_COLUMN.horseName] ?? "")
      .replace(/ブリンカー着用/g, "")
      .trim();
    if (!horseName) continue;

    parsed.push({
      horseNo,
      frameNo: frameMatch?.[1] ? Number(frameMatch[1]) : null,
      horseName,
      sexAge,
      coatColor: null,
      horseWeight: body?.[1] ? Number(body[1]) : null,
      weightChange: body?.[2] ? Number(body[2]) : null,
      jockey: cells[RESULT_COLUMN.jockey]?.trim() || null,
      assignedWeight: assignedWeight ? Number(assignedWeight) : null,
      trainer: trainer.trainer,
      stable: trainer.stable,
      popularity,
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
