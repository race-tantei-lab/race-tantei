export interface Env {
  DB: D1Database;
  ENVIRONMENT: string;
  MODEL_VERSION: string;
  JRA_HOME_URL: string;
  JRA_SEED_ENTRY_URLS: string;
  MIN_EXPECTED_VALUE: string;
  MAX_RACE_BUDGET_YEN: string;
  SYNC_BATCH_SIZE: string;
  ADMIN_TOKEN?: string;
}

export interface RaceRecord {
  raceId: string;
  raceDate: string;
  venue: string;
  meetingNo: number;
  meetingDay: number;
  raceNo: number;
  raceName: string;
  conditions: string | null;
  surface: string | null;
  distanceM: number | null;
  direction: string | null;
  startTimeJst: string | null;
  startTimeUtc: string | null;
  weather: string | null;
  trackCondition: string | null;
  entryUrl: string;
  resultUrl: string;
  status: "scheduled" | "finished" | "cancelled";
}

export interface RunnerRecord {
  horseNo: number;
  frameNo: number | null;
  horseName: string;
  sexAge: string | null;
  coatColor: string | null;
  horseWeight: number | null;
  weightChange: number | null;
  jockey: string | null;
  assignedWeight: number | null;
  trainer: string | null;
  stable: string | null;
  winOdds: number | null;
  popularity: number | null;
  runnerStatus: "active" | "excluded" | "scratched";
}

export interface ResultRecord {
  horseNo: number;
  finishPosition: number | null;
  resultStatus: string;
  timeText: string | null;
  marginText: string | null;
  final3f: number | null;
}

export interface PayoutRecord {
  betType: string;
  combination: string;
  payoutYen: number;
  popularity: number | null;
}

export interface RaceBundle {
  race: RaceRecord;
  runners: RunnerRecord[];
  results: ResultRecord[];
  payouts: PayoutRecord[];
  refundHorseNos: number[];
}

export interface RunnerHistoryStats {
  horseNo: number;
  horseStarts: number;
  horseWins: number;
  horsePlaces: number;
  jockeyStarts: number;
  jockeyWins: number;
  trainerStarts: number;
  trainerWins: number;
  courseStarts: number;
  courseWins: number;
}

export interface RunnerPrediction {
  horseNo: number;
  horseName: string;
  winProbability: number;
  placeProbability: number;
  fairOdds: number;
  currentOdds: number | null;
  expectedValuePct: number | null;
  predictedOrder: number;
  explanation: string;
  popularity?: number | null;
}

export type BetType = "単勝" | "ワイド" | "馬連" | "馬単" | "3連複" | "3連単";
export type BudgetCourse = "ライト" | "スタンダード" | "プレミアム";

export interface BetRecommendation {
  course: BudgetCourse;
  betType: BetType;
  combination: string;
  stakeYen: number;
  assumedOdds: number;
  hitProbability: number;
  expectedValuePct: number;
}

export interface PredictionOutput {
  modelVersion: string;
  runners: RunnerPrediction[];
  bets: BetRecommendation[];
  generatedAt: string;
}

export interface DashboardMetrics {
  raceCount: number;
  predictionCount: number;
  settledBetCount: number;
  totalStakeYen: number;
  totalReturnYen: number;
  profitYen: number;
  roiPct: number | null;
  hitRatePct: number | null;
}
