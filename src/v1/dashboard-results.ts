import type { BudgetCourse } from "./types.js";
import { escapeHtml, formatYen } from "./utils.js";

const BACKTEST_DATE = "2026-08-01";
const BACKTEST_MODEL = "backtest-2026-08-01-budget-courses-v3";
const COURSES: Array<{ name: BudgetCourse; budget: string; prefix: string }> = [
  { name: "ライト", budget: "2,000円", prefix: "light" },
  { name: "スタンダード", budget: "5,000円", prefix: "standard" },
  { name: "プレミアム", budget: "10,000円", prefix: "premium" }
];

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
  topHorseNo: number | null;
  topHorseName: string | null;
  winnerHorseNo: number | null;
  winnerHorseName: string | null;
  betCount: number;
  lightStake: number;
  lightReturn: number;
  standardStake: number;
  standardReturn: number;
  premiumStake: number;
  premiumReturn: number;
}

interface CourseMetric {
  course: BudgetCourse;
  stake: number;
  returns: number;
  races: number;
  hits: number;
}

export async function getResultDashboard(db: D1Database, liveModel: string): Promise<{ races: DashboardRace[]; metrics: CourseMetric[] }> {
  const races = await db.prepare(`
    WITH chosen_prediction AS (
      SELECT p.*
      FROM rt_predictions p
      JOIN rt_races r ON r.race_id=p.race_id
      WHERE (r.race_date=? AND p.model_version=?)
         OR (r.race_date<>? AND p.model_version=?)
    )
    SELECT r.race_id AS raceId, r.race_date AS raceDate, r.venue, r.race_no AS raceNo,
      r.race_name AS raceName, r.start_time_jst AS startTimeJst, r.start_time_utc AS startTimeUtc,
      r.status, p.status AS predictionStatus,
      (SELECT horse_no FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseNo,
      (SELECT horse_name FROM rt_prediction_runners WHERE prediction_id=p.id ORDER BY predicted_order LIMIT 1) AS topHorseName,
      (SELECT horse_no FROM rt_results WHERE race_id=r.race_id AND finish_position=1 LIMIT 1) AS winnerHorseNo,
      (SELECT rr.horse_name FROM rt_results rs JOIN rt_runners rr ON rr.race_id=rs.race_id AND rr.horse_no=rs.horse_no
       WHERE rs.race_id=r.race_id AND rs.finish_position=1 LIMIT 1) AS winnerHorseName,
      COALESCE((SELECT COUNT(*) FROM rt_bets WHERE prediction_id=p.id),0) AS betCount,
      COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'ライト｜%'),0) AS lightStake,
      COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'ライト｜%'),0) AS lightReturn,
      COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'スタンダード｜%'),0) AS standardStake,
      COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'スタンダード｜%'),0) AS standardReturn,
      COALESCE((SELECT SUM(stake_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'プレミアム｜%'),0) AS premiumStake,
      COALESCE((SELECT SUM(return_yen) FROM rt_bets WHERE prediction_id=p.id AND bet_type LIKE 'プレミアム｜%'),0) AS premiumReturn
    FROM rt_races r
    LEFT JOIN chosen_prediction p ON p.race_id=r.race_id
    WHERE r.race_date >= date('now','+9 hours','-2 day')
    ORDER BY r.race_date, r.venue, r.race_no
    LIMIT 120
  `).bind(BACKTEST_DATE, BACKTEST_MODEL, BACKTEST_DATE, liveModel).all<DashboardRace>();

  const metricRows = await db.prepare(`
    SELECT CASE
      WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト'
      WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード'
      WHEN b.bet_type LIKE 'プレミアム｜%' THEN 'プレミアム'
    END AS course,
    COALESCE(SUM(b.stake_yen),0) AS stake,
    COALESCE(SUM(b.return_yen),0) AS returns,
    COUNT(DISTINCT b.race_id) AS races,
    COUNT(DISTINCT CASE WHEN b.return_yen>0 THEN b.race_id END) AS hits
    FROM rt_bets b
    JOIN rt_predictions p ON p.id=b.prediction_id
    JOIN rt_races r ON r.race_id=b.race_id
    WHERE b.settlement_status='settled'
      AND ((r.race_date=? AND p.model_version=?) OR (r.race_date<>? AND p.model_version=?))
      AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')
    GROUP BY course
  `).bind(BACKTEST_DATE, BACKTEST_MODEL, BACKTEST_DATE, liveModel).all<CourseMetric>();

  const metricMap = new Map(metricRows.results.map((row) => [row.course, row]));
  return {
    races: races.results.map((r) => ({
      ...r,
      raceNo: Number(r.raceNo), betCount: Number(r.betCount),
      lightStake: Number(r.lightStake), lightReturn: Number(r.lightReturn),
      standardStake: Number(r.standardStake), standardReturn: Number(r.standardReturn),
      premiumStake: Number(r.premiumStake), premiumReturn: Number(r.premiumReturn)
    })),
    metrics: COURSES.map(({ name }) => ({
      course: name,
      stake: Number(metricMap.get(name)?.stake ?? 0),
      returns: Number(metricMap.get(name)?.returns ?? 0),
      races: Number(metricMap.get(name)?.races ?? 0),
      hits: Number(metricMap.get(name)?.hits ?? 0)
    }))
  };
}

