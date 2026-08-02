import type { RaceDetail } from "./db.js";
import { escapeHtml, formatYen } from "./utils.js";

type BetRow = RaceDetail["bets"][number];
type Course = "ライト" | "スタンダード" | "プレミアム";

const COURSES: Array<{ name: Course; budget: number }> = [
  { name: "ライト", budget: 2000 },
  { name: "スタンダード", budget: 5000 },
  { name: "プレミアム", budget: 10000 }
];
const ORDER = ["単勝", "複勝", "ワイド", "馬連", "馬単", "3連複", "3連単"];
const MARKS = ["◎", "○", "▲", "△"];

function splitType(value: string): { course: Course | null; ticket: string } {
  const [course, ticket] = value.split("｜");
  if ((course === "ライト" || course === "スタンダード" || course === "プレミアム") && ticket) {
    return { course, ticket };
  }
  return { course: null, ticket: value };
}

function numbers(value: string): number[] {
  return (value.match(/\d{1,2}/g) ?? []).map(Number);
}

function combinationLabel(ticket: string, bet: BetRow): string {
  const separator = ticket === "馬単" || ticket === "3連単" ? "→" : "－";
  return numbers(bet.combination).join(separator);
}

function ticketGrid(ticket: string, bets: BetRow[], finished: boolean): string {
  return `<div class="ticket-grid">${bets.map((bet) => {
    const payout = Number(bet.returnYen ?? 0);
    return `<div class="ticket-item${payout > 0 ? " hit" : ""}">
      <b>${escapeHtml(combinationLabel(ticket, bet))}</b>
      <span>${formatYen(bet.stakeYen)}</span>
      ${finished ? `<small>${payout > 0 ? "的中・" : ""}払戻 ${formatYen(payout)}</small>` : ""}
    </div>`;
  }).join("")}</div>`;
}

function courseStats(course: Course, allBets: BetRow[]): { stake: number; returns: number; profit: number; count: number } {
  const bets = allBets.filter((bet) => splitType(bet.betType).course === course);
  const stake = bets.reduce((sum, bet) => sum + bet.stakeYen, 0);
  const returns = bets.reduce((sum, bet) => sum + Number(bet.returnYen ?? 0), 0);
  return { stake, returns, profit: returns - stake, count: bets.length };
}

function coursePanel(course: Course, budget: number, allBets: BetRow[], finished: boolean, index: number): string {
  const bets = allBets.filter((bet) => splitType(bet.betType).course === course);
  const { stake, returns, profit } = courseStats(course, allBets);
  const groups = ORDER.map((ticket) => ({
    ticket,
    bets: bets.filter((bet) => splitType(bet.betType).ticket === ticket)
  })).filter((group) => group.bets.length > 0);

  const body = groups.length === 0
    ? `<div class="empty">${finished ? "このコースの買い目はありません。" : "買い目を作成中です。"}</div>`
    : groups.map(({ ticket, bets: ticketBets }) => {
        const subtotal = ticketBets.reduce((sum, bet) => sum + bet.stakeYen, 0);
        const payout = ticketBets.reduce((sum, bet) => sum + Number(bet.returnYen ?? 0), 0);
        return `<section class="ticket">
          <div class="ticket-head">
            <div><b>${ticket}</b><small>${ticketBets.length}点</small></div>
            <strong>${formatYen(subtotal)}</strong>
          </div>
          ${ticketGrid(ticket, ticketBets, finished)}
          ${finished ? `<div class="payout">券種払戻 ${formatYen(payout)}</div>` : ""}
        </section>`;
      }).join("");

  return `<section class="course-panel" id="course-panel-${index}" data-course-panel="${index}" hidden>
    <header class="course-summary">
      <div><h2>${course}コース</h2><small>予算 ${formatYen(budget)}</small></div>
      <div class="course-total">
        <span>購入 ${formatYen(stake)}</span>
        ${finished ? `<span>払戻 ${formatYen(returns)}</span><b class="${profit >= 0 ? "plus" : "minus"}">${profit >= 0 ? "+" : ""}${formatYen(profit)}</b>` : ""}
      </div>
    </header>
    ${body}
  </section>`;
}

