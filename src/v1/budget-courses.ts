import type {
  BetRecommendation,
  BetType,
  BudgetCourse,
  RunnerPrediction
} from "./types.js";
import { clamp } from "./utils.js";

export const COURSE_BUDGETS = {
  ライト: 2000,
  スタンダード: 5000,
  プレミアム: 10000
} as const;

export const COURSE_TARGET_STAKES = {
  ライト: 1600,
  スタンダード: 4200,
  プレミアム: 8800
} as const;

type WeightMap = Map<number, number>;

interface Candidate {
  betType: BetType;
  combination: number[];
  assumedOdds: number;
  hitProbability: number;
  expectedValuePct: number;
  reliability: number;
}

interface CoursePolicy {
  allowed: ReadonlySet<BetType>;
  minimumExpectedValuePct: number;
  minimumHitProbability: Partial<Record<BetType, number>>;
  maximumTickets: number;
  kellyScale: number;
  maximumTicketShare: number;
}

interface CoveragePolicy {
  allowed: ReadonlySet<BetType>;
  maximumTickets: number;
  maximumTicketShare: number;
  targetStakeYen: number;
  typeCaps: Partial<Record<BetType, number>>;
}

const TICKET_ORDER: BetType[] = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"];

const TICKET_CONFIG: Record<BetType, {
  payoutRatio: number;
  reliability: number;
  maximumOdds: number;
  riskWeight: number;
}> = {
  単勝: { payoutRatio: 1, reliability: 0.98, maximumOdds: 100, riskWeight: 1 },
  ワイド: { payoutRatio: 0.77, reliability: 0.92, maximumOdds: 80, riskWeight: 0.9 },
  馬連: { payoutRatio: 0.77, reliability: 0.89, maximumOdds: 250, riskWeight: 0.76 },
  馬単: { payoutRatio: 0.75, reliability: 0.85, maximumOdds: 500, riskWeight: 0.62 },
  "3連複": { payoutRatio: 0.75, reliability: 0.82, maximumOdds: 800, riskWeight: 0.55 },
  "3連単": { payoutRatio: 0.72, reliability: 0.76, maximumOdds: 2500, riskWeight: 0.34 }
};

const MINIMUM_HIT: Record<BetType, number> = {
  単勝: 0.06,
  ワイド: 0.14,
  馬連: 0.055,
  馬単: 0.025,
  "3連複": 0.025,
  "3連単": 0.004
};

const COVERAGE_MINIMUM_HIT: Record<BetType, number> = {
  単勝: 0.035,
  ワイド: 0.08,
  馬連: 0.025,
  馬単: 0.012,
  "3連複": 0.012,
  "3連単": 0.0015
};

const COVERAGE_ALLOWED: Record<BudgetCourse, ReadonlySet<BetType>> = {
  ライト: new Set<BetType>(["単勝", "ワイド", "馬連"]),
  スタンダード: new Set<BetType>(["単勝", "ワイド", "馬連", "馬単", "3連複"]),
  プレミアム: new Set<BetType>(TICKET_ORDER)
};

const COVERAGE_POLICIES: Record<BudgetCourse, CoveragePolicy> = {
  ライト: {
    allowed: COVERAGE_ALLOWED.ライト,
    maximumTickets: 5,
    maximumTicketShare: 0.45,
    targetStakeYen: COURSE_TARGET_STAKES.ライト,
    typeCaps: { 単勝: 1, ワイド: 3, 馬連: 2 }
  },
  スタンダード: {
    allowed: COVERAGE_ALLOWED.スタンダード,
    maximumTickets: 9,
    maximumTicketShare: 0.30,
    targetStakeYen: COURSE_TARGET_STAKES.スタンダード,
    typeCaps: { 単勝: 1, ワイド: 3, 馬連: 2, 馬単: 2, "3連複": 3 }
  },
  プレミアム: {
    allowed: COVERAGE_ALLOWED.プレミアム,
    maximumTickets: 16,
    maximumTicketShare: 0.20,
    targetStakeYen: COURSE_TARGET_STAKES.プレミアム,
    typeCaps: { 単勝: 1, ワイド: 3, 馬連: 2, 馬単: 3, "3連複": 4, "3連単": 7 }
  }
};

function floor100(value: number): number {
  return Math.max(0, Math.floor(value / 100) * 100);
}

