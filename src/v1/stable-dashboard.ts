import { getResultDashboard, renderResultDashboard } from "./dashboard-results.js";
import type { BudgetCourse } from "./types.js";

const BACKTEST_DATE = "2026-08-01";
const BACKTEST_MODEL = "backtest-2026-08-01-budget-courses-v3";
const COURSES: BudgetCourse[] = ["ライト", "スタンダード", "プレミアム"];

interface StableMetric {
  course: BudgetCourse;
  stake: number;
  returns: number;
  races: number;
  hits: number;
}

async function backtestProgress(db: D1Database): Promise<{ completed: number; total: number }> {
  const total = await db.prepare(`
    SELECT COUNT(*) AS count FROM rt_races
    WHERE race_date=? AND status='finished'
  `).bind(BACKTEST_DATE).first<{ count: number }>();
  const completed = await db.prepare(`
    SELECT COUNT(DISTINCT p.race_id) AS count
    FROM rt_predictions p
    JOIN rt_races r ON r.race_id=p.race_id
    WHERE r.race_date=? AND p.model_version=? AND p.status='locked'
      AND EXISTS (
        SELECT 1 FROM rt_bets b
        WHERE b.prediction_id=p.id AND b.settlement_status='settled'
      )
  `).bind(BACKTEST_DATE, BACKTEST_MODEL).first<{ count: number }>();
  return { completed: Number(completed?.count ?? 0), total: Number(total?.count ?? 0) };
}

async function liveOnlyMetrics(db: D1Database, liveModel: string): Promise<StableMetric[]> {
  const rows = await db.prepare(`
    SELECT CASE
      WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
      WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
      WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
    END AS course,
    COALESCE(SUM(b.stake_yen),0) AS stake,
    COALESCE(SUM(b.return_yen),0) AS returns,
    COUNT(DISTINCT b.race_id) AS races,
    COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) AS hits
    FROM rt_bets b
    JOIN rt_predictions p ON p.id=b.prediction_id
    JOIN rt_races r ON r.race_id=b.race_id
    WHERE b.settlement_status='settled'
      AND r.race_date<>?
      AND p.model_version=?
      AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
    GROUP BY course
  `).bind(BACKTEST_DATE, liveModel).all<StableMetric>();
  const map = new Map(rows.results.map((row) => [row.course, row]));
  return COURSES.map((course) => ({
    course,
    stake: Number(map.get(course)?.stake ?? 0),
    returns: Number(map.get(course)?.returns ?? 0),
    races: Number(map.get(course)?.races ?? 0),
    hits: Number(map.get(course)?.hits ?? 0)
  }));
}

export async function getStableDashboard(db: D1Database, liveModel: string): Promise<{ html: string; backtestComplete: boolean }> {
  const [dashboard, progress] = await Promise.all([
    getResultDashboard(db, liveModel),
    backtestProgress(db)
  ]);
  const complete = progress.total > 0 && progress.completed >= progress.total;
  const metrics = complete ? dashboard.metrics : await liveOnlyMetrics(db, liveModel);
  let html = renderResultDashboard(dashboard.races, metrics);
  if (!complete) {
    const notice = `<div class="calc-note">8月1日検証を集計中 ${progress.completed}/${progress.total || 36}R。完了するまで8月1日の数値は累計回収率に含めません。</div>`;
    html = html.replace('<section class="metrics">', `${notice}<section class="metrics">`)
      .replace('</style>', '.calc-note{margin:0 0 10px;padding:10px 12px;border:1px solid #61512d;border-radius:12px;background:#241f13;color:#f0cf82;font-size:12px}</style>');
  }
  return { html, backtestComplete: complete };
}
