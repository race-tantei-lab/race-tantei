import type { CourseMetric } from "./course-db.js";
import type { CourseValidationSummary } from "./validation.js";
import { escapeHtml, formatYen } from "./utils.js";

function pct(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}%`;
}

function courseBudget(course: string): string {
  if (course === "ライト") return "2,000円";
  if (course === "スタンダード") return "5,000円";
  return "10,000円";
}

function metricCard(row: CourseMetric, heading: string): string {
  return `<section class="course ${row.course}">
    <div class="course-head"><div><span class="label">${escapeHtml(heading)}</span><h2>${escapeHtml(row.course)} ${courseBudget(row.course)}</h2></div><strong class="roi ${row.roiPct !== null && row.roiPct >= 100 ? "plus" : "minus"}">${pct(row.roiPct)}</strong></div>
    <div class="stats">
      <div><small>累計購入</small><b>${formatYen(row.stakeYen)}</b></div>
      <div><small>累計払戻</small><b>${formatYen(row.returnYen)}</b></div>
      <div><small>累計収支</small><b class="${row.profitYen >= 0 ? "plus" : "minus"}">${row.profitYen >= 0 ? "+" : ""}${formatYen(row.profitYen)}</b></div>
      <div><small>選出レース</small><b>${row.settledRaces}R</b></div>
    </div>
  </section>`;
}

function validationToMetric(row: CourseValidationSummary): CourseMetric {
  return {
    course: row.course,
    settledRaces: row.selectedRaces,
    betCount: row.tickets,
    stakeYen: row.stakeYen,
    returnYen: row.returnYen,
    profitYen: row.profitYen,
    roiPct: row.roiPct,
    hitRatePct: row.hitRatePct
  };
}

function combinedMetric(live: CourseMetric, historical: CourseMetric): CourseMetric {
  const stakeYen = live.stakeYen + historical.stakeYen;
  const returnYen = live.returnYen + historical.returnYen;
  return {
    course: live.course,
    settledRaces: live.settledRaces + historical.settledRaces,
    betCount: live.betCount + historical.betCount,
    stakeYen,
    returnYen,
    profitYen: returnYen - stakeYen,
    roiPct: stakeYen > 0 ? returnYen / stakeYen * 100 : null,
    hitRatePct: null
  };
}

export function renderCoursePerformance(
  cumulative: CourseMetric[],
  monthly: Array<CourseMetric & { month: string }>,
  historical: CourseValidationSummary[] = []
): string {
  const historicalMetrics = cumulative.map((live) => validationToMetric(
    historical.find((row) => row.course === live.course) ?? {
      course: live.course,
      processedRaces: 0,
      selectedRaces: 0,
      skippedRaces: 0,
      hitRaces: 0,
      tickets: 0,
      pendingTickets: 0,
      stakeYen: 0,
      returnYen: 0,
      profitYen: 0,
      expectedReturnYen: 0,
      roiPct: null,
      expectedRoiPct: null,
      hitRatePct: null,
      byTicketType: []
    }
  ));
  const combined = cumulative.map((live) => combinedMetric(
    live,
    historicalMetrics.find((row) => row.course === live.course)!
  ));

  const combinedCards = combined.map((row) => metricCard(row, "過去検証込み回収率")).join("");
  const liveCards = cumulative.map((row) => metricCard(row, "本番公開成績")).join("");
  const historyCards = historicalMetrics.map((row) => metricCard(row, "8月1日・2日 遡及検証")).join("");

  const months = [...new Set(monthly.map((row) => row.month))];
  const monthlyHtml = months.map((month) => {
    const rows = monthly.filter((row) => row.month === month);
    return `<section class="month"><h2>${escapeHtml(month)}</h2><div class="table-wrap"><table><thead><tr><th>コース</th><th>購入</th><th>払戻</th><th>収支</th><th>回収率</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${escapeHtml(row.course)}</td><td>${formatYen(row.stakeYen)}</td><td>${formatYen(row.returnYen)}</td><td class="${row.profitYen >= 0 ? "plus" : "minus"}">${row.profitYen >= 0 ? "+" : ""}${formatYen(row.profitYen)}</td><td>${pct(row.roiPct)}</td></tr>`).join("")}</tbody></table></div></section>`;
  }).join("");

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0b0f14"><title>コース別回収率｜レース探偵</title><style>
  :root{color-scheme:dark;--bg:#0b0f14;--panel:#121923;--line:#293649;--text:#eef3f8;--muted:#9fb0c2;--green:#4fd1a1;--red:#ff7b72;--gold:#ffd166}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#091018,#0b0f14);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:960px;margin:auto;padding:16px}a{color:inherit;text-decoration:none}.top{display:flex;justify-content:space-between;align-items:center;padding:12px 0 20px}.brand{font-size:22px;font-weight:900}.brand span{color:var(--green)}nav{display:flex;gap:8px;overflow:auto}nav a{white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:8px 11px;background:#111925;font-size:13px}.hero{border:1px solid #2b5448;background:linear-gradient(135deg,#172638,#10241e);border-radius:20px;padding:22px;margin-bottom:16px}.hero h1{margin:0 0 8px}.hero p{margin:0;color:var(--muted);line-height:1.6}.notice{border:1px solid #65552f;background:#241f13;color:#f2d28a;border-radius:14px;padding:12px;margin:14px 0;line-height:1.6}.section-title{margin:28px 0 8px}.section-title small{display:block;color:var(--muted);font-weight:400;margin-top:4px}.course{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:18px;margin:12px 0}.course-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.course-head h2{margin:4px 0 0}.label{color:var(--muted)}.roi{font-size:30px}.stats{display:grid;grid-template-columns:repeat(2,1fr);gap:9px;margin-top:16px}.stats div{background:#0d141d;border-radius:12px;padding:12px}.stats small{display:block;color:var(--muted)}.stats b{display:block;margin-top:4px;font-size:18px}.plus{color:var(--green)}.minus{color:var(--red)}.month{margin-top:28px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:14px}table{width:100%;border-collapse:collapse;min-width:620px;background:var(--panel)}th,td{padding:12px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--muted)}@media(min-width:760px){.stats{grid-template-columns:repeat(4,1fr)}.wrap{padding:24px}}
  </style></head><body><main class="wrap"><div class="top"><a class="brand" href="/"><span>レース</span>探偵</a><nav><a href="/">予想</a><a href="/performance">成績</a><a href="/validation">検証</a><a href="/methodology">予想方法</a><a href="/system">稼働状況</a></nav></div><section class="hero"><h1>コース別回収率</h1><p>各会場から原則5Rを選出し、ライト・スタンダード・プレミアムを同じ基準で集計します。</p></section><div class="notice">過去分は保存済みオッズを使った遡及検証です。実際の発走前公開成績とは分けたうえで、合算値も確認できるようにしています。</div><h2 class="section-title">過去検証込み<small>8月1日・2日の遡及検証＋本番公開分</small></h2>${combinedCards}<h2 class="section-title">遡及検証のみ<small>8月1日・2日を会場別5R方式で集計</small></h2>${historyCards}<h2 class="section-title">本番公開のみ<small>発走前に公開した現行モデル</small></h2>${liveCards}<h2 class="section-title">本番月別成績</h2>${monthlyHtml || '<p>現行モデルの精算結果はまだありません。</p>'}</main></body></html>`;
}
