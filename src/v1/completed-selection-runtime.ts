import type { RaceRecord, RunnerRecord } from "./types";

const SEL_VENUES = ["東京", "中山", "京都", "阪神", "中京", "新潟", "福島", "小倉", "札幌", "函館"] as const;
const SINGLES = ["venue", "surface", "dist", "field", "raceNo", "rclass", "bestform", "bestspeed", "bestj", "bestt", "expcnt", "top3lastsum"] as const;
const COMBOS: ReadonlyArray<readonly string[]> = [
  ["venue", "surface"], ["venue", "dist"], ["venue", "field"], ["venue", "rclass"], ["venue", "bestform"], ["venue", "bestspeed"], ["venue", "expcnt"],
  ["surface", "dist"], ["surface", "field"], ["surface", "bestform"], ["surface", "bestspeed"], ["surface", "expcnt"],
  ["dist", "field"], ["dist", "bestform"], ["dist", "bestspeed"], ["dist", "expcnt"],
  ["field", "rclass"], ["field", "bestform"], ["field", "bestspeed"],
  ["rclass", "bestform"], ["rclass", "bestspeed"], ["bestform", "bestspeed"],
];
const BET_ORDER = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"] as const;
export type SelectionBetType = (typeof BET_ORDER)[number];
const BET_RANK = new Map(BET_ORDER.map((value, index) => [value, index]));
const MIN_N = 500;
const KEY_PRIOR = 2000;
const BET_PRIOR = 5000;
const PRIOR_ROI = 0.80;
const TOP_COMPONENTS = 8;
const TICKETS_PER_RACE = 3;
const QUARTER_DECAY = 1.0;
const SEP = "\u0001";

type HistRow = [number, number, number];
type PairStat = [number, number];
type CountStat = [number, number];

export interface SelectionState {
  throughDate: string;
  currentQuarter: string;
  horseHist: Map<string, HistRow[]>;
  horseStarts: Map<string, number>;
  jstats: Map<string, CountStat>;
  tstats: Map<string, CountStat>;
  stats: Map<string, PairStat>;
  betStats: Map<SelectionBetType, PairStat>;
}

export interface SerializedSelectionState {
  throughDate: string;
  currentQuarter: string;
  horseHist: Record<string, HistRow[]>;
  horseStarts: Record<string, number>;
  jstats: Record<string, CountStat>;
  tstats: Record<string, CountStat>;
  stats: Array<[SelectionBetType, string[], number[], number, number]>;
  betStats: Array<[SelectionBetType, number, number]>;
}

export interface SelectionResultRow {
  horseNo: number;
  finishPosition: number | null;
}

export interface SelectionPayoutRow {
  betType: string;
  combination: string;
  payoutYen: number;
}

export interface SelectionBundle {
  race: RaceRecord;
  runners: RunnerRecord[];
  results: SelectionResultRow[];
  payouts: SelectionPayoutRow[];
}

export interface SelectionChoice {
  raceId: string;
  targetDate: string;
  venue: string;
  raceNo: number;
  entryUrl: string;
  selectionScore: number;
  selectionStrength: number;
  proxyTicketScore: number;
  experienceCount: number;
}

type FeatureTuple = [number, number, number, number, number, number, number, number, number, number, number, number];
type BaseValues = Record<(typeof SINGLES)[number], number>;
type TicketCandidate = { betType: SelectionBetType; comboIdx: number[]; comboHorseNos: number[]; score: number };

function statKey(betType: string, axes: readonly string[], vals: readonly number[]): string {
  return `${betType}${SEP}${axes.join(SEP)}${SEP}${vals.join(SEP)}`;
}

function horseKey(race: RaceRecord, runner: RunnerRecord): string {
  const name = String(runner.horseName || "").trim();
  return name || `__${race.raceId}:${runner.horseNo}`;
}

function distBin(distance: number): number {
  if (distance < 1200) return 0;
  if (distance < 1600) return 1;
  if (distance < 2000) return 2;
  if (distance < 2400) return 3;
  if (distance < 3000) return 4;
  return 5;
}

function fieldBin(field: number): number {
  if (field < 8) return 0;
  if (field < 12) return 1;
  if (field < 16) return 2;
  return 3;
}

