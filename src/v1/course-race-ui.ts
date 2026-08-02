import type { RaceDetail } from "./db.js";
import { escapeHtml, formatYen } from "./utils.js";

const COURSES = [
  { name: "ライト", budget: "2,000円", cls: "light" },
  { name: "スタンダード", budget: "5,000円", cls: "standard" },
  { name: "プレミアム", budget: "10,000円", cls: "premium" }
] as const;

const CSS = `:root{color-scheme:dark;--bg:#0b0f14;--panel:#121923;--line:#293649;--text:#eef3f8;--muted:#9fb0c2;--green:#4fd1a1;--red:#ff7b72;--gold:#ffd166}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#091018,#0b0f14);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif;line-height:1.55}.wrap{max-width:920px;margin:auto;padding:16px}a{color:inherit;text-decoration:none}.top{display:flex;justify-content:space-between;align-items:center;padding:10px 0 18px}.brand{font-size:22px;font-weight:900}.brand span{color:var(--green)}nav{display:flex;gap:7px;overflow:auto}nav a{white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:8px 11px;background:#111925;font-size:13px}.hero,.panel,.course{background:var(--panel);border:1px solid var(--line);border-radius:18px}.hero{padding:20px;background:linear-gradient(135deg,#172638,#10241e);border-color:#2b5448}.hero h1{margin:5px 0}.muted{color:var(--muted)}.marks{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.pill{border:1px solid var(--line);border-radius:999px;padding:5px 10px}.pill.first{color:#8df0cc;border-color:#347a65}.panel{padding:16px;margin:12px 0}.result{border-color:#76613a;background:#251e12}.course{margin:18px 0;overflow:hidden}.course.light{border-color:#397361}.course.standard{border-color:#796b35}.course.premium{border-color:#805477}.course-head{display:flex;justify-content:space-between;align-items:center;padding:16px;background:#101925}.course-head h2{margin:0;font-size:21px}.course-summary{padding:12px 16px;background:#0d141d;border-top:1px solid var(--line);font-size:16px}.tickets{display:grid;gap:9px;padding:11px}.ticket{background:#162416;border:1px solid #516d42;border-radius:14px;padding:14px}.ticket b{font-size:17px}.positive{color:var(--green)}.negative{color:var(--red)}table{width:100%;border-collapse:collapse;min-width:650px}th,td{padding:10px 7px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--muted)}.scroll{overflow:auto}.horse{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:7px;background:#e8edf2;color:#101820;font-weight:900;margin-right:7px}.empty{padding:18px;color:var(--muted)}.footer{padding:35px 3px;color:var(--muted);font-size:12px}@media(min-width:720px){.wrap{padding:24px}.tickets{grid-template-columns:repeat(2,minmax(0,1fr))}}`;

export function renderCourseRace(detail: RaceDetail): string {
  const { race, runners, prediction, predictedRunners, bets } = detail;
  const finished = race.status === "finished";
  const marks = ["◎", "○", "▲", "△"];
  const predMap = new Map(predictedRunners.map((row) => [row.horseNo, row]));
  const finishers = [...runners].filter((row) => row.finishPosition !== null).sort((a, b) => (a.finishPosition ?? 99) - (b.finishPosition ?? 99));

  const courses = COURSES.map((course) => {
    const rows = bets.filter((bet) => bet.betType.startsWith(`${course.name}｜`));
    const stake = rows.reduce((sum, row) => sum + row.stakeYen, 0);
    const returns = rows.reduce((sum, row) => sum + (row.returnYen ?? 0), 0);
    const profit = returns - stake;
    const tickets = rows.map((row) => {
      const ticket = row.betType.split("｜").pop() ?? row.betType;
      return `<div class="ticket"><b>${escapeHtml(ticket)} ${escapeHtml(row.combination)}</b><div>購入 ${formatYen(row.stakeYen)} ／ 使用オッズ ${row.assumedOdds.toFixed(1)}</div><div class="muted">期待値 ${row.expectedValuePct.toFixed(1)}% ／ ${row.settlementStatus === "settled" ? `払戻 ${formatYen(row.returnYen ?? 0)}` : "発走前固定済み"}</div></div>`;
    }).join("");
    return `<section class="course ${course.cls}"><div class="course-head"><h2>${course.name}コース</h2><b>${course.budget}</b></div><div class="course-summary">${finished ? `購入 ${formatYen(stake)} ／ 払戻 ${formatYen(returns)} ／ <strong class="${profit >= 0 ? "positive" : "negative"}">${profit >= 0 ? "+" : ""}${formatYen(profit)}</strong>` : `合計購入 ${formatYen(stake)}`}</div><div class="tickets">${tickets || '<div class="empty">このコースの買い目はまだ生成されていません。</div>'}</div></section>`;
  }).join("");

  const runnerRows = runners.map((runner) => {
    const pred = predMap.get(runner.horseNo);
    return `<tr><td><span class="horse">${runner.horseNo}</span>${escapeHtml(runner.horseName)}</td><td>${pred ? `${pred.predictedOrder}位<br>${(pred.winProbability * 100).toFixed(1)}%` : "—"}</td><td>${runner.winOdds ?? "—"}</td><td>${pred?.expectedValuePct != null ? `${pred.expectedValuePct.toFixed(1)}%` : "—"}</td><td>${runner.finishPosition ?? "—"}</td></tr>`;
  }).join("");

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0b0f14"><title>${escapeHtml(race.raceDate)} ${escapeHtml(race.venue)}${race.raceNo}R｜レース探偵</title><style>${CSS}</style></head><body><main class="wrap"><div class="top"><a class="brand" href="/"><span>レース</span>探偵</a><nav><a href="/">予想</a><a href="/performance">成績</a><a href="/backtest/2026-08-01">8/1検証</a></nav></div><section class="hero"><div class="muted">${escapeHtml(race.raceDate)} ／ ${escapeHtml(race.venue)}競馬場</div><h1>${race.raceNo}R ${escapeHtml(race.raceName)}</h1><div><b>${escapeHtml(race.startTimeJst ?? "時刻未定")} 発走</b>　${escapeHtml(race.surface ?? "")}${race.distanceM ?? ""}m</div></section><section class="panel"><b>${prediction?.status === "locked" ? "発走前固定予想" : prediction ? "暫定予想" : "予想待ち"}</b><div class="marks">${predictedRunners.slice(0, 4).map((row, index) => `<span class="pill ${index === 0 ? "first" : ""}">${marks[index]} ${row.horseNo} ${escapeHtml(row.horseName)}</span>`).join("") || '<span class="muted">オッズ取得後に生成します。</span>'}</div></section>${finished ? `<section class="panel result"><b>レース結果</b><div class="marks">${finishers.slice(0, 3).map((row) => `<span class="pill">${row.finishPosition}着 ${row.horseNo} ${escapeHtml(row.horseName)}</span>`).join("")}</div><div class="muted">払戻・収支は各コース内に分けて表示します。</div></section>` : '<section class="panel"><b>結果待ち</b><div class="muted">終了後に各コースを個別精算します。</div></section>'}<h2>予算コース別の買い目</h2>${courses}<h2>出走馬・予想・結果</h2><section class="panel scroll"><table><thead><tr><th>馬</th><th>予想</th><th>単勝</th><th>期待値</th><th>着順</th></tr></thead><tbody>${runnerRows}</tbody></table></section><footer class="footer">各コースは独立した購入プランです。3コースを合算して購入する想定ではありません。</footer></main></body></html>`;
}
