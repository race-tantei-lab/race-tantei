import {
  advanceCompletedSelectionState,
  hydrateCompletedSelectionState,
  selectCompletedTargetRaces,
  type CompletedSelectionBundle,
  type CompletedSelectionState,
  type RawCompletedSelectionState,
} from "./completed-selection-runtime.js";
import { COMPLETED_MODEL_VERSION } from "./completed-feature-runtime.js";
import type { RaceRecord, RunnerRecord } from "./types.js";

const SEL_VENUES = ["東京", "中山", "京都", "阪神", "中京", "新潟", "福島", "小倉", "札幌", "函館"] as const;
const SEL_VENUE_MAP = new Map(SEL_VENUES.map((venue, index) => [venue, index]));
const SINGLES = ["venue", "surface", "dist", "field", "raceNo", "rclass", "bestform", "bestspeed", "bestj", "bestt", "expcnt", "top3lastsum"] as const;
const PAIRS = [["surface", "bestform"], ["dist", "bestform"], ["rclass", "bestform"], ["field", "expcnt"], ["bestform", "bestspeed"], ["bestj", "bestt"], ["expcnt", "top3lastsum"], ["bestform", "top3lastsum"]] as const;
const TOP_HORSES = 5;
const MIN_N = 500;
const KEY_PRIOR = 2000;
const BET_PRIOR = 5000;
const PRIOR_ROI = 0.80;
const TOP_COMPONENTS = 8;
const TICKETS_PER_RACE = 3;
const LOCAL_WEIGHT = 0.60;
const SELECTION_PREFIX = "final_daily_selection:";
const EXPLANATION_PREFIX = "worker_selection_explanation:";
const EXPLANATION_VERSION = "canonical-selection-trace-v1";

type FeatureTuple = [number, number, number, number, number, number];
type Stat2 = [number, number];
type ResultRow = { horseNo: number; finishPosition: number | null; final3f: number | null };
type PayoutRow = { betType: string; combination: string; payoutYen: number };
type StateChunk = { seq: number; dataB64: string };
type SelectionTicket = { bt: number; betType: string; combo: string; horses: number[]; vals: Record<string, number>; score?: number };
type FrozenSelectedRace = { raceId: string; venue: string; raceNo: number; raceScore: number };

type SelectionComponentEvidence = {
  axes: string[];
  values: number[];
  label: string;
  sampleN: number;
  smoothedRoi: number;
  reliability: number;
  complexity: number;
  effectiveWeight: number;
};

export type SelectionProxyTicketEvidence = {
  betType: string;
  combination: string;
  horses: number[];
  globalSampleN: number;
  globalSmoothedRoi: number;
  eligibleComponentCount: number;
  localWeightedRoi: number | null;
  localWeight: number;
  globalWeight: number;
  finalScore: number;
  usedFallback: boolean;
  topComponents: SelectionComponentEvidence[];
};

export type SelectionHorseEvidence = {
  horseNo: number;
  horseName: string;
  jockey: string;
  trainer: string;
  formCode: number;
  speedCode: number;
  jockeyCode: number;
  trainerCode: number;
  startsCode: number;
  recentTop3Count: number;
  strength: number[];
};

export type CompletedSelectionExplanation = {
  version: string;
  sourceModel: string;
  raceId: string;
  raceDate: string;
  venue: string;
  raceNo: number;
  venueRank: number;
  raceScore: number;
  verifiedAgainstFrozenSelection: true;
  stateBaseThroughDate: string;
  stateAdvancedThroughDate: string;
  topHorses: SelectionHorseEvidence[];
  proxyTickets: SelectionProxyTicketEvidence[];
  scoreFormula: { localWeight: number; globalWeight: number; topComponents: number; minSampleN: number; keyPriorN: number; betPriorN: number; priorRoi: number };
};

const BET_SPECS: Record<number, { k: number; betType: string; ordered: boolean }> = {
  0: { k: 1, betType: "単勝", ordered: false },
  1: { k: 2, betType: "馬連", ordered: false },
  2: { k: 2, betType: "ワイド", ordered: false },
  3: { k: 2, betType: "馬単", ordered: true },
  4: { k: 3, betType: "3連複", ordered: false },
  5: { k: 3, betType: "3連単", ordered: true },
};

let ensurePromises = new Map<string, Promise<void>>();

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

