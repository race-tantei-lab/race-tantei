import { COMPLETED_MODEL_VERSION } from "./completed-feature-runtime";
import type { Env, RaceRecord, RunnerRecord } from "./types";

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
const AUDIT_PREFIX = "worker_selection:";

type FeatureTuple = [number, number, number, number, number, number];
type Stat2 = [number, number];
export type RawCompletedSelectionState = {
  throughDate: string;
  currentQuarter: string;
  horseHist: Record<string, Array<[number, number, number]>>;
  horseStarts: Record<string, number>;
  jstats: Record<string, Stat2>;
  tstats: Record<string, Stat2>;
  stats: Array<[number, string[], number[], number, number]>;
  betStats: Array<[number, number, number]>;
};
export type CompletedSelectionState = {
  throughDate: string;
  currentQuarter: string;
  horseHist: Map<string, Array<[number, number, number]>>;
  horseStarts: Map<string, number>;
  jstats: Map<string, Stat2>;
  tstats: Map<string, Stat2>;
  stats: Map<string, Stat2>;
  betStats: Map<number, Stat2>;
};
type ResultRow = { horseNo: number; finishPosition: number | null; final3f: number | null };
type PayoutRow = { betType: string; combination: string; payoutYen: number };
export type CompletedSelectionBundle = { race: RaceRecord; runners: RunnerRecord[]; results: ResultRow[]; payouts: PayoutRow[] };
type SelectionTicket = { bt: number; betType: string; combo: string; vals: Record<string, number>; score?: number };
export type CompletedSelectedRace = { raceId: string; raceDate: string; venue: string; raceNo: number; raceName: string | null; startTimeJst: string | null; raceScore: number };
type StateChunk = { seq: number; dataB64: string };

const BET_SPECS: Record<number, { k: number; betType: string; ordered: boolean }> = {
  0: { k: 1, betType: "単勝", ordered: false },
  1: { k: 2, betType: "馬連", ordered: false },
  2: { k: 2, betType: "ワイド", ordered: false },
  3: { k: 2, betType: "馬単", ordered: true },
  4: { k: 3, betType: "3連複", ordered: false },
  5: { k: 3, betType: "3連単", ordered: true },
};

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

async function gunzipJson(bytes: Uint8Array): Promise<RawCompletedSelectionState> {
  const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
  const body = new Response(buffer).body;
  if (!body) throw new Error("SELECTION_STATE_BODY_MISSING");
  const text = await new Response(body.pipeThrough(new DecompressionStream("gzip"))).text();
  return JSON.parse(text) as RawCompletedSelectionState;
}

function statsKey(bt: number, axes: readonly string[], vals: readonly number[]): string {
  return JSON.stringify([bt, axes, vals]);
}

export function hydrateCompletedSelectionState(raw: RawCompletedSelectionState): CompletedSelectionState {
  if (!raw.throughDate || !raw.currentQuarter || !raw.horseHist || !raw.stats || !raw.betStats) throw new Error("SELECTION_STATE_PAYLOAD_INVALID");
  const state: CompletedSelectionState = {
    throughDate: raw.throughDate,
    currentQuarter: raw.currentQuarter,
    horseHist: new Map(), horseStarts: new Map(), jstats: new Map(), tstats: new Map(), stats: new Map(), betStats: new Map(),
  };
  for (const [key, rows] of Object.entries(raw.horseHist)) state.horseHist.set(key, rows.slice(-3).map((row) => [Number(row[0]), Number(row[1]), Number(row[2])]));
  for (const [key, value] of Object.entries(raw.horseStarts)) state.horseStarts.set(key, Number(value));
  for (const [key, value] of Object.entries(raw.jstats)) state.jstats.set(key, [Number(value[0]), Number(value[1])]);
  for (const [key, value] of Object.entries(raw.tstats)) state.tstats.set(key, [Number(value[0]), Number(value[1])]);
  for (const [bt, axes, vals, n, ret] of raw.stats) state.stats.set(statsKey(Number(bt), axes, vals.map(Number)), [Number(n), Number(ret)]);
  for (const [bt, n, ret] of raw.betStats) state.betStats.set(Number(bt), [Number(n), Number(ret)]);
  return state;
}

