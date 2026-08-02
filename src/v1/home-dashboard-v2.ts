import type { CourseMetric } from "./course-db.js";
import { escapeHtml, formatYen } from "./utils.js";

type CourseName = "ライト" | "スタンダード" | "プレミアム";

export interface DashboardRaceV2 {
  raceId: string;
  raceDate: string;
  venue: string;
  raceNo: number;
  raceName: string;
  startTimeJst: string | null;
  startTimeUtc: string | null;
  status: string;
  predictionStatus: string | null;
  generatedAt: string | null;
  lockedAt: string | null;
  topHorseNo: number | null;
  topHorseName: string | null;
  betCount: number;
  lightStake: number;
  lightReturn: number;
  standardStake: number;
  standardReturn: number;
  premiumStake: number;
  premiumReturn: number;
}

const COURSES: Array<{ name: CourseName; budget: string; key: "light" | "standard" | "premium" }> = [
  { name: "ライト", budget: "2,000円", key: "light" },
  { name: "スタンダード", budget: "5,000円", key: "standard" },
  { name: "プレミアム", budget: "10,000円", key: "premium" }
];

function dateLabel(date: string): string {
  const m = date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return date;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  const wd = ["日", "月", "火", "水", "木", "金", "土"][new Date(Date.UTC(y, mo - 1, d)).getUTCDay()] ?? "";
  return `${mo}月${d}日（${wd}）`;
}

function timeLabel(value: string | null): string {
  if (!value) return "時刻未定";
  return value.match(/(\d{1,2}:\d{2})/)?.[1] ?? value;
}

function publishTime(race: DashboardRaceV2): string {
  if (!race.startTimeUtc) return "オッズ取得後に公開";
  const ms = new Date(race.startTimeUtc).getTime() - 60 * 60_000;
  if (!Number.isFinite(ms)) return "オッズ取得後に公開";
  return `${new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date(ms))}ごろ公開`;
}

function raceState(race: DashboardRaceV2): { label: string; detail: string; cls: string } {
  const courseValues = [
    [race.lightStake, race.lightReturn],
    [race.standardStake, race.standardReturn],
    [race.premiumStake, race.premiumReturn]
  ];

  if (race.status === "finished") {
    const totalStake = courseValues.reduce((sum, [stake]) => sum + stake, 0);
    const totalReturn = courseValues.reduce((sum, [, ret]) => sum + ret, 0);
    const hitCount = courseValues.filter(([stake, ret]) => stake > 0 && ret > 0).length;
    if (totalStake === 0) return { label: "検証対象外", detail: "現行モデルの固定買い目なし", cls: "neutral" };
    if (hitCount > 0) {
      const profit = totalReturn - totalStake;
      return { label: `的中 ${hitCount}/3`, detail: `合計 ${profit >= 0 ? "+" : ""}${formatYen(profit)}`, cls: "hit" };
    }
    return { label: "不的中", detail: `合計 -${formatYen(totalStake)}`, cls: "miss" };
  }

  if (race.betCount > 0 && race.predictionStatus === "locked") {
    return { label: "買い目確定", detail: "発走前固定済み", cls: "open" };
  }
  if (race.betCount > 0) {
    return { label: "買い目公開中", detail: "発走15分前まで更新", cls: "open" };
  }
  if (race.predictionStatus === "locked") {
    return { label: "見送り", detail: "固定時点で購入対象なし", cls: "skip" };
  }
  if (race.predictionStatus) {
    return { label: "買い目調整中", detail: "発走15分前まで更新", cls: "wait" };
  }
  return { label: "公開待ち", detail: publishTime(race), cls: "wait" };
}

function metricsHtml(metrics: CourseMetric[]): string {
  const byName = new Map(metrics.map((metric) => [metric.course, metric]));
  return COURSES.map((course) => {
    const metric = byName.get(course.name);
    const roi = metric?.roiPct == null ? "—" : `${metric.roiPct.toFixed(1)}%`;
    const profit = metric?.profitYen ?? 0;
    return `<a class="metric ${course.key}" href="/performance"><div><b>${course.name}</b><small>${course.budget}</small></div><strong class="${profit >= 0 ? "plus" : "minus"}">${roi}</strong><span>収支 ${profit >= 0 ? "+" : ""}${formatYen(profit)}</span></a>`;
  }).join("");
}

