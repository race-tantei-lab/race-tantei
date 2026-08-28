import { ensurePublicHistory } from "./public-history-db.js";

export const DAILY_PERFORMANCE_VERSION = "daily-performance-v3-roi-only-history-20260828";
const COURSES = ["ライト", "スタンダード", "プレミアム"] as const;
type CourseName = typeof COURSES[number];

type DailyPerformanceRow = {
  raceDate: string;
  course: string;
  finalizedRaces: number;
  settledRaces: number;
  finalizedStakeYen: number;
  settledStakeYen: number;
  returnYen: number;
};

type CoursePerformance = {
  course: CourseName;
  finalizedRaces: number;
  settledRaces: number;
  finalizedStakeYen: number;
  settledStakeYen: number;
  returnYen: number;
  pendingStakeYen: number;
  profitYen: number;
  roiPct: number | null;
};

type DayPerformance = {
  date: string;
  finalizedRaces: number;
  settledRaces: number;
  finalizedStakeYen: number;
  settledStakeYen: number;
  returnYen: number;
  pendingStakeYen: number;
  profitYen: number;
  roiPct: number | null;
  courses: CoursePerformance[];
};

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function validDate(value: string | null): value is string {
  return Boolean(value && /^20\d{2}-\d{2}-\d{2}$/.test(value));
}

function numberValue(value: unknown): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function summarizeDay(date: string, rows: DailyPerformanceRow[]): DayPerformance {
  const byCourse = new Map<string, DailyPerformanceRow>();
  for (const row of rows) byCourse.set(String(row.course), row);
  const courses: CoursePerformance[] = COURSES.map((course) => {
    const row = byCourse.get(course);
    const finalizedStakeYen = numberValue(row?.finalizedStakeYen);
    const settledStakeYen = numberValue(row?.settledStakeYen);
    const returnYen = numberValue(row?.returnYen);
    return {
      course,
      finalizedRaces: numberValue(row?.finalizedRaces),
      settledRaces: numberValue(row?.settledRaces),
      finalizedStakeYen,
      settledStakeYen,
      returnYen,
      pendingStakeYen: Math.max(0, finalizedStakeYen - settledStakeYen),
      profitYen: returnYen - settledStakeYen,
      roiPct: settledStakeYen > 0 ? returnYen / settledStakeYen * 100 : null,
    };
  });
  const finalizedStakeYen = courses.reduce((sum, row) => sum + row.finalizedStakeYen, 0);
  const settledStakeYen = courses.reduce((sum, row) => sum + row.settledStakeYen, 0);
  const returnYen = courses.reduce((sum, row) => sum + row.returnYen, 0);
  return {
    date,
    finalizedRaces: Math.max(0, ...courses.map((row) => row.finalizedRaces)),
    settledRaces: Math.max(0, ...courses.map((row) => row.settledRaces)),
    finalizedStakeYen,
    settledStakeYen,
    returnYen,
    pendingStakeYen: Math.max(0, finalizedStakeYen - settledStakeYen),
    profitYen: returnYen - settledStakeYen,
    roiPct: settledStakeYen > 0 ? returnYen / settledStakeYen * 100 : null,
    courses,
  };
}