async function loadCanonicalSelectionState(db: D1Database): Promise<CompletedSelectionState> {
  const metaRows = await db.prepare("SELECT key,value FROM rt_selection_state_meta").all<{ key: string; value: string }>();
  const meta = new Map((metaRows.results ?? []).map((row) => [row.key, row.value]));
  if (meta.get("ready") !== "1" || meta.get("modelVersion") !== COMPLETED_MODEL_VERSION) throw new Error("SELECTION_STATE_NOT_READY");
  const generation = meta.get("generation") || "";
  const chunkCount = Number(meta.get("chunkCount") || 0);
  const byteLength = Number(meta.get("byteLength") || 0);
  if (!generation || !Number.isInteger(chunkCount) || chunkCount <= 0 || !Number.isInteger(byteLength) || byteLength <= 0) throw new Error("SELECTION_STATE_META_INVALID");
  const chunkRows = await db.prepare("SELECT seq,data_b64 AS dataB64 FROM rt_selection_state_chunk WHERE generation=? ORDER BY seq").bind(generation).all<StateChunk>();
  const rows = chunkRows.results ?? [];
  if (rows.length !== chunkCount || rows.some((row, index) => Number(row.seq) !== index)) throw new Error("SELECTION_STATE_CHUNKS_INCOMPLETE");
  const parts = rows.map((row) => decodeBase64(row.dataB64));
  const actualLength = parts.reduce((sum, part) => sum + part.byteLength, 0);
  if (actualLength !== byteLength) throw new Error(`SELECTION_STATE_BYTE_LENGTH_MISMATCH:${actualLength}:${byteLength}`);
  const bytes = new Uint8Array(byteLength);
  let offset = 0;
  for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
  const state = hydrateCompletedSelectionState(await gunzipJson(bytes));
  if (state.throughDate !== meta.get("throughDate") || state.currentQuarter !== meta.get("currentQuarter")) throw new Error("SELECTION_STATE_METADATA_MISMATCH");
  return state;
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
function quarter(date: string): string { const year = Number(date.slice(0, 4)); const month = Number(date.slice(5, 7)); return `${year}Q${Math.floor((month - 1) / 3) + 1}`; }
function quarterTransition(state: CompletedSelectionState, date: string): void { state.currentQuarter = quarter(date); }

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
  const jockey = String(runner.jockey || "");
  const trainer = String(runner.trainer || "");
  const js: Stat2 = jockey ? (state.jstats.get(jockey) ?? [0, 0]) : [0, 0];
  const ts: Stat2 = trainer ? (state.tstats.get(trainer) ?? [0, 0]) : [0, 0];
  const jr = (js[1] + 3) / (js[0] + 15);
  const tr = (ts[1] + 3) / (ts[0] + 15);
  const starts = state.horseStarts.get(key) ?? 0;
  return [formCode(form, has), formCode(speed, has), rateCode(jr), rateCode(tr), startsBin(starts), Math.trunc(top3)];
}
function strength(feature: FeatureTuple, horseNo: number): number[] {
  return [feature.slice(0, 5).reduce((sum, value) => sum + value, 0) + Math.min(3, feature[5]), feature[0] + feature[1], feature[2] + feature[3], feature[5], -horseNo];
}
function compareTupleDesc(a: readonly number[], b: readonly number[]): number { for (let i = 0; i < Math.min(a.length, b.length); i += 1) if (a[i] !== b[i]) return b[i] - a[i]; return 0; }
function baseVals(race: RaceRecord, n: number): Record<string, number> {
  const venue = String(race.venue || ""), surface = String(race.surface || "障害"), distance = Number(race.distanceM || 0), raceNo = Number(race.raceNo || 0);
  const venueCode = SEL_VENUE_MAP.get(venue as (typeof SEL_VENUES)[number]);
  if (venueCode == null) throw new Error(`SELECTION_UNKNOWN_VENUE:${venue}`);
  return { venue: venueCode, surface: surface === "芝" ? 0 : surface === "ダート" ? 1 : 2, dist: distBin(distance), field: fieldBin(n), raceNo: raceNoBin(raceNo), rclass: classBin(race.raceName, race.conditions) };
}
function comboVals(base: Record<string, number>, bt: number, features: FeatureTuple[]): Record<string, number> {
  return { ...base, bet: bt, goodcnt: Math.min(3, features.filter((x) => x[0] >= 3).length), bestform: Math.max(...features.map((x) => x[0])), bestspeed: Math.max(...features.map((x) => x[1])), bestj: Math.max(...features.map((x) => x[2])), bestt: Math.max(...features.map((x) => x[3])), expcnt: Math.min(3, features.filter((x) => x[4] >= 2).length), top3lastsum: Math.min(7, features.reduce((sum, x) => sum + x[5], 0)) };
}
function candidateKeys(bt: number, vals: Record<string, number>): Array<[string[], number[]]> {
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
function candidateRows(state: CompletedSelectionState, bundle: CompletedSelectionBundle): SelectionTicket[] {
  const race = bundle.race, raceId = String(race.raceId);
  const runners = bundle.runners.filter((runner) => (runner.runnerStatus || "active") === "active").slice().sort((a, b) => Number(a.horseNo) - Number(b.horseNo));
  if (runners.length < 3) return [];
  const features = new Map<number, FeatureTuple>();
  for (const runner of runners) features.set(Number(runner.horseNo), selectionFeatureTuple(state, raceId, runner));
  const ranked = [...features.keys()].sort((a, b) => compareTupleDesc(strength(features.get(a)!, a), strength(features.get(b)!, b))).slice(0, TOP_HORSES);
  const base = baseVals(race, runners.length), out: SelectionTicket[] = [];
  for (let bt = 0; bt <= 5; bt += 1) {
    const spec = BET_SPECS[bt];
    if (ranked.length < spec.k) continue;
    const iterator = spec.ordered ? permutations(ranked, spec.k) : combinations(ranked, spec.k);
    for (const horses of iterator) {
      const comboValues = spec.ordered ? horses : horses.slice().sort((a, b) => a - b);
      out.push({ bt, betType: spec.betType, combo: comboValues.join("-"), vals: comboVals(base, bt, horses.map((horse) => features.get(horse)!)) });
    }
  }
  return out;
}
function meanRoi(n: number, ret: number, priorN: number, priorRoi: number): number { return (ret + priorN * 100 * priorRoi) / (100 * (n + priorN)); }
function ticketScore(ticket: SelectionTicket, state: CompletedSelectionState): number {
  const bs = state.betStats.get(ticket.bt) ?? [0, 0], bmean = meanRoi(bs[0], bs[1], BET_PRIOR, PRIOR_ROI);
  const comps: Array<[number, number, number]> = [];
  for (const [axes, vals] of candidateKeys(ticket.bt, ticket.vals)) {
    const stat = state.stats.get(statsKey(ticket.bt, axes, vals)) ?? [0, 0];
    if (stat[0] < MIN_N) continue;
    const km = meanRoi(stat[0], stat[1], KEY_PRIOR, bmean), reliability = stat[0] / (stat[0] + KEY_PRIOR), complexity = axes.length === 1 ? 1 : .92;
    comps.push([km, reliability * complexity, stat[0]]);
  }
  if (!comps.length) return bmean * .95;
  comps.sort((a, b) => (b[0] - a[0]) || (b[1] - a[1]) || (b[2] - a[2]));
  const top = comps.slice(0, TOP_COMPONENTS), weight = top.reduce((sum, row) => sum + row[1], 0);
  const local = weight ? top.reduce((sum, row) => sum + row[0] * row[1], 0) / weight : bmean;
  return (1 - LOCAL_WEIGHT) * bmean + LOCAL_WEIGHT * local;
}
function selectProxyTickets(rows: SelectionTicket[], state: CompletedSelectionState): SelectionTicket[] {
  const scored = rows.map((ticket) => ({ ...ticket, score: ticketScore(ticket, state) }));
  scored.sort((a, b) => ((b.score ?? 0) - (a.score ?? 0)) || (a.bt - b.bt) || (a.combo < b.combo ? -1 : a.combo > b.combo ? 1 : 0));
  if (scored.length < TICKETS_PER_RACE) throw new Error("TOO_FEW_CANDIDATE_TICKETS");
  const chosen = scored.slice(0, TICKETS_PER_RACE), types = new Set(chosen.map((ticket) => ticket.bt));
  if (types.size < 2) {
    const alt = scored.slice(TICKETS_PER_RACE).find((ticket) => !types.has(ticket.bt));
    if (!alt) throw new Error("NO_SECOND_BET_TYPE");
    chosen[chosen.length - 1] = alt;
  }
  chosen.sort((a, b) => ((b.score ?? 0) - (a.score ?? 0)) || (a.bt - b.bt) || (a.combo < b.combo ? -1 : a.combo > b.combo ? 1 : 0));
  if (chosen.length !== 3 || new Set(chosen.map((ticket) => ticket.bt)).size < 2) throw new Error("PROXY_TICKET_GATE_FAILED");
  return chosen;
}
function payoutIndex(bundle: CompletedSelectionBundle): Map<string, number> {
  const out = new Map<string, number>();
  for (const row of bundle.payouts) {
    const betType = String(row.betType || ""), combo = String(row.combination || ""), payout = Number(row.payoutYen || 0), key = `${betType}\u0001${combo}`;
    if (betType && combo && payout > 0) out.set(key, Math.max(out.get(key) ?? 0, payout));
  }
  return out;
}
function updateSelectionHistory(state: CompletedSelectionState, bundles: CompletedSelectionBundle[]): void {
  for (const bundle of bundles) {
    const raceId = String(bundle.race.raceId), runners = bundle.runners.filter((runner) => (runner.runnerStatus || "active") === "active"), byNo = new Map(runners.map((runner) => [Number(runner.horseNo), runner])), field = runners.length;
    const results = bundle.results.map((row) => ({ hno: Number(row.horseNo), pos: row.finishPosition == null ? null : Number(row.finishPosition), f3: row.final3f == null ? null : Number(row.final3f) })).filter((row) => row.pos != null && row.pos > 0 && byNo.has(row.hno));
    const validF3 = results.filter((row) => row.f3 != null && Number.isFinite(row.f3)).slice().sort((a, b) => ((a.f3 as number) - (b.f3 as number)) || (a.hno - b.hno));
    const f3Rank = new Map(validF3.map((row, index) => [row.hno, index])), vf = validF3.length;
    for (const row of results) {
      const runner = byNo.get(row.hno)!, key = horseKey(raceId, runner), form = Math.max(0, 1 - ((row.pos as number) - 1) / Math.max(1, field - 1)), speed = row.f3 == null ? .5 : 1 - (f3Rank.get(row.hno) ?? 0) / Math.max(1, vf - 1), top3 = Number((row.pos as number) <= 3);
      const history = state.horseHist.get(key) ?? []; history.push([form, speed, top3]); state.horseHist.set(key, history.slice(-3)); state.horseStarts.set(key, (state.horseStarts.get(key) ?? 0) + 1);
      const jockey = String(runner.jockey || ""), trainer = String(runner.trainer || "");
      if (jockey) { const stat = state.jstats.get(jockey) ?? [0, 0]; stat[0] += 1; stat[1] += top3; state.jstats.set(jockey, stat); }
      if (trainer) { const stat = state.tstats.get(trainer) ?? [0, 0]; stat[0] += 1; stat[1] += top3; state.tstats.set(trainer, stat); }
    }
  }
}
export function advanceCompletedSelectionState(state: CompletedSelectionState, bundles: CompletedSelectionBundle[]): void {
  const byDate = new Map<string, CompletedSelectionBundle[]>();
  for (const bundle of bundles) { const date = bundle.race.raceDate; const bucket = byDate.get(date) ?? []; bucket.push(bundle); byDate.set(date, bucket); }
  for (const date of [...byDate.keys()].sort()) {
    const day = byDate.get(date)!; quarterTransition(state, date);
    for (const bundle of day) {
      const pays = payoutIndex(bundle);
      for (const ticket of candidateRows(state, bundle)) {
        const ret = pays.get(`${ticket.betType}\u0001${ticket.combo}`) ?? 0, bs = state.betStats.get(ticket.bt) ?? [0, 0]; bs[0] += 1; bs[1] += ret; state.betStats.set(ticket.bt, bs);
        for (const [axes, vals] of candidateKeys(ticket.bt, ticket.vals)) { const key = statsKey(ticket.bt, axes, vals), stat = state.stats.get(key) ?? [0, 0]; stat[0] += 1; stat[1] += ret; state.stats.set(key, stat); }
      }
    }
    updateSelectionHistory(state, day); state.throughDate = date;
  }
}
export function selectCompletedTargetRaces(state: CompletedSelectionState, bundles: CompletedSelectionBundle[], date: string): CompletedSelectedRace[] {
  quarterTransition(state, date);
  const byVenue = new Map<string, Array<{ bundle: CompletedSelectionBundle; score: number }>>();
  for (const bundle of bundles) {
    const chosen = selectProxyTickets(candidateRows(state, bundle), state), score = chosen.reduce((sum, ticket) => sum + Number(ticket.score), 0) / chosen.length, venue = String(bundle.race.venue || ""), bucket = byVenue.get(venue) ?? [];
    bucket.push({ bundle, score }); byVenue.set(venue, bucket);
  }
  const selected: CompletedSelectedRace[] = [];
  for (const [venue, rows] of byVenue) {
    rows.sort((a, b) => (b.score - a.score) || (Number(a.bundle.race.raceNo) - Number(b.bundle.race.raceNo)));
    if (rows.length < 5) throw new Error(`TARGET_VENUE_FEWER_THAN_FIVE:${venue}:${rows.length}`);
    for (const { bundle, score } of rows.slice(0, 5)) {
      const race = bundle.race;
      selected.push({ raceId: String(race.raceId), raceDate: date, venue, raceNo: Number(race.raceNo || 0), raceName: race.raceName ?? null, startTimeJst: race.startTimeJst ?? null, raceScore: Math.round(score * 1e8) / 1e8 });
    }
  }
  selected.sort((a, b) => ((SEL_VENUE_MAP.get(a.venue as (typeof SEL_VENUES)[number]) ?? 99) - (SEL_VENUE_MAP.get(b.venue as (typeof SEL_VENUES)[number]) ?? 99)) || (a.raceNo - b.raceNo));
  return selected;
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
function jstDate(now: Date): string { return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10); }
function jstHour(now: Date): number { return Number(new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(11, 13)); }

export async function freezeCompletedWorkerSelectionIfNeeded(env: Env, now = new Date()): Promise<Record<string, unknown>> {
  const date = jstDate(now), key = `${SELECTION_PREFIX}${date}`;
  const existing = await env.DB.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1").bind(key).first<{ value: string }>();
  if (existing?.value) return { status: "loaded", date, payload: JSON.parse(existing.value) };
  if (jstHour(now) < 8) return { status: "before_selection_time", date };
  const structure = await env.DB.prepare(`SELECT venue,COUNT(*) AS races,SUM(CASE WHEN start_time_utc IS NOT NULL THEN 1 ELSE 0 END) AS timed,SUM(CASE WHEN EXISTS(SELECT 1 FROM rt_runners u WHERE u.race_id=r.race_id AND COALESCE(u.runner_status,'active')='active') THEN 1 ELSE 0 END) AS withRunners FROM rt_races r WHERE race_date=? GROUP BY venue ORDER BY venue`).bind(date).all<{ venue: string; races: number; timed: number; withRunners: number }>();
  const program = structure.results ?? [];
  if (program.length < 2 || program.some((row) => Number(row.races) !== 12 || Number(row.timed) !== 12 || Number(row.withRunners) !== 12)) return { status: "waiting_complete_program", date, program };
  const state = await loadCanonicalSelectionState(env.DB), baseThroughDate = state.throughDate;
  if (state.throughDate < date) advanceCompletedSelectionState(state, await loadBundles(env.DB, "race_date>? AND race_date<?", [state.throughDate, date]));
  const targets = await loadBundles(env.DB, "race_date=?", [date]), venueCounts = new Map<string, number>();
  for (const bundle of targets) venueCounts.set(bundle.race.venue, (venueCounts.get(bundle.race.venue) ?? 0) + 1);
  if (venueCounts.size < 2 || [...venueCounts.values()].some((count) => count !== 12)) throw new Error(`TARGET_RACE_STRUCTURE_INCOMPLETE:${JSON.stringify(Object.fromEntries(venueCounts))}`);
  const selected = selectCompletedTargetRaces(state, targets, date), selectedCounts = new Map<string, number>();
  for (const row of selected) selectedCounts.set(row.venue, (selectedCounts.get(row.venue) ?? 0) + 1);
  if (selectedCounts.size !== venueCounts.size || [...selectedCounts.values()].some((count) => count !== 5)) throw new Error(`CANONICAL_SELECTION_NOT_FIVE_PER_VENUE:${JSON.stringify(Object.fromEntries(selectedCounts))}`);
  const payload = { date, sourceModel: COMPLETED_MODEL_VERSION, selectionMode: "canonical-ten-year-race-score", selected, venueCounts: Object.fromEntries(venueCounts), selectedVenueCounts: Object.fromEntries(selectedCounts), stateBaseThroughDate: baseThroughDate, stateAdvancedThroughDate: state.throughDate, resultDataUsedForTargetDay: false, historicalFinalOddsUsedForSelection: false, syntheticOddsUsed: false };
  await env.DB.prepare("INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(state_key) DO NOTHING").bind(key, JSON.stringify(payload)).run();
  const authoritative = await env.DB.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1").bind(key).first<{ value: string }>();
  if (!authoritative?.value) throw new Error("WORKER_SELECTION_FREEZE_VERIFY_MISSING");
  const finalPayload = JSON.parse(authoritative.value) as { sourceModel?: string; resultDataUsedForTargetDay?: boolean; selected?: CompletedSelectedRace[] };
  if (finalPayload.sourceModel !== COMPLETED_MODEL_VERSION || finalPayload.resultDataUsedForTargetDay !== false || !Array.isArray(finalPayload.selected)) throw new Error("WORKER_SELECTION_AUTHORITATIVE_INVALID");
  const finalCounts = new Map<string, number>(); for (const row of finalPayload.selected) finalCounts.set(String(row.venue), (finalCounts.get(String(row.venue)) ?? 0) + 1);
  if (finalCounts.size < 2 || [...finalCounts.values()].some((count) => count !== 5)) throw new Error(`WORKER_SELECTION_AUTHORITATIVE_COUNTS_INVALID:${JSON.stringify(Object.fromEntries(finalCounts))}`);
  const audit = { status: "frozen", date, sourceModel: COMPLETED_MODEL_VERSION, selectedRaceCount: finalPayload.selected.length, selectedVenueCounts: Object.fromEntries(finalCounts), selectedRaceIds: finalPayload.selected.map((row) => row.raceId), resultDataUsedForTargetDay: false };
  await env.DB.prepare("INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP").bind(`${AUDIT_PREFIX}${date}`, JSON.stringify(audit)).run();
  return { ...audit, payload: finalPayload };
}
