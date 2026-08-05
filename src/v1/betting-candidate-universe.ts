import type { BetType, RunnerPrediction } from "./types.js";
import { clamp } from "./utils.js";

type WeightMap = Map<number, number>;

export interface BettingCandidateUniverseRow {
  betType: BetType;
  combination: string;
  assumedOdds: number;
  hitProbability: number;
  expectedValuePct: number;
  reliability: number;
  rankSum: number;
  maximumRank: number;
  includesFirst: boolean;
}

const TICKET_CONFIG: Record<BetType, {
  payoutRatio: number;
  reliability: number;
}> = {
  単勝: { payoutRatio: 1, reliability: 0.98 },
  ワイド: { payoutRatio: 0.77, reliability: 0.92 },
  馬連: { payoutRatio: 0.77, reliability: 0.89 },
  馬単: { payoutRatio: 0.75, reliability: 0.85 },
  "3連複": { payoutRatio: 0.75, reliability: 0.82 },
  "3連単": { payoutRatio: 0.72, reliability: 0.76 }
};

function normalizedModelWeights(predictions: RunnerPrediction[]): WeightMap {
  const total = predictions.reduce((sum, row) => sum + Math.max(0, row.winProbability), 0);
  return new Map(predictions.map((row) => [
    row.horseNo,
    total > 0 ? Math.max(0, row.winProbability) / total : 1 / Math.max(1, predictions.length)
  ]));
}

function normalizedMarketWeights(predictions: RunnerPrediction[]): WeightMap {
  const raw = predictions.map((row) => ({
    horseNo: row.horseNo,
    weight: row.currentOdds && row.currentOdds > 1
      ? 1 / row.currentOdds
      : Math.max(0.0001, row.winProbability)
  }));
  const total = raw.reduce((sum, row) => sum + row.weight, 0);
  return new Map(raw.map((row) => [row.horseNo, total > 0 ? row.weight / total : 0]));
}

function orderedProbability(order: number[], weights: WeightMap): number {
  let remaining = [...weights.values()].reduce((sum, value) => sum + value, 0);
  let probability = 1;
  const used = new Set<number>();
  for (const horseNo of order) {
    if (used.has(horseNo) || remaining <= 0) return 0;
    const weight = weights.get(horseNo) ?? 0;
    if (weight <= 0) return 0;
    probability *= weight / remaining;
    remaining -= weight;
    used.add(horseNo);
  }
  return clamp(probability, 0, 1);
}

function permutations(values: number[]): number[][] {
  if (values.length <= 1) return [values];
  const result: number[][] = [];
  values.forEach((value, index) => {
    const rest = values.filter((_, restIndex) => restIndex !== index);
    for (const tail of permutations(rest)) result.push([value, ...tail]);
  });
  return result;
}

function unorderedTopTwoProbability(a: number, b: number, weights: WeightMap): number {
  return clamp(
    orderedProbability([a, b], weights) + orderedProbability([b, a], weights),
    0,
    1
  );
}

function unorderedTopThreeProbability(horses: number[], weights: WeightMap): number {
  if (new Set(horses).size !== 3) return 0;
  return clamp(
    permutations(horses).reduce((sum, order) => sum + orderedProbability(order, weights), 0),
    0,
    1
  );
}

function wideProbability(a: number, b: number, weights: WeightMap): number {
  if (a === b || weights.size < 3) return 0;
  let probability = 0;
  for (const third of weights.keys()) {
    if (third === a || third === b) continue;
    probability += unorderedTopThreeProbability([a, b, third], weights);
  }
  return clamp(probability, 0, 1);
}

function eventProbability(betType: BetType, combination: number[], weights: WeightMap): number {
  const [a, b, c] = combination;
  if (a === undefined) return 0;
  if (betType === "単勝") return clamp(weights.get(a) ?? 0, 0, 1);
  if (b === undefined) return 0;
  if (betType === "ワイド") return wideProbability(a, b, weights);
  if (betType === "馬連") return unorderedTopTwoProbability(a, b, weights);
  if (betType === "馬単") return orderedProbability([a, b], weights);
  if (c === undefined) return 0;
  if (betType === "3連複") return unorderedTopThreeProbability([a, b, c], weights);
  return orderedProbability([a, b, c], weights);
}

function key(betType: BetType, combination: number[]): string {
  const values = ["ワイド", "馬連", "3連複"].includes(betType)
    ? [...combination].sort((a, b) => a - b)
    : combination;
  return `${betType}:${values.join("-")}`;
}

export function buildBettingCandidateUniverse(
  predictions: RunnerPrediction[],
  poolSize = 7
): BettingCandidateUniverseRow[] {
  const ranked = [...predictions]
    .filter((row) => row.winProbability > 0)
    .sort((a, b) => a.predictedOrder - b.predictedOrder);
  if (ranked.length === 0) return [];

  const pool = ranked.slice(0, Math.max(3, poolSize));
  const modelWeights = normalizedModelWeights(ranked);
  const marketWeights = normalizedMarketWeights(ranked);
  const byHorse = new Map(ranked.map((row) => [row.horseNo, row]));
  const firstHorseNo = ranked[0]!.horseNo;
  const seen = new Set<string>();
  const result: BettingCandidateUniverseRow[] = [];

  const add = (betType: BetType, combination: number[]) => {
    const candidateKey = key(betType, combination);
    if (seen.has(candidateKey) || new Set(combination).size !== combination.length) return;
    const modelProbability = eventProbability(betType, combination, modelWeights);
    const marketProbability = eventProbability(betType, combination, marketWeights);
    if (modelProbability <= 0 || marketProbability <= 0) return;

    const config = TICKET_CONFIG[betType];
    let assumedOdds: number;
    if (betType === "単勝") {
      const row = byHorse.get(combination[0] ?? -1);
      if (!row?.currentOdds || row.currentOdds <= 1) return;
      assumedOdds = row.currentOdds;
    } else {
      assumedOdds = config.payoutRatio / marketProbability;
    }
    assumedOdds = Math.floor(clamp(assumedOdds, 1.1, 2500) * 10) / 10;
    const ranks = combination.map((horseNo) => byHorse.get(horseNo)?.predictedOrder ?? 99);
    seen.add(candidateKey);
    result.push({
      betType,
      combination: combination.join("-"),
      assumedOdds,
      hitProbability: modelProbability,
      expectedValuePct: clamp(modelProbability * assumedOdds * 100 * config.reliability, 1, 9999),
      reliability: config.reliability,
      rankSum: ranks.reduce((sum, value) => sum + value, 0),
      maximumRank: Math.max(...ranks),
      includesFirst: combination.includes(firstHorseNo)
    });
  };

  for (const row of pool) add("単勝", [row.horseNo]);
  for (let first = 0; first < pool.length; first += 1) {
    for (let second = first + 1; second < pool.length; second += 1) {
      const a = pool[first];
      const b = pool[second];
      if (!a || !b) continue;
      add("ワイド", [a.horseNo, b.horseNo]);
      add("馬連", [a.horseNo, b.horseNo]);
      add("馬単", [a.horseNo, b.horseNo]);
      add("馬単", [b.horseNo, a.horseNo]);
    }
  }
  for (let first = 0; first < pool.length; first += 1) {
    for (let second = first + 1; second < pool.length; second += 1) {
      for (let third = second + 1; third < pool.length; third += 1) {
        const a = pool[first];
        const b = pool[second];
        const c = pool[third];
        if (!a || !b || !c) continue;
        const horses = [a.horseNo, b.horseNo, c.horseNo];
        add("3連複", horses);
        for (const order of permutations(horses)) add("3連単", order);
      }
    }
  }
  return result;
}