async function gunzipJson(bytes: Uint8Array): Promise<RawCompletedSelectionState> {
  const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
  const body = new Response(buffer).body;
  if (!body) throw new Error("SELECTION_EXPLANATION_STATE_BODY_MISSING");
  return JSON.parse(await new Response(body.pipeThrough(new DecompressionStream("gzip"))).text()) as RawCompletedSelectionState;
}

function statsKey(bt: number, axes: readonly string[], vals: readonly number[]): string {
  return JSON.stringify([bt, axes, vals]);
}

async function loadCanonicalSelectionState(db: D1Database): Promise<CompletedSelectionState> {
  const metaRows = await db.prepare("SELECT key,value FROM rt_selection_state_meta").all<{ key: string; value: string }>();
  const meta = new Map((metaRows.results ?? []).map((row) => [row.key, row.value]));
  if (meta.get("ready") !== "1" || meta.get("modelVersion") !== COMPLETED_MODEL_VERSION) throw new Error("SELECTION_EXPLANATION_STATE_NOT_READY");
  const generation = meta.get("generation") || "";
  const chunkCount = Number(meta.get("chunkCount") || 0);
  const byteLength = Number(meta.get("byteLength") || 0);
  if (!generation || !Number.isInteger(chunkCount) || chunkCount <= 0 || !Number.isInteger(byteLength) || byteLength <= 0) throw new Error("SELECTION_EXPLANATION_STATE_META_INVALID");
  const chunkRows = await db.prepare("SELECT seq,data_b64 AS dataB64 FROM rt_selection_state_chunk WHERE generation=? ORDER BY seq").bind(generation).all<StateChunk>();
  const rows = chunkRows.results ?? [];
  if (rows.length !== chunkCount || rows.some((row, index) => Number(row.seq) !== index)) throw new Error("SELECTION_EXPLANATION_STATE_CHUNKS_INCOMPLETE");
  const parts = rows.map((row) => decodeBase64(row.dataB64));
  const actualLength = parts.reduce((sum, part) => sum + part.byteLength, 0);
  if (actualLength !== byteLength) throw new Error(`SELECTION_EXPLANATION_STATE_BYTE_LENGTH_MISMATCH:${actualLength}:${byteLength}`);
  const bytes = new Uint8Array(byteLength);
  let offset = 0;
  for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
  const state = hydrateCompletedSelectionState(await gunzipJson(bytes));
  if (state.throughDate !== meta.get("throughDate") || state.currentQuarter !== meta.get("currentQuarter")) throw new Error("SELECTION_EXPLANATION_STATE_METADATA_MISMATCH");
  return state;
}

async function loadBundles(db: D1Database, where: string, params: unknown[]): Promise<CompletedSelectionBundle[]> {
  const raceResult = await db.prepare(`SELECT race_id AS raceId,race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,race_no AS raceNo,race_name AS raceName,conditions,surface,distance_m AS distanceM,direction,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,weather,track_condition AS trackCondition,entry_url AS entryUrl,result_url AS resultUrl,status FROM rt_races WHERE ${where} ORDER BY race_date,venue,race_no`).bind(...params).all<RaceRecord>();
  const races = raceResult.results ?? [];
  if (!races.length) return [];
  const idsJson = JSON.stringify(races.map((race) => race.raceId));
  const [runnerResult, resultResult, payoutResult] = await db.batch([
    db.prepare("SELECT race_id AS raceId,horse_no AS horseNo,frame_no AS frameNo,horse_name AS horseName,sex_age AS sexAge,coat_color AS coatColor,horse_weight AS horseWeight,weight_change AS weightChange,jockey,assigned_weight AS assignedWeight,trainer,stable,win_odds AS winOdds,popularity,runner_status AS runnerStatus FROM rt_runners WHERE race_id IN (SELECT value FROM json_each(?)) ORDER BY race_id,horse_no").bind(idsJson),
    db.prepare("SELECT race_id AS raceId,horse_no AS horseNo,finish_position AS finishPosition,final3f FROM rt_results WHERE race_id IN (SELECT value FROM json_each(?)) ORDER BY race_id,horse_no").bind(idsJson),
    db.prepare("SELECT race_id AS raceId,bet_type AS betType,combination,payout_yen AS payoutYen FROM rt_payouts WHERE race_id IN (SELECT value FROM json_each(?)) ORDER BY race_id,bet_type,combination").bind(idsJson),
  ]);
  const byId = new Map(races.map((race) => [race.raceId, { race, runners: [] as RunnerRecord[], results: [] as ResultRow[], payouts: [] as PayoutRow[] }]));
  for (const row of (runnerResult.results ?? []) as Array<RunnerRecord & { raceId: string }>) byId.get(String(row.raceId))?.runners.push(row);
  for (const row of (resultResult.results ?? []) as Array<ResultRow & { raceId: string }>) byId.get(String(row.raceId))?.results.push(row);
  for (const row of (payoutResult.results ?? []) as Array<PayoutRow & { raceId: string }>) byId.get(String(row.raceId))?.payouts.push(row);
  return races.map((race) => byId.get(race.raceId)!);
}