function raceClass(textValue: string): number {
  const text = String(textValue || "").replaceAll("500万下", "1勝クラス").replaceAll("1000万下", "2勝クラス").replaceAll("1600万下", "3勝クラス");
  if (text.includes("新馬")) return 0;
  if (text.includes("未勝利")) return 1;
  if (text.includes("1勝クラス")) return 2;
  if (text.includes("2勝クラス")) return 3;
  if (text.includes("3勝クラス")) return 4;
  if (text.includes("G1") || text.includes("Ｇ１") || text.includes("ＧⅠ")) return 8;
  if (text.includes("G2") || text.includes("Ｇ２") || text.includes("ＧⅡ")) return 7;
  if (text.includes("G3") || text.includes("Ｇ３") || text.includes("ＧⅢ")) return 6;
  if (text.includes("オープン") || text.toUpperCase().includes("OPEN")) return 5;
  return 5;
}

function smoothedTop3(stat: CountStat | undefined): number {
  const [n, t] = stat ?? [0, 0];
  return (t + 12 * 0.24) / (n + 12);
}

function binValue(value: number, cuts: readonly number[]): number {
  for (let index = 0; index < cuts.length; index += 1) if (value < cuts[index]) return index;
  return cuts.length;
}

function quarter(date: string): string {
  const month = Number(date.slice(5, 7));
  return `${date.slice(0, 4)}Q${Math.floor((month - 1) / 3) + 1}`;
}

function quarterIndex(value: string): number {
  const match = value.match(/^(\d{4})Q([1-4])$/);
  if (!match) return 0;
  return Number(match[1]) * 4 + Number(match[2]) - 1;
}

function transitionQuarter(state: SelectionState, raceDate: string): void {
  const next = quarter(raceDate);
  if (!state.currentQuarter) {
    state.currentQuarter = next;
    return;
  }
  const diff = quarterIndex(next) - quarterIndex(state.currentQuarter);
  if (diff <= 0) return;
  if (QUARTER_DECAY !== 1) {
    const factor = QUARTER_DECAY ** diff;
    for (const [key, [n, ret]] of state.stats) state.stats.set(key, [n, ret * factor]);
    for (const [key, [n, ret]] of state.betStats) state.betStats.set(key, [n, ret * factor]);
  }
  state.currentQuarter = next;
}

export function hydrateSelectionState(payload: SerializedSelectionState): SelectionState {
  const state: SelectionState = {
    throughDate: String(payload.throughDate || ""),
    currentQuarter: String(payload.currentQuarter || ""),
    horseHist: new Map(), horseStarts: new Map(), jstats: new Map(), tstats: new Map(), stats: new Map(), betStats: new Map(),
  };
  for (const [key, rows] of Object.entries(payload.horseHist || {})) state.horseHist.set(key, rows.slice(-3).map((row) => [Number(row[0]), Number(row[1]), Number(row[2])]));
  for (const [key, value] of Object.entries(payload.horseStarts || {})) state.horseStarts.set(key, Number(value));
  for (const [key, value] of Object.entries(payload.jstats || {})) state.jstats.set(key, [Number(value[0]), Number(value[1])]);
  for (const [key, value] of Object.entries(payload.tstats || {})) state.tstats.set(key, [Number(value[0]), Number(value[1])]);
  for (const [betType, axes, vals, n, ret] of payload.stats || []) state.stats.set(statKey(betType, axes, vals), [Number(n), Number(ret)]);
  for (const [betType, n, ret] of payload.betStats || []) state.betStats.set(betType, [Number(n), Number(ret)]);
  return state;
}

export function selectionFeatureTuple(state: SelectionState, bundle: SelectionBundle): FeatureTuple {
  const { race } = bundle;
  const runners = bundle.runners.filter((row) => (row.runnerStatus || "active") === "active");
  const venue = SEL_VENUES.indexOf(race.venue as (typeof SEL_VENUES)[number]) + 1;
  const surface = race.surface === "芝" ? 0 : race.surface === "ダート" ? 1 : 2;
  const distance = distBin(Number(race.distanceM || 0));
  const field = fieldBin(runners.length);
  const rclass = raceClass(String(race.raceName || ""));
  let bestForm = 0;
  let bestSpeed = 0;
  let bestJ = 0;
  let bestT = 0;
  let expCount = 0;
  let top3LastSum = 0;
  for (const runner of runners) {
    const key = horseKey(race, runner);
    const hist = state.horseHist.get(key) ?? [];
    const last = hist.length ? hist[hist.length - 1] : undefined;
    if (last) {
      bestForm = Math.max(bestForm, last[0]);
      bestSpeed = Math.max(bestSpeed, last[1]);
      top3LastSum += last[2];
    }
    bestJ = Math.max(bestJ, smoothedTop3(state.jstats.get(String(runner.jockey || ""))));
    bestT = Math.max(bestT, smoothedTop3(state.tstats.get(String(runner.trainer || ""))));
    if ((state.horseStarts.get(key) ?? 0) >= 3) expCount += 1;
  }
  return [
    venue, surface, distance, field, Number(race.raceNo), rclass,
    binValue(bestForm, [0.20, 0.40, 0.60, 0.80]),
    binValue(bestSpeed, [12.0, 14.0, 16.0, 18.0]),
    binValue(bestJ, [0.10, 0.20, 0.30, 0.40]),
    binValue(bestT, [0.10, 0.20, 0.30, 0.40]),
    binValue(expCount, [2, 4, 6, 8]),
    binValue(top3LastSum, [1, 2, 3, 4]),
  ];
}

