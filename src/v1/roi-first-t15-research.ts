/**
 * RESEARCH ONLY: price-aware EV candidate for the user's >=20% hit floor.
 * Pure computation; no Worker/D1 writes, no public prediction change.
 * Odds MUST be genuinely observed official JRA odds before T-15.
 * "Expected" win probability is a hypothesis, not empirically calibrated.
 * Do NOT present this as proven profitable or a deployable live model.
 */
import {
  COMPLETED_BET_ORDER,
  completedCombinationProbability,
  type CompletedBetType,
  type OfficialOddsRow,
} from "./completed-ticket-runtime.js";

const UNORDERED = new Set<CompletedBetType>(["ワイド", "馬連", "3連複"]);
const TYPE_SET = new Set<CompletedBetType>(COMPLETED_BET_ORDER);
const MAX_QUOTES = 12000;
const MAX_RUNNERS = 18;
const MAX_CANDIDATES_PER_TYPE = 5;

export type RoiFirstCandidate = {
  betType: CompletedBetType;
  combination: string;
  officialConservativeOdds: number;
  modelProbability: number;
  modeledReturnPerYen: number;
  expectedNetPerYen: number;
};
export type RoiFirstSelection = {
  researchOnly: true;
  selectionBeforeT15: true;
  oddsObservedAt: string;
  startAt: string;
  ticket1: RoiFirstCandidate & { stakeYen: number };
  ticket2: RoiFirstCandidate & { stakeYen: number };
  estimatedPairedHitPct: number;
  estimatedRoiPct: number;
  estimatedNetYen: number;
  stakeYen: number;
  // Exact statement about what is (and isn't) validated.
  estimationStatus: "UNCALIBRATED_PL_PROBABILITY_HYPOTHESIS_NOT_REAL_JRA_ROI";
};

type CandidateInternal = RoiFirstCandidate & { eventHits: Uint8Array };
type FinishOutcome = { horses: readonly number[]; probability: number };

function canonicalKey(kind: CompletedBetType, horses: number[]): string {
  if (UNORDERED.has(kind)) horses.sort((a, b) => a - b);
  return horses.join("-");
}

function isWinning(kind: CompletedBetType, selection: readonly number[], order: readonly number[]): boolean {
  if (kind === "単勝") return order[0] === selection[0];
  if (kind === "馬単") return order[0] === selection[0] && order[1] === selection[1];
  if (kind === "馬連") return selection.includes(order[0]!) && selection.includes(order[1]!);
  if (kind === "ワイド") return selection.every((horse) => order.includes(horse));
  if (kind === "3連単") return selection.every((horse, i) => order[i] === horse);
  if (kind === "3連複") return selection.every((horse) => order.includes(horse));
  throw new Error("UNKNOWN_TYPE");
}

/** Enumerate Plackett-Luce top-three outcomes once, for EXACT union of 2 ticket hit events. */
function finishOutcomes(horses: readonly number[], probabilities: readonly number[]): FinishOutcome[] {
  const out: FinishOutcome[] = [];
  for (let a = 0; a < horses.length; a++) {
    for (let b = 0; b < horses.length; b++) {
      if (a === b) continue;
      for (let c = 0; c < horses.length; c++) {
        if (a === c || b === c) continue;
        const pa = probabilities[a]!;
        const pb = probabilities[b]!;
        const pc = probabilities[c]!;
        const q = pa * pb / Math.max(1e-12, 1 - pa) * pc / Math.max(1e-12, 1 - pa - pb);
        out.push({ horses: [horses[a]!, horses[b]!, horses[c]!], probability: q });
      }
    }
  }
  const sum = out.reduce((a, b) => a + b.probability, 0);
  if (!Number.isFinite(sum) || Math.abs(sum - 1) > 1e-7) throw new Error("PL_TOP3_PROBABILITY_DOES_NOT_SUM_TO_ONE");
  return out;
}

function candidateCompare(a: RoiFirstCandidate, b: RoiFirstCandidate): number {
  return (b.expectedNetPerYen - a.expectedNetPerYen)
    || (b.modelProbability - a.modelProbability)
    || a.betType.localeCompare(b.betType)
    || a.combination.localeCompare(b.combination);
}

