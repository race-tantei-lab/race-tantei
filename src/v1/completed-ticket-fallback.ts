import {
  COMPLETED_BET_ORDER,
  completedCombinationProbability,
  normalizeCompletedWeights,
  type CompletedBetType,
  type CompletedTicket,
} from "./completed-ticket-runtime.js";

/** Network-independent last-resort ticket generator. */
export type CompletedFallbackTicket = CompletedTicket & {
  oddsMode: "probability_fallback";
};

function* combinations(n: number, k: number, start = 0, prefix: number[] = []): Generator<number[]> {
  if (prefix.length === k) { yield prefix.slice(); return; }
  for (let i = start; i <= n - (k - prefix.length); i += 1) {
    prefix.push(i); yield* combinations(n, k, i + 1, prefix); prefix.pop();
  }
}

function* permutations(n: number, k: number, prefix: number[] = [], used = new Set<number>()): Generator<number[]> {
  if (prefix.length === k) { yield prefix.slice(); return; }
  for (let i = 0; i < n; i += 1) {
    if (used.has(i)) continue;
    used.add(i); prefix.push(i); yield* permutations(n, k, prefix, used); prefix.pop(); used.delete(i);
  }
}

function positions(kind: CompletedBetType, n: number): Iterable<number[]> {
  if (kind === "単勝") return (function* () { for (let i = 0; i < n; i += 1) yield [i]; })();
  if (kind === "ワイド" || kind === "馬連") return combinations(n, 2);
  if (kind === "馬単") return permutations(n, 2);
  if (kind === "3連複") return combinations(n, 3);
  return permutations(n, 3);
}

function combination(kind: CompletedBetType, pos: readonly number[], horseNos: readonly number[]): string {
  const values = pos.map((index) => horseNos[index]);
  if (kind === "ワイド" || kind === "馬連" || kind === "3連複") values.sort((a, b) => a - b);
  return values.join("-");
}

function compareText(a: string, b: string): number { return a < b ? -1 : a > b ? 1 : 0; }

export function emergencyRunnerWeights(winOdds: readonly Array<number | null | undefined>): number[] {
  const usable = winOdds.length >= 3 && winOdds.every((value) => Number.isFinite(Number(value)) && Number(value) > 1);
  if (usable) return normalizeCompletedWeights(winOdds.map((value) => 1 / Number(value)));
  return normalizeCompletedWeights(winOdds.map(() => 1));
}

export function chooseCompletedProbabilityFallbackTickets(
  horseNos: readonly number[],
  weightsInput: readonly number[],
  recencyFactor?: (betType: CompletedBetType, neutralOdds: number) => number,
): CompletedFallbackTicket[] {
  if (horseNos.length !== weightsInput.length || horseNos.length < 3) throw new Error("fallback ticket runner shape is invalid");
  if (new Set(horseNos).size !== horseNos.length || horseNos.some((value) => !Number.isInteger(value) || value < 1 || value > 18)) {
    throw new Error("fallback ticket horse numbers are invalid");
  }
  const weights = normalizeCompletedWeights(weightsInput);
  const bestByType: CompletedFallbackTicket[] = [];
  for (const betType of COMPLETED_BET_ORDER) {
    let best: CompletedFallbackTicket | null = null;
    for (const pos of positions(betType, horseNos.length)) {
      const predictedProbability = completedCombinationProbability(betType, pos, weights);
      if (!Number.isFinite(predictedProbability) || predictedProbability <= 0) continue;
      const factor = recencyFactor ? recencyFactor(betType, 1) : 1;
      if (!Number.isFinite(factor) || factor <= 0) continue;
      const current: CompletedFallbackTicket = {
        betType,
        combination: combination(betType, pos, horseNos),
        horses: pos.map((index) => horseNos[index]),
        predictedProbability,
        officialOdds: 1,
        valueProduct: predictedProbability * factor,
        score: Math.log(predictedProbability) + Math.log(factor),
        recencyFactor: factor,
        oddsMode: "probability_fallback",
      };
      if (!best || current.score > best.score || (current.score === best.score && compareText(current.combination, best.combination) < 0)) best = current;
    }
    if (best) bestByType.push(best);
  }
  bestByType.sort((a, b) => (b.score - a.score)
    || (COMPLETED_BET_ORDER.indexOf(a.betType) - COMPLETED_BET_ORDER.indexOf(b.betType))
    || compareText(a.combination, b.combination));
  const chosen = bestByType.slice(0, 2);
  if (chosen.length !== 2 || new Set(chosen.map((ticket) => ticket.betType)).size !== 2) throw new Error("FALLBACK_TWO_DISTINCT_TYPES_FAILED");
  return chosen;
}
