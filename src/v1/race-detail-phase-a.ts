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
  if ((course === "ライト" || course === "スタンダード" || course === "プレミアム") && ticket) return { course, ticket };
  return { course: null, ticket: value };
}

function numbers(value: string): number[] {
  return (value.match(/\d{1,2}/g) ?? []).map(Number);
}

function combinationLabel(ticket: string, bet: BetRow): string {
  const separator = ticket === "馬単" || ticket === "3連単" ? "→" : "－";
  return numbers(bet.combination).join(separator);
}

function courseBets(course: Course, allBets: BetRow[]): BetRow[] {
  return allBets.filter((bet) => splitType(bet.betType).course === course);
}

function courseStats(course: Course, allBets: BetRow[]): { stake: number; returns: number; profit: number; count: number } {
  const bets = courseBets(course, allBets);
  const stake = bets.reduce((sum, bet) => sum + bet.stakeYen, 0);
  const returns = bets.reduce((sum, bet) => sum + Number(bet.returnYen ?? 0), 0);
  return { stake, returns, profit: returns - stake, count: bets.length };
}

function ticketGrid(ticket: string, bets: BetRow[], finished: boolean): string {
  return `<div class="ticket-grid">${bets.map((bet) => {
    const payout = Number(bet.returnYen ?? 0);
    return `<div class="ticket-item${payout > 0 ? " hit" : ""}">
      <b>${escapeHtml(combinationLabel(ticket, bet))}</b>
      <span>${formatYen(bet.stakeYen)}</span>
      ${finished ? `<small>${payout > 0 ? "的中　" : ""}払戻 ${formatYen(payout)}</small>` : ""}
    </div>`;
  }).join("")}</div>`;
}

function coursePanel(course: Course, budget: number, allBets: BetRow[], finished: boolean, index: number): string {
  const bets = courseBets(course, allBets);
  const stats = courseStats(course, allBets);
  const groups = ORDER.map((ticket) => ({ ticket, bets: bets.filter((bet) => splitType(bet.betType).ticket === ticket) }))
    .filter((group) => group.bets.length > 0);

  const body = groups.length === 0
    ? `<div class="empty">${finished ? "このコースの買い目はありません。" : "買い目を作成中です。"}</div>`
    : groups.map(({ ticket, bets: ticketBets }) => {
        const subtotal = ticketBets.reduce((sum, bet) => sum + bet.stakeYen, 0);
        const payout = ticketBets.reduce((sum, bet) => sum + Number(bet.returnYen ?? 0), 0);
        return `<section class="ticket">
          <div class="ticket-head"><div><b>${ticket}</b><small>${ticketBets.length}点</small></div><strong>${formatYen(subtotal)}</strong></div>
          ${ticketGrid(ticket, ticketBets, finished)}
          ${finished ? `<div class="ticket-return">券種払戻 ${formatYen(payout)}</div>` : ""}
        </section>`;
      }).join("");

  return `<section class="course-panel" id="course-panel-${index}" data-course-panel="${index}" hidden>
    <header class="course-summary">
      <div><h2>${course}</h2><small>上限 ${formatYen(budget)}</small></div>
      <div class="course-total"><span>購入 ${formatYen(stats.stake)}</span>${finished ? `<span>払戻 ${formatYen(stats.returns)}</span><b class="${stats.profit >= 0 ? "plus" : "minus"}">${stats.profit >= 0 ? "+" : ""}${formatYen(stats.profit)}</b>` : ""}</div>
    </header>
    ${body}
  </section>`;
}

