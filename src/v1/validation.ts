import { savePredictionWithCourses, settleRaceWithCourses } from "./course-db.js";
import { getRace, getRunnerHistoryStats, getRunners } from "./db.js";
import { generatePrediction } from "./model.js";
import type { BetType, BudgetCourse, PredictionOutput } from "./types.js";
import { escapeHtml, formatYen, nowIso } from "./utils.js";

export const PHASE_C_VERSION = "phase-c-validation-v1";

export interface ValidationConfig {
  raceDate: string;
  modelVersion: string;
  label: string;
}

export const VALIDATION_CONFIGS: readonly ValidationConfig[] = [
  {
    raceDate: "2026-08-01",
    modelVersion: "validation-2026-08-01-v3.0.0-value-engine-v1",
    label: "2026年8月1日"
  },
  {
    raceDate: "2026-08-02",
    modelVersion: "validation-2026-08-02-v3.0.0-value-engine-v1",
    label: "2026年8月2日"
  }
];

const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];
const TICKET_ORDER: BetType[] = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"];

export interface ValidationTicketInput {
  raceId: string;
  betType: string;
  stakeYen: number;
  returnYen: number | null;
  expectedValuePct: number;
  settlementStatus: string;
}

export interface TicketTypeValidationSummary {
  betType: BetType;
  tickets: number;
  stakeYen: number;
  returnYen: number;
  profitYen: number;
  expectedReturnYen: number;
  roiPct: number | null;
  expectedRoiPct: number | null;
  hits: number;
  pendingTickets: number;
}

export interface CourseValidationSummary {
  course: BudgetCourse;
  processedRaces: number;
  selectedRaces: number;
  skippedRaces: number;
  hitRaces: number;
  tickets: number;
  pendingTickets: number;
  stakeYen: number;
  returnYen: number;
  profitYen: number;
  expectedReturnYen: number;
  roiPct: number | null;
  expectedRoiPct: number | null;
  hitRatePct: number | null;
  byTicketType: TicketTypeValidationSummary[];
}

export interface ValidationDateSnapshot {
  raceDate: string;
  label: string;
  modelVersion: string;
  totalRaces: number;
  processedRaces: number;
  remainingRaces: number;
  noBetRaces: number;
  complete: boolean;
  courses: CourseValidationSummary[];
}

export interface ValidationSnapshot {
  phase: string;
  generatedAt: string;
  complete: boolean;
  totalRaces: number;
  processedRaces: number;
  remainingRaces: number;
  noBetRaces: number;
  dates: ValidationDateSnapshot[];
  combined: CourseValidationSummary[];
}

function parseStoredBetType(value: string): { course: BudgetCourse | null; ticket: BetType | null } {
  const [course, ticket] = value.split("｜");
  const validCourse = COURSES.includes(course as BudgetCourse) ? course as BudgetCourse : null;
  const validTicket = TICKET_ORDER.includes(ticket as BetType) ? ticket as BetType : null;
  return { course: validCourse, ticket: validTicket };
}

function emptyTicketSummary(betType: BetType): TicketTypeValidationSummary {
  return {
    betType,
    tickets: 0,
    stakeYen: 0,
    returnYen: 0,
    profitYen: 0,
    expectedReturnYen: 0,
    roiPct: null,
    expectedRoiPct: null,
    hits: 0,
    pendingTickets: 0
  };
}

