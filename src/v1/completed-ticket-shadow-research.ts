/** Read-only counterfactual research: never use these tickets in public bets.
 *
 * Candidates come exclusively from the same verified, live JRA odds snapshot
 * and feature-state weights used by the immutable official two-ticket lock.
 * This code has NO database access and no authority to replace public bets.
 */
import {
  COMPLETED_ODDS_SCORE_POWER,
  completedCombinationProbability,
  type CompletedBetType,
  type OfficialOddsRow,
} from "./completed-ticket-runtime.js";

export type CompletedShadowTicket = {
  betType: CompletedBetType;
  combination: string;
  officialOdds: number;
  rawModelProbability: number;
  marketImpliedProbability: number;
  blendedProbability: number;
  score: number;
};

export type CompletedShadowPortfolio = {
  policy: "market_implied_only" | "market_blend_30pct_model";
  blendModelFraction: number;
  // The original live research uses only these TWO immutable candidate bets.
  // They are unchanged; the additional research candidates below never
  // influence canonical public bets or market selection.
  tickets: CompletedShadowTicket[];
  // Six (one per JRA bet type) PRE-result candidates from the exact SAME
  // official odds snapshot and existing frozen model. Future payout audits
  // can reconstruct all 15 DISTINCT pairs without re-fetching odds after
  // the race or adding any D1 query. Never backfill missing historical pairs.
  candidatesByType: CompletedShadowTicket[];
};

const BET_TYPE_ORDER: readonly CompletedBetType[] = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"];
const BET_TYPES = new Set<CompletedBetType>(BET_TYPE_ORDER);
const UNORDERED = new Set<CompletedBetType>(["ワイド", "馬連", "3連複"]);
const MAX_ODDS_CANDIDATES = 12000;

/** No fitting on target-day results. Market probability is 1/posted decimal odds.
 * This is an uncorrected market-implied probability, not a claim of positive EV.
 */
export function shadowCompletedPortfolioResearch(
  horseNos: readonly number[],
  weights: readonly number[],
  oddsRows: readonly OfficialOddsRow[],
): CompletedShadowPortfolio[] {
  if (horseNos.length !== weights.length || horseNos.length < 3) throw new Error("SHADOW_RUNNER_SHAPE_INVALID");
  if (oddsRows.length > MAX_ODDS_CANDIDATES) throw new Error("SHADOW_CANDIDATES_TOO_MANY");
  const totalWeight = weights.reduce((s, p) => s + p, 0);
  if (!Number.isFinite(totalWeight) || Math.abs(totalWeight - 1) > 1e-9 || weights.some((w) => !(w > 0))) {
    throw new Error("SHADOW_WEIGHTS_INVALID");
  }
  const indexes = new Map(horseNos.map((horse, index) => [horse, index]));
  if (indexes.size !== horseNos.length) throw new Error("SHADOW_DUPLICATE_HORSE");
  const candidates: Array<{betType: CompletedBetType; combination: string; officialOdds: number; modelP: number; marketP: number}> = [];
  const seen = new Set<string>();
  for (const row of oddsRows) {
    if (!BET_TYPES.has(row.betType)) continue;
    const min = Number(row.oddsMin);
    const max = Number(row.oddsMax);
    if (!(min >= 1) || !(max >= min) || !Number.isFinite(max)) continue;
    const odds = (min + max) / 2;
    if (!Number.isFinite(odds) || odds < 1) continue;
    const parts = String(row.combination).split("-").map(Number);
    const expected = row.betType === "単勝" ? 1 : row.betType === "ワイド" || row.betType === "馬連" || row.betType === "馬単" ? 2 : 3;
    if (parts.length !== expected || new Set(parts).size !== expected) continue;
    if (UNORDERED.has(row.betType) && parts.some((horse, i) => i > 0 && parts[i - 1]! >= horse)) continue;
    const pos = parts.map((horse) => indexes.get(horse));
    if (pos.some((p) => p === undefined)) continue;
    const key = row.betType + "\u0001" + row.combination;
    if (seen.has(key)) continue;
    seen.add(key);
    const modelP = completedCombinationProbability(row.betType, pos as number[], weights);
    if (!(modelP > 0) || modelP > 1 || !Number.isFinite(modelP)) continue;
    candidates.push({
      betType: row.betType, combination: row.combination, officialOdds: odds,
      modelP, marketP: Math.min(0.999999, 1 / odds),
    });
  }
  const policies: Array<CompletedShadowPortfolio["policy"]> = ["market_implied_only", "market_blend_30pct_model"];
  return policies.map((policy) => {
    const alpha = policy === "market_implied_only" ? 0 : 0.3;
    const bestByType = new Map<CompletedBetType, CompletedShadowTicket>();
    for (const candidate of candidates) {
      const p = alpha * candidate.modelP + (1 - alpha) * candidate.marketP;
      if (!(p > 0)) continue;
      const ticket: CompletedShadowTicket = {
        betType: candidate.betType,
        combination: candidate.combination,
        officialOdds: candidate.officialOdds,
        rawModelProbability: candidate.modelP,
        marketImpliedProbability: candidate.marketP,
        blendedProbability: p,
        score: Math.log(p) + COMPLETED_ODDS_SCORE_POWER * Math.log(candidate.officialOdds),
      };
      const old = bestByType.get(ticket.betType);
      if (!old || ticket.score > old.score || (ticket.score === old.score && ticket.combination < old.combination)) {
        bestByType.set(ticket.betType, ticket);
      }
    }
    const sorted = [...bestByType.values()].sort((a, b) =>
      (b.score - a.score) || a.betType.localeCompare(b.betType) || a.combination.localeCompare(b.combination));
    // This is an in-memory copy of the already calculated six best-by-type
    // candidates. No extra official fetch, no model infer/retrain, no new D1
    // SELECT/INSERT. Remains at most 6 compact records per policy/snapshot.
    const candidatesByType = [...bestByType.values()].sort((a, b) =>
      BET_TYPE_ORDER.indexOf(a.betType) - BET_TYPE_ORDER.indexOf(b.betType));
    // Important operational isolation: when JRA has not published one
    // official market, retain the ORIGINAL two shadow choices unchanged.
    // The 15-pair audit will reject partial candidates, but the research
    // extension itself must never introduce a new public finalization risk.
    return {policy, blendModelFraction: alpha, tickets: sorted.slice(0, 2), candidatesByType};
  });
}