function resultSection(detail: RaceDetail): string {
  if (detail.race.status !== "finished") return "";
  const finishers = [...detail.runners]
    .filter((runner) => runner.finishPosition !== null)
    .sort((a, b) => Number(a.finishPosition) - Number(b.finishPosition));
  return `<section class="result"><div class="section-title"><h2>確定結果</h2></div><div class="result-grid">${finishers.slice(0, 3).map((runner) => `<div><span>${runner.finishPosition}着</span><b>${runner.horseNo}</b><strong>${escapeHtml(runner.horseName)}</strong></div>`).join("")}</div></section>`;
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
      <span class="horse-no">${runner.horseNo}</span>
      <div class="horse-info"><b>${mark ? `<em>${mark}</em> ` : ""}${escapeHtml(runner.horseName)}</b><small>${escapeHtml(runner.jockey ?? "騎手未取得")}${runner.sexAge ? ` ／ ${escapeHtml(runner.sexAge)}` : ""}</small></div>
      <div class="runner-side">${finish ? `<strong>${finish}</strong>` : ""}<span>単勝 ${odds !== null ? odds.toFixed(1) : "－"}${runner.popularity ? ` ／ ${runner.popularity}人気` : ""}</span></div>
    </article>`;
  }).join("");
  return `<section class="runners"><div class="section-title"><h2>出走馬</h2><span>${detail.runners.length}頭</span></div>${rows || `<div class="empty">出走馬情報を取得中です。</div>`}</section>`;
}

export function renderPhaseARaceDetail(detail: RaceDetail): string {
  const { race, prediction, predictedRunners, bets } = detail;
  const finished = race.status === "finished";
  const marks = prediction
    ? predictedRunners.slice(0, 4).map((runner, index) => `<span><b>${MARKS[index]}</b>${runner.horseNo} ${escapeHtml(runner.horseName)}</span>`).join("")
    : `<span>予想未生成</span>`;
  const stats = COURSES.map(({ name }) => courseStats(name, bets));
  const standardHasBets = (stats[1]?.count ?? 0) > 0;
  const firstWithBets = stats.findIndex((stat) => stat.count > 0);
  const defaultIndex = standardHasBets ? 1 : Math.max(0, firstWithBets);
  const tabs = COURSES.map(({ name, budget }, index) => {
    const stat = stats[index] ?? { stake: 0, returns: 0, profit: 0, count: 0 };
    const tail = finished && stat.stake > 0
      ? `<span class="${stat.profit >= 0 ? "plus" : "minus"}">${stat.profit >= 0 ? "+" : ""}${formatYen(stat.profit)}</span>`
      : `<span>${stat.count}点</span>`;
    return `<button class="course-tab${index === defaultIndex ? " active" : ""}" type="button" data-course-tab="${index}" aria-selected="${index === defaultIndex ? "true" : "false"}"><b>${name}</b><small>${formatYen(budget)}</small>${tail}</button>`;
  }).join("");

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>${escapeHtml(race.venue)}${race.raceNo}R｜レース探偵</title><style>
  :root{color-scheme:dark;--bg:#071019;--panel:#101a25;--panel2:#0b141e;--line:#2a3b4e;--text:#f4f7fa;--muted:#94a7b9;--green:#52d5a5;--red:#ff7b72}
  *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}a{color:inherit;text-decoration:none}button{font:inherit}.wrap{max-width:860px;margin:auto;padding:14px}.top{display:flex;justify-content:space-between;align-items:center;padding:10px 0 14px}.brand{font-size:22px;font-weight:900;color:var(--green)}.back{border:1px solid var(--line);border-radius:999px;padding:8px 12px;font-size:13px}.hero,.course-panel,.result,.runners{border:1px solid var(--line);border-radius:17px;background:var(--panel);margin-bottom:12px;overflow:hidden}.hero{padding:17px}.hero small,.empty{color:var(--muted)}.hero h1{margin:6px 0 12px;font-size:23px}.marks{display:flex;gap:7px;overflow:auto}.marks span{display:flex;gap:5px;align-items:center;white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:7px 10px}.marks b{color:var(--green)}.buy-title{display:flex;justify-content:space-between;align-items:end;margin:4px 1px 5px}.buy-title h2{margin:0;font-size:19px}.buy-title span{color:var(--muted);font-size:11px}.course-tabs{position:sticky;top:0;z-index:5;display:grid;grid-template-columns:repeat(3,1fr);gap:7px;padding:6px 0 10px;background:linear-gradient(var(--bg) 76%,transparent)}.course-tab{appearance:none;border:1px solid var(--line);background:#0d1722;color:var(--text);border-radius:13px;padding:9px 4px;min-width:0}.course-tab b,.course-tab small,.course-tab span{display:block}.course-tab b{font-size:14px}.course-tab small,.course-tab span{font-size:11px;color:var(--muted);margin-top:2px}.course-tab.active{border-color:var(--green);background:#10231f}.course-tab.active b{color:var(--green)}.plus{color:var(--green)!important}.minus{color:var(--red)!important}.course-panel[hidden]{display:none}.course-summary{display:flex;justify-content:space-between;align-items:center;padding:14px 15px;background:#0d1722}.course-summary h2{margin:0;font-size:19px}.course-summary small{color:var(--muted)}.course-total{text-align:right}.course-total span,.course-total b{display:block;font-size:12px}.course-total b{font-size:16px;margin-top:2px}.ticket{padding:13px 15px;border-top:1px solid var(--line)}.ticket-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}.ticket-head>div{display:flex;gap:8px;align-items:baseline}.ticket-head b{color:#a7ecd5;font-size:18px}.ticket-head small{color:var(--muted);font-size:11px}.ticket-head strong{font-size:18px}.ticket-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.ticket-item{display:grid;grid-template-columns:1fr auto;gap:4px 8px;align-items:center;padding:10px 11px;border:1px solid #30465d;border-radius:11px;background:var(--panel2)}.ticket-item b{white-space:nowrap;font-size:15px}.ticket-item>span{white-space:nowrap;color:#c9d4df;font-size:12px;font-weight:900}.ticket-item small{grid-column:1/-1;color:var(--muted);font-size:10px}.ticket-item.hit{border-color:#3d8b72;background:#0d211d}.ticket-item.hit small{color:var(--green)}.ticket-return{text-align:right;color:var(--muted);font-size:11px;margin-top:8px}.section-title{display:flex;justify-content:space-between;align-items:center;padding:14px 15px;border-bottom:1px solid var(--line)}.section-title h2{margin:0;font-size:18px}.section-title span{color:var(--muted);font-size:12px}.result-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:13px}.result-grid div{display:grid;grid-template-columns:auto auto 1fr;align-items:center;gap:6px;padding:10px;border-radius:11px;background:var(--panel2)}.result-grid span{color:var(--muted);font-size:11px}.result-grid b{font-size:18px;color:var(--green)}.result-grid strong{font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.runner{display:grid;grid-template-columns:40px 1fr auto;gap:10px;align-items:center;padding:12px 13px;border-bottom:1px solid var(--line)}.runner:last-child{border-bottom:0}.runner.top-finish{background:#10211d}.horse-no{display:flex;align-items:center;justify-content:center;width:38px;height:38px;border-radius:10px;background:#1a293a;border:1px solid #3b536c;font-size:18px;font-weight:900}.horse-info b{display:block;font-size:14px}.horse-info em{font-style:normal;color:var(--green)}.horse-info small{display:block;color:var(--muted);font-size:10px;margin-top:3px}.runner-side{text-align:right}.runner-side strong,.runner-side span{display:block}.runner-side strong{color:var(--green);font-size:13px}.runner-side span{color:var(--muted);font-size:10px;margin-top:3px}.empty{padding:20px 15px}.version{text-align:center;color:#5c7084;font-size:10px;padding:12px 0 28px}
  @media(max-width:540px){.ticket{padding:12px}.ticket-grid{gap:7px}.ticket-item{padding:9px}.ticket-item b{font-size:14px}.result-grid{grid-template-columns:1fr}.course-tab b{font-size:13px}.runner{grid-template-columns:38px 1fr}.runner-side{grid-column:2;text-align:left;display:flex;gap:8px}.runner-side span{margin-top:0}}
  @media(max-width:360px){.ticket-grid{grid-template-columns:1fr}.course-tab b{font-size:12px}}
  </style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><a class="back" href="/">一覧へ</a></header><section class="hero"><small>${escapeHtml(race.raceDate)} ／ ${escapeHtml(race.venue)}競馬場 ／ ${escapeHtml(race.startTimeJst ?? "時刻未定")}発走</small><h1>${race.raceNo}R ${escapeHtml(race.raceName)}</h1><div class="marks">${marks}</div></section><div class="buy-title"><h2>買い目</h2><span>コースを切り替えて表示</span></div><nav class="course-tabs" aria-label="予算コース">${tabs}</nav>${COURSES.map(({ name, budget }, index) => coursePanel(name, budget, bets, finished, index)).join("")}${resultSection(detail)}${runnerList(detail)}<div class="version">Phase A 詳細表示</div></main><script>(()=>{const buttons=[...document.querySelectorAll('[data-course-tab]')];const panels=[...document.querySelectorAll('[data-course-panel]')];const activate=(index)=>{buttons.forEach((button,i)=>{const active=i===index;button.classList.toggle('active',active);button.setAttribute('aria-selected',active?'true':'false')});panels.forEach((panel,i)=>{panel.hidden=i!==index})};buttons.forEach((button,index)=>button.addEventListener('click',()=>activate(index)));activate(${defaultIndex});})();</script></body></html>`;
}
