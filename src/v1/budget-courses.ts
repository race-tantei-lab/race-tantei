import type { BetRecommendation, RunnerPrediction } from "./types.js";
import { clamp, round100 } from "./utils.js";

export const COURSE_BUDGETS = {
  ライト: 2000,
  スタンダード: 5000,
  プレミアム: 10000
} as const;

function oddsOf(p: RunnerPrediction): number {
  return Math.max(1.1, p.currentOdds ?? p.fairOdds);
}

function make(
  course: keyof typeof COURSE_BUDGETS,
  betType: BetRecommendation["betType"],
  combination: number[],
  stakeYen: number,
  assumedOdds: number,
  hitProbability: number
): BetRecommendation {
  const stake = Math.max(100, round100(stakeYen));
  return {
    course,
    betType,
    combination: combination.join("-"),
    stakeYen: stake,
    assumedOdds: Math.max(1.1, assumedOdds),
    hitProbability: clamp(hitProbability, 0.0005, 0.99),
    expectedValuePct: clamp(hitProbability * Math.max(1.1, assumedOdds) * 100, 1, 9999)
  };
}

function pairProb(a: RunnerPrediction, b: RunnerPrediction): number {
  return clamp(a.placeProbability * b.placeProbability * 0.52, 0.01, 0.75);
}

function exactProb(a: RunnerPrediction, b: RunnerPrediction): number {
  return clamp(a.winProbability * b.placeProbability * 0.55, 0.003, 0.45);
}

function trioProb(a: RunnerPrediction, b: RunnerPrediction, c: RunnerPrediction): number {
  return clamp(a.placeProbability * b.placeProbability * c.placeProbability * 0.22, 0.002, 0.35);
}

function trifectaProb(a: RunnerPrediction, b: RunnerPrediction, c: RunnerPrediction): number {
  return clamp(a.winProbability * b.placeProbability * c.placeProbability * 0.10, 0.0005, 0.15);
}

function pairOdds(a: RunnerPrediction, b: RunnerPrediction, multiplier: number): number {
  return Math.sqrt(oddsOf(a) * oddsOf(b)) * multiplier;
}

function tripleOdds(a: RunnerPrediction, b: RunnerPrediction, c: RunnerPrediction, multiplier: number): number {
  return Math.cbrt(oddsOf(a) * oddsOf(b) * oddsOf(c)) * multiplier;
}

export function buildBudgetCourseBets(predictions: RunnerPrediction[]): BetRecommendation[] {
  const [a, b, c, d] = predictions.slice(0, 4);
  if (!a) return [];
  if (!b || !c) {
    return [
      make("ライト", "単勝", [a.horseNo], 2000, oddsOf(a), a.winProbability),
      make("スタンダード", "単勝", [a.horseNo], 5000, oddsOf(a), a.winProbability),
      make("プレミアム", "単勝", [a.horseNo], 10000, oddsOf(a), a.winProbability)
    ];
  }

  const bets: BetRecommendation[] = [];
  const add = (...items: BetRecommendation[]) => bets.push(...items);

  add(
    make("ライト", "単勝", [a.horseNo], 600, oddsOf(a), a.winProbability),
    make("ライト", "ワイド", [a.horseNo, b.horseNo], 600, pairOdds(a, b, 1.8), pairProb(a, b)),
    make("ライト", "馬連", [a.horseNo, b.horseNo], 400, pairOdds(a, b, 3.1), pairProb(a, b) * 0.52),
    make("ライト", "3連複", [a.horseNo, b.horseNo, c.horseNo], 400, tripleOdds(a, b, c, 5.8), trioProb(a, b, c))
  );

  add(
    make("スタンダード", "単勝", [a.horseNo], 1000, oddsOf(a), a.winProbability),
    make("スタンダード", "ワイド", [a.horseNo, b.horseNo], 900, pairOdds(a, b, 1.8), pairProb(a, b)),
    make("スタンダード", "ワイド", [a.horseNo, c.horseNo], 600, pairOdds(a, c, 2.1), pairProb(a, c)),
    make("スタンダード", "馬連", [a.horseNo, b.horseNo], 700, pairOdds(a, b, 3.1), pairProb(a, b) * 0.52),
    make("スタンダード", "馬単", [a.horseNo, b.horseNo], 500, pairOdds(a, b, 5.0), exactProb(a, b)),
    make("スタンダード", "3連複", [a.horseNo, b.horseNo, c.horseNo], 700, tripleOdds(a, b, c, 5.8), trioProb(a, b, c)),
    make("スタンダード", "3連単", [a.horseNo, b.horseNo, c.horseNo], 300, tripleOdds(a, b, c, 15), trifectaProb(a, b, c)),
    make("スタンダード", "3連単", [a.horseNo, c.horseNo, b.horseNo], 300, tripleOdds(a, c, b, 17), trifectaProb(a, c, b))
  );

  add(
    make("プレミアム", "単勝", [a.horseNo], 1600, oddsOf(a), a.winProbability),
    make("プレミアム", "ワイド", [a.horseNo, b.horseNo], 1200, pairOdds(a, b, 1.8), pairProb(a, b)),
    make("プレミアム", "ワイド", [a.horseNo, c.horseNo], 800, pairOdds(a, c, 2.1), pairProb(a, c)),
    make("プレミアム", "馬連", [a.horseNo, b.horseNo], 1000, pairOdds(a, b, 3.1), pairProb(a, b) * 0.52),
    make("プレミアム", "馬連", [a.horseNo, c.horseNo], 600, pairOdds(a, c, 3.6), pairProb(a, c) * 0.50),
    make("プレミアム", "馬単", [a.horseNo, b.horseNo], 800, pairOdds(a, b, 5.0), exactProb(a, b)),
    make("プレミアム", "馬単", [a.horseNo, c.horseNo], 400, pairOdds(a, c, 5.8), exactProb(a, c)),
    make("プレミアム", "3連複", [a.horseNo, b.horseNo, c.horseNo], 1000, tripleOdds(a, b, c, 5.8), trioProb(a, b, c))
  );

  if (d) {
    add(make("プレミアム", "3連複", [a.horseNo, b.horseNo, d.horseNo], 600, tripleOdds(a, b, d, 7.2), trioProb(a, b, d)));
  } else {
    add(make("プレミアム", "3連複", [a.horseNo, b.horseNo, c.horseNo], 600, tripleOdds(a, b, c, 5.8), trioProb(a, b, c)));
  }

  const tri = [
    [a, b, c, 500],
    [a, c, b, 500],
    [a, b, d ?? c, 300],
    [a, d ?? c, b, 300],
    [b, a, c, 200],
    [c, a, b, 200]
  ] as const;
  for (const [x, y, z, stake] of tri) {
    if (new Set([x.horseNo, y.horseNo, z.horseNo]).size < 3) continue;
    add(make("プレミアム", "3連単", [x.horseNo, y.horseNo, z.horseNo], stake, tripleOdds(x, y, z, 16), trifectaProb(x, y, z)));
  }

  return bets;
}