function horseKey(raceId: string, runner: RunnerRecord): string {
  const name = String(runner.horseName || "").trim();
  return name || `__missing__:${raceId}:${runner.horseNo}`;
}
function formCode(value: number, has: boolean): number { return !has ? 0 : value < .30 ? 1 : value < .50 ? 2 : value < .70 ? 3 : 4; }
function rateCode(value: number): number { return value < .15 ? 0 : value < .25 ? 1 : value < .35 ? 2 : value < .45 ? 3 : 4; }
function startsBin(n: number): number { return n === 0 ? 0 : n <= 2 ? 1 : n <= 5 ? 2 : n <= 10 ? 3 : 4; }
function distBin(distance: number): number { return distance <= 1200 ? 0 : distance <= 1500 ? 1 : distance <= 1800 ? 2 : distance <= 2200 ? 3 : distance <= 2600 ? 4 : 5; }
function fieldBin(n: number): number { return n <= 8 ? 0 : n <= 11 ? 1 : n <= 13 ? 2 : n <= 16 ? 3 : 4; }
function raceNoBin(n: number): number { return n <= 3 ? 0 : n <= 6 ? 1 : n <= 9 ? 2 : 3; }
function normalizeClassText(value: unknown): string { return String(value || "").replaceAll("500万下", "1勝クラス").replaceAll("1000万下", "2勝クラス").replaceAll("1600万下", "3勝クラス"); }
function classBin(name: unknown, conditions: unknown): number {
  const text = `${normalizeClassText(name)} ${normalizeClassText(conditions)}`.replaceAll(" ", "");
  if (text.includes("(GI)") || text.includes("GⅠ") || text.includes("ＧⅠ")) return 8;
  if (text.includes("(GII)") || text.includes("GⅡ") || text.includes("ＧⅡ")) return 7;
  if (text.includes("(GIII)") || text.includes("GⅢ") || text.includes("ＧⅢ")) return 6;
  if (text.includes("新馬")) return 0;
  if (text.includes("未勝利")) return 1;
  if (text.includes("1勝")) return 2;
  if (text.includes("2勝")) return 3;
  if (text.includes("3勝")) return 4;
  if (text.includes("(L)") || text.includes("オープン") || text.includes("OP")) return 5;
  return 9;
}

