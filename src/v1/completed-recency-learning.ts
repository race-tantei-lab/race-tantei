import type { RaceRecord, RunnerRecord } from "./types";
import type { CompletedBetType } from "./completed-ticket-runtime";

export const COMPLETED_RECENCY_VERSION = "canonical-recency-v1";
export const COMPLETED_RECENCY_HISTORY_DAYS = 30;
export const COMPLETED_RECENCY_HALF_LIFE_DAYS = 7;
const RUNNER_FACTOR_MIN = 0.5;
const RUNNER_FACTOR_MAX = 2.0;
const BET_FACTOR_MIN = 0.7;
const BET_FACTOR_MAX = 1.35;
const BET_ROI_CAP = 8;
const ODDS_EDGES = [2,3,5,7,10,15,20,30,50,75,100,150,300,500,800,1200,2000] as const;

type RunnerHistoryRow = {
  raceId: string; raceDate: string; startTimeUtc: string; venue: string; surface: string | null;
  horseNo: number; horseName: string; jockey: string | null; trainer: string | null;
  finishPosition: number; marketProbability: number; fieldSize: number;
};

type BetHistoryRow = {
  raceId: string; raceDate: string; startTimeUtc: string; venue: string;
  betType: string; stakeYen: number; returnYen: number; assumedOdds: number;
};

type Signal = { weightedResidual: number; weight: number; samples: number; sameDaySamples: number };
type BetBucket = { weightedRoi: number; weight: number; samples: number; sameDaySamples: number };

export type CompletedRunnerRecencyDetail = {
  horseNo: number;
  factor: number;
  signals: { horse: number; jockey: number; trainer: number; sameVenueSurfaceDraw: number };
  samples: { horse: number; jockey: number; trainer: number; sameVenueSurfaceDraw: number };
  sameDaySamples: { horse: number; jockey: number; trainer: number; sameVenueSurfaceDraw: number };
};

export type CompletedRecencyAudit = {
  status: "applied" | "neutral_fallback";
  version: string;
  cutoffUtc: string;
  historyDays: number;
  halfLifeDays: number;
  dateMultipliers: { sameDay: number; previousDay: number; days2To7: number; days8To30: number };
  futureResultsAllowed: false;
  sameDayFinishedResultsAllowed: true;
  runnerHistoryRaces: number;
  sameDayFinishedRaces: number;
  previousDayFinishedRaces: number;
  last7DaysFinishedRaces: number;
  betHistoryRaces: number;
  sameDaySettledBetRaces: number;
  previousDaySettledBetRaces: number;
  last7DaysSettledBetRaces: number;
  runnerFactorRange: [number, number];
  betFactorRange: [number, number];
  error?: string;
};

export type CompletedRecencyLearning = {
  runnerFactors: number[];
  runnerDetails: CompletedRunnerRecencyDetail[];
  betBuckets: Map<string, BetBucket>;
  audit: CompletedRecencyAudit;
};

function clamp(value: number, low: number, high: number): number { return Math.max(low, Math.min(high, value)); }

function dateDiffDays(later: string, earlier: string): number {
  const a = Date.parse(`${later}T00:00:00Z`); const b = Date.parse(`${earlier}T00:00:00Z`);
  return Math.round((a - b) / 86_400_000);
}

export function completedRecencyWeight(eventTimeUtc: string, eventDate: string, cutoffUtc: string, targetDate: string): number {
  const eventMs = Date.parse(eventTimeUtc); const cutoffMs = Date.parse(cutoffUtc);
  if (!Number.isFinite(eventMs) || !Number.isFinite(cutoffMs) || eventMs >= cutoffMs) return 0;
  const ageDays = Math.max(0, (cutoffMs - eventMs) / 86_400_000);
  if (ageDays > COMPLETED_RECENCY_HISTORY_DAYS + 1) return 0;
  const dayDiff = dateDiffDays(targetDate, eventDate);
  if (dayDiff < 0) return 0;
  const multiplier = dayDiff === 0 ? 6 : dayDiff === 1 ? 4 : dayDiff <= 7 ? 2 : 1;
  return multiplier * Math.pow(0.5, ageDays / COMPLETED_RECENCY_HALF_LIFE_DAYS);
}

function oddsBin(value: number): number | null {
  if (!Number.isFinite(value) || value <= 1) return null;
  let index = 0; while (index < ODDS_EDGES.length && value >= ODDS_EDGES[index]) index += 1; return index;
}

function drawBucket(horseNo: number, field: number): number {
  const pct = (horseNo - 0.5) / Math.max(1, field); return pct < 1 / 3 ? 0 : pct < 2 / 3 ? 1 : 2;
}