export function summarizeValidationTickets(
  processedRaceIds: readonly string[],
  tickets: readonly ValidationTicketInput[]
): CourseValidationSummary[] {
  const processedRaces = new Set(processedRaceIds).size;
  const state = new Map<BudgetCourse, {
    selectedRaces: Set<string>;
    hitRaces: Set<string>;
    tickets: number;
    pendingTickets: number;
    stakeYen: number;
    returnYen: number;
    expectedReturnYen: number;
    byTicketType: Map<BetType, TicketTypeValidationSummary>;
  }>();

  for (const course of COURSES) {
    state.set(course, {
      selectedRaces: new Set(),
      hitRaces: new Set(),
      tickets: 0,
      pendingTickets: 0,
      stakeYen: 0,
      returnYen: 0,
      expectedReturnYen: 0,
      byTicketType: new Map(TICKET_ORDER.map((ticket) => [ticket, emptyTicketSummary(ticket)]))
    });
  }

  for (const row of tickets) {
    const { course, ticket } = parseStoredBetType(row.betType);
    if (!course || !ticket) continue;
    const target = state.get(course);
    if (!target) continue;
    const stake = Number(row.stakeYen ?? 0);
    const returns = Number(row.returnYen ?? 0);
    const expectedReturn = stake * Number(row.expectedValuePct ?? 0) / 100;
    const pending = row.settlementStatus !== "settled";

    target.selectedRaces.add(row.raceId);
    if (returns > 0) target.hitRaces.add(row.raceId);
    target.tickets += 1;
    target.pendingTickets += pending ? 1 : 0;
    target.stakeYen += stake;
    target.returnYen += returns;
    target.expectedReturnYen += expectedReturn;

    const ticketTarget = target.byTicketType.get(ticket) ?? emptyTicketSummary(ticket);
    ticketTarget.tickets += 1;
    ticketTarget.pendingTickets += pending ? 1 : 0;
    ticketTarget.stakeYen += stake;
    ticketTarget.returnYen += returns;
    ticketTarget.expectedReturnYen += expectedReturn;
    ticketTarget.hits += returns > 0 ? 1 : 0;
    target.byTicketType.set(ticket, ticketTarget);
  }

  return COURSES.map((course) => {
    const target = state.get(course)!;
    const byTicketType = TICKET_ORDER.map((ticket) => {
      const row = target.byTicketType.get(ticket) ?? emptyTicketSummary(ticket);
      return {
        ...row,
        profitYen: row.returnYen - row.stakeYen,
        roiPct: row.stakeYen > 0 ? row.returnYen / row.stakeYen * 100 : null,
        expectedRoiPct: row.stakeYen > 0 ? row.expectedReturnYen / row.stakeYen * 100 : null
      };
    }).filter((row) => row.tickets > 0);

    return {
      course,
      processedRaces,
      selectedRaces: target.selectedRaces.size,
      skippedRaces: Math.max(0, processedRaces - target.selectedRaces.size),
      hitRaces: target.hitRaces.size,
      tickets: target.tickets,
      pendingTickets: target.pendingTickets,
      stakeYen: target.stakeYen,
      returnYen: target.returnYen,
      profitYen: target.returnYen - target.stakeYen,
      expectedReturnYen: target.expectedReturnYen,
      roiPct: target.stakeYen > 0 ? target.returnYen / target.stakeYen * 100 : null,
      expectedRoiPct: target.stakeYen > 0 ? target.expectedReturnYen / target.stakeYen * 100 : null,
      hitRatePct: target.selectedRaces.size > 0 ? target.hitRaces.size / target.selectedRaces.size * 100 : null,
      byTicketType
    };
  });
}

export function validationModelForDate(raceDate: string): string | null {
  return VALIDATION_CONFIGS.find((config) => config.raceDate === raceDate)?.modelVersion ?? null;
}

export function isValidationModel(modelVersion: string | null | undefined): boolean {
  return Boolean(modelVersion) && VALIDATION_CONFIGS.some((config) => config.modelVersion === modelVersion);
}

