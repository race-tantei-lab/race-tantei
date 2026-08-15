import publicSite from "./public-site-entry-v13.js";
import { jstDateKey } from "./v1/jra-calendar.js";
import { summarizeTodayPerformance, type TodayPerformanceBetRow } from "./v1/today-performance.js";
import type { Env } from "./v1/types.js";

const COURSES = ["ライト", "スタンダード", "プレミアム"] as const;
type TicketReasonRow = { betType: string; combination: string; assumedOdds: number | null };

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] ?? ch));
}

function yen(value: number): string {
  return `¥${Math.round(value).toLocaleString("ja-JP")}`;
}

async function todaySummary(db: D1Database, date = jstDateKey()): Promise<Record<string, unknown>> {
  const result = await db.prepare(`
    SELECT b.race_id AS raceId,b.course,b.bet_type AS betType,b.combination,
           b.stake_yen AS stakeYen,b.return_yen AS returnYen,
           b.settlement_status AS settlementStatus,r.refund_horse_nos_json AS refundsJson
    FROM rt_public_bets b
    JOIN rt_races r ON r.race_id=b.race_id
    WHERE r.race_date=?
    ORDER BY b.race_id,b.course,b.id
  `).bind(date).all<TodayPerformanceBetRow>();

  const courses = summarizeTodayPerformance(result.results ?? [], COURSES);
  return {
    date,
    hasPredictions: courses.some((row) => row.totalRaces > 0),
    complete: courses.some((row) => row.totalRaces > 0) && courses.every((row) => row.totalRaces === 0 || row.complete),
    courses
  };
}

function summaryHtml(summary: any): string {
  if (!summary?.hasPredictions) return "";
  const rows = (summary.courses ?? []).map((row: any) => {
    const roi = row.roiPct === null ? "—" : `${Number(row.roiPct).toFixed(1)}%`;
    const cls = row.roiPct === null ? "" : Number(row.roiPct) >= 100 ? "plus" : "minus";
    const progress = row.complete ? `${row.settledRaces}R` : `集計中 ${row.settledRaces}/${row.totalRaces}R`;
    return `<div class="today-result-row"><div><b>${esc(row.course)}</b><span>${esc(progress)}・的中 ${Number(row.hitRaces)}R</span></div><div class="today-result-money"><span>${yen(Number(row.stakeYen))} → ${yen(Number(row.returnYen))}</span><strong class="${cls}">${roi}</strong></div></div>`;
  }).join("");
  const status = summary.complete ? "確定" : "自動集計中";
  return `<section class="today-result" id="today-result"><div class="today-result-head"><div><h2>今日の結果</h2><span>${esc(summary.date.replace(/-/g, "/"))}</span></div><em>${status}</em></div>${rows}</section>`;
}

function homeEnhancement(html: string, summary: any): string {
  const css = `<style>
    .today-result{margin:18px 0 4px;border:1px solid var(--line);background:var(--panel);border-radius:16px;padding:14px 15px}
    .today-result-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}
    .today-result-head>div{display:flex;align-items:baseline;gap:8px}.today-result-head h2{font-size:18px;margin:0}.today-result-head span{font-size:11px;color:var(--muted)}
    .today-result-head em{font-style:normal;font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:4px 8px}
    .today-result-row{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:10px 0;border-top:1px solid rgba(43,61,82,.55)}
    .today-result-row>div:first-child{display:grid;gap:2px}.today-result-row b{font-size:14px}.today-result-row span{font-size:11px;color:var(--muted)}
    .today-result-money{display:flex;align-items:center;gap:12px;text-align:right}.today-result-money strong{font-size:16px;min-width:58px}.today-result-money .plus{color:var(--green)}.today-result-money .minus{color:var(--red)}
    @media(max-width:760px){.today-result-row{align-items:flex-start}.today-result-money{display:grid;gap:2px}.today-result-money strong{justify-self:end}}
  </style>`;
  const script = `<script>(()=>{async function refreshTodayResult(){try{const r=await fetch('/api/public/today-summary',{cache:'no-store'});if(!r.ok)return;const s=await r.json();const root=document.getElementById('today-result');if(!root||!s.hasPredictions)return;const y=n=>'¥'+Math.round(Number(n||0)).toLocaleString('ja-JP');const rows=(s.courses||[]).map(x=>{const roi=x.roiPct==null?'—':Number(x.roiPct).toFixed(1)+'%';const cls=x.roiPct==null?'':Number(x.roiPct)>=100?'plus':'minus';const progress=x.complete?x.settledRaces+'R':'集計中 '+x.settledRaces+'/'+x.totalRaces+'R';return '<div class="today-result-row"><div><b>'+x.course+'</b><span>'+progress+'・的中 '+x.hitRaces+'R</span></div><div class="today-result-money"><span>'+y(x.stakeYen)+' → '+y(x.returnYen)+'</span><strong class="'+cls+'">'+roi+'</strong></div></div>'}).join('');root.innerHTML='<div class="today-result-head"><div><h2>今日の結果</h2><span>'+String(s.date||'').replaceAll('-','/')+'</span></div><em>'+(s.complete?'確定':'自動集計中')+'</em></div>'+rows;}catch{}}setInterval(refreshTodayResult,60000);})();</script>`;
  let out = html.replace("</head>", `${css}</head>`).replace("</body>", `${script}</body>`);
  const anchor = `<div class="section-title"><h2 id="selected-date">`;
  const block = summaryHtml(summary);
  if (block && out.includes(anchor)) out = out.replace(anchor, `${block}${anchor}`);
  return out;
}

