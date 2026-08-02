import { buildVenueCoverageBets, coverageRaceScore } from "./budget-courses.js";
import { settleRaceWithCourses } from "./course-db.js";
import type { BetRecommendation, RunnerPrediction } from "./types.js";

export const MINIMUM_SELECTED_RACES_PER_VENUE = 5;

export type VenueQuotaMode = "live" | "validation";

interface QuotaRaceRow {
  raceId: string;
  raceDate: string;
  venue: string;
  raceNo: number;
  raceStatus: string;
  predictionId: number;
  predictionStatus: string;
  betCount: number;
}

interface RankedQuotaCandidate extends QuotaRaceRow {
  score: number;
  predictions: RunnerPrediction[];
  bets: BetRecommendation[];
}

export interface VenueQuotaVenueResult {
  venue: string;
  availableRaces: number;
  targetRaces: number;
  selectedBefore: number;
  addedRaces: number;
  selectedAfter: number;
}

export interface VenueQuotaResult {
  raceDate: string;
  modelVersion: string;
  mode: VenueQuotaMode;
  addedRaces: number;
  addedTickets: number;
  venues: VenueQuotaVenueResult[];
}

function toNumber(value: unknown): number {
  return Number(value ?? 0);
}

async function loadQuotaRaces(
  db: D1Database,
  modelVersion: string,
  raceDate: string,
  mode: VenueQuotaMode
): Promise<QuotaRaceRow[]> {
  const statusCondition = mode === "validation"
    ? "r.status='finished' AND p.status='locked'"
    : "r.status='scheduled' AND r.start_time_utc IS NOT NULL AND datetime(r.start_time_utc)>datetime('now')";
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId, r.race_date AS raceDate, r.venue,
      r.race_no AS raceNo, r.status AS raceStatus,
      p.id AS predictionId, p.status AS predictionStatus,
      COALESCE((
        SELECT COUNT(*) FROM rt_bets b
        WHERE b.prediction_id=p.id
          AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      ),0) AS betCount
    FROM rt_races r
    JOIN rt_predictions p ON p.race_id=r.race_id AND p.model_version=?
    WHERE r.race_date=? AND ${statusCondition}
    ORDER BY r.venue, r.race_no
  `).bind(modelVersion, raceDate).all<QuotaRaceRow>();
  return rows.results.map((row) => ({
    ...row,
    raceNo: toNumber(row.raceNo),
    predictionId: toNumber(row.predictionId),
    betCount: toNumber(row.betCount)
  }));
}

async function loadPredictions(db: D1Database, predictionId: number): Promise<RunnerPrediction[]> {
  const rows = await db.prepare(`
    SELECT horse_no AS horseNo, horse_name AS horseName,
      win_probability AS winProbability, place_probability AS placeProbability,
      fair_odds AS fairOdds, current_odds AS currentOdds,
      expected_value_pct AS expectedValuePct, predicted_order AS predictedOrder,
      explanation
    FROM rt_prediction_runners
    WHERE prediction_id=?
    ORDER BY predicted_order
  `).bind(predictionId).all<RunnerPrediction>();
  return rows.results.map((row) => ({
    ...row,
    horseNo: toNumber(row.horseNo),
    winProbability: toNumber(row.winProbability),
    placeProbability: toNumber(row.placeProbability),
    fairOdds: toNumber(row.fairOdds),
    currentOdds: row.currentOdds === null ? null : toNumber(row.currentOdds),
    expectedValuePct: row.expectedValuePct === null ? null : toNumber(row.expectedValuePct),
    predictedOrder: toNumber(row.predictedOrder)
  }));
}

function encodedBetType(bet: BetRecommendation): string {
  return `${bet.course}｜${bet.betType}`;
}

async function claimAndInsertBets(
  db: D1Database,
  row: RankedQuotaCandidate
): Promise<number> {
  const [first, ...rest] = row.bets;
  if (!first) return 0;
  const claim = await db.prepare(`
    INSERT INTO rt_bets (
      prediction_id, race_id, bet_type, combination, stake_yen, assumed_odds,
      hit_probability, expected_value_pct, settlement_status
    )
    SELECT ?, ?, ?, ?, ?, ?, ?, ?, 'pending'
    WHERE NOT EXISTS (
      SELECT 1 FROM rt_bets existing
      WHERE existing.prediction_id=?
        AND (existing.bet_type LIKE 'ライト｜%' OR existing.bet_type LIKE 'スタンダード｜%' OR existing.bet_type LIKE 'プレミアム｜%')
    )
  `).bind(
    row.predictionId,
    row.raceId,
    encodedBetType(first),
    first.combination,
    first.stakeYen,
    first.assumedOdds,
    first.hitProbability,
    first.expectedValuePct,
    row.predictionId
  ).run();
  if (Number(claim.meta?.changes ?? 0) === 0) return 0;

  if (rest.length > 0) {
    await db.batch(rest.map((bet) => db.prepare(`
      INSERT INTO rt_bets (
        prediction_id, race_id, bet_type, combination, stake_yen, assumed_odds,
        hit_probability, expected_value_pct, settlement_status
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
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
  return row.bets.length;
}

export async function ensureVenueDailyQuota(
  db: D1Database,
  modelVersion: string,
  raceDate: string,
  mode: VenueQuotaMode,
  minimumPerVenue = MINIMUM_SELECTED_RACES_PER_VENUE
): Promise<VenueQuotaResult> {
  const rows = await loadQuotaRaces(db, modelVersion, raceDate, mode);
  const venues = [...new Set(rows.map((row) => row.venue))];
  const venueResults: VenueQuotaVenueResult[] = [];
  let addedRaces = 0;
  let addedTickets = 0;

  for (const venue of venues) {
    const venueRows = rows.filter((row) => row.venue === venue);
    const selectedBefore = venueRows.filter((row) => row.betCount > 0).length;
    const targetRaces = Math.min(minimumPerVenue, venueRows.length);
    const needed = Math.max(0, targetRaces - selectedBefore);
    const candidates: RankedQuotaCandidate[] = [];

    if (needed > 0) {
      for (const row of venueRows.filter((item) => item.betCount === 0)) {
        const predictions = await loadPredictions(db, row.predictionId);
        const bets = buildVenueCoverageBets(predictions);
        const score = coverageRaceScore(predictions);
        if (bets.length === 0 || !Number.isFinite(score)) continue;
        candidates.push({ ...row, score, predictions, bets });
      }
      candidates.sort((a, b) => b.score - a.score || a.raceNo - b.raceNo);
    }

    let venueAdded = 0;
    for (const candidate of candidates.slice(0, needed)) {
      const inserted = await claimAndInsertBets(db, candidate);
      if (inserted === 0) continue;
      venueAdded += 1;
      addedRaces += 1;
      addedTickets += inserted;
      if (mode === "validation" || candidate.raceStatus === "finished") {
        await settleRaceWithCourses(db, candidate.raceId);
      }
    }

    venueResults.push({
      venue,
      availableRaces: venueRows.length,
      targetRaces,
      selectedBefore,
      addedRaces: venueAdded,
      selectedAfter: Math.min(targetRaces, selectedBefore + venueAdded)
    });
  }

  return {
    raceDate,
    modelVersion,
    mode,
    addedRaces,
    addedTickets,
    venues: venueResults
  };
}

export async function ensureValidationVenueQuotas(
  db: D1Database,
  configs: ReadonlyArray<{ raceDate: string; modelVersion: string }>
): Promise<VenueQuotaResult[]> {
  const results: VenueQuotaResult[] = [];
  for (const config of configs) {
    results.push(await ensureVenueDailyQuota(db, config.modelVersion, config.raceDate, "validation"));
  }
  return results;
}