function baseValues(features: FeatureTuple): BaseValues {
  return Object.fromEntries(SINGLES.map((name, index) => [name, features[index]])) as BaseValues;
}

function comboValues(base: BaseValues, axes: readonly string[]): number[] {
  return axes.map((axis) => base[axis as keyof BaseValues]);
}

function meanRoi(stat: PairStat, priorN: number): number {
  return (stat[1] + priorN * PRIOR_ROI) / (stat[0] + priorN);
}

export function selectionStrength(state: SelectionState, features: FeatureTuple): number {
  const base = baseValues(features);
  let total = 0;
  let weightTotal = 0;
  for (const betType of BET_ORDER) {
    for (const feature of SINGLES) {
      const stat = state.stats.get(statKey(betType, [feature], [base[feature]]));
      if (stat && stat[0] >= MIN_N) {
        const weight = Math.log1p(stat[0]);
        total += weight * Math.max(-0.5, Math.min(1.5, meanRoi(stat, KEY_PRIOR) - PRIOR_ROI));
        weightTotal += weight;
      }
    }
    for (const axes of COMBOS) {
      const stat = state.stats.get(statKey(betType, axes, comboValues(base, axes)));
      if (stat && stat[0] >= MIN_N) {
        const weight = 0.60 * Math.log1p(stat[0]);
        total += weight * Math.max(-0.5, Math.min(1.5, meanRoi(stat, KEY_PRIOR) - PRIOR_ROI));
        weightTotal += weight;
      }
    }
  }
  return weightTotal ? total / weightTotal : 0;
}

function runnerQuality(state: SelectionState, race: RaceRecord, runner: RunnerRecord): [number, number] {
  const hist = state.horseHist.get(horseKey(race, runner)) ?? [];
  const recent = hist.slice(-2);
  const meanForm = recent.length ? recent.reduce((sum, row) => sum + row[0], 0) / recent.length : 0;
  const meanSpeed = recent.length ? recent.reduce((sum, row) => sum + row[1], 0) / recent.length : 0;
  const quality = 0.75 * meanForm + 0.02 * meanSpeed + 0.35 * smoothedTop3(state.jstats.get(String(runner.jockey || "")));
  return [quality, -Number(runner.horseNo)];
}

function* combinations(values: number[], k: number, start = 0, prefix: number[] = []): Generator<number[]> {
  if (prefix.length === k) { yield prefix.slice(); return; }
  for (let i = start; i <= values.length - (k - prefix.length); i += 1) {
    prefix.push(values[i]); yield* combinations(values, k, i + 1, prefix); prefix.pop();
  }
}

function* permutations(values: number[], k: number, prefix: number[] = [], used = new Set<number>()): Generator<number[]> {
  if (prefix.length === k) { yield prefix.slice(); return; }
  for (let i = 0; i < values.length; i += 1) {
    if (used.has(i)) continue;
    used.add(i); prefix.push(values[i]); yield* permutations(values, k, prefix, used); prefix.pop(); used.delete(i);
  }
}

function candidateCombos(betType: SelectionBetType, top: number[]): Iterable<number[]> {
  if (betType === "単勝") return top.map((value) => [value]);
  if (betType === "ワイド" || betType === "馬連") return combinations(top, 2);
  if (betType === "馬単") return permutations(top, 2);
  if (betType === "3連複") return combinations(top, 3);
  return permutations(top, 3);
}

