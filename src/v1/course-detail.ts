import type { RaceDetail } from "./db.js";
import { escapeHtml, formatYen } from "./utils.js";

type BetRow = RaceDetail["bets"][number];
type CourseName = "ライト" | "スタンダード" | "プレミアム";

const COURSES: Array<{ name: CourseName; budget: string; cls: string }> = [
  { name: "ライト", budget: "2,000円", cls: "light" },
  { name: "スタンダード", budget: "5,000円", cls: "standard" },
  { name: "プレミアム", budget: "10,000円", cls: "premium" }
];

const TYPE_ORDER = ["単勝", "複勝", "ワイド", "馬連", "馬単", "3連複", "3連単"];

function ticketType(bet: BetRow): string {
  return bet.betType.includes("｜") ? bet.betType.split("｜").pop() ?? bet.betType : bet.betType;
}

function courseOf(bet: BetRow): CourseName | null {
  const name = bet.betType.split("｜")[0];
  return name === "ライト" || name === "スタンダード" || name === "プレミアム" ? name : null;
}

function nums(combination: string): number[] {
  return combination.split("-").map(Number).filter(Number.isFinite);
}

function unique(values: number[]): number[] {
  return [...new Set(values)];
}

function formation(type: string, bets: BetRow[]): string {
  const combos = bets.map((bet) => nums(bet.combination));
  if (type === "単勝" || type === "複勝") return unique(combos.flat()).join("・");
  if (type === "ワイド" || type === "馬連") {
    const firsts = unique(combos.map((c) => c[0]).filter((n): n is number => n !== undefined));
    if (firsts.length === 1) {
      const partners = unique(combos.map((c) => c[1]).filter((n): n is number => n !== undefined));
      return `${firsts[0]}－${partners.join("・")}（軸流し）`;
    }
    return combos.map((c) => c.join("－")).join(" / ");
  }
  if (type === "馬単") {
    const firsts = unique(combos.map((c) => c[0]).filter((n): n is number => n !== undefined));
    if (firsts.length === 1) {
      const seconds = unique(combos.map((c) => c[1]).filter((n): n is number => n !== undefined));
      return `${firsts[0]} → ${seconds.join("・")}（1着固定）`;
    }
    return combos.map((c) => c.join("→")).join(" / ");
  }
  if (type === "3連複") {
    const common = combos.length ? combos[0].filter((n) => combos.every((c) => c.includes(n))) : [];
    if (common.length === 1) {
      const others = unique(combos.flat().filter((n) => n !== common[0]));
      return `${common[0]}－${others.join("・")}（1頭軸流し）`;
    }
    return combos.map((c) => [...c].sort((a, b) => a - b).join("－")).join(" / ");
  }
  if (type === "3連単") {
    const firsts = unique(combos.map((c) => c[0]).filter((n): n is number => n !== undefined));
    if (firsts.length === 1) {
      const second = unique(combos.map((c) => c[1]).filter((n): n is number => n !== undefined));
      const third = unique(combos.map((c) => c[2]).filter((n): n is number => n !== undefined));
      return `${firsts[0]} → ${second.join("・")} → ${third.join("・")}（1着固定）`;
    }
    return combos.map((c) => c.join("→")).join(" / ");
  }
  return bets.map((b) => b.combination).join(" / ");
}

function breakdown(type: string, bets: BetRow[]): string {
  const arrow = type === "馬単" || type === "3連単" ? "→" : "－";
  return bets.map((b) => `${nums(b.combination).join(arrow)} ${formatYen(b.stakeYen)}`).join("　");
}

function courseBlock(course: typeof COURSES[number], bets: BetRow[], finished: boolean): string {
  const list = bets.filter((b) => courseOf(b) === course.name);
  const stake = list.reduce((n, b) => n + b.stakeYen, 0);
  const returns = list.reduce((n, b) => n + (b.returnYen ?? 0), 0);
  const profit = returns - stake;
  const groups = TYPE_ORDER.map((type) => ({ type, bets: list.filter((b) => ticketType(b) === type) })).filter((g) => g.bets.length);
  const content = groups.length ? groups.map((group) => {
    const total = group.bets.reduce((n, b) => n + b.stakeYen, 0);
    const payout = group.bets.reduce((n, b) => n + (b.returnYen ?? 0), 0);
    return `<div class="ticket"><div class="ticket-main"><span class="type">${group.type}</span><b>${escapeHtml(formation(group.type, group.bets))}</b><strong>${formatYen(total)}</strong></div><div class="breakdown">${escapeHtml(breakdown(group.type, group.bets))}</div>${finished ? `<div class="settle">払戻 ${formatYen(payout)}</div>` : ""}</div>`;
  }).join("") : `<div class="empty">${finished ? "このモデルでは検証対象外です。" : "買い目を調整中です。発走15分前まで更新します。"}</div>`;
  return `<section class="course ${course.cls}"><div class="course-head"><div><h2>${course.name}</h2><span>予算 ${course.budget}</span></div>${finished && list.length ? `<div class="course-result"><small>収支</small><b class="${profit >= 0 ? "plus" : "minus"}">${profit >= 0 ? "+" : ""}${formatYen(profit)}</b></div>` : `<b>${formatYen(stake)}</b>`}</div>${content}</section>`;
}

