import type { PayoutRecord, RunnerRecord } from "./types.js";
import { clamp, decodeEntities, stripHtml } from "./utils.js";

const MARKET_TAKEOUT_FACTOR = 0.8;
const POPULARITY_POWER = 1.07;

interface RunnerTableRow {
  cells: string[];
  popularityIndex: number | null;
}

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

function expandedCells(rowHtml: string): string[] {
  const cells: string[] = [];
  for (const cellMatch of rowHtml.matchAll(/<t([dh])\b([^>]*)>([\s\S]*?)<\/t\1>/gi)) {
    const attributes = cellMatch[2] ?? "";
    const text = normalizedText(cellMatch[3] ?? "");
    const parsedColspan = Number(attributes.match(/\bcolspan\s*=\s*["']?(\d+)/i)?.[1] ?? "1");
    const colspan = Number.isInteger(parsedColspan) && parsedColspan > 0 && parsedColspan <= 20
      ? parsedColspan
      : 1;
    for (let index = 0; index < colspan; index += 1) cells.push(text);
  }
  return cells;
}

function runnerTableRows(html: string): RunnerTableRow[] {
  const tables = [...html.matchAll(/<table\b[^>]*>([\s\S]*?)<\/table>/gi)]
    .map((match) => match[1] ?? "");
  const sections = tables.length > 0 ? tables : [html];
  const rows: RunnerTableRow[] = [];

  for (const section of sections) {
    let popularityIndex: number | null = null;
    for (const rowMatch of section.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
      const cells = expandedCells(rowMatch[1] ?? "");
      if (cells.length === 0) continue;

      const isRunnerRow = cells.length >= 10
        && (/^\d+$/.test(cells[2] ?? "") || cells.some((cell) => /取消|除外|中止|失格/.test(cell)));
      if (!isRunnerRow) {
        const headerIndex = cells.findIndex((cell) => /人気/.test(cell.replace(/\s+/g, "")));
        if (headerIndex >= 0) popularityIndex = headerIndex;
        continue;
      }

      rows.push({ cells, popularityIndex });
    }
  }

  return rows;
}

function parsedPopularity(cells: string[], popularityIndex: number | null): number | null {
  for (const cell of cells) {
    const explicit = cell.match(/(?:^|\s)(\d{1,2})\s*番人気(?:\s|$)/)?.[1];
    if (explicit) {
      const rank = Number(explicit);
      return Number.isInteger(rank) && rank >= 1 && rank <= 18 ? rank : null;
    }
  }

  if (popularityIndex === null) return null;
  const cell = cells[popularityIndex] ?? "";
  const bare = cell.match(/(?:^|\s)(\d{1,2})\s*$/)?.[1] ?? null;
  if (!bare) return null;
  const rank = Number(bare);
  return Number.isInteger(rank) && rank >= 1 && rank <= 18 ? rank : null;
}

function popularityOdds(runners: Array<{ horseNo: number; popularity: number | null; active: boolean }>): Map<number, number> {
  const active = runners.filter((runner) => runner.active);
  if (active.length === 0 || active.some((runner) => runner.popularity === null)) return new Map();

  const weights = new Map<number, number>();
  for (const runner of active) {
    const rank = runner.popularity;
    if (rank === null) continue;
    weights.set(runner.horseNo, Math.pow(Math.max(1, rank), -POPULARITY_POWER));
  }
  const total = [...weights.values()].reduce((sum, value) => sum + value, 0);
  const odds = new Map<number, number>();
  for (const runner of active) {
    const probability = total > 0
      ? (weights.get(runner.horseNo) ?? 0) / total
      : 0;
    if (probability <= 0) continue;
    const decimalOdds = clamp(MARKET_TAKEOUT_FACTOR / Math.max(0.0001, probability), 1.1, 999.9);
    odds.set(runner.horseNo, Math.floor(decimalOdds * 10) / 10);
  }
  return odds;
}

export function parseDesktopResultRunners(html: string): RunnerRecord[] {
  const parsed: RunnerRecord[] = [];
  for (const { cells, popularityIndex } of runnerTableRows(html)) {
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
    const popularity = parsedPopularity(cells, popularityIndex);
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
      popularity,
      runnerStatus,
      winOdds: null
    });
  }

  const unique = new Map<number, RunnerRecord>();
  for (const runner of parsed) unique.set(runner.horseNo, runner);
  const values = [...unique.values()].sort((a, b) => a.horseNo - b.horseNo);
  const activeCount = values.filter((runner) => runner.runnerStatus === "active").length;
  const sanitized = values.map((runner) => {
    const validPopularity = runner.runnerStatus === "active"
      && runner.popularity !== null
      && runner.popularity >= 1
      && runner.popularity <= activeCount
        ? runner.popularity
        : null;
    return { ...runner, popularity: validPopularity };
  });
  const odds = popularityOdds(sanitized.map((runner) => ({
    horseNo: runner.horseNo,
    popularity: runner.popularity,
    active: runner.runnerStatus === "active"
  })));
  return sanitized.map((runner) => ({
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