function signalKey(kind: string, ...parts: Array<string | number>): string { return [kind, ...parts].join("\u0001"); }
function betKey(kind: string, ...parts: Array<string | number>): string { return [kind, ...parts].join("\u0001"); }

function addSignal(map: Map<string, Signal>, key: string, weight: number, residual: number, sameDay: boolean): void {
  const item = map.get(key) ?? { weightedResidual: 0, weight: 0, samples: 0, sameDaySamples: 0 };
  item.weightedResidual += weight * residual; item.weight += weight; item.samples += 1; item.sameDaySamples += sameDay ? 1 : 0; map.set(key, item);
}

function signal(map: Map<string, Signal>, key: string, priorMass: number): [number, number, number] {
  const item = map.get(key); if (!item) return [0, 0, 0]; return [item.weightedResidual / (item.weight + priorMass), item.samples, item.sameDaySamples];
}

function addBetBucket(map: Map<string, BetBucket>, key: string, weight: number, roi: number, sameDay: boolean): void {
  const item = map.get(key) ?? { weightedRoi: 0, weight: 0, samples: 0, sameDaySamples: 0 };
  item.weightedRoi += weight * roi; item.weight += weight; item.samples += 1; item.sameDaySamples += sameDay ? 1 : 0; map.set(key, item);
}

function posteriorBetFactor(map: Map<string, BetBucket>, key: string, priorMass: number): number | null {
  const item = map.get(key); if (!item) return null;
  const mean = (item.weightedRoi + priorMass) / (item.weight + priorMass);
  return clamp(Math.sqrt(Math.max(0.01, mean)), BET_FACTOR_MIN, BET_FACTOR_MAX);
}

function startDate(targetDate: string): string {
  const d = new Date(`${targetDate}T00:00:00Z`); d.setUTCDate(d.getUTCDate() - COMPLETED_RECENCY_HISTORY_DAYS); return d.toISOString().slice(0, 10);
}

async function loadRunnerRows(db: D1Database, race: RaceRecord, runners: RunnerRecord[], cutoffUtc: string): Promise<RunnerHistoryRow[]> {
  const horses = [...new Set(runners.map((row) => String(row.horseName || "").trim()).filter(Boolean))];
  const jockeys = [...new Set(runners.map((row) => String(row.jockey || "").trim()).filter(Boolean))];
  const trainers = [...new Set(runners.map((row) => String(row.trainer || "").trim()).filter(Boolean))];
  const result = await db.prepare(`
    WITH scored AS (
      SELECT r.race_id AS raceId,r.race_date AS raceDate,r.start_time_utc AS startTimeUtc,r.venue,r.surface,
             x.horse_no AS horseNo,x.horse_name AS horseName,x.jockey,x.trainer,
             CAST(y.finish_position AS INTEGER) AS finishPosition,
             (1.0 / CAST(x.win_odds AS REAL)) /
               SUM(1.0 / CAST(x.win_odds AS REAL)) OVER (PARTITION BY r.race_id) AS marketProbability,
             COUNT(*) OVER (PARTITION BY r.race_id) AS fieldSize
      FROM rt_races r
      JOIN rt_runners x ON x.race_id=r.race_id
      LEFT JOIN rt_results y ON y.race_id=x.race_id AND y.horse_no=x.horse_no
      WHERE r.race_date BETWEEN ? AND ?
        AND r.status='finished'
        AND r.start_time_utc IS NOT NULL
        AND datetime(r.start_time_utc) < datetime(?)
        AND COALESCE(x.runner_status,'active')='active'
        AND CAST(x.win_odds AS REAL)>1.0
    )
    SELECT * FROM scored
    WHERE finishPosition>0 AND (
      horseName IN (SELECT value FROM json_each(?))
      OR COALESCE(jockey,'') IN (SELECT value FROM json_each(?))
      OR COALESCE(trainer,'') IN (SELECT value FROM json_each(?))
      OR (raceDate=? AND venue=? AND COALESCE(surface,'')=?)
    )
    ORDER BY startTimeUtc,raceId,horseNo
  `).bind(startDate(race.raceDate), race.raceDate, cutoffUtc, JSON.stringify(horses), JSON.stringify(jockeys), JSON.stringify(trainers), race.raceDate, race.venue, String(race.surface || "")).all<RunnerHistoryRow>();
  return result.results ?? [];
}