export function renderCompactRace(detail: RaceDetail): string {
  const { race, runners, prediction, predictedRunners, bets } = detail;
  const finished = race.status === "finished";
  const finishers = [...runners].filter((r) => r.finishPosition !== null).sort((a, b) => (a.finishPosition ?? 99) - (b.finishPosition ?? 99));
  const marks = ["◎", "○", "▲", "△"];
  const markHtml = prediction ? predictedRunners.slice(0, 4).map((p, i) => `<span>${marks[i]} ${p.horseNo} ${escapeHtml(p.horseName)}</span>`).join("") : "<span>予想計算中</span>";
  const result = finished ? `<section class="result"><h2>結果</h2><div class="finish">${finishers.slice(0, 3).map((r) => `<span>${r.finishPosition}着 <b>${r.horseNo}</b> ${escapeHtml(r.horseName)}</span>`).join("")}</div></section>` : "";
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>${escapeHtml(race.venue)}${race.raceNo}R｜レース探偵</title><style>
  :root{color-scheme:dark;--bg:#081019;--panel:#111a25;--line:#2b3b4e;--text:#f3f6fa;--muted:#9eb0c1;--green:#52d5a5;--red:#ff7b72}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:850px;margin:auto;padding:14px}a{color:inherit;text-decoration:none}.top{display:flex;justify-content:space-between;align-items:center;padding:12px 0}.brand{font-weight:900;font-size:21px;color:var(--green)}.back{border:1px solid var(--line);border-radius:999px;padding:7px 11px}.hero,.result,.course{border:1px solid var(--line);border-radius:18px;background:var(--panel);margin-bottom:12px}.hero{padding:18px;background:linear-gradient(135deg,#163047,#102a22)}.hero small,.course-head span,.breakdown,.settle{color:var(--muted)}.hero h1{font-size:25px;margin:5px 0}.marks{display:flex;gap:7px;overflow:auto;margin-top:13px}.marks span{white-space:nowrap;border:1px solid #3b6e61;border-radius:999px;padding:6px 10px}.result{padding:15px}.result h2{margin:0 0 9px}.finish{display:flex;gap:7px;overflow:auto}.finish span{white-space:nowrap;border:1px solid #705e38;border-radius:999px;padding:6px 10px}.course{overflow:hidden}.course.light{border-color:#356c60}.course.standard{border-color:#6b6038}.course.premium{border-color:#754c69}.course-head{display:flex;justify-content:space-between;align-items:center;padding:14px 15px;background:#0d1620}.course-head h2{margin:0;font-size:20px}.course-head b{font-size:18px}.course-result{text-align:right}.course-result small,.course-result b{display:block}.plus{color:var(--green)}.minus{color:var(--red)}.ticket{padding:13px 15px;border-top:1px solid var(--line)}.ticket-main{display:grid;grid-template-columns:65px 1fr auto;gap:9px;align-items:center}.ticket-main .type{font-weight:900;color:#a8ead4}.ticket-main b{font-size:15px}.ticket-main strong{white-space:nowrap}.breakdown{font-size:12px;margin:7px 0 0 74px;line-height:1.7}.settle{text-align:right;font-size:12px;margin-top:5px}.empty{padding:20px 15px;color:var(--muted)}.note{color:var(--muted);font-size:12px;padding:12px 2px 35px}@media(max-width:520px){.ticket-main{grid-template-columns:58px 1fr}.ticket-main strong{grid-column:2}.breakdown{margin-left:67px}.hero h1{font-size:22px}}
  </style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><a class="back" href="/">一覧へ</a></header><section class="hero"><small>${escapeHtml(race.raceDate)} ／ ${escapeHtml(race.venue)}競馬場 ／ ${escapeHtml(race.startTimeJst ?? "時刻未定")}発走</small><h1>${race.raceNo}R ${escapeHtml(race.raceName)}</h1><div class="marks">${markHtml}</div></section>${result}${COURSES.map((c) => courseBlock(c, bets, finished)).join("")}<div class="note">券種は単勝→複勝→ワイド→馬連→馬単→3連複→3連単の順です。フォーメーション表示の下に、実際の購入金額の内訳を表示しています。</div></main></body></html>`;
}