function runnerList(detail: RaceDetail): string {
  const predictedByHorse = new Map(detail.predictedRunners.map((runner) => [runner.horseNo, runner]));
  const rows = [...detail.runners].sort((a, b) => a.horseNo - b.horseNo).map((runner) => {
    const predicted = predictedByHorse.get(runner.horseNo);
    const mark = predicted && predicted.predictedOrder <= MARKS.length ? MARKS[predicted.predictedOrder - 1] : "";
    const odds = runner.winOdds ?? predicted?.currentOdds ?? null;
    const finish = runner.finishPosition !== null ? `${runner.finishPosition}着` : "";
    const topFinish = runner.finishPosition !== null && runner.finishPosition <= 3;
    return `<article class="runner${topFinish ? " top-finish" : ""}">
      <div class="runner-main">
        <span class="horse-no">${runner.horseNo}</span>
        <div class="horse-info"><b>${mark ? `<em>${mark}</em> ` : ""}${escapeHtml(runner.horseName)}</b><small>${escapeHtml(runner.jockey ?? "騎手未取得")}${runner.sexAge ? ` ／ ${escapeHtml(runner.sexAge)}` : ""}</small></div>
        ${finish ? `<strong class="finish">${finish}</strong>` : ""}
      </div>
      <div class="runner-metrics">
        <span><small>単勝</small><b>${odds !== null ? odds.toFixed(1) : "－"}</b></span>
        <span><small>予想順位</small><b>${predicted ? `${predicted.predictedOrder}位` : "－"}</b></span>
        <span><small>勝率</small><b>${predicted ? `${(predicted.winProbability * 100).toFixed(1)}%` : "－"}</b></span>
        <span><small>期待値</small><b>${predicted?.expectedValuePct !== null && predicted?.expectedValuePct !== undefined ? `${predicted.expectedValuePct.toFixed(1)}%` : "－"}</b></span>
      </div>
    </article>`;
  }).join("");
  return `<section class="runners"><div class="section-head"><h2>出走馬・予想・結果</h2><span>${detail.runners.length}頭</span></div>${rows || `<div class="empty">出走馬情報を取得中です。</div>`}</section>`;
}

