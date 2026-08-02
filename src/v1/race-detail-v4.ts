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

function uniq(values: number[]): number[] {
  return [...new Set(values)];
}

function numberChips(values: number[]): string {
  return values.map((value) => `<span class="number-chip">${value}</span>`).join("");
}

function formationHtml(ticket: string, bets: BetRow[]): string {
  const combos = bets.map((bet) => numbers(bet.combination));

  if (ticket === "単勝" || ticket === "複勝") {
    return `<div class="simple-picks">${numberChips(uniq(combos.flat()))}</div>`;
  }

  if (ticket === "ワイド" || ticket === "馬連") {
    const axes = uniq(combos.map((combo) => combo[0] ?? -1)).filter((value) => value >= 0);
    if (axes.length === 1) {
      const partners = uniq(combos.map((combo) => combo[1] ?? -1)).filter((value) => value >= 0);
      return `<div class="flow-layout"><div class="flow-row"><span class="flow-label">軸</span><div>${numberChips(axes)}</div></div><div class="flow-arrow">↓</div><div class="flow-row"><span class="flow-label">相手</span><div>${numberChips(partners)}</div></div></div>`;
    }
  }

  if (ticket === "馬単") {
    const first = uniq(combos.map((combo) => combo[0] ?? -1)).filter((value) => value >= 0);
    if (first.length === 1) {
      const second = uniq(combos.map((combo) => combo[1] ?? -1)).filter((value) => value >= 0);
      return `<div class="flow-layout"><div class="flow-row"><span class="flow-label">1着</span><div>${numberChips(first)}</div></div><div class="flow-arrow">↓</div><div class="flow-row"><span class="flow-label">2着</span><div>${numberChips(second)}</div></div></div>`;
    }
  }

  if (ticket === "3連複") {
    const common = combos[0]?.filter((value) => combos.every((combo) => combo.includes(value))) ?? [];
    if (common.length === 1) {
      const others = uniq(combos.flat().filter((value) => value !== common[0]));
      return `<div class="flow-layout"><div class="flow-row"><span class="flow-label">軸</span><div>${numberChips(common)}</div></div><div class="flow-arrow">↓</div><div class="flow-row"><span class="flow-label">相手</span><div>${numberChips(others)}</div></div><div class="formation-note">1頭軸流し</div></div>`;
    }
  }

  if (ticket === "3連単") {
    const first = uniq(combos.map((combo) => combo[0] ?? -1)).filter((value) => value >= 0);
    const second = uniq(combos.map((combo) => combo[1] ?? -1)).filter((value) => value >= 0);
    const third = uniq(combos.map((combo) => combo[2] ?? -1)).filter((value) => value >= 0);
    return `<div class="trifecta-layout"><div class="trifecta-row"><span>1着</span><div>${numberChips(first)}</div></div><div class="flow-arrow">↓</div><div class="trifecta-row"><span>2着</span><div>${numberChips(second)}</div></div><div class="flow-arrow">↓</div><div class="trifecta-row"><span>3着</span><div>${numberChips(third)}</div></div><div class="formation-note">フォーメーション ${bets.length}点</div></div>`;
  }

  const arrow = ticket === "馬単" || ticket === "3連単" ? "→" : "－";
  return `<div class="combo-list">${combos.map((combo) => `<span>${combo.join(arrow)}</span>`).join("")}</div>`;
}

