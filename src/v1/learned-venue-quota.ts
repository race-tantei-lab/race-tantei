import { settleRaceWithCourses } from "./course-db.js";
import {
  buildLearnedVenueBets,
  learnedPredictionRaceScore
} from "./learned-betting-policy.js";
import { loadCalibrationRunners } from "./learned-calibration-data.js";
import { WORKER_LEARNED_MODEL_VERSION } from "./learned-calibration-state.js";
import type { BetRecommendation, RunnerPrediction } from "./types.js";

interface LearnedQuotaRow {
  raceId: string;
  venue: string;
  raceNo: number;
  predictionId: number;
}

interface RankedLearnedQuotaRow extends LearnedQuotaRow {
  score: number;
  bets: BetRecommendation[];
}

function encodedBetType(row: BetRecommendation): string {
  return `${row.course}｜${row.betType}`;
}

async function deleteCourseBets(db: D1Database, predictionId: number): Promise<void> {
  await db.prepare(`
    DELETE FROM rt_bets
    WHERE prediction_id=?
      AND (bet_type LIKE 'ライト｜%' OR bet_type LIKE 'スタンダード｜%' OR bet_type LIKE 'プレミアム｜%')
  `).bind(predictionId).run();
}

async function insertCourseBets(
  db: D1Database,
  row: RankedLearnedQuotaRow
): Promise<void> {
  if (row.bets.length === 0) return;
  await db.batch(row.bets.map((bet) => db.prepare(`
    INSERT OR REPLACE INTO rt_bets (
      prediction_id, race_id, bet_type, combination, stake_yen, assumed_odds,
      hit_probability, expected_value_pct, settlement_status, return_yen, settled_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL)
  `).bind(
    row.predictionId,
    row.raceId,
    encodedBetType(bet),
    bet.combination,
    bet.stakeYen,
    bet.assumedOdds,
    bet.hitProbability,
    bet.expectedValuePct
  )));
}

async function rankedRows(
  db: D1Database,
  rows: LearnedQuotaRow[]
): Promise<RankedLearnedQuotaRow[]> {
  const ranked: RankedLearnedQuotaRow[] = [];
  for (const row of rows) {
    const stored = await loadCalibrationRunners(db, row.predictionId);
    const predictions: RunnerPrediction[] = stored.map((runner) => ({ ...runner }));
    const bets = buildLearnedVenueBets(predictions);
    const score = learnedPredictionRaceScore(predictions);
    if (bets.length === 0 || !Number.isFinite(score)) continue;
    ranked.push({ ...row, score, bets });
  }
  return ranked.sort((a, b) => b.score - a.score || a.raceNo - b.raceNo);
}

export interface LearnedVenueQuotaResult {
  raceDate: string;
  venues: number;
  selectedRaces: number;
  insertedTickets: number;
}

export async function ensureLearnedVenueQuota(
  db: D1Database,
  raceDate: string
): Promise<LearnedVenueQuotaResult> {
  const result = await db.prepare(`
    SELECT r.race_id AS raceId, r.venue, r.race_no AS raceNo, p.id AS predictionId
    FROM rt_races r JOIN rt_predictions p ON p.race_id=r.race_id
    WHERE r.race_date=? AND r.status='finished'
      AND p.model_version=? AND p.status='locked'
    ORDER BY r.venue, r.race_no
  `).bind(raceDate, WORKER_LEARNED_MODEL_VERSION).all<LearnedQuotaRow>();
  const rows = result.results.map((row) => ({
    ...row,
    raceNo: Number(row.raceNo),
    predictionId: Number(row.predictionId)
  }));
  const venues = [...new Set(rows.map((row) => row.venue))];
  let selectedRaces = 0;
  let insertedTickets = 0;

  for (const venue of venues) {
    const venueRows = rows.filter((row) => row.venue === venue);
    const ranked = await rankedRows(db, venueRows);
    const selected = new Set(ranked.slice(0, Math.min(5, ranked.length)).map((row) => row.predictionId));
    for (const row of ranked) {
      await deleteCourseBets(db, row.predictionId);
      if (!selected.has(row.predictionId)) continue;
      await insertCourseBets(db, row);
      await settleRaceWithCourses(db, row.raceId);
      selectedRaces += 1;
      insertedTickets += row.bets.length;
    }
  }

  return { raceDate, venues: venues.length, selectedRaces, insertedTickets };
}