function dateLabel(date: string): string {
  const m=date.match(/^(\d{4})-(\d{2})-(\d{2})$/); if(!m) return date;
  const wd=["日","月","火","水","木","金","土"][new Date(Date.UTC(+m[1],+m[2]-1,+m[3])).getUTCDay()];
  return `${+m[2]}月${+m[3]}日（${wd}）`;
}
function timeLabel(v:string|null):string { return v?.match(/\d{1,2}:\d{2}/)?.[0] ?? "時刻未定"; }
function money(v:number):string { return `${v>=0?"+":""}${formatYen(v)}`; }

function courseResult(r:DashboardRace, prefix:string):{stake:number;returns:number} {
  return { stake:Number(r[`${prefix}Stake` as keyof DashboardRace]??0), returns:Number(r[`${prefix}Return` as keyof DashboardRace]??0) };
}

function statusHtml(r:DashboardRace):string {
  if(r.status==="finished") {
    if(r.betCount===0) return `<div class="badge neutral">集計待ち</div><small>3コース検証を処理中</small>`;
    const lines=COURSES.map(c=>{
      const x=courseResult(r,c.prefix), profit=x.returns-x.stake, hit=x.returns>0;
      return `<div class="course-line ${hit?"hit":"miss"}"><b>${c.name}</b><span>${hit?"的中":"不的中"}</span><strong>${formatYen(x.stake)} → ${formatYen(x.returns)}</strong><em>${money(profit)}</em></div>`;
    }).join("");
    return `<div class="winner">1着 ${r.winnerHorseNo??"—"} ${escapeHtml(r.winnerHorseName??"")}</div>${lines}`;
  }
  if(r.betCount>0) return `<div class="badge open">${r.predictionStatus==="locked"?"買い目確定":"買い目公開中"}</div><small>${r.predictionStatus==="locked"?"発走前固定済み":"発走15分前まで更新"}</small>`;
  if(r.predictionStatus==="locked") return `<div class="badge skip">見送り</div><small>固定買い目なし</small>`;
  if(r.predictionStatus) return `<div class="badge neutral">買い目調整中</div><small>発走15分前まで更新</small>`;
  return `<div class="badge neutral">公開待ち</div><small>オッズ取得後に公開</small>`;
}

