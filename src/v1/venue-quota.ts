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
  settledCount: number;
  stakeYen: number;
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
  replacedRaces: number;
  removedRaces: number;
  selectedAfter: number;
}

export interface VenueQuotaResult {
  raceDate: string;
  modelVersion: string;
  mode: VenueQuotaMode;
  addedRaces: number;
  addedTickets: number;
  replacedRaces: number;
  removedRaces: number;
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
    : "r.status IN ('scheduled','finished')";
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId, r.race_date AS raceDate, r.venue,
      r.race_no AS raceNo, r.status AS raceStatus,
      p.id AS predictionId, p.status AS predictionStatus,
      COALESCE((
        SELECT COUNT(*) FROM rt_bets b
        WHERE b.prediction_id=p.id
          AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      ),0) AS betCount,
      COALESCE((
        SELECT COUNT(*) FROM rt_bets b
        WHERE b.prediction_id=p.id AND b.settlement_status='settled'
          AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      ),0) AS settledCount,
      COALESCE((
        SELECT SUM(b.stake_yen) FROM rt_bets b
        WHERE b.prediction_id=p.id
          AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
      ),0) AS stakeYen
    FROM rt_races r
    JOIN rt_predictions p ON p.race_id=r.race_id AND p.model_version=?
    WHERE r.race_date=? AND ${statusCondition}
    ORDER BY r.venue, r.race_no
  `).bind(modelVersion, raceDate).all<QuotaRaceRow>();
  return rows.results.map((row) => ({
    ...row,
    raceNo: toNumber(row.raceNo),
    predictionId: toNumber(row.predictionId),
    betCount: toNumber(row.betCount),
    settledCount: toNumber(row.settledCount),
    stakeYen: toNumber(row.stakeYen)
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

async function deleteCourseBets(db: D1Database, predictionId: number): Promise<number> {
  const result = await db.prepare(`
    DELETE FROM rt_bets
    WHERE prediction_id=?
      AND (bet_type LIKE 'ライト｜%' OR bet_type LIKE 'スタンダード｜%' OR bet_type LIKE 'プレミアム｜%')
  `).bind(predictionId).run();
  return Number(result.meta?.changes ?? 0);
}

async function replaceCourseBets(
  db: D1Database,
  row: RankedQuotaCandidate
): Promise<number> {
  await deleteCourseBets(db, row.predictionId);
  if (row.bets.length === 0) return 0;
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
  return row.bets.length;
}

function desiredStake(row: RankedQuotaCandidate): number {
  return row.bets.reduce((sum, bet) => sum + bet.stakeYen, 0);
}

function needsReplacement(row: RankedQuotaCandidate, mode: VenueQuotaMode): boolean {
  const desired = desiredStake(row);
  if (row.betCount !== row.bets.length || row.stakeYen !== desired) return true;
  if (mode === "validation" && row.settledCount !== row.bets.length) return true;
  if (mode === "live" && row.predictionStatus !== "locked" && row.raceStatus !== "finished") return true;
  return false;
}

async function rankRows(db: D1Database, rows: QuotaRaceRow[]): Promise<RankedQuotaCandidate[]> {
  const candidates: RankedQuotaCandidate[] = [];
  for (const row of rows) {
    const predictions = await loadPredictions(db, row.predictionId);
    const bets = buildVenueCoverageBets(predictions);
    const score = coverageRaceScore(predictions);
    if (bets.length === 0 || !Number.isFinite(score)) continue;
    candidates.push({ ...row, score, predictions, bets });
  }
  return candidates.sort((a, b) => b.score - a.score || a.raceNo - b.raceNo);
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
  let replacedRaces = 0;
  let removedRaces = 0;

  for (const venue of venues) {
    const venueRows = rows.filter((row) => row.venue === venue);
    const selectedBefore = venueRows.filter((row) => row.betCount > 0).length;
    const targetRaces = Math.min(minimumPerVenue, venueRows.length);
    const ranked = await rankRows(db, venueRows);

    const fixedLive = mode === "live"
      ? ranked.filter((row) => row.betCount > 0 && (row.predictionStatus === "locked" || row.raceStatus === "finished"))
      : [];
    const fixedIds = new Set(fixedLive.map((row) => row.raceId));
    const remainingSlots = Math.max(0, targetRaces - fixedLive.length);
    const chosen = [
      ...fixedLive,
      ...ranked.filter((row) => !fixedIds.has(row.raceId)).slice(0, remainingSlots)
    ];
    const selectedIds = new Set(chosen.map((row) => row.raceId));

    let venueAdded = 0;
    let venueReplaced = 0;
    let venueRemoved = 0;

    for (const row of venueRows) {
      if (selectedIds.has(row.raceId)) continue;
      const protectedLive = mode === "live" && (row.predictionStatus === "locked" || row.raceStatus === "finished");
      if (protectedLive || row.betCount === 0) continue;
      const deleted = await deleteCourseBets(db, row.predictionId);
      if (deleted > 0) {
        venueRemoved += 1;
        removedRaces += 1;
      }
    }

    for (const candidate of chosen) {
      const wasSelected = candidate.betCount > 0;
      if (!needsReplacement(candidate, mode)) continue;
      const inserted = await replaceCourseBets(db, candidate);
      if (inserted === 0) continue;
      addedTickets += inserted;
      if (wasSelected) {
        venueReplaced += 1;
        replacedRaces += 1;
      } else {
        venueAdded += 1;
        addedRaces += 1;
      }
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
      replacedRaces: venueReplaced,
      removedRaces: venueRemoved,
      selectedAfter: selectedIds.size
    });
  }

  return {
    raceDate,
    modelVersion,
    mode,
    addedRaces,
    addedTickets,
    replacedRaces,
    removedRaces,
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