function detailLine(ticket: string, bet: BetRow): string {
  const separator = ticket === "馬単" || ticket === "3連単" ? "→" : "－";
  return `${numbers(bet.combination).join(separator)}　${formatYen(bet.stakeYen)}`;
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
        return `<section class="ticket ticket-${ticket}"><div class="ticket-head"><div><b>${ticket}</b><small>${ticketBets.length}点</small></div><strong>${formatYen(subtotal)}</strong></div>${formationHtml(ticket, ticketBets)}<details><summary>購入金額の内訳を見る</summary>${ticketBets.map((bet) => `<div class="line"><span>${escapeHtml(detailLine(ticket, bet))}</span>${finished ? `<em>払戻 ${formatYen(Number(bet.returnYen ?? 0))}</em>` : ""}</div>`).join("")}</details>${finished ? `<div class="payout">券種払戻 ${formatYen(payout)}</div>` : ""}</section>`;
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

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>${escapeHtml(race.venue)}${race.raceNo}R｜レース探偵</title><style>:root{color-scheme:dark;--bg:#081019;--panel:#111a25;--line:#2a3a4c;--text:#f4f7fa;--muted:#9aabba;--green:#52d5a5;--red:#ff7b72}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:860px;margin:auto;padding:14px}a{color:inherit;text-decoration:none}.top{display:flex;justify-content:space-between;align-items:center;padding:10px 0 14px}.brand{font-size:22px;font-weight:900;color:var(--green)}.back{border:1px solid var(--line);border-radius:999px;padding:8px 12px}.hero,.result,.course{background:var(--panel);border:1px solid var(--line);border-radius:18px;margin-bottom:12px}.hero{padding:18px}.hero small,.course small,.empty,summary{color:var(--muted)}.hero h1{margin:6px 0 12px;font-size:24px}.marks,.result div{display:flex;gap:7px;overflow:auto}.marks span,.result span{white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:7px 10px}.result{padding:15px}.result h2{margin:0 0 10px}.course{overflow:hidden}.course>header{display:flex;justify-content:space-between;align-items:center;padding:15px;background:#0d1620}.course h2{margin:0}.course-total{text-align:right}.course-total span,.course-total b{display:block}.plus{color:var(--green)}.minus{color:var(--red)}.ticket{padding:14px 15px;border-top:1px solid var(--line)}.ticket-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:13px}.ticket-head>div{display:flex;align-items:baseline;gap:8px}.ticket-head b{color:#a5ecd4;font-size:18px}.ticket-head small{font-size:12px}.ticket-head strong{font-size:20px}.simple-picks,.flow-row>div,.trifecta-row>div{display:flex;gap:8px;flex-wrap:wrap}.number-chip{display:inline-flex;align-items:center;justify-content:center;min-width:44px;height:44px;padding:0 12px;border-radius:12px;background:#182739;border:1px solid #38506a;font-size:20px;font-weight:900}.flow-layout,.trifecta-layout{padding:14px;border-radius:14px;background:#0b141e;border:1px solid #26384a}.flow-row,.trifecta-row{display:grid;grid-template-columns:52px 1fr;gap:10px;align-items:center}.flow-label,.trifecta-row>span{color:var(--muted);font-size:13px;font-weight:800}.flow-arrow{text-align:center;color:#6f8398;font-size:18px;line-height:1.2;padding:3px 0}.formation-note{text-align:right;color:var(--muted);font-size:12px;margin-top:10px}.combo-list{display:flex;gap:7px;flex-wrap:wrap}.combo-list span{padding:7px 9px;border-radius:9px;background:#182739;border:1px solid #38506a;font-weight:800}.ticket details{border-top:1px dashed #31445a;padding-top:10px;margin-top:12px}.ticket summary{cursor:pointer;font-size:13px}.line{display:flex;justify-content:space-between;gap:12px;padding:7px 0;font-size:13px}.line em{font-style:normal;color:var(--muted);white-space:nowrap}.payout{text-align:right;color:var(--muted);font-size:12px;margin-top:7px}.empty{padding:20px 15px}.version{text-align:center;color:#5f7184;font-size:11px;padding:12px 0 30px}@media(max-width:520px){.course>header{align-items:flex-start}.line{display:block}.line em{display:block;margin-top:3px}.number-chip{min-width:40px;height:40px;font-size:18px}.flow-row,.trifecta-row{grid-template-columns:44px 1fr}.ticket{padding:13px 12px}}</style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><a class="back" href="/">一覧へ</a></header><section class="hero"><small>${escapeHtml(race.raceDate)} ／ ${escapeHtml(race.venue)}競馬場 ／ ${escapeHtml(race.startTimeJst ?? "時刻未定")}発走</small><h1>${race.raceNo}R ${escapeHtml(race.raceName)}</h1><div class="marks">${markHtml}</div></section>${result}${COURSES.map(({ name, budget }) => courseSection(name, budget, bets, finished)).join("")}<div class="version">詳細表示 v5</div></main></body></html>`;
}