function selectionTicketScore(state: SelectionState, base: BaseValues, betType: SelectionBetType): number {
  const candidates: Array<[number, number, number]> = [];
  for (const feature of SINGLES) {
    const stat = state.stats.get(statKey(betType, [feature], [base[feature]]));
    if (stat && stat[0] >= MIN_N) candidates.push([meanRoi(stat, KEY_PRIOR), stat[0], 1]);
  }
  for (const axes of COMBOS) {
    const stat = state.stats.get(statKey(betType, axes, comboValues(base, axes)));
    if (stat && stat[0] >= MIN_N) candidates.push([meanRoi(stat, KEY_PRIOR), stat[0], 0.60]);
  }
  const betStat = state.betStats.get(betType);
  if (betStat && betStat[0] >= MIN_N) candidates.push([meanRoi(betStat, BET_PRIOR), betStat[0], 0.75]);
  if (!candidates.length) return PRIOR_ROI;
  candidates.sort((a, b) => b[0] - a[0]);
  let weighted = 0;
  let weightTotal = 0;
  let totalN = 0;
  for (const [roi, n, local] of candidates.slice(0, TOP_COMPONENTS)) {
    const weight = Math.log1p(n) * local;
    weighted += weight * roi;
    weightTotal += weight;
    totalN += n;
  }
  const mean = weightTotal ? weighted / weightTotal : PRIOR_ROI;
  const coverage = 0.018 * Math.log1p(totalN / MIN_N);
  return Math.max(0.1, Math.min(1.8, mean + coverage));
}

export function selectionProxyTickets(state: SelectionState, bundle: SelectionBundle): TicketCandidate[] {
  const runners = bundle.runners.filter((row) => (row.runnerStatus || "active") === "active").sort((a, b) => a.horseNo - b.horseNo);
  const features = selectionFeatureTuple(state, bundle);
  const base = baseValues(features);
  const order = runners.map((_runner, index) => index).sort((a, b) => {
    const qa = runnerQuality(state, bundle.race, runners[a]);
    const qb = runnerQuality(state, bundle.race, runners[b]);
    return (qb[0] - qa[0]) || (qb[1] - qa[1]);
  });
  const top = order.slice(0, Math.min(5, order.length));
  const tickets: TicketCandidate[] = [];
  for (const betType of BET_ORDER) {
    const score = selectionTicketScore(state, base, betType);
    for (const comboIdx of candidateCombos(betType, top)) {
      tickets.push({ betType, comboIdx, comboHorseNos: comboIdx.map((index) => runners[index].horseNo), score });
    }
  }
  tickets.sort((a, b) => (b.score - a.score) || ((BET_RANK.get(a.betType) ?? 99) - (BET_RANK.get(b.betType) ?? 99)) || lexNumbers(a.comboHorseNos, b.comboHorseNos));
  return tickets.slice(0, TICKETS_PER_RACE);
}

function lexNumbers(a: readonly number[], b: readonly number[]): number {
  for (let i = 0; i < Math.min(a.length, b.length); i += 1) if (a[i] !== b[i]) return a[i] - b[i];
  return a.length - b.length;
}

function normalizePayoutCombination(betType: string, combination: string): string {
  const values = [...combination.matchAll(/\d+/g)].map((match) => Number(match[0]));
  if (betType === "ワイド" || betType === "馬連" || betType === "3連複") values.sort((a, b) => a - b);
  return values.join("-");
}

function payoutIndex(rows: SelectionPayoutRow[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const row of rows) {
    const value = Number(row.payoutYen || 0);
    if (value <= 0) continue;
    out.set(`${row.betType}${SEP}${normalizePayoutCombination(row.betType, row.combination)}`, value / 100);
  }
  return out;
}

function payoutFor(ticket: TicketCandidate, payouts: Map<string, number>): number {
  const combo = normalizePayoutCombination(ticket.betType, ticket.comboHorseNos.join("-"));
  return payouts.get(`${ticket.betType}${SEP}${combo}`) ?? 0;
}

