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
      ${finished ? `<small>払戻 ${formatYen(payout)}</small>` : ""}
    </div>`;
  }).join("")}</div>`;
}

function courseSection(course: Course, budget: number, allBets: BetRow[], finished: boolean): string {
  const bets = allBets.filter((bet) => splitType(bet.betType).course === course);
  const stake = bets.reduce((sum, bet) => sum + bet.stakeYen, 0);
  const returns = bets.reduce((sum, bet) => sum + Number(bet.returnYen ?? 0), 0);
  const profit = returns - stake;
  const groups = ORDER.map((ticket) => ({
    ticket,
    bets: bets.filter((bet) => splitType(bet.betType).ticket === ticket)
  })).filter((group) => group.bets.length > 0);

  const body = groups.length === 0
    ? `<div class="empty">${finished ? "このレースの3コース買い目は未生成です。" : "買い目を作成中です。"}</div>`
    : groups.map(({ ticket, bets: ticketBets }) => {
        const subtotal = ticketBets.reduce((sum, bet) => sum + bet.stakeYen, 0);
        const payout = ticketBets.reduce((sum, bet) => sum + Number(bet.returnYen ?? 0), 0);
        return `<section class="ticket ticket-${ticket}">
          <div class="ticket-head">
            <div><b>${ticket}</b><small>${ticketBets.length}点</small></div>
            <strong>${formatYen(subtotal)}</strong>
          </div>
          ${ticketGrid(ticket, ticketBets, finished)}
          ${finished ? `<div class="payout">券種払戻 ${formatYen(payout)}</div>` : ""}
        </section>`;
      }).join("");

  return `<section class="course"><header><div><h2>${course}</h2><small>予算 ${formatYen(budget)}</small></div><div class="course-total"><span>購入 ${formatYen(stake)}</span>${finished ? `<b class="${profit >= 0 ? "plus" : "minus"}">${profit >= 0 ? "+" : ""}${formatYen(profit)}</b>` : ""}</div></header>${body}</section>`;
}

export function renderRaceDetailV4(detail: RaceDetail): string {
  const { race, runners, prediction, predictedRunners, bets } = detail;
  const finished = race.status === "finished";
  const marks = ["◎", "○", "▲", "△"];
  const markHtml = prediction
    ? predictedRunners.slice(0, 4).map((runner, index) => `<span>${marks[index]} ${runner.horseNo} ${escapeHtml(runner.horseName)}</span>`).join("")
    : `<span>予想未生成</span>`;
  const finishers = [...runners].filter((runner) => runner.finishPosition !== null).sort((a, b) => Number(a.finishPosition) - Number(b.finishPosition));
  const result = finished ? `<section class="result"><h2>確定結果</h2><div>${finishers.slice(0, 3).map((runner) => `<span>${runner.finishPosition}着 <b>${runner.horseNo}</b> ${escapeHtml(runner.horseName)}</span>`).join("")}</div></section>` : "";

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>${escapeHtml(race.venue)}${race.raceNo}R｜レース探偵</title><style>
  :root{color-scheme:dark;--bg:#081019;--panel:#111a25;--line:#2a3a4c;--text:#f4f7fa;--muted:#9aabba;--green:#52d5a5;--red:#ff7b72}
  *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:860px;margin:auto;padding:14px}a{color:inherit;text-decoration:none}.top{display:flex;justify-content:space-between;align-items:center;padding:10px 0 14px}.brand{font-size:22px;font-weight:900;color:var(--green)}.back{border:1px solid var(--line);border-radius:999px;padding:8px 12px}.hero,.result,.course{background:var(--panel);border:1px solid var(--line);border-radius:18px;margin-bottom:12px}.hero{padding:18px}.hero small,.course small,.empty{color:var(--muted)}.hero h1{margin:6px 0 12px;font-size:24px}.marks,.result div{display:flex;gap:7px;overflow:auto}.marks span,.result span{white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:7px 10px}.result{padding:15px}.result h2{margin:0 0 10px}.course{overflow:hidden}.course>header{display:flex;justify-content:space-between;align-items:center;padding:15px;background:#0d1620}.course h2{margin:0}.course-total{text-align:right}.course-total span,.course-total b{display:block}.plus{color:var(--green)}.minus{color:var(--red)}.ticket{padding:14px 15px;border-top:1px solid var(--line)}.ticket-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:11px}.ticket-head>div{display:flex;align-items:baseline;gap:8px}.ticket-head b{color:#a5ecd4;font-size:18px}.ticket-head small{font-size:12px}.ticket-head strong{font-size:20px}.ticket-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.ticket-item{display:grid;grid-template-columns:1fr auto;gap:4px 8px;align-items:center;padding:11px 12px;border-radius:12px;background:#0b141e;border:1px solid #30465d}.ticket-item b{font-size:16px;letter-spacing:.2px;white-space:nowrap}.ticket-item>span{font-size:13px;font-weight:800;color:#c6d1dc;white-space:nowrap}.ticket-item small{grid-column:1/-1;color:var(--muted);font-size:11px}.ticket-item.hit{border-color:#3e8c73;background:#0d211d}.ticket-item.hit small{color:var(--green)}.payout{text-align:right;color:var(--muted);font-size:12px;margin-top:9px}.empty{padding:20px 15px}.version{text-align:center;color:#5f7184;font-size:11px;padding:12px 0 30px}.guide{color:var(--muted);font-size:12px;margin:-3px 0 10px}
  @media(max-width:520px){.course>header{align-items:flex-start}.ticket{padding:13px 12px}.ticket-grid{gap:7px}.ticket-item{padding:10px 9px}.ticket-item b{font-size:14px}.ticket-item>span{font-size:12px}}
  @media(max-width:360px){.ticket-grid{grid-template-columns:1fr}}
  </style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><a class="back" href="/">一覧へ</a></header><section class="hero"><small>${escapeHtml(race.raceDate)} ／ ${escapeHtml(race.venue)}競馬場 ／ ${escapeHtml(race.startTimeJst ?? "時刻未定")}発走</small><h1>${race.raceNo}R ${escapeHtml(race.raceName)}</h1><div class="marks">${markHtml}</div></section>${result}<div class="guide">実際に購入する組み合わせと金額だけを表示しています。</div>${COURSES.map(({ name, budget }) => courseSection(name, budget, bets, finished)).join("")}<div class="version">詳細表示 v6</div></main></body></html>`;
}