function normalizedModelWeights(predictions: RunnerPrediction[]): WeightMap {
  const total = predictions.reduce((sum, prediction) => sum + Math.max(0, prediction.winProbability), 0);
  const weights = new Map<number, number>();
  for (const prediction of predictions) {
    weights.set(
      prediction.horseNo,
      total > 0 ? Math.max(0, prediction.winProbability) / total : 1 / Math.max(1, predictions.length)
    );
  }
  return weights;
}

function normalizedMarketWeights(predictions: RunnerPrediction[]): WeightMap {
  const raw = predictions.map((prediction) => ({
    horseNo: prediction.horseNo,
    weight: prediction.currentOdds && prediction.currentOdds > 1
      ? 1 / prediction.currentOdds
      : Math.max(0.0001, prediction.winProbability)
  }));
  const total = raw.reduce((sum, item) => sum + item.weight, 0);
  return new Map(raw.map((item) => [item.horseNo, total > 0 ? item.weight / total : 0]));
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

function combinationKey(betType: BetType, combination: number[]): string {
  const values = ["ワイド", "馬連", "3連複"].includes(betType)
    ? [...combination].sort((a, b) => a - b)
    : combination;
  return `${betType}:${values.join("-")}`;
}

function candidate(
  betType: BetType,
  combination: number[],
  predictionsByHorse: Map<number, RunnerPrediction>,
  modelWeights: WeightMap,
  marketWeights: WeightMap
): Candidate | null {
  if (new Set(combination).size !== combination.length) return null;
  const modelProbability = eventProbability(betType, combination, modelWeights);
  const marketProbability = eventProbability(betType, combination, marketWeights);
  if (modelProbability <= 0 || marketProbability <= 0) return null;

  const config = TICKET_CONFIG[betType];
  let assumedOdds: number;
  if (betType === "単勝") {
    const runner = predictionsByHorse.get(combination[0] ?? -1);
    if (!runner?.currentOdds || runner.currentOdds <= 1) return null;
    assumedOdds = runner.currentOdds;
  } else {
    assumedOdds = config.payoutRatio / marketProbability;
  }
  assumedOdds = Math.floor(clamp(assumedOdds, 1.1, config.maximumOdds) * 10) / 10;
  const expectedValuePct = clamp(modelProbability * assumedOdds * 100 * config.reliability, 1, 9999);
  return {
    betType,
    combination,
    assumedOdds,
    hitProbability: modelProbability,
    expectedValuePct,
    reliability: config.reliability
  };
}

function buildCandidates(predictions: RunnerPrediction[]): Candidate[] {
  const ranked = [...predictions]
    .filter((prediction) => prediction.winProbability > 0)
    .sort((a, b) => a.predictedOrder - b.predictedOrder);
  if (ranked.length === 0) return [];

  const modelWeights = normalizedModelWeights(ranked);
  const marketWeights = normalizedMarketWeights(ranked);
  const predictionsByHorse = new Map(ranked.map((prediction) => [prediction.horseNo, prediction]));
  const candidates: Candidate[] = [];
  const seen = new Set<string>();
  const add = (betType: BetType, combination: number[]) => {
    const key = combinationKey(betType, combination);
    if (seen.has(key)) return;
    const built = candidate(betType, combination, predictionsByHorse, modelWeights, marketWeights);
    if (!built) return;
    seen.add(key);
    candidates.push(built);
  };

  for (const runner of ranked.slice(0, 6)) add("単勝", [runner.horseNo]);

  const pairPool = ranked.slice(0, 5);
  for (let first = 0; first < pairPool.length; first += 1) {
    for (let second = first + 1; second < pairPool.length; second += 1) {
      const a = pairPool[first];
      const b = pairPool[second];
      if (!a || !b) continue;
      add("ワイド", [a.horseNo, b.horseNo]);
      add("馬連", [a.horseNo, b.horseNo]);
      add("馬単", [a.horseNo, b.horseNo]);
      add("馬単", [b.horseNo, a.horseNo]);
    }
  }

  const triplePool = ranked.slice(0, 5);
  for (let first = 0; first < triplePool.length; first += 1) {
    for (let second = first + 1; second < triplePool.length; second += 1) {
      for (let third = second + 1; third < triplePool.length; third += 1) {
        const a = triplePool[first];
        const b = triplePool[second];
        const c = triplePool[third];
        if (!a || !b || !c) continue;
        const horses = [a.horseNo, b.horseNo, c.horseNo];
        add("3連複", horses);
        for (const order of permutations(horses)) add("3連単", order);
      }
    }
  }

  return candidates;
}

function policyFor(course: BudgetCourse, baseMinimum: number): CoursePolicy {
  if (course === "ライト") {
    return {
      allowed: COVERAGE_ALLOWED.ライト,
      minimumExpectedValuePct: Math.max(108, baseMinimum),
      minimumHitProbability: { 単勝: 0.09, ワイド: 0.2, 馬連: 0.08 },
      maximumTickets: 4,
      kellyScale: 0.12,
      maximumTicketShare: 0.25
    };
  }
  if (course === "スタンダード") {
    return {
      allowed: COVERAGE_ALLOWED.スタンダード,
      minimumExpectedValuePct: Math.max(110, baseMinimum + 2),
      minimumHitProbability: { 単勝: 0.07, ワイド: 0.16, 馬連: 0.065, 馬単: 0.03, "3連複": 0.03 },
      maximumTickets: 7,
      kellyScale: 0.16,
      maximumTicketShare: 0.22
    };
  }
  return {
    allowed: COVERAGE_ALLOWED.プレミアム,
    minimumExpectedValuePct: Math.max(115, baseMinimum + 7),
    minimumHitProbability: MINIMUM_HIT,
    maximumTickets: 10,
    kellyScale: 0.2,
    maximumTicketShare: 0.2
  };
}

function candidateScore(value: Candidate, threshold: number): number {
  return (value.expectedValuePct - threshold) * Math.sqrt(value.hitProbability) * value.reliability;
}

function coverageCandidateScore(value: Candidate): number {
  const valueFactor = clamp(value.expectedValuePct / 100, 0.55, 2.5);
  return valueFactor * Math.sqrt(value.hitProbability) * value.reliability;
}

function stakeFor(candidateBet: Candidate, course: BudgetCourse, policy: CoursePolicy): number {
  const budget = COURSE_BUDGETS[course];
  const config = TICKET_CONFIG[candidateBet.betType];
  const adjustedProbability = candidateBet.hitProbability * candidateBet.reliability;
  const denominator = Math.max(0.1, candidateBet.assumedOdds - 1);
  const fullKelly = Math.max(0, (adjustedProbability * candidateBet.assumedOdds - 1) / denominator);
  const rawStake = Math.min(
    budget * policy.maximumTicketShare,
    budget * fullKelly * policy.kellyScale * config.riskWeight
  );
  return Math.max(100, floor100(rawStake));
}

function toRecommendation(course: BudgetCourse, item: Candidate, stakeYen: number): BetRecommendation {
  return {
    course,
    betType: item.betType,
    combination: item.combination.join("-"),
    stakeYen,
    assumedOdds: item.assumedOdds,
    hitProbability: item.hitProbability,
    expectedValuePct: item.expectedValuePct
  };
}

function selectCourse(
  course: BudgetCourse,
  candidates: Candidate[],
  baseMinimumExpectedValuePct: number
): BetRecommendation[] {
  const policy = policyFor(course, baseMinimumExpectedValuePct);
  const budget = COURSE_BUDGETS[course];
  const eligible = candidates
    .filter((item) => policy.allowed.has(item.betType))
    .filter((item) => item.expectedValuePct >= policy.minimumExpectedValuePct)
    .filter((item) => item.hitProbability >= (policy.minimumHitProbability[item.betType] ?? MINIMUM_HIT[item.betType]))
    .sort((a, b) => candidateScore(b, policy.minimumExpectedValuePct) - candidateScore(a, policy.minimumExpectedValuePct));

  const selected: BetRecommendation[] = [];
  let spent = 0;
  for (const item of eligible) {
    if (selected.length >= policy.maximumTickets || spent >= budget) break;
    let stakeYen = stakeFor(item, course, policy);
    if (spent + stakeYen > budget) stakeYen = floor100(budget - spent);
    if (stakeYen < 100) continue;
    selected.push(toRecommendation(course, item, stakeYen));
    spent += stakeYen;
  }
  return selected;
}

function selectCoverageCandidates(course: BudgetCourse, candidates: Candidate[]): Candidate[] {
  const policy = COVERAGE_POLICIES[course];
  const allowed = candidates.filter((item) => policy.allowed.has(item.betType));
  const reliable = allowed.filter((item) => item.hitProbability >= COVERAGE_MINIMUM_HIT[item.betType]);
  const pool = (reliable.length >= policy.maximumTickets ? reliable : allowed)
    .sort((a, b) => coverageCandidateScore(b) - coverageCandidateScore(a));
  const typeCounts = new Map<BetType, number>();
  const selected: Candidate[] = [];

  for (const item of pool) {
    if (selected.length >= policy.maximumTickets) break;
    const used = typeCounts.get(item.betType) ?? 0;
    const cap = policy.typeCaps[item.betType] ?? policy.maximumTickets;
    if (used >= cap) continue;
    selected.push(item);
    typeCounts.set(item.betType, used + 1);
  }

  if (selected.length === 0 && allowed[0]) selected.push(allowed[0]);
  return selected;
}

function allocateCoverageStakes(
  course: BudgetCourse,
  selected: Candidate[]
): BetRecommendation[] {
  if (selected.length === 0) return [];
  const policy = COVERAGE_POLICIES[course];
  const budget = COURSE_BUDGETS[course];
  const target = Math.min(budget, Math.max(selected.length * 100, floor100(policy.targetStakeYen)));
  const maximumPerTicket = Math.max(100, floor100(budget * policy.maximumTicketShare));
  const stakes = selected.map(() => 100);
  let remaining = target - selected.length * 100;
  const weights = selected.map((item) => Math.max(0.01, coverageCandidateScore(item)));
  const totalWeight = weights.reduce((sum, value) => sum + value, 0);

  for (let index = 0; index < selected.length && remaining >= 100; index += 1) {
    const proportional = floor100(remaining * (weights[index] ?? 0) / Math.max(0.01, totalWeight));
    const room = Math.max(0, maximumPerTicket - (stakes[index] ?? 0));
    const addition = Math.min(room, proportional);
    stakes[index] = (stakes[index] ?? 0) + addition;
    remaining -= addition;
  }

  const order = selected
    .map((item, index) => ({ index, score: coverageCandidateScore(item) }))
    .sort((a, b) => b.score - a.score);
  while (remaining >= 100) {
    let allocated = false;
    for (const item of order) {
      const current = stakes[item.index] ?? 0;
      if (current + 100 > maximumPerTicket) continue;
      stakes[item.index] = current + 100;
      remaining -= 100;
      allocated = true;
      if (remaining < 100) break;
    }
    if (!allocated) break;
  }

  return selected.map((item, index) => toRecommendation(course, item, stakes[index] ?? 100));
}

export function coverageRaceScore(predictions: RunnerPrediction[]): number {
  const candidates = buildCandidates(predictions);
  if (candidates.length === 0) return Number.NEGATIVE_INFINITY;
  const best = candidates
    .filter((item) => item.hitProbability >= COVERAGE_MINIMUM_HIT[item.betType])
    .sort((a, b) => coverageCandidateScore(b) - coverageCandidateScore(a))[0]
    ?? candidates.sort((a, b) => coverageCandidateScore(b) - coverageCandidateScore(a))[0];
  const ranked = [...predictions].sort((a, b) => a.predictedOrder - b.predictedOrder);
  const first = ranked[0]?.winProbability ?? 0;
  const second = ranked[1]?.winProbability ?? 0;
  return coverageCandidateScore(best) * 100 + first * 20 + Math.max(0, first - second) * 40;
}

export function buildVenueCoverageBets(predictions: RunnerPrediction[]): BetRecommendation[] {
  const candidates = buildCandidates(predictions);
  if (candidates.length === 0) return [];
  return (["ライト", "スタンダード", "プレミアム"] as BudgetCourse[])
    .flatMap((course) => allocateCoverageStakes(course, selectCoverageCandidates(course, candidates)));
}

export function buildBudgetCourseBets(
  predictions: RunnerPrediction[],
  minimumExpectedValuePct = 108
): BetRecommendation[] {
  const candidates = buildCandidates(predictions);
  if (candidates.length === 0) return [];
  return (["ライト", "スタンダード", "プレミアム"] as BudgetCourse[])
    .flatMap((course) => selectCourse(course, candidates, Math.max(100, minimumExpectedValuePct)));
}