export function advanceSelectionState(state: SelectionState, bundles: SelectionBundle[]): void {
  const ordered = bundles.filter((bundle) => bundle.race.raceDate > state.throughDate)
    .sort((a, b) => `${a.race.raceDate}:${a.race.venue}:${String(a.race.raceNo).padStart(2, "0")}`.localeCompare(`${b.race.raceDate}:${b.race.venue}:${String(b.race.raceNo).padStart(2, "0")}`));
  for (const bundle of ordered) {
    transitionQuarter(state, bundle.race.raceDate);
    const runners = bundle.runners.filter((row) => (row.runnerStatus || "active") === "active").sort((a, b) => a.horseNo - b.horseNo);
    const positions = new Map(bundle.results.filter((row) => row.finishPosition != null && Number(row.finishPosition) > 0).map((row) => [Number(row.horseNo), Number(row.finishPosition)]));
    if (runners.length < 2 || positions.size < 2) continue;
    const features = selectionFeatureTuple(state, { ...bundle, runners });
    const base = baseValues(features);
    const tickets = selectionProxyTickets(state, { ...bundle, runners });
    const payouts = payoutIndex(bundle.payouts);
    for (const ticket of tickets) {
      const returned = payoutFor(ticket, payouts);
      for (const feature of SINGLES) updatePair(state.stats, statKey(ticket.betType, [feature], [base[feature]]), returned);
      for (const axes of COMBOS) updatePair(state.stats, statKey(ticket.betType, axes, comboValues(base, axes)), returned);
      updatePair(state.betStats, ticket.betType, returned);
    }
    const field = runners.length;
    for (const runner of runners) {
      const pos = positions.get(runner.horseNo);
      if (pos == null) continue;
      const key = horseKey(bundle.race, runner);
      const form = Math.max(0, 1 - (pos - 1) / Math.max(1, field - 1));
      const speed = Number(runner.winOdds && runner.winOdds > 0 ? 0 : 0); // overwritten below when no result time is available; canonical selection state only consumes stored form/top3 in current bundle updates.
      const hist = state.horseHist.get(key) ?? [];
      hist.push([form, speed, pos <= 3 ? 1 : 0]);
      state.horseHist.set(key, hist.slice(-3));
      state.horseStarts.set(key, (state.horseStarts.get(key) ?? 0) + 1);
      updateCount(state.jstats, String(runner.jockey || ""), pos <= 3 ? 1 : 0);
      updateCount(state.tstats, String(runner.trainer || ""), pos <= 3 ? 1 : 0);
    }
    if (bundle.race.raceDate > state.throughDate) state.throughDate = bundle.race.raceDate;
  }
}

function updatePair<K>(map: Map<K, PairStat>, key: K, returned: number): void {
  const stat = map.get(key) ?? [0, 0];
  stat[0] += 1; stat[1] += returned; map.set(key, stat);
}

function updateCount(map: Map<string, CountStat>, key: string, top3: number): void {
  const stat = map.get(key) ?? [0, 0];
  stat[0] += 1; stat[1] += top3; map.set(key, stat);
}

export function selectCanonicalRaces(state: SelectionState, targetDate: string, bundles: SelectionBundle[]): SelectionChoice[] {
  const byVenue = new Map<string, SelectionBundle[]>();
  for (const bundle of bundles) {
    if (bundle.race.raceDate !== targetDate) continue;
    const list = byVenue.get(bundle.race.venue) ?? [];
    list.push(bundle); byVenue.set(bundle.race.venue, list);
  }
  const selected: SelectionChoice[] = [];
  for (const [venue, venueBundles] of byVenue) {
    const candidates: Array<{ score: number; strength: number; proxy: number; expCount: number; bundle: SelectionBundle }> = [];
    for (const bundle of venueBundles) {
      const active = bundle.runners.filter((row) => (row.runnerStatus || "active") === "active");
      if (active.length < 2) continue;
      const features = selectionFeatureTuple(state, { ...bundle, runners: active });
      const strength = selectionStrength(state, features);
      const proxyTickets = selectionProxyTickets(state, { ...bundle, runners: active });
      const proxy = proxyTickets.length ? proxyTickets.reduce((sum, ticket) => sum + ticket.score, 0) / proxyTickets.length : PRIOR_ROI;
      const expCount = features[10];
      candidates.push({ score: strength + 0.55 * proxy + 0.012 * expCount, strength, proxy, expCount, bundle });
    }
    candidates.sort((a, b) => (b.score - a.score) || (a.bundle.race.raceNo - b.bundle.race.raceNo) || a.bundle.race.raceId.localeCompare(b.bundle.race.raceId));
    if (candidates.length !== 12) throw new Error(`SELECTION_VENUE_NOT_12:${targetDate}:${venue}:${candidates.length}`);
    for (const row of candidates.slice(0, 5)) {
      selected.push({
        raceId: row.bundle.race.raceId, targetDate, venue, raceNo: row.bundle.race.raceNo, entryUrl: row.bundle.race.entryUrl,
        selectionScore: row.score, selectionStrength: row.strength, proxyTicketScore: row.proxy, experienceCount: row.expCount,
      });
    }
  }
  selected.sort((a, b) => a.venue.localeCompare(b.venue) || a.raceNo - b.raceNo);
  return selected;
}