/** Accepts official odds (not payout or final odds). No implicit network calls. */
export function researchRoiFirstPair(
  horseNos: readonly number[],
  modelWeights: readonly number[],
  oddsRows: readonly OfficialOddsRow[],
  oddsObservedAt: string,
  raceStartAt: string,
  options?: { budgetYen?: number; minimumModeledHitPct?: number },
): RoiFirstSelection | null {
  const observed = Date.parse(oddsObservedAt);
  const starts = Date.parse(raceStartAt);
  if (!Number.isFinite(observed) || !Number.isFinite(starts)
      || !/(Z|[+-]\d{2}:\d{2})$/.test(oddsObservedAt)
      || !/(Z|[+-]\d{2}:\d{2})$/.test(raceStartAt)
      || observed > starts - 15 * 60 * 1000) {
    throw new Error("UNVERIFIED_OFFICIAL_PRE_T15_ODDS_TIMESTAMP");
  }
  if (horseNos.length < 3 || horseNos.length > MAX_RUNNERS
      || modelWeights.length !== horseNos.length
      || horseNos.some((horse) => !Number.isInteger(horse) || horse < 1 || horse > 18)
      || new Set(horseNos).size !== horseNos.length) throw new Error("INVALID_RACE_HORSES");
  if (modelWeights.some((p) => !(p > 0) || !Number.isFinite(p))
      || Math.abs(modelWeights.reduce((s, p) => s + p, 0) - 1) > 1e-9) {
    throw new Error("UNCALIBRATED_MODEL_PROBABILITIES_INVALID");
  }
  if (oddsRows.length > MAX_QUOTES) throw new Error("ODDS_SNAPSHOT_TOO_LARGE");
  const budget = options?.budgetYen ?? 2000;
  const floor = options?.minimumModeledHitPct ?? 20;
  if (budget < 200 || budget % 100 !== 0 || !Number.isInteger(budget)
      || floor < 20 || floor > 100 || !Number.isFinite(floor)) {
    throw new Error("INVALID_RESEARCH_BUDGET_OR_MINIMUM_HIT");
  }
  const byHorse = new Map(horseNos.map((horse, i) => [horse, i]));
  const allOutcomes = finishOutcomes(horseNos, modelWeights);
  const uniqueQuotes = new Set<string>();
  const all = new Map<CompletedBetType, CandidateInternal[]>();
  for (const row of oddsRows) {
    if (!TYPE_SET.has(row.betType)) continue;
    const n = row.betType === "単勝" ? 1 : row.betType === "3連複" || row.betType === "3連単" ? 3 : 2;
    const horses = row.combination.split("-").map(Number);
    if (horses.length !== n || horses.some((x) => !byHorse.has(x)) || new Set(horses).size !== n) continue;
    if (canonicalKey(row.betType, horses.slice()) !== row.combination) continue;
    const key = row.betType + "|" + row.combination;
    if (uniqueQuotes.has(key)) throw new Error("DUPLICATED_OFFICIAL_ODDS_ROW");
    uniqueQuotes.add(key);
    // For ranges (e.g. WIDE), use the MINIMUM posted odds conservatively.
    // Final actual payout may differ; never call this a realized return.
    const odds = Number(row.oddsMin);
    const max = Number(row.oddsMax);
    if (!Number.isFinite(odds) || !Number.isFinite(max) || odds < 1 || max < odds) continue;
    const p = completedCombinationProbability(row.betType, horses.map((x) => byHorse.get(x)!), modelWeights);
    if (!Number.isFinite(p) || !(p > 0) || p > 1) continue;
    const eventHits = Uint8Array.from(allOutcomes.map((v) => Number(isWinning(row.betType, horses, v.horses))));
    const eventProbability = allOutcomes.reduce((sum, v, i) => sum + v.probability * eventHits[i]!, 0);
    if (Math.abs(eventProbability - p) > 1e-7) throw new Error("COMBINATION_PROBABILITY_DISAGREES_WITH_PL_EVENTS");
    const candidate: CandidateInternal = {
      betType: row.betType, combination: row.combination,
      officialConservativeOdds: odds, modelProbability: p,
      modeledReturnPerYen: odds * p, expectedNetPerYen: odds * p - 1, eventHits,
    };
    if (!all.has(row.betType)) all.set(row.betType, []);
    all.get(row.betType)!.push(candidate);
  }
  // Refuse incomplete market snapshots rather than silently substituting
  // unsupported synthetic odds or missing bet types.
  if (all.size !== COMPLETED_BET_ORDER.length) return null;
  const picks = COMPLETED_BET_ORDER.map((type) =>
    all.get(type)!.sort(candidateCompare).slice(0, MAX_CANDIDATES_PER_TYPE));
  let best: RoiFirstSelection | null = null;
  for (let first = 0; first < picks.length; first++) {
    for (let second = first + 1; second < picks.length; second++) {
      for (const a of picks[first]!) for (const b of picks[second]!) {
        let combinedP = 0;
        for (let i = 0; i < allOutcomes.length; i++)
          if (a.eventHits[i] || b.eventHits[i]) combinedP += allOutcomes[i]!.probability;
        if (combinedP * 100 + 1e-9 < floor) continue;
        for (let stake1 = 100; stake1 <= budget - 100; stake1 += 100) {
          const stake2 = budget - stake1;
          const ret = a.modeledReturnPerYen * stake1 + b.modeledReturnPerYen * stake2;
          const selected: RoiFirstSelection = {
            researchOnly: true, selectionBeforeT15: true,
            oddsObservedAt, startAt: raceStartAt,
            ticket1: {
              betType:a.betType, combination:a.combination,
              modelProbability:a.modelProbability,
              officialConservativeOdds:a.officialConservativeOdds,
              modeledReturnPerYen:a.modeledReturnPerYen,
              expectedNetPerYen:a.expectedNetPerYen, stakeYen:stake1,
            },
            ticket2: {
              betType:b.betType, combination:b.combination,
              modelProbability:b.modelProbability,
              officialConservativeOdds:b.officialConservativeOdds,
              modeledReturnPerYen:b.modeledReturnPerYen,
              expectedNetPerYen:b.expectedNetPerYen, stakeYen:stake2,
            },
            estimatedPairedHitPct:Math.round(combinedP * 10000) / 100,
            estimatedRoiPct:Math.round(ret / budget * 10000) / 100,
            estimatedNetYen:Math.round((ret - budget) * 100) / 100,
            stakeYen:budget,
            estimationStatus:"UNCALIBRATED_PL_PROBABILITY_HYPOTHESIS_NOT_REAL_JRA_ROI",
          };
          if (!best || selected.estimatedNetYen > best.estimatedNetYen
              || (selected.estimatedNetYen === best.estimatedNetYen
              && selected.estimatedPairedHitPct > best.estimatedPairedHitPct)) best = selected;
        }
      }
    }
  }
  return best;
}