async function pendingRaceIds(db: D1Database, config: ValidationConfig, limit: number): Promise<string[]> {
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId
    FROM rt_races r
    WHERE r.race_date=? AND r.status='finished'
      AND NOT EXISTS (
        SELECT 1 FROM rt_predictions p
        WHERE p.race_id=r.race_id AND p.model_version=? AND p.status='locked'
      )
    ORDER BY r.venue, r.race_no
    LIMIT ?
  `).bind(config.raceDate, config.modelVersion, limit).all<{ raceId: string }>();
  return rows.results.map((row) => row.raceId);
}

async function remainingForConfig(db: D1Database, config: ValidationConfig): Promise<number> {
  const row = await db.prepare(`
    SELECT COUNT(*) AS count
    FROM rt_races r
    WHERE r.race_date=? AND r.status='finished'
      AND NOT EXISTS (
        SELECT 1 FROM rt_predictions p
        WHERE p.race_id=r.race_id AND p.model_version=? AND p.status='locked'
      )
  `).bind(config.raceDate, config.modelVersion).first<{ count: number }>();
  return Number(row?.count ?? 0);
}

function emptyPrediction(modelVersion: string): PredictionOutput {
  return { modelVersion, runners: [], bets: [], generatedAt: nowIso() };
}

export async function runValidationBatch(
  db: D1Database,
  limit = 6
): Promise<{ processed: number; errors: number; remaining: number; byDate: Array<{ raceDate: string; remaining: number }> }> {
  let processed = 0;
  let errors = 0;

  for (const config of VALIDATION_CONFIGS) {
    const capacity = Math.max(0, limit - processed);
    if (capacity === 0) break;
    const raceIds = await pendingRaceIds(db, config, capacity);
    for (const raceId of raceIds) {
      try {
        const race = await getRace(db, raceId);
        if (!race || race.status !== "finished") continue;
        const runners = await getRunners(db, raceId);
        const usable = runners.filter((runner) => runner.runnerStatus === "active" && runner.winOdds !== null);
        if (usable.length < 2) {
          await savePredictionWithCourses(db, raceId, emptyPrediction(config.modelVersion), "locked");
          processed += 1;
          continue;
        }
        const history = await getRunnerHistoryStats(db, race, runners);
        const prediction = generatePrediction(race, runners, history, config.modelVersion, 108, 10000);
        await savePredictionWithCourses(db, raceId, prediction, "locked");
        await settleRaceWithCourses(db, raceId);
        processed += 1;
      } catch (error) {
        errors += 1;
        console.error("PHASE_C_VALIDATION_FAILED", raceId, error);
      }
    }
  }

  const byDate = await Promise.all(VALIDATION_CONFIGS.map(async (config) => ({
    raceDate: config.raceDate,
    remaining: await remainingForConfig(db, config)
  })));
  return { processed, errors, remaining: byDate.reduce((sum, row) => sum + row.remaining, 0), byDate };
}

interface LoadedDateData {
  snapshot: ValidationDateSnapshot;
  processedRaceIds: string[];
  tickets: ValidationTicketInput[];
}

async function loadDateData(db: D1Database, config: ValidationConfig): Promise<LoadedDateData> {
  const [totalRow, predictionRows, ticketRows] = await Promise.all([
    db.prepare(`SELECT COUNT(*) AS count FROM rt_races WHERE race_date=? AND status='finished'`)
      .bind(config.raceDate).first<{ count: number }>(),
    db.prepare(`
      SELECT p.id, p.race_id AS raceId
      FROM rt_predictions p
      JOIN rt_races r ON r.race_id=p.race_id
      WHERE r.race_date=? AND p.model_version=? AND p.status='locked'
    `).bind(config.raceDate, config.modelVersion).all<{ id: number; raceId: string }>(),
    db.prepare(`
      SELECT b.race_id AS raceId, b.bet_type AS betType, b.stake_yen AS stakeYen,
        b.return_yen AS returnYen, b.expected_value_pct AS expectedValuePct,
        b.settlement_status AS settlementStatus
      FROM rt_bets b
      JOIN rt_predictions p ON p.id=b.prediction_id
      WHERE p.model_version=?
        AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
    `).bind(config.modelVersion).all<ValidationTicketInput>()
  ]);

  const processedRaceIds = predictionRows.results.map((row) => row.raceId);
  const tickets = ticketRows.results.map((row) => ({
    ...row,
    stakeYen: Number(row.stakeYen),
    returnYen: row.returnYen === null ? null : Number(row.returnYen),
    expectedValuePct: Number(row.expectedValuePct)
  }));
  const totalRaces = Number(totalRow?.count ?? 0);
  const processedRaces = new Set(processedRaceIds).size;
  const wageredRaces = new Set(tickets.map((row) => row.raceId)).size;

  return {
    processedRaceIds,
    tickets,
    snapshot: {
      raceDate: config.raceDate,
      label: config.label,
      modelVersion: config.modelVersion,
      totalRaces,
      processedRaces,
      remainingRaces: Math.max(0, totalRaces - processedRaces),
      noBetRaces: Math.max(0, processedRaces - wageredRaces),
      complete: totalRaces > 0 && processedRaces >= totalRaces,
      courses: summarizeValidationTickets(processedRaceIds, tickets)
    }
  };
}

export async function getValidationSnapshot(db: D1Database): Promise<ValidationSnapshot> {
  const loaded = await Promise.all(VALIDATION_CONFIGS.map((config) => loadDateData(db, config)));
  const dates = loaded.map((row) => row.snapshot);
  const processedRaceIds = loaded.flatMap((row) => row.processedRaceIds);
  const tickets = loaded.flatMap((row) => row.tickets);
  const totalRaces = dates.reduce((sum, row) => sum + row.totalRaces, 0);
  const processedRaces = dates.reduce((sum, row) => sum + row.processedRaces, 0);
  const wageredRaces = new Set(tickets.map((row) => row.raceId)).size;

  return {
    phase: PHASE_C_VERSION,
    generatedAt: nowIso(),
    complete: totalRaces > 0 && processedRaces >= totalRaces,
    totalRaces,
    processedRaces,
    remainingRaces: Math.max(0, totalRaces - processedRaces),
    noBetRaces: Math.max(0, processedRaces - wageredRaces),
    dates,
    combined: summarizeValidationTickets(processedRaceIds, tickets)
  };
}

function pct(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}%`;
}

