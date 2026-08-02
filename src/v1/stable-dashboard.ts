import { getResultDashboard, renderResultDashboard } from "./dashboard-results.js";

const BACKTEST_DATE = "2026-08-01";
const BACKTEST_MODEL = "backtest-2026-08-01-budget-courses-v3";

async function backtestProgress(db: D1Database): Promise<{ completed: number; total: number }> {
  const total = await db.prepare(`SELECT COUNT(*) AS count FROM rt_races WHERE race_date=? AND status='finished'`)
    .bind(BACKTEST_DATE).first<{ count: number }>();
  const completed = await db.prepare(`
    SELECT COUNT(DISTINCT p.race_id) AS count
    FROM rt_predictions p JOIN rt_races r ON r.race_id=p.race_id
    WHERE r.race_date=? AND p.model_version=? AND p.status='locked'
      AND EXISTS (SELECT 1 FROM rt_bets b WHERE b.prediction_id=p.id AND b.settlement_status='settled')
  `).bind(BACKTEST_DATE, BACKTEST_MODEL).first<{ count: number }>();
  return { completed:Number(completed?.count??0), total:Number(total?.count??0) };
}

export async function getStableDashboard(db: D1Database, liveModel: string): Promise<{ html: string; backtestComplete: boolean }> {
  const [dashboard, progress] = await Promise.all([getResultDashboard(db, liveModel), backtestProgress(db)]);
  const complete = progress.total > 0 && progress.completed >= progress.total;
  // getResultDashboard already excludes the incomplete August 1 batch while retaining settled live/August 2 rows.
  let html = renderResultDashboard(dashboard.races, dashboard.metrics);
  if (!complete) {
    const notice = `<div class="calc-note">8月1日検証を集計中 ${progress.completed}/${progress.total || 36}R。完了するまで8月1日の数値は累計回収率に含めません。</div>`;
    html = html.replace('<section class="metrics">', `${notice}<section class="metrics">`)
      .replace('</style>', '.calc-note{margin:0 0 10px;padding:10px 12px;border:1px solid #61512d;border-radius:12px;background:#241f13;color:#f0cf82;font-size:12px}</style>');
  }
  return { html, backtestComplete:complete };
}