function selectionFeatureTuple(state: CompletedSelectionState, raceId: string, runner: RunnerRecord): FeatureTuple {
  const key = horseKey(raceId, runner);
  const prior = state.horseHist.get(key) ?? [];
  let form = 0, speed = 0, top3 = 0, has = false;
  if (prior.length) {
    form = prior.reduce((sum, row) => sum + row[0], 0) / prior.length;
    speed = prior.reduce((sum, row) => sum + row[1], 0) / prior.length;
    top3 = prior.reduce((sum, row) => sum + row[2], 0);
    has = true;
  }
  const jockey = String(runner.jockey || ""), trainer = String(runner.trainer || "");
  const js: Stat2 = jockey ? (state.jstats.get(jockey) ?? [0, 0]) : [0, 0];
  const ts: Stat2 = trainer ? (state.tstats.get(trainer) ?? [0, 0]) : [0, 0];
  const jr = (js[1] + 3) / (js[0] + 15), tr = (ts[1] + 3) / (ts[0] + 15), starts = state.horseStarts.get(key) ?? 0;
  return [formCode(form, has), formCode(speed, has), rateCode(jr), rateCode(tr), startsBin(starts), Math.trunc(top3)];
}
function strength(feature: FeatureTuple, horseNo: number): number[] { return [feature.slice(0, 5).reduce((sum, value) => sum + value, 0) + Math.min(3, feature[5]), feature[0] + feature[1], feature[2] + feature[3], feature[5], -horseNo]; }
function compareTupleDesc(a: readonly number[], b: readonly number[]): number { for (let i = 0; i < Math.min(a.length, b.length); i += 1) if (a[i] !== b[i]) return b[i] - a[i]; return 0; }
function baseVals(race: RaceRecord, n: number): Record<string, number> {
  const venue = String(race.venue || ""), surface = String(race.surface || "障害"), distance = Number(race.distanceM || 0), raceNo = Number(race.raceNo || 0);
  const venueCode = SEL_VENUE_MAP.get(venue as (typeof SEL_VENUES)[number]);
  if (venueCode == null) throw new Error(`SELECTION_EXPLANATION_UNKNOWN_VENUE:${venue}`);
  return { venue: venueCode, surface: surface === "芝" ? 0 : surface === "ダート" ? 1 : 2, dist: distBin(distance), field: fieldBin(n), raceNo: raceNoBin(raceNo), rclass: classBin(race.raceName, race.conditions) };
}
function comboVals(base: Record<string, number>, bt: number, features: FeatureTuple[]): Record<string, number> {
  return { ...base, bet: bt, goodcnt: Math.min(3, features.filter((x) => x[0] >= 3).length), bestform: Math.max(...features.map((x) => x[0])), bestspeed: Math.max(...features.map((x) => x[1])), bestj: Math.max(...features.map((x) => x[2])), bestt: Math.max(...features.map((x) => x[3])), expcnt: Math.min(3, features.filter((x) => x[4] >= 2).length), top3lastsum: Math.min(7, features.reduce((sum, x) => sum + x[5], 0)) };
}
function candidateKeys(vals: Record<string, number>): Array<[string[], number[]]> {
  const out: Array<[string[], number[]]> = [];
  for (const axis of SINGLES) out.push([[axis], [vals[axis]]]);
  for (const [a, b] of PAIRS) out.push([[a, b], [vals[a], vals[b]]]);
  return out;
}
function* combinations(values: readonly number[], k: number, start = 0, prefix: number[] = []): Generator<number[]> {
  if (prefix.length === k) { yield prefix.slice(); return; }
  for (let index = start; index <= values.length - (k - prefix.length); index += 1) { prefix.push(values[index]); yield* combinations(values, k, index + 1, prefix); prefix.pop(); }
}
function* permutations(values: readonly number[], k: number, prefix: number[] = [], used = new Set<number>()): Generator<number[]> {
  if (prefix.length === k) { yield prefix.slice(); return; }
  for (let index = 0; index < values.length; index += 1) { if (used.has(index)) continue; used.add(index); prefix.push(values[index]); yield* permutations(values, k, prefix, used); prefix.pop(); used.delete(index); }
}

function candidateRows(state: CompletedSelectionState, bundle: CompletedSelectionBundle): { tickets: SelectionTicket[]; topHorses: SelectionHorseEvidence[] } {
  const race = bundle.race, raceId = String(race.raceId);
  const runners = bundle.runners.filter((runner) => (runner.runnerStatus || "active") === "active").slice().sort((a, b) => Number(a.horseNo) - Number(b.horseNo));
  if (runners.length < 3) return { tickets: [], topHorses: [] };
  const features = new Map<number, FeatureTuple>();
  for (const runner of runners) features.set(Number(runner.horseNo), selectionFeatureTuple(state, raceId, runner));
  const ranked = [...features.keys()].sort((a, b) => compareTupleDesc(strength(features.get(a)!, a), strength(features.get(b)!, b))).slice(0, TOP_HORSES);
  const byNo = new Map(runners.map((runner) => [Number(runner.horseNo), runner]));
  const topHorses = ranked.map((horseNo) => {
    const feature = features.get(horseNo)!, runner = byNo.get(horseNo)!;
    return { horseNo, horseName: String(runner.horseName || ""), jockey: String(runner.jockey || ""), trainer: String(runner.trainer || ""), formCode: feature[0], speedCode: feature[1], jockeyCode: feature[2], trainerCode: feature[3], startsCode: feature[4], recentTop3Count: feature[5], strength: strength(feature, horseNo) };
  });
  const base = baseVals(race, runners.length), tickets: SelectionTicket[] = [];
  for (let bt = 0; bt <= 5; bt += 1) {
    const spec = BET_SPECS[bt];
    if (ranked.length < spec.k) continue;
    const iterator = spec.ordered ? permutations(ranked, spec.k) : combinations(ranked, spec.k);
    for (const horses of iterator) {
      const comboValues = spec.ordered ? horses : horses.slice().sort((a, b) => a - b);
      tickets.push({ bt, betType: spec.betType, combo: comboValues.join("-"), horses: comboValues, vals: comboVals(base, bt, horses.map((horse) => features.get(horse)!)) });
    }
  }
  return { tickets, topHorses };
}

