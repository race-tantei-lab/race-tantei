import type { BetType, BudgetCourse, RunnerPrediction } from "./types.js";
import { clamp } from "./utils.js";

export const ROI_POLICY_VERSION = "roi-policy-v1";

export const ROI_POLICY_TARGET_STAKES = {
  ライト: 1600,
  スタンダード: 4200,
  プレミアム: 8800
} as const;

export const ROI_POLICY_ANALYSIS_METRICS = {
  usableRaces: 64,
  selectedRaces: 30,
  minimumCourseRoiPct: 177.0340909090909,
  averageCourseRoiPct: 179.71010702260705,
  courses: {
    ライト: { roiPct: 179.10416666666666, hitRatePct: 76.66666666666667 },
    スタンダード: { roiPct: 182.9920634920635, hitRatePct: 73.33333333333333 },
    プレミアム: { roiPct: 177.0340909090909, hitRatePct: 76.66666666666667 }
  }
} as const;

export interface RoiPolicyCandidate {
  betType: BetType;
  assumedOdds: number;
  hitProbability: number;
  expectedValuePct: number;
  rankSum: number;
  includesFirst: boolean;
}

interface TicketPolicy {
  ticketCount: number;
  evWeight: number;
  probabilityWeight: number;
  oddsWeight: number;
  rankWeight: number;
  firstWeight: number;
  temperature: number;
  typeBias: Partial<Record<BetType, number>>;
  typeCaps: Partial<Record<BetType, number>>;
}

const TICKET_POLICIES: Record<BudgetCourse, TicketPolicy> = {
  ライト: {
    ticketCount: 6,
    evWeight: 2.002791382841485,
    probabilityWeight: 0.9945825426512676,
    oddsWeight: 0.8745773805861319,
    rankWeight: -0.16260266870806017,
    firstWeight: 0.20812264852025464,
    temperature: 1.8092974375227913,
    typeBias: { 単勝: -1.8823857505802501, ワイド: 1.9861787771837367, 馬連: 2.282755209735998 },
    typeCaps: { 単勝: 2, ワイド: 4, 馬連: 2 }
  },
  スタンダード: {
    ticketCount: 15,
    evWeight: 2.448426025483065,
    probabilityWeight: 0.6442199397939466,
    oddsWeight: 1.10786229170172,
    rankWeight: -0.4424013070881061,
    firstWeight: 0.19175246432695292,
    temperature: 1.0713287921387726,
    typeBias: {
      単勝: 0.9815552702951948,
      ワイド: -2.471790022375782,
      馬連: -1.839918491936583,
      馬単: -0.6995578694074225,
      "3連複": -2.4933270986794525
    },
    typeCaps: { 単勝: 1, ワイド: 4, 馬連: 2, 馬単: 8, "3連複": 12 }
  },
  プレミアム: {
    ticketCount: 16,
    evWeight: 1.4997241836636233,
    probabilityWeight: 0.33235115100077034,
    oddsWeight: 0.44878479210632105,
    rankWeight: -0.5280945621804399,
    firstWeight: 0.15055666817087598,
    temperature: 2.1457988887321537,
    typeBias: {
      単勝: -2.195983671005196,
      ワイド: 0.7970673189260613,
      馬連: -0.9703925652940055,
      馬単: -1.1629063402365234,
      "3連複": -0.366139876100982,
      "3連単": 1.6391215410163928
    },
    typeCaps: { 単勝: 2, ワイド: 3, 馬連: 4, 馬単: 11, "3連複": 6, "3連単": 15 }
  }
};

const FEATURE_MEANS = [
  0.28288958841952383,
  0.10698926863310165,
  0.45878990820594595,
  0.5871920020961061,
  0.834773182126594,
  2.5285271060158836,
  0.926216577750105,
  1.078125,
  0.9644399131736092,
  0.3142226531493207,
  0.18834771206696763,
  0.12386683494339304,
  0.04794274878268724
] as const;

const FEATURE_DEVIATIONS = [
  0.0929979999677625,
  0.10117127372035124,
  0.09985576580062853,
  0.09402832250624983,
  0.05780197492800177,
  0.23014853964971374,
  0.34193289048993514,
  0.36677170607204695,
  0.2138989923942059,
  0.06519555143402252,
  0.04180283032701416,
  0.04134323831220061,
  0.017366141284634835
] as const;

const RACE_WEIGHTS = [
  0.8740450255858834,
  0.6050938813889939,
  3.1245537819266307,
  -3.1531554172402796,
  -0.712013190151616,
  3.0785702907492833,
  2.3274649088307973,
  -0.3023200930185759,
  -0.3183553284615508,
  -3.434767258708955,
  2.498025416905846,
  0.606816251541189,
  2.4469246570585232
] as const;

