import type { CourseMetric } from "./course-db.js";
import { escapeHtml, formatYen } from "./utils.js";

type CourseName = "ライト" | "スタンダード" | "プレミアム";

interface DashboardRace {
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

export async function getDashboardRaces(db: D1Database, modelVersion: string): Promise<DashboardRace[]> {
  const rows = await db.prepare(`
    SELECT r.race_id AS raceId, r.race_date AS raceDate, r.venue, r.race_no AS raceNo,
      r.race_name AS raceName, r.start_time_jst AS startTimeJst, r.start_time_utc AS startTimeUtc,
      r.status,
      p.status AS predictionStatus, p.generated_at AS generatedAt, p.locked_at AS lockedAt,
      (SELECT horse_no FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseNo,
      (SELECT horse_name FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseName,
      COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id),0) AS betCount,
      COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'ライト｜%'),0) AS lightStake,
      COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'ライト｜%'),0) AS lightReturn,
      COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'スタンダード｜%'),0) AS standardStake,
      COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'スタンダード｜%'),0) AS standardReturn,
      COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'プレミアム｜%'),0) AS premiumStake,
      COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'プレミアム｜%'),0) AS premiumReturn
    FROM rt_races r
    LEFT JOIN rt_predictions p ON p.race_id=r.race_id AND p.model_version=?
    WHERE r.race_date >= date('now','+9 hours','-2 day')
    ORDER BY r.race_date, r.venue, r.race_no
    LIMIT 120
  `).bind(modelVersion).all<DashboardRace>();
  return rows.results.map((row) => ({
    ...row,
    raceNo: Number(row.raceNo), betCount: Number(row.betCount),
    lightStake: Number(row.lightStake), lightReturn: Number(row.lightReturn),
    standardStake: Number(row.standardStake), standardReturn: Number(row.standardReturn),
    premiumStake: Number(row.premiumStake), premiumReturn: Number(row.premiumReturn)
  }));
}

function dateLabel(date: string): string {
  const m = date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return date;
  const y = Number(m[1]), mo = Number(m[2]), d = Number(m[3]);
  const wd = ["日", "月", "火", "水", "木", "金", "土"][new Date(Date.UTC(y, mo - 1, d)).getUTCDay()];
  return `${mo}月${d}日（${wd}）`;
}

function jstTime(value: string | null): string {
  if (!value) return "時刻未定";
  const match = value.match(/(\d{1,2}:\d{2})/);
  return match?.[1] ?? value;
}

function publishTime(race: DashboardRace): string {
  if (!race.startTimeUtc) return "オッズ取得後に公開";
  const ms = new Date(race.startTimeUtc).getTime() - 60 * 60_000;
  if (!Number.isFinite(ms)) return "オッズ取得後に公開";
  return `${new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(ms))}ごろ公開`;
}

function resultSummary(race: DashboardRace): { label: string; cls: string; detail: string } {
  const values = [
    [race.lightStake, race.lightReturn],
    [race.standardStake, race.standardReturn],
    [race.premiumStake, race.premiumReturn]
  ];
  const hitCourses = values.filter(([stake, ret]) => stake > 0 && ret > 0).length;
  const totalStake = values.reduce((n, [stake]) => n + stake, 0);
  const totalReturn = values.reduce((n, [, ret]) => n + ret, 0);
  if (totalStake === 0) return { label: "見送り", cls: "skip", detail: "固定買い目なし" };
  if (hitCourses > 0) return { label: `的中 ${hitCourses}/3`, cls: "hit", detail: `3コース合計 ${totalReturn - totalStake >= 0 ? "+" : ""}${formatYen(totalReturn - totalStake)}` };
  return { label: "不的中", cls: "miss", detail: `3コース合計 -${formatYen(totalStake)}` };
}

function stateSummary(race: DashboardRace): { label: string; cls: string; detail: string } {
  if (race.status === "finished") return resultSummary(race);
  if (race.betCount > 0 && race.predictionStatus === "locked") return { label: "買い目確定", cls: "open", detail: "発走前固定済み" };
  if (race.betCount > 0) return { label: "買い目公開中", cls: "open", detail: "発走15分前に確定" };
  if (race.predictionStatus) return { label: "見送り", cls: "skip", detail: "購入条件を満たす券なし" };
  return { label: "公開待ち", cls: "wait", detail: publishTime(race) };
}

function metricCards(metrics: CourseMetric[]): string {
  const byName = new Map(metrics.map((m) => [m.course, m]));
  return `<div class="course-metrics">${COURSES.map((c) => {
    const m = byName.get(c.name);
    const roi = m?.roiPct == null ? "—" : `${m.roiPct.toFixed(1)}%`;
    const profit = m?.profitYen ?? 0;
    return `<a href="/performance" class="course-metric ${c.key}"><div><b>${c.name}</b><small>${c.budget}</small></div><strong class="${profit >= 0 ? "plus" : "minus"}">${roi}</strong><span>収支 ${profit >= 0 ? "+" : ""}${formatYen(profit)}</span></a>`;
  }).join("")}</div>`;
}

export function renderDashboard(races: DashboardRace[], metrics: CourseMetric[]): string {
  const dates = [...new Set(races.map((r) => r.raceDate))];
  const dateTabs = dates.map((date, i) => `<a href="#day-${date}" class="day-chip ${i === 0 ? "active" : ""}">${dateLabel(date)}</a>`).join("");
  const dateSections = dates.map((date) => {
    const dayRaces = races.filter((r) => r.raceDate === date);
    const venues = [...new Set(dayRaces.map((r) => r.venue))];
    return `<section class="day" id="day-${date}"><div class="day-title"><h2>${dateLabel(date)}</h2><span>${dayRaces.length}R</span></div><div class="venue-chips">${venues.map((v, i) => `<a href="#${date}-${encodeURIComponent(v)}" class="venue-chip ${i === 0 ? "active" : ""}">${escapeHtml(v)}</a>`).join("")}</div>${venues.map((venue) => {
      const list = dayRaces.filter((r) => r.venue === venue);
      return `<section class="venue" id="${date}-${encodeURIComponent(venue)}"><div class="venue-title"><b>${escapeHtml(venue)}競馬場</b><span>横にスワイプ</span></div><div class="race-strip">${list.map((r) => {
        const state = stateSummary(r);
        const marks = r.topHorseNo ? `<div class="pick">◎ ${r.topHorseNo} ${escapeHtml(r.topHorseName ?? "")}</div>` : `<div class="pick muted">予想計算前</div>`;
        return `<a class="race-card ${state.cls}" href="/races/${encodeURIComponent(r.raceId)}"><div class="race-top"><b>${r.raceNo}R</b><span>${jstTime(r.startTimeJst)}</span></div><h3>${escapeHtml(r.raceName)}</h3>${marks}<div class="state ${state.cls}">${state.label}</div><small>${escapeHtml(state.detail)}</small></a>`;
      }).join("")}</div></section>`;
    }).join("")}</section>`;
  }).join("");

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#081019"><title>予想一覧｜レース探偵</title><style>
  :root{color-scheme:dark;--bg:#081019;--panel:#111a25;--line:#29394b;--text:#f1f5f9;--muted:#9aacbd;--green:#4fd1a1;--red:#ff7b72;--gold:#ffd166}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:linear-gradient(#081019,#0b1119);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:1040px;margin:auto;padding:14px}a{color:inherit;text-decoration:none}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0 16px}.brand{font-size:23px;font-weight:900}.brand i{font-style:normal;color:var(--green)}nav{display:flex;gap:7px;overflow:auto}nav a{white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:8px 11px;background:#101925;font-size:13px}.hero{background:linear-gradient(135deg,#173047,#102921);border:1px solid #2c6252;border-radius:20px;padding:19px}.hero h1{margin:3px 0 8px;font-size:26px}.hero p{margin:0;color:var(--muted)}.course-metrics{display:grid;grid-template-columns:repeat(3,minmax(210px,1fr));gap:9px;overflow:auto;margin:12px 0;padding-bottom:3px}.course-metric{display:grid;grid-template-columns:1fr auto;gap:4px;border:1px solid var(--line);border-radius:15px;padding:13px;background:var(--panel);min-width:210px}.course-metric b,.course-metric small,.course-metric span{display:block}.course-metric small,.course-metric span{color:var(--muted);font-size:12px}.course-metric strong{font-size:22px}.plus{color:var(--green)}.minus{color:var(--red)}.day-nav,.venue-chips{display:flex;gap:7px;overflow:auto;scrollbar-width:none}.day-nav{position:sticky;top:0;z-index:10;background:rgba(8,16,25,.94);backdrop-filter:blur(12px);padding:10px 0}.day-chip,.venue-chip{white-space:nowrap;border:1px solid var(--line);background:#101925;border-radius:999px;padding:8px 12px;font-size:13px}.active{border-color:#3a806c;color:#83ecc8}.day{scroll-margin-top:70px;margin:18px 0 30px}.day-title,.venue-title,.race-top{display:flex;justify-content:space-between;align-items:center}.day-title h2{margin:0;font-size:22px}.day-title span,.venue-title span{color:var(--muted);font-size:12px}.venue{scroll-margin-top:115px;margin-top:18px}.venue-title{margin:0 2px 8px}.venue-title b{font-size:18px}.race-strip{display:flex;gap:10px;overflow-x:auto;scroll-snap-type:x mandatory;padding:1px 1px 10px;scrollbar-width:none}.race-card{flex:0 0 245px;scroll-snap-align:start;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:14px;min-height:192px}.race-card.hit{border-color:#347a65}.race-card.miss{border-color:#74403d}.race-card.open{border-color:#526f43}.race-card.skip{opacity:.8}.race-top b{font-size:20px}.race-top span{color:var(--muted)}.race-card h3{font-size:15px;min-height:44px;margin:12px 0 8px}.pick{font-weight:800;color:#8ce8ca;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.muted{color:var(--muted)}.state{display:inline-block;border-radius:999px;padding:4px 9px;margin-top:13px;font-size:12px;font-weight:800}.state.hit,.state.open{background:#153b31;color:#80ebc5}.state.miss{background:#3b1d1d;color:#ff9b95}.state.wait{background:#1b2a3b;color:#a9c6e5}.state.skip{background:#2b2b2b;color:#bbb}.race-card small{display:block;color:var(--muted);margin-top:7px}.footer{color:var(--muted);font-size:12px;padding:30px 2px 50px}@media(max-width:700px){.top{align-items:flex-start}.brand{max-width:90px}.course-metrics{grid-template-columns:repeat(3,220px)}.race-card{flex-basis:78vw;max-width:280px}}
  </style></head><body><main class="wrap"><header class="top"><a href="/" class="brand"><i>レース</i>探偵</a><nav><a href="/">予想</a><a href="/performance">成績</a><a href="/backtest/2026-08-01">8/1検証</a><a href="/methodology">予想方法</a></nav></header><section class="hero"><small>● 全自動・公開予想記録</small><h1>今日の買い目と結果を、開かずに確認。</h1><p>会場とレースは横にスワイプ。カード上で公開時刻、見送り、的中・不的中まで分かります。</p></section>${metricCards(metrics)}<div class="day-nav">${dateTabs}</div>${dateSections || '<p>レースデータを準備中です。</p>'}<footer class="footer">買い目はオッズ取得後、原則として発走60分前を目安に公開し、発走15分前に固定します。期待値条件を満たさないレースは「見送り」と表示します。</footer></main></body></html>`;
}