export function renderRaceDetailV4(detail: RaceDetail): string {
  const { race, runners, prediction, predictedRunners, bets } = detail;
  const finished = race.status === "finished";
  const markHtml = prediction
    ? predictedRunners.slice(0, 4).map((runner, index) => `<span>${MARKS[index]} ${runner.horseNo} ${escapeHtml(runner.horseName)}</span>`).join("")
    : `<span>予想未生成</span>`;
  const finishers = [...runners].filter((runner) => runner.finishPosition !== null).sort((a, b) => Number(a.finishPosition) - Number(b.finishPosition));
  const result = finished ? `<section class="result"><h2>確定結果</h2><div>${finishers.slice(0, 3).map((runner) => `<span>${runner.finishPosition}着 <b>${runner.horseNo}</b> ${escapeHtml(runner.horseName)}</span>`).join("")}</div></section>` : "";
  const stats = COURSES.map(({ name }) => courseStats(name, bets));
  const defaultIndex = stats[1]?.count ? 1 : Math.max(0, stats.findIndex((stat) => stat.count > 0));
  const tabs = COURSES.map(({ name, budget }, index) => {
    const stat = stats[index] ?? { stake: 0, returns: 0, profit: 0, count: 0 };
    return `<button class="course-tab${index === defaultIndex ? " active" : ""}" type="button" data-course-tab="${index}" aria-controls="course-panel-${index}" aria-selected="${index === defaultIndex ? "true" : "false"}">
      <b>${name}</b><small>${formatYen(budget)}</small>${finished && stat.stake > 0 ? `<span class="${stat.profit >= 0 ? "plus" : "minus"}">${stat.profit >= 0 ? "+" : ""}${formatYen(stat.profit)}</span>` : `<span>${stat.count}点</span>`}
    </button>`;
  }).join("");

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>${escapeHtml(race.venue)}${race.raceNo}R｜レース探偵</title><style>
  :root{color-scheme:dark;--bg:#081019;--panel:#111a25;--line:#2a3a4c;--text:#f4f7fa;--muted:#9aabba;--green:#52d5a5;--red:#ff7b72}
  *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:860px;margin:auto;padding:14px}a{color:inherit;text-decoration:none}.top{display:flex;justify-content:space-between;align-items:center;padding:10px 0 14px}.brand{font-size:22px;font-weight:900;color:var(--green)}.back{border:1px solid var(--line);border-radius:999px;padding:8px 12px}.hero,.result,.runners,.course-panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;margin-bottom:12px}.hero{padding:18px}.hero small,.empty{color:var(--muted)}.hero h1{margin:6px 0 12px;font-size:24px}.marks,.result div{display:flex;gap:7px;overflow:auto}.marks span,.result span{white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:7px 10px}.result{padding:15px}.result h2{margin:0 0 10px}.section-head{display:flex;justify-content:space-between;align-items:center;padding:15px;border-bottom:1px solid var(--line)}.section-head h2{font-size:18px;margin:0}.section-head span{color:var(--muted);font-size:13px}.runner{padding:13px 14px;border-bottom:1px solid var(--line)}.runner:last-child{border-bottom:0}.runner.top-finish{background:#10221d}.runner-main{display:grid;grid-template-columns:42px 1fr auto;gap:10px;align-items:center}.horse-no{display:flex;align-items:center;justify-content:center;width:38px;height:38px;border-radius:10px;background:#1a293a;border:1px solid #3a526b;font-weight:900;font-size:18px}.horse-info b{display:block;font-size:15px}.horse-info em{font-style:normal;color:var(--green)}.horse-info small{display:block;color:var(--muted);margin-top:3px;font-size:11px}.finish{color:var(--green);font-size:14px}.runner-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px}.runner-metrics span{background:#0b141e;border-radius:9px;padding:7px;text-align:center}.runner-metrics small,.runner-metrics b{display:block}.runner-metrics small{color:var(--muted);font-size:10px}.runner-metrics b{font-size:12px;margin-top:2px}.course-tabs{position:sticky;top:0;z-index:5;display:grid;grid-template-columns:repeat(3,1fr);gap:7px;padding:8px 0 11px;background:linear-gradient(var(--bg) 78%,transparent)}.course-tab{appearance:none;border:1px solid var(--line);background:#0d1620;color:var(--text);border-radius:13px;padding:9px 5px;min-width:0}.course-tab b,.course-tab small,.course-tab span{display:block}.course-tab b{font-size:14px}.course-tab small{font-size:11px;color:var(--muted);margin-top:2px}.course-tab span{font-size:11px;margin-top:4px;color:var(--muted)}.course-tab.active{border-color:var(--green);background:#10241f;box-shadow:0 0 0 1px rgba(82,213,165,.18)}.course-tab.active b{color:var(--green)}.plus{color:var(--green)!important}.minus{color:var(--red)!important}.course-panel{overflow:hidden}.course-panel[hidden]{display:none}.course-summary{display:flex;justify-content:space-between;align-items:center;padding:15px;background:#0d1620}.course-summary h2{margin:0;font-size:19px}.course-summary small{color:var(--muted)}.course-total{text-align:right}.course-total span,.course-total b{display:block;font-size:12px}.course-total b{font-size:16px;margin-top:3px}.ticket{padding:14px 15px;border-top:1px solid var(--line)}.ticket-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:11px}.ticket-head>div{display:flex;align-items:baseline;gap:8px}.ticket-head b{color:#a5ecd4;font-size:18px}.ticket-head small{font-size:12px;color:var(--muted)}.ticket-head strong{font-size:20px}.ticket-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.ticket-item{display:grid;grid-template-columns:1fr auto;gap:4px 8px;align-items:center;padding:11px 12px;border-radius:12px;background:#0b141e;border:1px solid #30465d}.ticket-item b{font-size:16px;white-space:nowrap}.ticket-item>span{font-size:13px;font-weight:800;color:#c6d1dc;white-space:nowrap}.ticket-item small{grid-column:1/-1;color:var(--muted);font-size:11px}.ticket-item.hit{border-color:#3e8c73;background:#0d211d}.ticket-item.hit small{color:var(--green)}.payout{text-align:right;color:var(--muted);font-size:12px;margin-top:9px}.empty{padding:20px 15px}.guide{color:var(--muted);font-size:12px;margin:3px 0 8px}.version{text-align:center;color:#5f7184;font-size:11px;padding:12px 0 30px}
  @media(max-width:520px){.runner-metrics{grid-template-columns:repeat(2,1fr)}.ticket{padding:13px 12px}.ticket-grid{gap:7px}.ticket-item{padding:10px 9px}.ticket-item b{font-size:14px}.ticket-item>span{font-size:12px}.course-tab b{font-size:13px}.course-summary{align-items:flex-start}}
  @media(max-width:360px){.ticket-grid{grid-template-columns:1fr}.course-tab b{font-size:12px}}
  </style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><a class="back" href="/">一覧へ</a></header><section class="hero"><small>${escapeHtml(race.raceDate)} ／ ${escapeHtml(race.venue)}競馬場 ／ ${escapeHtml(race.startTimeJst ?? "時刻未定")}発走</small><h1>${race.raceNo}R ${escapeHtml(race.raceName)}</h1><div class="marks">${markHtml}</div></section>${result}<div class="guide">コースを選ぶと、その予算の買い目だけを表示します。</div><nav class="course-tabs" aria-label="予算コース">${tabs}</nav>${COURSES.map(({ name, budget }, index) => coursePanel(name, budget, bets, finished, index)).join("")}${runnerList(detail)}<div class="version">詳細表示 v8</div></main><script>(()=>{const buttons=[...document.querySelectorAll('[data-course-tab]')];const panels=[...document.querySelectorAll('[data-course-panel]')];const activate=(index)=>{buttons.forEach((button,i)=>{const active=i===index;button.classList.toggle('active',active);button.setAttribute('aria-selected',active?'true':'false')});panels.forEach((panel,i)=>{panel.hidden=i!==index})};buttons.forEach((button,index)=>button.addEventListener('click',()=>activate(index)));activate(${defaultIndex});})();</script></body></html>`;
}