function candidateScore(candidate: RoiPolicyCandidate, policy: TicketPolicy): number {
  return (
    policy.evWeight * Math.log(Math.max(0.05, candidate.expectedValuePct / 100))
    + policy.probabilityWeight * Math.log(Math.max(0.000001, candidate.hitProbability))
    + policy.oddsWeight * Math.log(Math.max(1.1, candidate.assumedOdds))
    + policy.rankWeight * candidate.rankSum
    + policy.firstWeight * (candidate.includesFirst ? 1 : 0)
    + (policy.typeBias[candidate.betType] ?? -99)
  );
}

export function selectRoiPolicyCandidates<T extends RoiPolicyCandidate>(
  course: BudgetCourse,
  candidates: readonly T[]
): T[] {
  const policy = TICKET_POLICIES[course];
  const counts = new Map<BetType, number>();
  const selected: T[] = [];
  const ranked = [...candidates]
    .filter((candidate) => (policy.typeCaps[candidate.betType] ?? 0) > 0)
    .sort((a, b) => candidateScore(b, policy) - candidateScore(a, policy));

  for (const candidate of ranked) {
    if (selected.length >= policy.ticketCount) break;
    const used = counts.get(candidate.betType) ?? 0;
    const cap = policy.typeCaps[candidate.betType] ?? 0;
    if (used >= cap) continue;
    selected.push(candidate);
    counts.set(candidate.betType, used + 1);
  }
  return selected;
}

export function allocateRoiPolicyStakes<T extends RoiPolicyCandidate>(
  course: BudgetCourse,
  selected: readonly T[]
): number[] {
  if (selected.length === 0) return [];
  const policy = TICKET_POLICIES[course];
  const target = ROI_POLICY_TARGET_STAKES[course];
  const stakes = selected.map(() => 100);
  let remaining = target - selected.length * 100;
  const scores = selected.map((candidate) => candidateScore(candidate, policy));
  const maximumScore = Math.max(...scores);
  const weights = scores.map((score) => Math.exp(clamp((score - maximumScore) / policy.temperature, -12, 0)));

  while (remaining >= 100) {
    let bestIndex = 0;
    let bestWeight = Number.NEGATIVE_INFINITY;
    for (let index = 0; index < selected.length; index += 1) {
      const adjusted = (weights[index] ?? 0) / (1 + (stakes[index] ?? 0) / 100);
      if (adjusted > bestWeight) {
        bestWeight = adjusted;
        bestIndex = index;
      }
    }
    stakes[bestIndex] = (stakes[bestIndex] ?? 0) + 100;
    remaining -= 100;
  }
  return stakes;
}

function bestValueCoverage(candidates: readonly RoiPolicyCandidate[], betType?: BetType): number {
  let best = 0;
  for (const candidate of candidates) {
    if (betType && candidate.betType !== betType) continue;
    const value = betType
      ? candidate.expectedValuePct / 100 * Math.sqrt(candidate.hitProbability)
      : candidate.expectedValuePct / 100;
    if (value > best) best = value;
  }
  return best;
}

export function roiPolicyRaceFeatures(
  predictions: readonly RunnerPrediction[],
  candidates: readonly RoiPolicyCandidate[]
): number[] {
  const ranked = [...predictions].sort((a, b) => a.predictedOrder - b.predictedOrder);
  if (ranked.length === 0) return [];
  const probabilities = ranked.map((runner) => Math.max(0, runner.winProbability));
  const first = probabilities[0] ?? 0;
  const second = probabilities[1] ?? 0;
  const third = probabilities[2] ?? 0;
  const entropy = probabilities.reduce(
    (sum, probability) => sum - probability * Math.log(Math.max(probability, 0.000000000001)),
    0
  );
  const maximumEntropy = Math.log(Math.max(2, ranked.length));
  const top = ranked[0]!;
  return [
    first,
    first - second,
    first + second,
    first + second + third,
    maximumEntropy > 0 ? entropy / maximumEntropy : 0,
    Math.log(Math.max(3, ranked.length)),
    Math.log(Math.max(1.1, top.currentOdds ?? 99)),
    Number(top.popularity ?? ranked.length),
    bestValueCoverage(candidates),
    bestValueCoverage(candidates, "ワイド"),
    bestValueCoverage(candidates, "馬連"),
    bestValueCoverage(candidates, "3連複"),
    bestValueCoverage(candidates, "3連単")
  ];
}

export function roiPolicyRaceScore(
  predictions: readonly RunnerPrediction[],
  candidates: readonly RoiPolicyCandidate[]
): number {
  const features = roiPolicyRaceFeatures(predictions, candidates);
  if (features.length !== RACE_WEIGHTS.length) return Number.NEGATIVE_INFINITY;
  return features.reduce((sum, feature, index) => {
    const standardized = (feature - FEATURE_MEANS[index]!) / FEATURE_DEVIATIONS[index]!;
    return sum + standardized * RACE_WEIGHTS[index]!;
  }, 0);
}