async function ticketReasons(db: D1Database, raceId: string): Promise<string[]> {
  const q = await db.prepare(`
    SELECT bet_type AS betType,combination,AVG(assumed_odds) AS assumedOdds
    FROM rt_public_bets
    WHERE race_id=?
    GROUP BY bet_type,combination
    ORDER BY bet_type,combination
  `).bind(raceId).all<TicketReasonRow>();
  const rows = q.results;
  if (!rows.length) return [];

  const betTypes = [...new Set(rows.map((row) => String(row.betType)).filter(Boolean))];
  const odds = rows.map((row) => Number(row.assumedOdds)).filter((value) => Number.isFinite(value) && value > 1).sort((a, b) => a - b);
  const reasons: string[] = [];

  if (betTypes.length >= 2) reasons.push(`${betTypes.slice(0, 3).join("・")}${betTypes.length > 3 ? "など" : ""}で条件合致`);
  else if (betTypes.length === 1) reasons.push(`${betTypes[0]}の条件に合致`);

  if (odds.length) {
    const median = odds[Math.floor(odds.length / 2)];
    if (median >= 75) reasons.push("高配当帯の妙味を評価");
    else if (median >= 20) reasons.push("中穴〜高配当帯の妙味を評価");
    else if (median >= 7) reasons.push("中穴帯の妙味を評価");
    else reasons.push("人気寄りでも条件一致を優先");
  }

  reasons.push(`${rows.length}点まで候補を絞り込み`);
  return reasons.slice(0, 3);
}

async function enhanceRaceReasons(request: Request, response: Response, db: D1Database): Promise<Response> {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  const path = new URL(request.url).pathname;
  if (!path.startsWith("/races/")) return response;
  try {
    const raceId = decodeURIComponent(path.slice("/races/".length));
    const reasons = await ticketReasons(db, raceId);
    if (!reasons.length) return response;
    let html = await response.text();
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    if (html.includes('prediction-reasons')) {
      return new Response(html, { status: response.status, headers });
    }
    const block = `<section class="prediction-reasons live-prediction-reasons"><div class="prediction-reasons-head"><h2>予想根拠</h2><span>簡易表示</span></div><div class="prediction-reason-list">${reasons.map((reason) => `<span>${esc(reason)}</span>`).join("")}</div></section>`;
    const css = `<style>
      .prediction-reasons{margin:12px 0 16px;padding:13px 14px;border:1px solid var(--line);border-radius:14px;background:var(--panel)}
      .prediction-reasons-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:9px}.prediction-reasons-head h2{margin:0;font-size:16px}.prediction-reasons-head span{font-size:10px;color:var(--muted)}
      .prediction-reason-list{display:flex;flex-wrap:wrap;gap:7px}.prediction-reason-list span{display:inline-flex;padding:6px 9px;border-radius:999px;background:var(--panel2);border:1px solid var(--line);font-size:11px;font-weight:700}
    </style>`;
    html = html.replace("</head>", `${css}</head>`);
    const anchors = [
      `<div class="section-title"><h2>出走馬`,
      `<section class="card"><h2>出走馬`,
      `<section class="runner-table`
    ];
    let inserted = false;
    for (const anchor of anchors) {
      if (!html.includes(anchor)) continue;
      html = html.replace(anchor, `${block}${anchor}`);
      inserted = true;
      break;
    }
    if (!inserted && html.includes("</main>")) {
      html = html.replace("</main>", `${block}</main>`);
      inserted = true;
    }
    if (!inserted) html += block;
    return new Response(html, { status: response.status, headers });
  } catch {
    return response;
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/public/today-summary") {
      try {
        return Response.json(await todaySummary(env.DB), { headers: { "cache-control": "no-store" } });
      } catch {
        return Response.json({ date: jstDateKey(), hasPredictions: false, complete: false, courses: [] }, { status: 200, headers: { "cache-control": "no-store" } });
      }
    }
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    let response = await publicSite.fetch(request, env, ctx);
    if (url.pathname.startsWith("/races/")) response = await enhanceRaceReasons(request, response, env.DB);
    if (url.pathname === "/" && response.ok && response.headers.get("content-type")?.includes("text/html")) {
      try {
        const summary = await todaySummary(env.DB);
        const headers = new Headers(response.headers);
        headers.delete("content-length");
        response = new Response(homeEnhancement(await response.text(), summary), { status: response.status, headers });
      } catch {/* keep base page */}
    }
    return response;
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
