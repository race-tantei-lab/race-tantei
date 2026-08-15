export const COMPLETED_BET_ORDER = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"] as const;
export type CompletedBetType = (typeof COMPLETED_BET_ORDER)[number];

export const COMPLETED_COURSE_STAKES = {
  "ライト": [1000, 1000],
  "スタンダード": [2500, 2500],
  "プレミアム": [5000, 5000],
} as const;

export type CompletedCourse = keyof typeof COMPLETED_COURSE_STAKES;

export interface OfficialOddsRow {
  betType: CompletedBetType;
  combination: string;
  oddsMin: number;
  oddsMax: number;
}

export interface CompletedTicket {
  betType: CompletedBetType;
  combination: string;
  horses: number[];
  predictedProbability: number;
  officialOdds: number;
  valueProduct: number;
  score: number;
  recencyFactor?: number;
}

export interface CompletedCourseBet {
  course: CompletedCourse;
  betType: CompletedBetType;
  combination: string;
  stakeYen: number;
  assumedOdds: number;
}

function ordered2(weights: readonly number[], a: number, b: number): number {
  return weights[a] * weights[b] / Math.max(1e-15, 1 - weights[a]);
}

function ordered3(weights: readonly number[], a: number, b: number, c: number): number {
  return weights[a]
    * (weights[b] / Math.max(1e-15, 1 - weights[a]))
    * (weights[c] / Math.max(1e-15, 1 - weights[a] - weights[b]));
}

export function completedCombinationProbability(kind: CompletedBetType, pos: readonly number[], weights: readonly number[]): number {
  if (kind === "単勝") return weights[pos[0]];
  if (kind === "馬単") return ordered2(weights, pos[0], pos[1]);
  if (kind === "馬連") {
    const [a, b] = pos;
    return ordered2(weights, a, b) + ordered2(weights, b, a);
  }
  if (kind === "3連単") return ordered3(weights, pos[0], pos[1], pos[2]);
  if (kind === "3連複") {
    const [a, b, c] = pos;
    return ordered3(weights, a, b, c) + ordered3(weights, a, c, b)
      + ordered3(weights, b, a, c) + ordered3(weights, b, c, a)
      + ordered3(weights, c, a, b) + ordered3(weights, c, b, a);
  }
  if (kind === "ワイド") {
    const [a, b] = pos;
    let out = 0;
    for (let c = 0; c < weights.length; c += 1) {
      if (c === a || c === b) continue;
      out += ordered3(weights, a, b, c) + ordered3(weights, a, c, b)
        + ordered3(weights, b, a, c) + ordered3(weights, b, c, a)
        + ordered3(weights, c, a, b) + ordered3(weights, c, b, a);
    }
    return out;
  }
  throw new Error(`unknown completed bet type: ${kind}`);
}

function* combinations(n: number, k: number, start = 0, prefix: number[] = []): Generator<number[]> {
  if (prefix.length === k) {
    yield prefix.slice();
    return;
  }
  for (let i = start; i <= n - (k - prefix.length); i += 1) {
    prefix.push(i);
    yield* combinations(n, k, i + 1, prefix);
    prefix.pop();
  }
}

function* permutations(n: number, k: number, prefix: number[] = [], used = new Set<number>()): Generator<number[]> {
  if (prefix.length === k) {
    yield prefix.slice();
    return;
  }
  for (let i = 0; i < n; i += 1) {
    if (used.has(i)) continue;
    used.add(i);
    prefix.push(i);
    yield* permutations(n, k, prefix, used);
    prefix.pop();
    used.delete(i);
  }
}

function positions(kind: CompletedBetType, n: number): Iterable<number[]> {
  if (kind === "単勝") return (function* () { for (let i = 0; i < n; i += 1) yield [i]; })();
  if (kind === "ワイド" || kind === "馬連") return combinations(n, 2);
  if (kind === "馬単") return permutations(n, 2);
  if (kind === "3連複") return combinations(n, 3);
  return permutations(n, 3);
}

function comboText(kind: CompletedBetType, pos: readonly number[], horseNos: readonly number[]): string {
  const values = pos.map((index) => horseNos[index]);
  if (kind === "ワイド" || kind === "馬連" || kind === "3連複") values.sort((a, b) => a - b);
  return values.join("-");
}