export async function dailyPerformanceResponse(db: D1Database, requestedDate: string): Promise<Response> {
  const today = jstDate();
  const date = validDate(requestedDate) ? requestedDate : today;
  try {
    await ensurePublicHistory(db);
    const [selectedResult, historyResult] = await Promise.all([
      db.prepare(`
        SELECT r.race_date AS raceDate,b.course,
               COUNT(DISTINCT b.race_id) AS finalizedRaces,
               COUNT(DISTINCT CASE WHEN b.settlement_status='settled' THEN b.race_id END) AS settledRaces,
               COALESCE(SUM(b.stake_yen),0) AS finalizedStakeYen,
               COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN b.stake_yen ELSE 0 END),0) AS settledStakeYen,
               COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN COALESCE(b.return_yen,0) ELSE 0 END),0) AS returnYen
        FROM rt_public_bets b
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE r.race_date=?
        GROUP BY r.race_date,b.course
        ORDER BY CASE b.course WHEN 'ライト' THEN 1 WHEN 'スタンダード' THEN 2 WHEN 'プレミアム' THEN 3 ELSE 9 END
      `).bind(date).all<DailyPerformanceRow>(),
      db.prepare(`
        WITH recent_dates AS (
          SELECT DISTINCT r.race_date AS raceDate
          FROM rt_public_bets b
          JOIN rt_races r ON r.race_id=b.race_id
          WHERE r.race_date<=?
          ORDER BY r.race_date DESC
          LIMIT 30
        )
        SELECT r.race_date AS raceDate,b.course,
               COUNT(DISTINCT b.race_id) AS finalizedRaces,
               COUNT(DISTINCT CASE WHEN b.settlement_status='settled' THEN b.race_id END) AS settledRaces,
               COALESCE(SUM(b.stake_yen),0) AS finalizedStakeYen,
               COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN b.stake_yen ELSE 0 END),0) AS settledStakeYen,
               COALESCE(SUM(CASE WHEN b.settlement_status='settled' THEN COALESCE(b.return_yen,0) ELSE 0 END),0) AS returnYen
        FROM rt_public_bets b
        JOIN rt_races r ON r.race_id=b.race_id
        JOIN recent_dates d ON d.raceDate=r.race_date
        GROUP BY r.race_date,b.course
        ORDER BY r.race_date DESC,CASE b.course WHEN 'ライト' THEN 1 WHEN 'スタンダード' THEN 2 WHEN 'プレミアム' THEN 3 ELSE 9 END
      `).bind(today).all<DailyPerformanceRow>(),
    ]);

    const historyByDate = new Map<string, DailyPerformanceRow[]>();
    for (const row of historyResult.results ?? []) {
      const key = String(row.raceDate);
      const list = historyByDate.get(key) ?? [];
      list.push(row);
      historyByDate.set(key, list);
    }
    const history = [...historyByDate.entries()]
      .sort((a, b) => b[0].localeCompare(a[0]))
      .slice(0, 30)
      .map(([historyDate, rows]) => summarizeDay(historyDate, rows));

    return Response.json({ ok: true, version: DAILY_PERFORMANCE_VERSION, today, summary: summarizeDay(date, selectedResult.results ?? []), history }, {
      headers: { "cache-control": "no-store, max-age=0", "x-race-performance-api": DAILY_PERFORMANCE_VERSION },
    });
  } catch (error) {
    console.error("DAILY_PERFORMANCE_API_FAILED", error);
    return Response.json({ ok: false, error: "DAILY_PERFORMANCE_UNAVAILABLE" }, {
      status: 500,
      headers: { "cache-control": "no-store, max-age=0" },
    });
  }
}