async function loadBetRows(db: D1Database, race: RaceRecord, cutoffUtc: string): Promise<BetHistoryRow[]> {
  const result = await db.prepare(`
    SELECT b.race_id AS raceId,b.bet_type AS betType,b.stake_yen AS stakeYen,COALESCE(b.return_yen,0) AS returnYen,
           b.assumed_odds AS assumedOdds,r.race_date AS raceDate,r.start_time_utc AS startTimeUtc,r.venue
    FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
    WHERE r.race_date BETWEEN ? AND ? AND r.start_time_utc IS NOT NULL AND datetime(r.start_time_utc)<datetime(?)
      AND b.source_prediction_id=-2 AND b.course='ライト' AND b.settlement_status='settled'
    ORDER BY r.start_time_utc,b.race_id,b.id
  `).bind(startDate(race.raceDate), race.raceDate, cutoffUtc).all<BetHistoryRow>();
  return result.results ?? [];
}

export function buildCompletedRunnerRecency(rows: RunnerHistoryRow[], race: RaceRecord, runners: RunnerRecord[], cutoffUtc: string): { factors: number[]; details: CompletedRunnerRecencyDetail[]; audit: Pick<CompletedRecencyAudit,"runnerHistoryRaces"|"sameDayFinishedRaces"|"previousDayFinishedRaces"|"last7DaysFinishedRaces"> } {
  const stats = new Map<string, Signal>(); const used = new Set<string>(); const same = new Set<string>(); const previous = new Set<string>(); const last7 = new Set<string>();
  for (const row of rows) {
    const weight = completedRecencyWeight(row.startTimeUtc, row.raceDate, cutoffUtc, race.raceDate);
    const market = Number(row.marketProbability); const pos = Number(row.finishPosition); const field = Number(row.fieldSize);
    if (!(weight > 0) || !Number.isFinite(market) || market <= 0 || !Number.isFinite(pos) || pos <= 0 || !Number.isFinite(field) || field < 3) continue;
    const dayDiff = dateDiffDays(race.raceDate, row.raceDate); const residual = (pos === 1 ? 1 : 0) - market; const sameDay = dayDiff === 0;
    used.add(row.raceId); if (sameDay) same.add(row.raceId); if (dayDiff === 1) previous.add(row.raceId); if (dayDiff >= 0 && dayDiff <= 7) last7.add(row.raceId);
    const horse = String(row.horseName || "").trim(); const jockey = String(row.jockey || "").trim(); const trainer = String(row.trainer || "").trim();
    if (horse) addSignal(stats, signalKey("horse", horse), weight, residual, sameDay);
    if (jockey) addSignal(stats, signalKey("jockey", jockey), weight, residual, sameDay);
    if (trainer) addSignal(stats, signalKey("trainer", trainer), weight, residual, sameDay);
    addSignal(stats, signalKey("draw", row.venue, String(row.surface || ""), drawBucket(Number(row.horseNo), field)), weight, residual, sameDay);
  }
  const field = runners.length; const factors: number[] = []; const details: CompletedRunnerRecencyDetail[] = [];
  for (const runner of runners) {
    const [horse, horseN, horseSame] = signal(stats, signalKey("horse", String(runner.horseName || "").trim()), 2);
    const [jockey, jockeyN, jockeySame] = signal(stats, signalKey("jockey", String(runner.jockey || "").trim()), 10);
    const [trainer, trainerN, trainerSame] = signal(stats, signalKey("trainer", String(runner.trainer || "").trim()), 14);
    const [draw, drawN, drawSame] = signal(stats, signalKey("draw", race.venue, String(race.surface || ""), drawBucket(Number(runner.horseNo), field)), 10);
    const factor = clamp(Math.exp(0.9 * horse + 1.2 * jockey + 0.75 * trainer + draw), RUNNER_FACTOR_MIN, RUNNER_FACTOR_MAX);
    factors.push(factor); details.push({ horseNo: Number(runner.horseNo), factor, signals: { horse, jockey, trainer, sameVenueSurfaceDraw: draw }, samples: { horse: horseN, jockey: jockeyN, trainer: trainerN, sameVenueSurfaceDraw: drawN }, sameDaySamples: { horse: horseSame, jockey: jockeySame, trainer: trainerSame, sameVenueSurfaceDraw: drawSame } });
  }
  return { factors, details, audit: { runnerHistoryRaces: used.size, sameDayFinishedRaces: same.size, previousDayFinishedRaces: previous.size, last7DaysFinishedRaces: last7.size } };
}