function signedYen(value: number): string {
  return `${value >= 0 ? "+" : ""}${formatYen(value)}`;
}

function courseCard(row: CourseValidationSummary): string {
  const budget = row.course === "ライト" ? 2000 : row.course === "スタンダード" ? 5000 : 10000;
  return `<section class="course-card">
    <div class="course-head"><div><small>${escapeHtml(row.course)}コース</small><h2>上限 ${formatYen(budget)}</h2></div><strong class="${row.roiPct !== null && row.roiPct >= 100 ? "plus" : "minus"}">${pct(row.roiPct)}</strong></div>
    <div class="stats">
      <div><span>購入レース</span><b>${row.selectedRaces}/${row.processedRaces}R</b></div>
      <div><span>見送り</span><b>${row.skippedRaces}R</b></div>
      <div><span>購入額</span><b>${formatYen(row.stakeYen)}</b></div>
      <div><span>払戻</span><b>${formatYen(row.returnYen)}</b></div>
      <div><span>収支</span><b class="${row.profitYen >= 0 ? "plus" : "minus"}">${signedYen(row.profitYen)}</b></div>
      <div><span>的中レース</span><b>${row.hitRaces}R</b></div>
    </div>
    <div class="expected">購入時の推定期待回収率 ${pct(row.expectedRoiPct)}${row.pendingTickets > 0 ? ` ／ 精算待ち ${row.pendingTickets}点` : ""}</div>
  </section>`;
}