function styles(): string {
  return `<style>
    .daily-performance-wrap{margin:18px 0 20px}.daily-performance-head{display:flex;align-items:end;justify-content:space-between;gap:10px;margin-bottom:9px}.daily-performance-head h2{margin:0;font-size:19px}.daily-performance-head span{font-size:10px;color:var(--muted)}
    .daily-summary{border:1px solid var(--line);border-radius:16px;background:var(--panel);overflow:hidden}.daily-summary-loading,.daily-summary-empty{padding:16px;color:var(--muted);font-size:11px}.daily-summary-top{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line)}.daily-summary-metric{padding:11px 12px;background:var(--panel2);min-width:0}.daily-summary-metric span{display:block;font-size:9px;color:var(--muted)}.daily-summary-metric b{display:block;margin-top:3px;font-size:17px;white-space:nowrap}.daily-summary-metric b.plus,.daily-course-row strong.plus,.daily-history-day summary strong.plus{color:var(--green)}.daily-summary-metric b.minus,.daily-course-row strong.minus,.daily-history-day summary strong.minus{color:var(--red)}
    .daily-summary-note{padding:8px 12px;border-top:1px solid var(--line);font-size:9px;color:var(--muted);line-height:1.6}.daily-course-list{border-top:1px solid var(--line)}.daily-course-row{display:grid;grid-template-columns:92px repeat(4,minmax(0,1fr));gap:8px;align-items:center;padding:9px 12px;border-bottom:1px solid rgba(43,61,82,.65);font-size:10px}.daily-course-row:last-child{border-bottom:0}.daily-course-row b{font-size:11px}.daily-course-row span{color:var(--muted);white-space:nowrap}.daily-course-row strong{text-align:right;white-space:nowrap}.daily-course-row em{font-style:normal;text-align:right;font-weight:800;white-space:nowrap}
    .daily-history{margin-top:10px;border:1px solid var(--line);border-radius:16px;background:var(--panel);overflow:hidden}.daily-history>summary{list-style:none;cursor:pointer;display:flex;justify-content:space-between;gap:10px;align-items:center;padding:12px 13px}.daily-history>summary::-webkit-details-marker{display:none}.daily-history>summary b{font-size:13px}.daily-history>summary span{font-size:9px;color:var(--muted)}.daily-history>summary:after{content:"＋";margin-left:auto;color:var(--muted);font-weight:900}.daily-history[open]>summary:after{content:"−"}.daily-history-list{max-height:440px;overflow:auto;border-top:1px solid var(--line)}
    .daily-history-day{border-bottom:1px solid rgba(43,61,82,.65)}.daily-history-day:last-child{border-bottom:0}.daily-history-day>summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:72px minmax(0,1fr);gap:9px;align-items:center;padding:10px 12px}.daily-history-day>summary::-webkit-details-marker{display:none}.daily-history-day>summary b{font-size:11px}.daily-history-day>summary span{font-size:10px;color:var(--muted)}.daily-history-day>summary strong{font-size:11px;white-space:nowrap}.daily-history-courses{padding:0 10px 9px;background:var(--panel2)}.daily-history-courses .daily-course-row{grid-template-columns:82px repeat(4,minmax(0,1fr));padding:7px 3px;background:transparent}
    @media(max-width:760px){.daily-summary-top{grid-template-columns:repeat(2,minmax(0,1fr))}.daily-summary-metric b{font-size:16px}.daily-course-row,.daily-history-courses .daily-course-row{grid-template-columns:70px minmax(0,1fr) minmax(0,1fr)}.daily-course-row span:nth-of-type(2),.daily-course-row em{display:none}.daily-course-row strong{text-align:right}.daily-history-day>summary{grid-template-columns:60px minmax(0,1fr)}.daily-history-list{max-height:390px}}
  </style>`;
}

function block(today: string): string {
  const [, month, day] = today.split("-");
  return `<section class="daily-performance-wrap" data-daily-performance>
    <div class="daily-performance-head"><h2 id="daily-performance-title">本日の集計（${Number(month)}/${Number(day)}）</h2><span>JST・公開買い目</span></div>
    <div id="daily-performance-current" class="daily-summary"><div class="daily-summary-loading">集計を読み込み中…</div></div>
    <details class="daily-history" open><summary><b>日別回収率</b><span>直近30開催日</span></summary><div id="daily-performance-history" class="daily-history-list"><div class="daily-summary-loading">日別成績を読み込み中…</div></div></details>
  </section>`;
}