export function buildCompletedBetRecency(rows: BetHistoryRow[], race: RaceRecord, cutoffUtc: string): { buckets: Map<string, BetBucket>; audit: Pick<CompletedRecencyAudit,"betHistoryRaces"|"sameDaySettledBetRaces"|"previousDaySettledBetRaces"|"last7DaysSettledBetRaces"> } {
  const buckets = new Map<string, BetBucket>(); const used = new Set<string>(); const same = new Set<string>(); const previous = new Set<string>(); const last7 = new Set<string>();
  for (const row of rows) {
    const stake = Number(row.stakeYen); const returned = Number(row.returnYen); const odds = Number(row.assumedOdds); const weight = completedRecencyWeight(row.startTimeUtc,row.raceDate,cutoffUtc,race.raceDate);
    if (!(stake > 0) || !Number.isFinite(returned) || !(weight > 0)) continue;
    const dayDiff = dateDiffDays(race.raceDate,row.raceDate); const roi = clamp(returned / stake, 0, BET_ROI_CAP); const obin = oddsBin(odds); const sameDay = dayDiff === 0;
    used.add(row.raceId); if (sameDay) same.add(row.raceId); if (dayDiff === 1) previous.add(row.raceId); if (dayDiff >= 0 && dayDiff <= 7) last7.add(row.raceId);
    addBetBucket(buckets, betKey("bt",row.betType),weight,roi,sameDay); addBetBucket(buckets,betKey("btv",row.betType,row.venue),weight,roi,sameDay);
    if (obin != null) { addBetBucket(buckets,betKey("bto",row.betType,obin),weight,roi,sameDay); addBetBucket(buckets,betKey("btvo",row.betType,row.venue,obin),weight,roi,sameDay); }
  }
  return { buckets, audit: { betHistoryRaces: used.size, sameDaySettledBetRaces: same.size, previousDaySettledBetRaces: previous.size, last7DaysSettledBetRaces: last7.size } };
}

export function completedRecencyBetFactor(learning: Pick<CompletedRecencyLearning,"betBuckets">, betType: CompletedBetType, venue: string, odds: number): number {
  const obin = oddsBin(odds); const parts: number[] = [];
  const specs: Array<[string,number]> = [[betKey("bt",betType),20],[betKey("btv",betType,venue),12]];
  if (obin != null) specs.push([betKey("bto",betType,obin),12],[betKey("btvo",betType,venue,obin),8]);
  for (const [key,prior] of specs) { const factor = posteriorBetFactor(learning.betBuckets,key,prior); if (factor != null) parts.push(factor); }
  if (!parts.length) return 1; return clamp(Math.exp(parts.reduce((sum,value)=>sum+Math.log(value),0)/parts.length),BET_FACTOR_MIN,BET_FACTOR_MAX);
}

function baseAudit(cutoffUtc: string): CompletedRecencyAudit {
  return { status:"applied", version:COMPLETED_RECENCY_VERSION, cutoffUtc, historyDays:COMPLETED_RECENCY_HISTORY_DAYS, halfLifeDays:COMPLETED_RECENCY_HALF_LIFE_DAYS,
    dateMultipliers:{sameDay:6,previousDay:4,days2To7:2,days8To30:1}, futureResultsAllowed:false, sameDayFinishedResultsAllowed:true,
    runnerHistoryRaces:0,sameDayFinishedRaces:0,previousDayFinishedRaces:0,last7DaysFinishedRaces:0,betHistoryRaces:0,sameDaySettledBetRaces:0,previousDaySettledBetRaces:0,last7DaysSettledBetRaces:0,
    runnerFactorRange:[RUNNER_FACTOR_MIN,RUNNER_FACTOR_MAX],betFactorRange:[BET_FACTOR_MIN,BET_FACTOR_MAX] };
}

export function neutralCompletedRecencyLearning(runners: RunnerRecord[], cutoffUtc: string, error?: string): CompletedRecencyLearning {
  const audit = baseAudit(cutoffUtc); audit.status="neutral_fallback"; if (error) audit.error=error;
  return { runnerFactors:runners.map(()=>1),runnerDetails:runners.map((runner)=>({horseNo:Number(runner.horseNo),factor:1,signals:{horse:0,jockey:0,trainer:0,sameVenueSurfaceDraw:0},samples:{horse:0,jockey:0,trainer:0,sameVenueSurfaceDraw:0},sameDaySamples:{horse:0,jockey:0,trainer:0,sameVenueSurfaceDraw:0}})),betBuckets:new Map(),audit };
}

export async function loadCompletedRecencyLearning(db: D1Database, race: RaceRecord, runners: RunnerRecord[], cutoffUtc: string): Promise<CompletedRecencyLearning> {
  const [runnerRows,betRows] = await Promise.all([loadRunnerRows(db,race,runners,cutoffUtc),loadBetRows(db,race,cutoffUtc)]);
  const runner = buildCompletedRunnerRecency(runnerRows,race,runners,cutoffUtc); const bet = buildCompletedBetRecency(betRows,race,cutoffUtc); const audit = baseAudit(cutoffUtc);
  Object.assign(audit,runner.audit,bet.audit); return { runnerFactors:runner.factors,runnerDetails:runner.details,betBuckets:bet.buckets,audit };
}