function ticketTable(courses: CourseValidationSummary[]): string {
  const rows = courses.flatMap((course) => course.byTicketType.map((ticket) => ({ course: course.course, ...ticket })));
  if (rows.length === 0) return `<p class="empty">期待値基準を通過した買い目はまだありません。</p>`;
  return `<div class="table-wrap"><table><thead><tr><th>コース</th><th>券種</th><th>点数</th><th>購入</th><th>払戻</th><th>収支</th><th>回収率</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${escapeHtml(row.course)}</td><td>${escapeHtml(row.betType)}</td><td>${row.tickets}</td><td>${formatYen(row.stakeYen)}</td><td>${formatYen(row.returnYen)}</td><td class="${row.profitYen >= 0 ? "plus" : "minus"}">${signedYen(row.profitYen)}</td><td>${pct(row.roiPct)}</td></tr>`).join("")}</tbody></table></div>`;
}

function dateCard(row: ValidationDateSnapshot): string {
  return `<a class="date-card" href="/validation/${row.raceDate}">
    <div><b>${escapeHtml(row.label)}</b><span>${row.complete ? "完了" : "計算中"}</span></div>
    <strong>${row.processedRaces}/${row.totalRaces}R</strong>
    <small>全コース見送り ${row.noBetRaces}R</small>
  </a>`;
}

export async function renderValidation(db: D1Database, onlyDate?: string): Promise<string> {
  const snapshot = await getValidationSnapshot(db);
  const selectedDates = onlyDate ? snapshot.dates.filter((row) => row.raceDate === onlyDate) : snapshot.dates;
  const selectedCourses = onlyDate
    ? selectedDates[0]?.courses ?? []
    : snapshot.combined;
  const selectedProcessed = selectedDates.reduce((sum, row) => sum + row.processedRaces, 0);
  const selectedTotal = selectedDates.reduce((sum, row) => sum + row.totalRaces, 0);
  const selectedRemaining = Math.max(0, selectedTotal - selectedProcessed);
  const title = onlyDate ? `${selectedDates[0]?.label ?? onlyDate} 検証` : "フェーズC 検証レポート";
  const refresh = selectedRemaining > 0 ? `<meta http-equiv="refresh" content="15">` : "";

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">${refresh}<title>${escapeHtml(title)}｜レース探偵</title><style>
  :root{color-scheme:dark;--bg:#071019;--panel:#101a25;--panel2:#0b141e;--line:#293b4e;--text:#f4f7fa;--muted:#93a6b9;--green:#52d5a5;--red:#ff7b72;--amber:#f0c36d}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}a{color:inherit;text-decoration:none}.wrap{max-width:1060px;margin:auto;padding:16px}.top{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 0 16px}.brand{font-size:23px;font-weight:900;color:var(--green)}.top nav{display:flex;gap:7px}.top nav a{border:1px solid var(--line);border-radius:999px;padding:8px 11px;font-size:12px}.hero,.course-card,.date-card,.warning{border:1px solid var(--line);border-radius:17px;background:var(--panel)}.hero{padding:20px}.hero h1{margin:0 0 8px}.hero p{color:var(--muted);line-height:1.7;margin:5px 0}.progress{display:flex;align-items:end;gap:9px;margin-top:14px}.progress strong{font-size:30px}.progress span{color:var(--muted);padding-bottom:4px}.warning{margin:12px 0;padding:13px 15px;border-color:#66542c;background:#241f13;color:#f3d28a;font-size:12px;line-height:1.6}.dates{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin:12px 0 18px}.date-card{padding:14px}.date-card>div{display:flex;justify-content:space-between;gap:8px}.date-card span{color:var(--green);font-size:11px}.date-card strong{display:block;font-size:22px;margin:7px 0 2px}.date-card small{color:var(--muted)}.section-title{display:flex;justify-content:space-between;align-items:end;margin:22px 0 8px}.section-title h2{margin:0}.section-title span{color:var(--muted);font-size:12px}.course-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.course-card{padding:15px}.course-head{display:flex;justify-content:space-between;align-items:center}.course-head small,.stats span,.expected,.empty{color:var(--muted)}.course-head h2{font-size:17px;margin:4px 0}.course-head strong{font-size:25px}.stats{display:grid;grid-template-columns:repeat(2,1fr);gap:7px;margin-top:10px}.stats div{background:var(--panel2);border-radius:10px;padding:9px}.stats span{display:block;font-size:10px}.stats b{display:block;margin-top:3px;font-size:14px}.expected{border-top:1px solid var(--line);margin-top:10px;padding-top:9px;font-size:10px}.plus{color:var(--green)}.minus{color:var(--red)}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:14px}table{width:100%;min-width:720px;border-collapse:collapse;background:var(--panel)}th,td{padding:11px;border-bottom:1px solid var(--line);text-align:left;font-size:12px}th{color:var(--muted)}.footer{padding:26px 0 40px;color:var(--muted);font-size:11px;text-align:center}@media(max-width:760px){.course-grid{display:flex;overflow:auto}.course-card{flex:0 0 285px}.dates{grid-template-columns:1fr}.hero{padding:16px}}
  </style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><nav><a href="/">予想</a><a href="/performance">本番成績</a><a href="/validation">検証</a></nav></header><section class="hero"><h1>${escapeHtml(title)}</h1><p>フェーズBの期待値エンジンを、保存済みの出走情報だけで再計算し、公式払戻と照合します。結果・払戻は予想生成へ渡していません。</p><div class="progress"><strong>${selectedProcessed}/${selectedTotal}R</strong><span>${selectedRemaining > 0 ? `残り${selectedRemaining}R` : "計算完了"}</span></div></section><div class="warning">これは遡及検証です。保存済みの最新単勝オッズを使うため、実際の公開時点オッズと一致しない可能性があります。本番公開成績には混ぜず、別集計しています。</div>${onlyDate ? `<p><a href="/validation">← 全日程へ戻る</a></p>` : `<section class="dates">${snapshot.dates.map(dateCard).join("")}</section>`}<div class="section-title"><h2>コース別検証</h2><span>予算は上限・条件未達は見送り</span></div><section class="course-grid">${selectedCourses.map(courseCard).join("")}</section><div class="section-title"><h2>券種別内訳</h2><span>公式払戻で精算</span></div>${ticketTable(selectedCourses)}<footer class="footer">検証モデル ${escapeHtml(selectedDates.map((row) => row.modelVersion).join(" / "))}</footer></main></body></html>`;
}