function script(today: string): string {
  return `<script>(()=>{
    const TODAY=${JSON.stringify(today)};
    const current=document.getElementById('daily-performance-current'),history=document.getElementById('daily-performance-history'),title=document.getElementById('daily-performance-title');
    if(!current||!history||!title)return;
    let seq=0;
    const yen=(v)=>Math.round(Number(v)||0).toLocaleString('ja-JP')+'円';
    const signed=(v)=>{const n=Math.round(Number(v)||0);return (n>0?'+':'')+n.toLocaleString('ja-JP')+'円';};
    const pct=(v)=>v==null?'—':Number(v).toFixed(1)+'%';
    const tone=(v)=>Number(v)>0?'plus':Number(v)<0?'minus':'';
    const esc=(v)=>String(v??'').replace(/[&<>"']/g,(c)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]||c));
    const shortDate=(d)=>{const p=d.split('-');return Number(p[1])+'/'+Number(p[2]);};
    const courseRows=(rows)=>rows.map((r)=>{const profitClass=r.settledStakeYen>0?tone(r.profitYen):'',profit=r.settledStakeYen>0?signed(r.profitYen):'—';return '<div class="daily-course-row"><b>'+esc(r.course)+'</b><span>購入 '+yen(r.settledStakeYen)+'</span><span>払戻 '+yen(r.returnYen)+'</span><strong class="'+profitClass+'">'+profit+'</strong><em>'+pct(r.roiPct)+'</em></div>';}).join('');
    const renderCurrent=(s)=>{const p=TODAY.split('-');title.textContent='本日の集計（'+Number(p[1])+'/'+Number(p[2])+'）';if(s.date!==TODAY){current.innerHTML='<div class="daily-summary-empty">本日の集計日付を取得できませんでした。</div>';return;}if(!s.finalizedStakeYen){current.innerHTML='<div class="daily-summary-empty">本日（'+Number(p[1])+'/'+Number(p[2])+'）の公開買い目はありません。</div>';return;}const profitShown=s.settledStakeYen>0?signed(s.profitYen):'—',profitClass=s.settledStakeYen>0?tone(s.profitYen):'',pending=s.pendingStakeYen>0?'未精算 '+yen(s.pendingStakeYen)+'（収支・回収率にはまだ算入していません）':'全て精算済み';current.innerHTML='<div class="daily-summary-top"><div class="daily-summary-metric"><span>精算済購入</span><b>'+yen(s.settledStakeYen)+'</b></div><div class="daily-summary-metric"><span>払戻</span><b>'+yen(s.returnYen)+'</b></div><div class="daily-summary-metric"><span>収支</span><b class="'+profitClass+'">'+profitShown+'</b></div><div class="daily-summary-metric"><span>回収率</span><b>'+pct(s.roiPct)+'</b></div></div><div class="daily-summary-note">3コース合計（比較用）・'+s.settledRaces+'R精算 / '+s.finalizedRaces+'R確定　'+pending+'　確定済み総購入 '+yen(s.finalizedStakeYen)+'</div><div class="daily-course-list">'+courseRows(s.courses)+'</div>';};
    const renderHistory=(days)=>{if(!Array.isArray(days)||!days.length){history.innerHTML='<div class="daily-summary-empty">日別成績はまだありません。</div>';return;}history.innerHTML=days.map((d)=>'<details class="daily-history-day"><summary><b>'+shortDate(d.date)+'</b><span>回収率 '+pct(d.roiPct)+'</span></summary><div class="daily-history-courses">'+courseRows(d.courses)+'</div></details>').join('');};
    const load=async()=>{const my=++seq;try{const res=await fetch('/api/public/daily-performance?date='+encodeURIComponent(TODAY)+'&_rt='+Date.now(),{cache:'no-store',headers:{'cache-control':'no-cache'}});if(!res.ok)throw new Error('HTTP_'+res.status);const data=await res.json();if(my!==seq||!data?.ok)return;if(data.today!==TODAY||data.summary?.date!==TODAY)throw new Error('TODAY_MISMATCH');renderCurrent(data.summary);renderHistory(data.history);}catch(e){if(my!==seq)return;current.innerHTML='<div class="daily-summary-empty">本日の集計を取得できませんでした。</div>';}};
    setTimeout(load,0);setInterval(()=>{if(document.visibilityState!=='hidden')load();},15000);window.addEventListener('pageshow',load);document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')load();});
  })();</script>`;
}

export async function enhanceDailyPerformanceHome(response: Response, today = jstDate()): Promise<Response> {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  let html = await response.text();
  if (!html.includes("data-daily-performance")) {
    const section = block(today);
    const anchor = /(<div class="section-title"><h2 id="selected-date">)/;
    if (anchor.test(html)) html = html.replace(anchor, `${section}$1`);
    else html = html.replace(/(<div class="section-title"><h2>累計回収率<\/h2>)/, `${section}$1`);
  }
  html = html.replace("</head>", `${styles()}</head>`).replace("</body>", `${script(today)}</body>`);
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-race-performance-ui", DAILY_PERFORMANCE_VERSION);
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}