function meanRoi(n: number, ret: number, priorN: number, priorRoi: number): number { return (ret + priorN * 100 * priorRoi) / (100 * (n + priorN)); }

function codeRange(kind: string, value: number): string {
  if (kind === "bestform" || kind === "bestspeed") return ["履歴なし", "30%未満", "30〜50%未満", "50〜70%未満", "70%以上"][value] ?? `区分${value}`;
  if (kind === "bestj" || kind === "bestt") return ["15%未満", "15〜25%未満", "25〜35%未満", "35〜45%未満", "45%以上"][value] ?? `区分${value}`;
  return String(value);
}
function axisValueLabel(axis: string, value: number): string {
  if (axis === "venue") return `会場=${SEL_VENUES[value] ?? `区分${value}`}`;
  if (axis === "surface") return `馬場=${["芝", "ダート", "障害"][value] ?? `区分${value}`}`;
  if (axis === "dist") return `距離=${["〜1200m", "1201〜1500m", "1501〜1800m", "1801〜2200m", "2201〜2600m", "2601m〜"][value] ?? `区分${value}`}`;
  if (axis === "field") return `頭数=${["8頭以下", "9〜11頭", "12〜13頭", "14〜16頭", "17頭以上"][value] ?? `区分${value}`}`;
  if (axis === "raceNo") return `R帯=${["1〜3R", "4〜6R", "7〜9R", "10〜12R"][value] ?? `区分${value}`}`;
  if (axis === "rclass") return `クラス=${["新馬", "未勝利", "1勝", "2勝", "3勝", "OP/L", "G3", "G2", "G1", "その他"][value] ?? `区分${value}`}`;
  if (axis === "bestform") return `組合せ内・近走着順指数の最高=${codeRange(axis, value)}`;
  if (axis === "bestspeed") return `組合せ内・近走速度指数の最高=${codeRange(axis, value)}`;
  if (axis === "bestj") return `組合せ内・騎手3着内率の最高=${codeRange(axis, value)}`;
  if (axis === "bestt") return `組合せ内・調教師3着内率の最高=${codeRange(axis, value)}`;
  if (axis === "expcnt") return `組合せ内・3走以上経験馬=${value >= 3 ? "3頭以上" : `${value}頭`}`;
  if (axis === "top3lastsum") return `組合せ馬・直近3走3着内合計=${value >= 7 ? "7回以上" : `${value}回`}`;
  return `${axis}=${value}`;
}
function componentLabel(axes: string[], vals: number[]): string { return axes.map((axis, index) => axisValueLabel(axis, vals[index])).join(" × "); }

function ticketEvidence(ticket: SelectionTicket, state: CompletedSelectionState): SelectionProxyTicketEvidence {
  const bs = state.betStats.get(ticket.bt) ?? [0, 0], bmean = meanRoi(bs[0], bs[1], BET_PRIOR, PRIOR_ROI);
  const comps: SelectionComponentEvidence[] = [];
  for (const [axes, vals] of candidateKeys(ticket.vals)) {
    const stat = state.stats.get(statsKey(ticket.bt, axes, vals)) ?? [0, 0];
    if (stat[0] < MIN_N) continue;
    const km = meanRoi(stat[0], stat[1], KEY_PRIOR, bmean), reliability = stat[0] / (stat[0] + KEY_PRIOR), complexity = axes.length === 1 ? 1 : .92;
    comps.push({ axes, values: vals, label: componentLabel(axes, vals), sampleN: stat[0], smoothedRoi: km, reliability, complexity, effectiveWeight: reliability * complexity });
  }
  comps.sort((a, b) => (b.smoothedRoi - a.smoothedRoi) || (b.effectiveWeight - a.effectiveWeight) || (b.sampleN - a.sampleN));
  const top = comps.slice(0, TOP_COMPONENTS), weight = top.reduce((sum, row) => sum + row.effectiveWeight, 0);
  const local = weight ? top.reduce((sum, row) => sum + row.smoothedRoi * row.effectiveWeight, 0) / weight : null;
  const score = local == null ? bmean * .95 : (1 - LOCAL_WEIGHT) * bmean + LOCAL_WEIGHT * local;
  return { betType: ticket.betType, combination: ticket.combo, horses: ticket.horses, globalSampleN: bs[0], globalSmoothedRoi: bmean, eligibleComponentCount: comps.length, localWeightedRoi: local, localWeight: LOCAL_WEIGHT, globalWeight: 1 - LOCAL_WEIGHT, finalScore: score, usedFallback: local == null, topComponents: top };
}

