import type { RaceRecord, RunnerRecord } from "./types";

export const COMPLETED_MODEL_VERSION = "ten-year-completed-model";
export const COMPLETED_MODEL_SHA256 = "63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5";

const ML_VENUES: Record<string, number> = { "札幌": 1, "函館": 2, "福島": 3, "新潟": 4, "東京": 5, "中山": 6, "中京": 7, "京都": 8, "阪神": 9, "小倉": 10 };
const SURF: Record<string, number> = { "芝": 0, "ダート": 1, "障害": 2 };
const WEATHER: Record<string, number> = { "晴": 0, "曇": 1, "雨": 2, "小雨": 3, "雪": 4, "小雪": 5 };
const TRACK: Record<string, number> = { "良": 0, "稍重": 1, "重": 2, "不良": 3 };
const SEX: Record<string, number> = { "牡": 0, "牝": 1, "セ": 2, "騸": 2 };
const PRIOR_WIN = 0.08;
const PRIOR_TOP3 = 0.24;
const SMOOTH = 12;
const SEP = "\u0001";

export const COMPLETED_FEATURE_NAMES = [
  "horseNoRaw", "venue", "raceNo", "surface", "distanceM", "direction", "fieldSize", "monthSin", "monthCos", "raceClass", "weather", "trackCondition",
  "horseNo", "frameNo", "drawPct", "sex", "age", "horseWeight", "weightChange", "assignedWeight",
  "horseStarts", "horseWinRate", "horseTop3Rate", "daysSinceLast", "debutFlag", "lastFinishPct", "avg3FinishPct", "avg5FinishPct", "lastTop3", "top3Last3", "lastFinal3fPct", "avg3Final3fPct", "avg5Final3fPct", "lastSpeedMps", "avg3SpeedMps", "avg5SpeedMps",
  "sameSurfaceStarts", "sameSurfaceWinRate", "sameSurfaceTop3Rate", "sameDistStarts", "sameDistWinRate", "sameDistTop3Rate", "sameVenueStarts", "sameVenueWinRate", "sameVenueTop3Rate", "distanceChange", "surfaceSwitch",
  "jockeyStarts", "jockeyWinRate", "jockeyTop3Rate", "trainerStarts", "trainerWinRate", "trainerTop3Rate", "pairStarts", "pairWinRate", "pairTop3Rate",
] as const;

export type CompletedFeatureName = (typeof COMPLETED_FEATURE_NAMES)[number];
type Stat = [number, number, number];

export interface CompletedHistoryRow {
  date: string;
  finishPct: number;
  final3fPct: number;
  speedMps: number;
  top3: number;
  distance: number;
  surface: string;
}

export interface CompletedFeatureState {
  generation: string;
  throughDate: string;
  horseHist: Map<string, CompletedHistoryRow[]>;
  horseTotal: Map<string, Stat>;
  horseSurface: Map<string, Stat>;
  horseDist: Map<string, Stat>;
  horseVenue: Map<string, Stat>;
  jockey: Map<string, Stat>;
  trainer: Map<string, Stat>;
  pair: Map<string, Stat>;
}

export interface SerializedCompletedFeatureState {
  generation: string;
  throughDate: string;
  horseHist: Record<string, CompletedHistoryRow[]>;
  horseTotal: Record<string, Stat>;
  horseSurface: Array<[string, string, number, number, number]>;
  horseDist: Array<[string, number, number, number, number]>;
  horseVenue: Array<[string, string, number, number, number]>;
  jockey: Record<string, Stat>;
  trainer: Record<string, Stat>;
  pair: Array<[string, string, number, number, number]>;
}

function statKey(a: string, b: string | number): string {
  return `${a}${SEP}${b}`;
}

function finiteNumber(value: unknown, fallback = 0): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function intNumber(value: unknown, fallback = 0): number {
  return Math.trunc(finiteNumber(value, fallback));
}

function rate(stat: Stat | undefined, kind: "win" | "top3"): number {
  if (!stat) return kind === "win" ? PRIOR_WIN : PRIOR_TOP3;
  const [n, w, t] = stat;
  const prior = kind === "win" ? PRIOR_WIN : PRIOR_TOP3;
  const hits = kind === "win" ? w : t;
  return (hits + SMOOTH * prior) / (n + SMOOTH);
}