export function renderDashboardV2(races: DashboardRaceV2[], metrics: CourseMetric[]): string {
  const dates = [...new Set(races.map((race) => race.raceDate))];
  const dateButtons = dates.map((date, index) => `<button type="button" class="day-chip ${index === 0 ? "active" : ""}" data-scroll-target="day-${date}">${dateLabel(date)}</button>`).join("");

  const daySections = dates.map((date) => {
    const dayRaces = races.filter((race) => race.raceDate === date);
    const venues = [...new Set(dayRaces.map((race) => race.venue))];
    const venueButtons = venues.map((venue, index) => `<button type="button" class="venue-chip ${index === 0 ? "active" : ""}" data-scroll-target="venue-${date}-${encodeURIComponent(venue)}">${escapeHtml(venue)}</button>`).join("");
    const venueSections = venues.map((venue) => {
      const cards = dayRaces.filter((race) => race.venue === venue).map((race) => {
        const state = raceState(race);
        const pick = race.topHorseNo ? `◎ ${race.topHorseNo} ${escapeHtml(race.topHorseName ?? "")}` : "予想計算前";
        return `<a class="race-card ${state.cls}" href="/races/${encodeURIComponent(race.raceId)}"><div class="race-top"><b>${race.raceNo}R</b><span>${timeLabel(race.startTimeJst)}</span></div><h3>${escapeHtml(race.raceName)}</h3><div class="pick">${pick}</div><div class="state ${state.cls}">${state.label}</div><small>${escapeHtml(state.detail)}</small></a>`;
      }).join("");
      return `<section class="venue" id="venue-${date}-${encodeURIComponent(venue)}"><div class="venue-title"><b>${escapeHtml(venue)}競馬場</b><span>横にスワイプ</span></div><div class="race-strip">${cards}</div></section>`;
    }).join("");
    return `<section class="day" id="day-${date}"><div class="day-title"><h2>${dateLabel(date)}</h2><span>${dayRaces.length}R</span></div><div class="venue-chips">${venueButtons}</div>${venueSections}</section>`;
  }).join("");

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#081019"><title>予想一覧｜レース探偵</title><style>
  :root{color-scheme:dark;--bg:#081019;--panel:#111a25;--line:#29394b;--text:#f1f5f9;--muted:#9aacbd;--green:#4fd1a1;--red:#ff7b72}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:linear-gradient(#081019,#0b1119);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:1040px;margin:auto;padding:14px}a{color:inherit;text-decoration:none}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0 16px}.brand{font-size:23px;font-weight:900}.brand i{font-style:normal;color:var(--green)}nav{display:flex;gap:7px;overflow:auto}nav a{white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:8px 11px;background:#101925;font-size:13px}.metrics{display:grid;grid-template-columns:repeat(3,minmax(210px,1fr));gap:9px;overflow:auto;margin:4px 0 14px;padding-bottom:3px}.metric{display:grid;grid-template-columns:1fr auto;gap:4px;border:1px solid var(--line);border-radius:15px;padding:13px;background:var(--panel);min-width:210px}.metric b,.metric small,.metric span{display:block}.metric small,.metric span{color:var(--muted);font-size:12px}.metric strong{font-size:22px}.plus{color:var(--green)}.minus{color:var(--red)}.day-nav,.venue-chips{display:flex;gap:7px;overflow:auto;scrollbar-width:none}.day-nav{position:sticky;top:0;z-index:10;background:rgba(8,16,25,.96);backdrop-filter:blur(12px);padding:8px 0 10px}.day-chip,.venue-chip{appearance:none;color:var(--text);white-space:nowrap;border:1px solid var(--line);background:#101925;border-radius:999px;padding:8px 12px;font-size:13px}.day-chip.active,.venue-chip.active{border-color:#3a806c;color:#83ecc8}.day{scroll-margin-top:62px;margin:14px 0 30px}.day-title,.venue-title,.race-top{display:flex;justify-content:space-between;align-items:center}.day-title h2{margin:0;font-size:22px}.day-title span,.venue-title span{color:var(--muted);font-size:12px}.venue{scroll-margin-top:112px;margin-top:17px}.venue-title{margin:0 2px 8px}.venue-title b{font-size:18px}.race-strip{display:flex;gap:10px;overflow-x:auto;scroll-snap-type:x mandatory;padding:1px 1px 10px;scrollbar-width:none}.race-card{flex:0 0 245px;scroll-snap-align:start;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:14px;min-height:190px}.race-card.hit,.race-card.open{border-color:#347a65}.race-card.miss{border-color:#74403d}.race-card.neutral,.race-card.skip{opacity:.76}.race-top b{font-size:20px}.race-top span{color:var(--muted)}.race-card h3{font-size:15px;min-height:44px;margin:12px 0 8px}.pick{font-weight:800;color:#8ce8ca;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.state{display:inline-block;border-radius:999px;padding:4px 9px;margin-top:13px;font-size:12px;font-weight:800}.state.hit,.state.open{background:#153b31;color:#80ebc5}.state.miss{background:#3b1d1d;color:#ff9b95}.state.wait{background:#1b2a3b;color:#a9c6e5}.state.skip,.state.neutral{background:#2b2b2b;color:#bbb}.race-card small{display:block;color:var(--muted);margin-top:7px}.footer{color:var(--muted);font-size:12px;padding:30px 2px 50px}@media(max-width:700px){.top{align-items:flex-start}.brand{max-width:90px}.metrics{grid-template-columns:repeat(3,220px)}.race-card{flex-basis:78vw;max-width:280px}}
  </style></head><body><main class="wrap"><header class="top"><a href="/" class="brand"><i>レース</i>探偵</a><nav><a href="/">予想</a><a href="/performance">成績</a><a href="/backtest/2026-08-01">8/1検証</a><a href="/methodology">予想方法</a></nav></header><section class="metrics">${metricsHtml(metrics)}</section><div class="day-nav">${dateButtons}</div>${daySections || '<p>レースデータを準備中です。</p>'}<footer class="footer">買い目はオッズ取得後に公開し、発走15分前に固定します。</footer></main><script>(()=>{if(location.hash){history.replaceState(null,"",location.pathname+location.search);}requestAnimationFrame(()=>window.scrollTo({top:0,left:0,behavior:"auto"}));document.querySelectorAll("[data-scroll-target]").forEach((button)=>{button.addEventListener("click",()=>{const id=button.getAttribute("data-scroll-target");const target=id?document.getElementById(id):null;if(!target)return;const group=button.parentElement;group?.querySelectorAll("button").forEach((item)=>item.classList.remove("active"));button.classList.add("active");target.scrollIntoView({behavior:"smooth",block:"start"});});});})();</script></body></html>`;
}