function selectProxyTicketEvidence(rows: SelectionTicket[], state: CompletedSelectionState): SelectionProxyTicketEvidence[] {
  const scored = rows.map((ticket) => ticketEvidence(ticket, state));
  scored.sort((a, b) => (b.finalScore - a.finalScore) || ((Object.entries(BET_SPECS).find(([, spec]) => spec.betType === a.betType)?.[0] ?? "9").localeCompare(Object.entries(BET_SPECS).find(([, spec]) => spec.betType === b.betType)?.[0] ?? "9")) || (a.combination < b.combination ? -1 : a.combination > b.combination ? 1 : 0));
  if (scored.length < TICKETS_PER_RACE) throw new Error("SELECTION_EXPLANATION_TOO_FEW_CANDIDATE_TICKETS");
  const chosen = scored.slice(0, TICKETS_PER_RACE), types = new Set(chosen.map((ticket) => ticket.betType));
  if (types.size < 2) {
    const alt = scored.slice(TICKETS_PER_RACE).find((ticket) => !types.has(ticket.betType));
    if (!alt) throw new Error("SELECTION_EXPLANATION_NO_SECOND_BET_TYPE");
    chosen[chosen.length - 1] = alt;
  }
  chosen.sort((a, b) => (b.finalScore - a.finalScore) || (a.betType < b.betType ? -1 : a.betType > b.betType ? 1 : 0) || (a.combination < b.combination ? -1 : a.combination > b.combination ? 1 : 0));
  return chosen;
}

function roundedScore(value: number): number { return Math.round(value * 1e8) / 1e8; }
function sameNumber(a: number, b: number): boolean { return Math.abs(Number(a) - Number(b)) <= 1e-8; }