function avg(history: CompletedHistoryRow[], key: keyof Pick<CompletedHistoryRow, "finishPct" | "final3fPct" | "speedMps">, n: number): number {
  const rows = history.slice(-n);
  const values = rows.map((row) => row[key]).filter(Number.isFinite);
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function mlDistBin(distance: number): number {
  if (distance < 1200) return 0;
  if (distance < 1600) return 1;
  if (distance < 2000) return 2;
  if (distance < 2400) return 3;
  if (distance < 3000) return 4;
  return 5;
}

function mlClassCode(name: string | null | undefined, conditions: string | null | undefined): number {
  const text = `${name ?? ""} ${conditions ?? ""}`
    .replaceAll("500万下", "1勝クラス")
    .replaceAll("1000万下", "2勝クラス")
    .replaceAll("1600万下", "3勝クラス");
  if (text.includes("新馬")) return 0;
  if (text.includes("未勝利")) return 1;
  if (text.includes("1勝クラス")) return 2;
  if (text.includes("2勝クラス")) return 3;
  if (text.includes("3勝クラス")) return 4;
  if (text.includes("G1") || text.includes("Ｇ１") || text.includes("ＧⅠ")) return 8;
  if (text.includes("G2") || text.includes("Ｇ２") || text.includes("ＧⅡ")) return 7;
  if (text.includes("G3") || text.includes("Ｇ３") || text.includes("ＧⅢ")) return 6;
  if (text.includes("オープン") || text.toUpperCase().includes("OPEN")) return 5;
  return 5;
}

function parseSexAge(value: string | null | undefined): [number, number] {
  const text = String(value ?? "").trim();
  const sex = SEX[text.slice(0, 1)] ?? 3;
  const match = text.match(/(\d+)/);
  return [sex, match ? Number.parseInt(match[1], 10) : 0];
}

function dateDiffDays(later: string, earlier: string): number {
  const a = Date.parse(`${later}T00:00:00Z`);
  const b = Date.parse(`${earlier}T00:00:00Z`);
  return Math.round((a - b) / 86_400_000);
}

function parseTimeSeconds(value: unknown): number | null {
  const text = String(value ?? "").trim();
  if (!text) return null;
  if (text.includes(":")) {
    const [minutes, seconds] = text.split(":", 2);
    const parsed = Number(minutes) * 60 + Number(seconds);
    return Number.isFinite(parsed) ? parsed : null;
  }
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}

function horseKey(raceId: string, runner: Pick<RunnerRecord, "horseName" | "horseNo">): string {
  const name = String(runner.horseName ?? "").trim();
  return name || `__${raceId}:${runner.horseNo}`;
}

export function hydrateCompletedFeatureState(payload: SerializedCompletedFeatureState): CompletedFeatureState {
  const state: CompletedFeatureState = {
    generation: payload.generation,
    throughDate: payload.throughDate,
    horseHist: new Map(), horseTotal: new Map(), horseSurface: new Map(), horseDist: new Map(), horseVenue: new Map(), jockey: new Map(), trainer: new Map(), pair: new Map(),
  };
  for (const [key, rows] of Object.entries(payload.horseHist)) state.horseHist.set(key, rows.slice(-5).map((row) => ({ ...row })));
  for (const [key, value] of Object.entries(payload.horseTotal)) state.horseTotal.set(key, [...value] as Stat);
  for (const [horse, surface, n, w, t] of payload.horseSurface) state.horseSurface.set(statKey(horse, surface), [n, w, t]);
  for (const [horse, dist, n, w, t] of payload.horseDist) state.horseDist.set(statKey(horse, dist), [n, w, t]);
  for (const [horse, venue, n, w, t] of payload.horseVenue) state.horseVenue.set(statKey(horse, venue), [n, w, t]);
  for (const [key, value] of Object.entries(payload.jockey)) state.jockey.set(key, [...value] as Stat);
  for (const [key, value] of Object.entries(payload.trainer)) state.trainer.set(key, [...value] as Stat);
  for (const [horse, jockey, n, w, t] of payload.pair) state.pair.set(statKey(horse, jockey), [n, w, t]);
  return state;
}

function increment(map: Map<string, Stat>, key: string, win: number, top3: number): void {
  const stat = map.get(key) ?? [0, 0, 0];
  stat[0] += 1; stat[1] += win; stat[2] += top3;
  map.set(key, stat);
}

interface DeltaRow {
  raceId: string;
  raceDate: string;
  venue: string;
  surface: string | null;
  distanceM: number | null;
  horseNo: number;
  horseName: string;
  jockey: string | null;
  trainer: string | null;
  runnerStatus: string | null;
  finishPosition: number | null;
  timeText: string | null;
  final3f: number | null;
}

export function advanceRelevantCompletedFeatureState(
  state: CompletedFeatureState,
  rows: DeltaRow[],
  relevantHorses: Set<string>,
  relevantJockeys: Set<string>,
  relevantTrainers: Set<string>,
): void {
  const byRace = new Map<string, DeltaRow[]>();
  for (const row of rows) {
    const bucket = byRace.get(row.raceId) ?? [];
    bucket.push(row); byRace.set(row.raceId, bucket);
  }
  const races = [...byRace.values()].sort((a, b) => `${a[0]?.raceDate ?? ""}:${a[0]?.raceId ?? ""}`.localeCompare(`${b[0]?.raceDate ?? ""}:${b[0]?.raceId ?? ""}`));
  for (const raceRows of races) {
    if (!raceRows.length) continue;
    const first = raceRows[0];
    const active = raceRows.filter((row) => (row.runnerStatus || "active") === "active");
    const field = active.length;
    if (field < 2) continue;
    const valid = active
      .map((row) => ({ row, pos: row.finishPosition == null ? null : intNumber(row.finishPosition), f3: row.final3f == null ? null : finiteNumber(row.final3f, Number.NaN) }))
      .filter((item) => item.pos != null && item.pos > 0);
    const rankedF3 = valid.filter((item) => item.f3 != null && Number.isFinite(item.f3)).sort((a, b) => (a.f3 as number) - (b.f3 as number));
    const f3Rank = new Map<number, number>();
    rankedF3.forEach((item, index) => f3Rank.set(item.row.horseNo, index));
    const nf = rankedF3.length;
    const distance = intNumber(first.distanceM);
    const surface = String(first.surface || "障害");
    const distBin = mlDistBin(distance);
    const venue = String(first.venue || "");

    for (const item of valid) {
      const row = item.row;
      const pos = item.pos as number;
      const name = String(row.horseName || `__${row.raceId}:${row.horseNo}`);
      const jockey = String(row.jockey || "");
      const trainer = String(row.trainer || "");
      const win = pos === 1 ? 1 : 0;
      const top3 = pos <= 3 ? 1 : 0;
      if (relevantHorses.has(name)) {
        const finishPct = Math.max(0, 1 - (pos - 1) / Math.max(1, field - 1));
        const rank = f3Rank.get(row.horseNo);
        const final3fPct = rank == null ? 0.5 : 1 - rank / Math.max(1, nf - 1);
        const seconds = parseTimeSeconds(row.timeText);
        const speedMps = seconds && seconds > 0 && distance > 0 ? distance / seconds : 0;
        const history = state.horseHist.get(name) ?? [];
        history.push({ date: row.raceDate, finishPct, final3fPct, speedMps, top3, distance, surface });
        state.horseHist.set(name, history.slice(-5));
        increment(state.horseTotal, name, win, top3);
        increment(state.horseSurface, statKey(name, surface), win, top3);
        increment(state.horseDist, statKey(name, distBin), win, top3);
        increment(state.horseVenue, statKey(name, venue), win, top3);
      }
      if (relevantJockeys.has(jockey)) increment(state.jockey, jockey, win, top3);
      if (relevantTrainers.has(trainer)) increment(state.trainer, trainer, win, top3);
      if (relevantHorses.has(name) && relevantJockeys.has(jockey)) increment(state.pair, statKey(name, jockey), win, top3);
    }
    if (first.raceDate > state.throughDate) state.throughDate = first.raceDate;
  }
}

export function completedFeatureRecord(state: CompletedFeatureState, race: RaceRecord, runner: RunnerRecord, field: number): Record<CompletedFeatureName, number> {
  const date = race.raceDate;
  const distance = intNumber(race.distanceM);
  const surface = String(race.surface || "障害");
  const distBin = mlDistBin(distance);
  const venue = String(race.venue || "");
  const month = Number.parseInt(date.slice(5, 7), 10);
  const hno = intNumber(runner.horseNo);
  const name = horseKey(race.raceId, runner);
  const history = state.horseHist.get(name) ?? [];
  const ht = state.horseTotal.get(name);
  const ss = state.horseSurface.get(statKey(name, surface));
  const ds = state.horseDist.get(statKey(name, distBin));
  const vs = state.horseVenue.get(statKey(name, venue));
  const jockey = String(runner.jockey || "");
  const trainer = String(runner.trainer || "");
  const js = state.jockey.get(jockey);
  const ts = state.trainer.get(trainer);
  const ps = state.pair.get(statKey(name, jockey));
  const [sex, age] = parseSexAge(runner.sexAge);
  const last = history.length ? history[history.length - 1] : undefined;
  const days = last ? dateDiffDays(date, last.date) : 999;
  const lastDistance = last?.distance ?? distance;
  const lastSurface = last?.surface ?? surface;
  const direction = String(race.direction || "");

  const out: Record<CompletedFeatureName, number> = {
    horseNoRaw: hno, venue: ML_VENUES[venue] ?? 0, raceNo: intNumber(race.raceNo), surface: SURF[surface] ?? 2, distanceM: distance,
    direction: direction.startsWith("右") ? 1 : direction.startsWith("左") ? 2 : 0, fieldSize: field,
    monthSin: Math.sin(2 * Math.PI * month / 12), monthCos: Math.cos(2 * Math.PI * month / 12), raceClass: mlClassCode(race.raceName, race.conditions),
    weather: WEATHER[String(race.weather || "")] ?? 6, trackCondition: TRACK[String(race.trackCondition || "")] ?? 4,
    horseNo: hno, frameNo: intNumber(runner.frameNo), drawPct: hno / Math.max(1, field), sex, age,
    horseWeight: finiteNumber(runner.horseWeight), weightChange: finiteNumber(runner.weightChange), assignedWeight: finiteNumber(runner.assignedWeight),
    horseStarts: ht?.[0] ?? 0, horseWinRate: rate(ht, "win"), horseTop3Rate: rate(ht, "top3"), daysSinceLast: Math.min(999, days), debutFlag: history.length ? 0 : 1,
    lastFinishPct: last?.finishPct ?? 0, avg3FinishPct: avg(history, "finishPct", 3), avg5FinishPct: avg(history, "finishPct", 5), lastTop3: last?.top3 ?? 0,
    top3Last3: history.slice(-3).reduce((sum, row) => sum + row.top3, 0), lastFinal3fPct: last?.final3fPct ?? 0, avg3Final3fPct: avg(history, "final3fPct", 3), avg5Final3fPct: avg(history, "final3fPct", 5),
    lastSpeedMps: last?.speedMps ?? 0, avg3SpeedMps: avg(history, "speedMps", 3), avg5SpeedMps: avg(history, "speedMps", 5),
    sameSurfaceStarts: ss?.[0] ?? 0, sameSurfaceWinRate: rate(ss, "win"), sameSurfaceTop3Rate: rate(ss, "top3"),
    sameDistStarts: ds?.[0] ?? 0, sameDistWinRate: rate(ds, "win"), sameDistTop3Rate: rate(ds, "top3"),
    sameVenueStarts: vs?.[0] ?? 0, sameVenueWinRate: rate(vs, "win"), sameVenueTop3Rate: rate(vs, "top3"),
    distanceChange: Math.abs(distance - lastDistance), surfaceSwitch: lastSurface !== surface ? 1 : 0,
    jockeyStarts: js?.[0] ?? 0, jockeyWinRate: rate(js, "win"), jockeyTop3Rate: rate(js, "top3"),
    trainerStarts: ts?.[0] ?? 0, trainerWinRate: rate(ts, "win"), trainerTop3Rate: rate(ts, "top3"),
    pairStarts: ps?.[0] ?? 0, pairWinRate: rate(ps, "win"), pairTop3Rate: rate(ps, "top3"),
  };
  for (const name of COMPLETED_FEATURE_NAMES) {
    if (!Number.isFinite(out[name])) throw new Error(`completed feature ${name} is non-finite for ${race.raceId} horse ${hno}`);
  }
  return out;
}

export function completedFeatureVector(state: CompletedFeatureState, race: RaceRecord, runner: RunnerRecord, field: number): number[] {
  const record = completedFeatureRecord(state, race, runner, field);
  return COMPLETED_FEATURE_NAMES.map((name) => record[name]);
}

function resultsOf<T>(result: D1Result<unknown>): T[] {
  return (result.results ?? []) as T[];
}

export async function loadCompletedFeatureStateForRace(db: D1Database, race: RaceRecord, runners: RunnerRecord[], cutoffUtc?: string): Promise<CompletedFeatureState> {
  const metadataRows = await db.prepare("SELECT key,value FROM rt_ml_feature_meta").all<{ key: string; value: string }>();
  const metadata = new Map((metadataRows.results ?? []).map((row) => [row.key, row.value]));
  if (metadata.get("ready") !== "1") throw new Error("completed feature state is not ready");
  if (metadata.get("modelVersion") !== COMPLETED_MODEL_VERSION || metadata.get("modelSha256") !== COMPLETED_MODEL_SHA256) {
    throw new Error("completed feature state model identity mismatch");
  }
  const generation = metadata.get("currentGeneration") || "";
  const throughDate = metadata.get("throughDate") || "";
  if (!generation || !/^\d{4}-\d{2}-\d{2}$/.test(throughDate)) throw new Error("completed feature state metadata is invalid");
  if (throughDate >= race.raceDate) throw new Error(`completed feature state throughDate ${throughDate} must precede target ${race.raceDate}`);

  const active = runners.filter((runner) => (runner.runnerStatus || "active") === "active");
  const horses = [...new Set(active.map((runner) => horseKey(race.raceId, runner)))];
  const jockeys = [...new Set(active.map((runner) => String(runner.jockey || "")))];
  const trainers = [...new Set(active.map((runner) => String(runner.trainer || "")))];
  const horseJson = JSON.stringify(horses);
  const jockeyJson = JSON.stringify(jockeys);
  const trainerJson = JSON.stringify(trainers);

  const base = await db.batch([
    db.prepare("SELECT horse_name AS horseName,seq,race_date AS date,finish_pct AS finishPct,final3f_pct AS final3fPct,speed_mps AS speedMps,top3,distance_m AS distance,surface FROM rt_ml_horse_hist WHERE generation=? AND horse_name IN (SELECT value FROM json_each(?)) ORDER BY horse_name,seq").bind(generation, horseJson),
    db.prepare("SELECT horse_name AS horseName,n,w,t FROM rt_ml_horse_total WHERE generation=? AND horse_name IN (SELECT value FROM json_each(?))").bind(generation, horseJson),
    db.prepare("SELECT horse_name AS horseName,surface,n,w,t FROM rt_ml_horse_surface WHERE generation=? AND horse_name IN (SELECT value FROM json_each(?))").bind(generation, horseJson),
    db.prepare("SELECT horse_name AS horseName,dist_bin AS distBin,n,w,t FROM rt_ml_horse_dist WHERE generation=? AND horse_name IN (SELECT value FROM json_each(?))").bind(generation, horseJson),
    db.prepare("SELECT horse_name AS horseName,venue,n,w,t FROM rt_ml_horse_venue WHERE generation=? AND horse_name IN (SELECT value FROM json_each(?))").bind(generation, horseJson),
    db.prepare("SELECT name,n,w,t FROM rt_ml_jockey WHERE generation=? AND name IN (SELECT value FROM json_each(?))").bind(generation, jockeyJson),
    db.prepare("SELECT name,n,w,t FROM rt_ml_trainer WHERE generation=? AND name IN (SELECT value FROM json_each(?))").bind(generation, trainerJson),
    db.prepare("SELECT horse_name AS horseName,jockey,n,w,t FROM rt_ml_pair WHERE generation=? AND horse_name IN (SELECT value FROM json_each(?)) AND jockey IN (SELECT value FROM json_each(?))").bind(generation, horseJson, jockeyJson),
  ]);

  const payload: SerializedCompletedFeatureState = { generation, throughDate, horseHist: {}, horseTotal: {}, horseSurface: [], horseDist: [], horseVenue: [], jockey: {}, trainer: {}, pair: [] };
  for (const row of resultsOf<{ horseName: string; seq: number; date: string; finishPct: number; final3fPct: number; speedMps: number; top3: number; distance: number; surface: string }>(base[0])) {
    (payload.horseHist[row.horseName] ??= []).push({ date: row.date, finishPct: row.finishPct, final3fPct: row.final3fPct, speedMps: row.speedMps, top3: row.top3, distance: row.distance, surface: row.surface });
  }
  for (const row of resultsOf<{ horseName: string; n: number; w: number; t: number }>(base[1])) payload.horseTotal[row.horseName] = [row.n, row.w, row.t];
  for (const row of resultsOf<{ horseName: string; surface: string; n: number; w: number; t: number }>(base[2])) payload.horseSurface.push([row.horseName, row.surface, row.n, row.w, row.t]);
  for (const row of resultsOf<{ horseName: string; distBin: number; n: number; w: number; t: number }>(base[3])) payload.horseDist.push([row.horseName, row.distBin, row.n, row.w, row.t]);
  for (const row of resultsOf<{ horseName: string; venue: string; n: number; w: number; t: number }>(base[4])) payload.horseVenue.push([row.horseName, row.venue, row.n, row.w, row.t]);
  for (const row of resultsOf<{ name: string; n: number; w: number; t: number }>(base[5])) payload.jockey[row.name] = [row.n, row.w, row.t];
  for (const row of resultsOf<{ name: string; n: number; w: number; t: number }>(base[6])) payload.trainer[row.name] = [row.n, row.w, row.t];
  for (const row of resultsOf<{ horseName: string; jockey: string; n: number; w: number; t: number }>(base[7])) payload.pair.push([row.horseName, row.jockey, row.n, row.w, row.t]);

  const state = hydrateCompletedFeatureState(payload);
  if (throughDate < race.raceDate) {
    const effectiveCutoff = cutoffUtc ?? race.startTimeUtc ?? new Date().toISOString();
    const raceIds = await db.prepare(
      "SELECT DISTINCT ra.race_id AS raceId FROM rt_races ra JOIN rt_runners ru ON ru.race_id=ra.race_id WHERE ra.race_date>? AND (ra.race_date<? OR (ra.race_date=? AND ra.start_time_utc IS NOT NULL AND datetime(ra.start_time_utc)<datetime(?) AND EXISTS (SELECT 1 FROM rt_results rr WHERE rr.race_id=ra.race_id AND rr.finish_position IS NOT NULL))) AND (ru.horse_name IN (SELECT value FROM json_each(?)) OR COALESCE(ru.jockey,'') IN (SELECT value FROM json_each(?)) OR COALESCE(ru.trainer,'') IN (SELECT value FROM json_each(?))) ORDER BY ra.race_date,ra.race_id"
    ).bind(throughDate, race.raceDate, race.raceDate, effectiveCutoff, horseJson, jockeyJson, trainerJson).all<{ raceId: string }>();
    const ids = (raceIds.results ?? []).map((row) => row.raceId);
    if (ids.length) {
      const delta = await db.prepare(
        "SELECT ra.race_id AS raceId,ra.race_date AS raceDate,ra.venue,ra.surface,ra.distance_m AS distanceM,ru.horse_no AS horseNo,ru.horse_name AS horseName,ru.jockey,ru.trainer,ru.runner_status AS runnerStatus,re.finish_position AS finishPosition,re.time_text AS timeText,re.final3f FROM rt_races ra JOIN rt_runners ru ON ru.race_id=ra.race_id LEFT JOIN rt_results re ON re.race_id=ru.race_id AND re.horse_no=ru.horse_no WHERE ra.race_id IN (SELECT value FROM json_each(?)) ORDER BY ra.race_date,ra.venue,ra.race_no,ru.horse_no"
      ).bind(JSON.stringify(ids)).all<DeltaRow>();
      advanceRelevantCompletedFeatureState(state, (delta.results ?? []) as DeltaRow[], new Set(horses), new Set(jockeys), new Set(trainers));
    }
  }
  return state;
}