function compareText(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

export function normalizeCompletedWeights(raw: readonly number[]): number[] {
  if (raw.length < 3 || raw.some((value) => !Number.isFinite(value) || value <= 0)) {
    throw new Error("completed runner probabilities are invalid");
  }
  const total = raw.reduce((sum, value) => sum + value, 0);
  if (!Number.isFinite(total) || total <= 0) throw new Error("completed runner probability total is invalid");
  return raw.map((value) => value / total);
}

function validateCanonicalWeights(weights: readonly number[]): void {
  if (weights.length < 3 || weights.some((value) => !Number.isFinite(value) || value <= 0)) {
    throw new Error("completed normalized runner probabilities are invalid");
  }
  const total = weights.reduce((sum, value) => sum + value, 0);
  if (!Number.isFinite(total) || Math.abs(total - 1) > 1e-9) {
    throw new Error(`completed runner probabilities must already be normalized: total=${total}`);
  }
}

export function chooseCompletedTwoTickets(
  horseNos: readonly number[],
  weights: readonly number[],
  rows: readonly OfficialOddsRow[],
  recencyFactor?: (betType: CompletedBetType, officialOdds: number) => number,
): CompletedTicket[] {
  if (horseNos.length !== weights.length || horseNos.length < 3) throw new Error("completed ticket runner shape is invalid");
  const unique = new Set(horseNos);
  if (unique.size !== horseNos.length || horseNos.some((value) => !Number.isInteger(value) || value < 1 || value > 18)) {
    throw new Error("completed ticket horse numbers are invalid");
  }
  validateCanonicalWeights(weights);
  const odds = new Map<string, number>();
  for (const row of rows) {
    const low = Number(row.oddsMin);
    const high = Number(row.oddsMax);
    const odd = (low + high) / 2;
    if (!Number.isFinite(low) || !Number.isFinite(high) || low <= 0 || high < low || !Number.isFinite(odd) || odd <= 0) continue;
    odds.set(`${row.betType}\u0001${row.combination}`, odd);
  }

  const bestByType: CompletedTicket[] = [];
  for (const betType of COMPLETED_BET_ORDER) {
    const candidates: CompletedTicket[] = [];
    for (const pos of positions(betType, horseNos.length)) {
      const combination = comboText(betType, pos, horseNos);
      const odd = odds.get(`${betType}\u0001${combination}`);
      if (odd == null) continue;
      const probability = completedCombinationProbability(betType, pos, weights);
      if (!Number.isFinite(probability) || probability <= 0) continue;
      const learnedFactor = recencyFactor ? recencyFactor(betType, odd) : 1;
      if (!Number.isFinite(learnedFactor) || learnedFactor <= 0) throw new Error(`invalid completed recency factor: ${betType}:${learnedFactor}`);
      const ticket: CompletedTicket = {
        betType,
        combination,
        horses: pos.map((index) => horseNos[index]),
        predictedProbability: probability,
        officialOdds: odd,
        valueProduct: probability * odd * learnedFactor,
        score: Number.NaN,
      };
      if (recencyFactor) ticket.recencyFactor = learnedFactor;
      candidates.push(ticket);
    }
    if (!candidates.length) throw new Error(`OFFICIAL_ODDS_MISSING_BET_TYPE:${betType}`);
    candidates.sort((a, b) => (b.valueProduct - a.valueProduct) || (a.officialOdds - b.officialOdds) || compareText(a.combination, b.combination));
    const retained = candidates.slice(0, 5).map((ticket) => ({
      ...ticket,
      score: Math.log(ticket.predictedProbability) + 0.4 * Math.log(ticket.officialOdds) + Math.log(ticket.recencyFactor ?? 1),
    }));
    retained.sort((a, b) => (b.score - a.score) || (b.predictedProbability - a.predictedProbability) || compareText(a.combination, b.combination));
    bestByType.push(retained[0]);
  }
  bestByType.sort((a, b) => (b.score - a.score) || (COMPLETED_BET_ORDER.indexOf(a.betType) - COMPLETED_BET_ORDER.indexOf(b.betType)) || compareText(a.combination, b.combination));
  const chosen: CompletedTicket[] = [];
  for (const ticket of bestByType) {
    if (!chosen.some((row) => row.betType === ticket.betType)) chosen.push(ticket);
    if (chosen.length === 2) break;
  }
  if (chosen.length !== 2 || new Set(chosen.map((row) => row.betType)).size !== 2) throw new Error("CANONICAL_TWO_DISTINCT_TYPES_FAILED");
  return chosen;
}

export function completedCourseBets(tickets: readonly CompletedTicket[]): CompletedCourseBet[] {
  if (tickets.length !== 2 || new Set(tickets.map((ticket) => ticket.betType)).size !== 2) throw new Error("completed course bets require two distinct ticket types");
  const out: CompletedCourseBet[] = [];
  for (const course of Object.keys(COMPLETED_COURSE_STAKES) as CompletedCourse[]) {
    const stakes = COMPLETED_COURSE_STAKES[course];
    for (let i = 0; i < 2; i += 1) {
      out.push({ course, betType: tickets[i].betType, combination: tickets[i].combination, stakeYen: stakes[i], assumedOdds: tickets[i].officialOdds });
    }
  }
  return out;
}