async function buildExplanations(db: D1Database, date: string): Promise<CompletedSelectionExplanation[]> {
  const frozenRow = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1").bind(`${SELECTION_PREFIX}${date}`).first<{ value: string }>();
  if (!frozenRow?.value) throw new Error(`SELECTION_EXPLANATION_FROZEN_SELECTION_MISSING:${date}`);
  const frozenPayload = JSON.parse(frozenRow.value) as { sourceModel?: string; resultDataUsedForTargetDay?: boolean; selected?: FrozenSelectedRace[] };
  if (frozenPayload.sourceModel !== COMPLETED_MODEL_VERSION || frozenPayload.resultDataUsedForTargetDay !== false || !Array.isArray(frozenPayload.selected)) throw new Error("SELECTION_EXPLANATION_FROZEN_SELECTION_INVALID");

  const state = await loadCanonicalSelectionState(db), baseThroughDate = state.throughDate;
  if (state.throughDate < date) advanceCompletedSelectionState(state, await loadBundles(db, "race_date>? AND race_date<?", [state.throughDate, date]));
  const targets = await loadBundles(db, "race_date=?", [date]);
  const canonicalSelected = selectCompletedTargetRaces(state, targets, date);
  const frozenById = new Map(frozenPayload.selected.map((row) => [String(row.raceId), row]));
  if (canonicalSelected.length !== frozenPayload.selected.length) throw new Error(`SELECTION_EXPLANATION_SELECTED_COUNT_MISMATCH:${canonicalSelected.length}:${frozenPayload.selected.length}`);
  for (const row of canonicalSelected) {
    const frozen = frozenById.get(row.raceId);
    if (!frozen || String(frozen.venue) !== row.venue || Number(frozen.raceNo) !== row.raceNo || !sameNumber(Number(frozen.raceScore), row.raceScore)) throw new Error(`SELECTION_EXPLANATION_FROZEN_PARITY_FAILED:${row.raceId}`);
  }

  const scoredByVenue = new Map<string, Array<{ bundle: CompletedSelectionBundle; topHorses: SelectionHorseEvidence[]; proxyTickets: SelectionProxyTicketEvidence[]; score: number }>>();
  for (const bundle of targets) {
    const candidates = candidateRows(state, bundle), proxyTickets = selectProxyTicketEvidence(candidates.tickets, state);
    const score = roundedScore(proxyTickets.reduce((sum, ticket) => sum + ticket.finalScore, 0) / proxyTickets.length);
    const venue = String(bundle.race.venue || ""), rows = scoredByVenue.get(venue) ?? [];
    rows.push({ bundle, topHorses: candidates.topHorses, proxyTickets, score }); scoredByVenue.set(venue, rows);
  }

  const out: CompletedSelectionExplanation[] = [];
  for (const [venue, rows] of scoredByVenue) {
    rows.sort((a, b) => (b.score - a.score) || (Number(a.bundle.race.raceNo) - Number(b.bundle.race.raceNo)));
    rows.forEach((row, index) => {
      const raceId = String(row.bundle.race.raceId), frozen = frozenById.get(raceId);
      if (!frozen) return;
      if (!sameNumber(row.score, Number(frozen.raceScore))) throw new Error(`SELECTION_EXPLANATION_SCORE_PARITY_FAILED:${raceId}:${row.score}:${frozen.raceScore}`);
      out.push({ version: EXPLANATION_VERSION, sourceModel: COMPLETED_MODEL_VERSION, raceId, raceDate: date, venue, raceNo: Number(row.bundle.race.raceNo || 0), venueRank: index + 1, raceScore: row.score, verifiedAgainstFrozenSelection: true, stateBaseThroughDate: baseThroughDate, stateAdvancedThroughDate: state.throughDate, topHorses: row.topHorses, proxyTickets: row.proxyTickets, scoreFormula: { localWeight: LOCAL_WEIGHT, globalWeight: 1 - LOCAL_WEIGHT, topComponents: TOP_COMPONENTS, minSampleN: MIN_N, keyPriorN: KEY_PRIOR, betPriorN: BET_PRIOR, priorRoi: PRIOR_ROI } });
    });
  }
  if (out.length !== frozenPayload.selected.length) throw new Error(`SELECTION_EXPLANATION_OUTPUT_COUNT_MISMATCH:${out.length}:${frozenPayload.selected.length}`);
  return out;
}

export async function ensureCompletedSelectionExplanations(db: D1Database, date: string): Promise<void> {
  const existing = await db.prepare("SELECT COUNT(*) AS n FROM rt_system_state WHERE state_key LIKE ? AND json_extract(state_value,'$.version')=? AND json_extract(state_value,'$.raceDate')=?").bind(`${EXPLANATION_PREFIX}${date}:%`, EXPLANATION_VERSION, date).first<{ n: number }>();
  if (Number(existing?.n || 0) >= 15) return;
  const running = ensurePromises.get(date);
  if (running) return running;
  const promise = (async () => {
    const explanations = await buildExplanations(db, date);
    const statements = explanations.map((row) => db.prepare("INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP").bind(`${EXPLANATION_PREFIX}${date}:${row.raceId}`, JSON.stringify(row)));
    if (statements.length) await db.batch(statements);
  })().finally(() => { ensurePromises.delete(date); });
  ensurePromises.set(date, promise);
  return promise;
}

export async function loadCompletedSelectionExplanation(db: D1Database, raceId: string, date: string): Promise<CompletedSelectionExplanation | null> {
  const key = `${EXPLANATION_PREFIX}${date}:${raceId}`;
  let row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1").bind(key).first<{ value: string }>();
  if (!row?.value) {
    await ensureCompletedSelectionExplanations(db, date);
    row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1").bind(key).first<{ value: string }>();
  }
  if (!row?.value) return null;
  const parsed = JSON.parse(row.value) as CompletedSelectionExplanation;
  if (parsed.version !== EXPLANATION_VERSION || parsed.sourceModel !== COMPLETED_MODEL_VERSION || parsed.raceId !== raceId || parsed.raceDate !== date || parsed.verifiedAgainstFrozenSelection !== true) throw new Error(`SELECTION_EXPLANATION_INVALID:${raceId}`);
  return parsed;
}