export function renderResultDashboard(races:DashboardRace[], metrics:CourseMetric[]):string {
  const dates=[...new Set(races.map(r=>r.raceDate))];
  const metricHtml=COURSES.map(c=>{const m=metrics.find(x=>x.course===c.name)!;const roi=m.stake?m.returns/m.stake*100:null;const p=m.returns-m.stake;return `<a class="metric" href="/performance"><div><b>${c.name}</b><small>${c.budget}／${m.hits}/${m.races}R的中</small></div><strong>${roi===null?"—":roi.toFixed(1)+"%"}</strong><span class="${p>=0?"plus":"minus"}">${money(p)}</span></a>`}).join("");
  const sections=dates.map(date=>{const dr=races.filter(r=>r.raceDate===date);const venues=[...new Set(dr.map(r=>r.venue))];return `<section class="day" data-day="${date}"><div class="dayhead"><h2>${dateLabel(date)}</h2><span>${dr.length}R</span></div><div class="venues">${venues.map(v=>`<button type="button" data-venue="${escapeHtml(v)}">${escapeHtml(v)}</button>`).join("")}</div>${venues.map((v,i)=>`<section class="venue ${i?"hidden":""}" data-venue-panel="${escapeHtml(v)}"><h3>${escapeHtml(v)}競馬場</h3><div class="strip">${dr.filter(r=>r.venue===v).map(r=>`<a class="race" href="/races/${encodeURIComponent(r.raceId)}"><header><b>${r.raceNo}R</b><span>${timeLabel(r.startTimeJst)}</span></header><h4>${escapeHtml(r.raceName)}</h4><div class="pick">◎ ${r.topHorseNo??"—"} ${escapeHtml(r.topHorseName??"")}</div>${statusHtml(r)}</a>`).join("")}</div></section>`).join("")}</section>`}).join("");
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>レース探偵</title><style>:root{color-scheme:dark;--bg:#081019;--panel:#111a25;--line:#29394b;--text:#f2f5f8;--muted:#98aabd;--green:#4fd1a1;--red:#ff7b72}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:1050px;margin:auto;padding:14px}a{color:inherit;text-decoration:none}.top{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:12px 0 18px}.brand{font-size:24px;font-weight:900}.brand i{font-style:normal;color:var(--green)}nav{display:flex;gap:7px;overflow:auto}nav a{white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:8px 11px}.metrics{display:flex;gap:9px;overflow:auto}.metric{min-width:235px;display:grid;grid-template-columns:1fr auto;gap:3px;padding:14px;border:1px solid var(--line);border-radius:15px;background:var(--panel)}.metric small,.metric span{color:var(--muted);font-size:12px}.metric strong{font-size:22px}.plus{color:var(--green)!important}.minus{color:var(--red)!important}.days{display:flex;gap:8px;margin:18px 0 8px}.days button,.venues button{border:1px solid var(--line);border-radius:999px;padding:9px 13px;background:#101925;color:var(--text);white-space:nowrap}.days button.active,.venues button.active{border-color:#3c8a73;color:#80ebc5}.day{display:none}.day.active{display:block}.dayhead{display:flex;justify-content:space-between;align-items:center}.venues{display:flex;gap:7px;overflow:auto;margin-bottom:13px}.venue.hidden{display:none}.strip{display:flex;gap:10px;overflow:auto;padding-bottom:12px;scroll-snap-type:x mandatory}.race{flex:0 0 min(88vw,330px);scroll-snap-align:start;background:var(--panel);border:1px solid var(--line);border-radius:17px;padding:14px}.race header{display:flex;justify-content:space-between}.race header b{font-size:22px}.race h4{min-height:42px;margin:11px 0}.pick{color:#8ce8ca;font-weight:800;margin-bottom:10px}.winner{font-size:13px;color:#ffd89a;margin-bottom:8px}.course-line{display:grid;grid-template-columns:72px 48px 1fr auto;align-items:center;gap:5px;padding:6px 0;border-top:1px solid var(--line);font-size:12px}.course-line.hit span,.course-line.hit em{color:var(--green)}.course-line.miss span,.course-line.miss em{color:var(--red)}.course-line em{font-style:normal;font-weight:800}.badge{display:inline-block;padding:4px 9px;border-radius:999px;font-size:12px;font-weight:800}.badge.open{background:#153b31;color:#80ebc5}.badge.skip{background:#392921;color:#f2c37e}.badge.neutral{background:#1b2a3b;color:#aec5df}.race small{display:block;color:var(--muted);margin-top:6px}.footer{color:var(--muted);font-size:12px;padding:28px 0 50px}@media(max-width:600px){.brand{max-width:85px}.course-line{grid-template-columns:65px 44px 1fr}.course-line em{grid-column:3;text-align:right}.metric{min-width:220px}}</style></head><body><main class="wrap"><header class="top"><a class="brand" href="/"><i>レース</i>探偵</a><nav><a href="/">予想</a><a href="/performance">成績</a><a href="/backtest/2026-08-01">8/1検証</a><a href="/methodology">予想方法</a></nav></header><section class="metrics">${metricHtml}</section><div class="days">${dates.map((d,i)=>`<button type="button" data-day-button="${d}" class="${i?"":"active"}">${dateLabel(d)}</button>`).join("")}</div>${sections}<footer class="footer">終了レースは、予想時の買い目と公式払戻をコース別に照合して表示しています。</footer></main><script>(()=>{history.replaceState(null,"",location.pathname+location.search);scrollTo(0,0);const ds=[...document.querySelectorAll(".day")],db=[...document.querySelectorAll("[data-day-button]")];function day(v){db.forEach(b=>b.classList.toggle("active",b.dataset.dayButton===v));ds.forEach(s=>s.classList.toggle("active",s.dataset.day===v))}db.forEach(b=>b.onclick=()=>day(b.dataset.dayButton));if(db[0])day(db[0].dataset.dayButton);document.querySelectorAll(".day").forEach(d=>{const bs=[...d.querySelectorAll("[data-venue]")],ps=[...d.querySelectorAll("[data-venue-panel]")];bs.forEach((b,i)=>{if(i===0)b.classList.add("active");b.onclick=()=>{bs.forEach(x=>x.classList.toggle("active",x===b));ps.forEach(p=>p.classList.toggle("hidden",p.dataset.venuePanel!==b.dataset.venue))}})});})();</script></body></html>`;
}
