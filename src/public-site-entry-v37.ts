import publicSite from "./public-site-entry-v34.js";
import { summarizeTodayPerformance, type TodayPerformanceBetRow } from "./v1/today-performance.js";
import { runUpcomingCalendarRepair } from "./v1/upcoming-calendar-repair.js";
import { runUpcomingEntryWorkerRepair } from "./v1/upcoming-entry-worker-repair.js";
import { runUpcomingEntryDerivedRepair } from "./v1/upcoming-entry-derived-repair.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v37-target-race-count-20260830";
const PERFORMANCE_VERSION = "daily-performance-v6-target-race-count-20260830";
const COURSES = ["ライト", "スタンダード", "プレミアム"] as const;
const BASE_COURSE = "ライト";

type CanonicalBetRow = TodayPerformanceBetRow & { raceDate: string };
type CourseView = {
  course: string;
  finalizedRaces: number;
  settledRaces: number;
  hitRaces: number;
  refundRaces: number;
  finalizedStakeYen: number;
  settledStakeYen: number;
  returnYen: number;
  pendingStakeYen: number;
  profitYen: number;
  roiPct: number | null;
};
type DayView = CourseView & { date: string; courses: CourseView[] };
type RecentView = { races: number; stakeYen: number; returnYen: number; roiPct: number | null };

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function validDate(value: string | null): value is string {
  return Boolean(value && /^20\d{2}-\d{2}-\d{2}$/.test(value));
}

function canonicalDay(date: string, rows: CanonicalBetRow[]): DayView {
  const stats = summarizeTodayPerformance(rows, COURSES);
  const courses: CourseView[] = stats.map((stat) => {
    const allRows = rows.filter((row) => String(row.course) === stat.course);
    const finalizedRaces = new Set(allRows.map((row) => String(row.raceId)).filter(Boolean)).size;
    const finalizedStakeYen = allRows.reduce((sum, row) => sum + Number(row.stakeYen ?? 0), 0);
    const settledStakeYen = Number(stat.stakeYen ?? 0);
    const returnYen = Number(stat.returnYen ?? 0);
    return {
      course: stat.course,
      finalizedRaces,
      settledRaces: Number(stat.settledRaces ?? 0),
      hitRaces: Number(stat.hitRaces ?? 0),
      refundRaces: Number(stat.refundRaces ?? 0),
      finalizedStakeYen,
      settledStakeYen,
      returnYen,
      pendingStakeYen: Math.max(0, finalizedStakeYen - settledStakeYen),
      profitYen: returnYen - settledStakeYen,
      roiPct: stat.roiPct == null ? null : Number(stat.roiPct),
    };
  });
  const base = courses.find((row) => row.course === BASE_COURSE) ?? courses[0] ?? {
    course: BASE_COURSE,
    finalizedRaces: 0,
    settledRaces: 0,
    hitRaces: 0,
    refundRaces: 0,
    finalizedStakeYen: 0,
    settledStakeYen: 0,
    returnYen: 0,
    pendingStakeYen: 0,
    profitYen: 0,
    roiPct: null,
  };
  return { ...base, date, courses };
}

async function rowsForDate(db: D1Database, date: string): Promise<CanonicalBetRow[]> {
  const result = await db.prepare(`
    SELECT r.race_date AS raceDate,b.race_id AS raceId,b.course,b.bet_type AS betType,b.combination,
           b.stake_yen AS stakeYen,b.return_yen AS returnYen,b.settlement_status AS settlementStatus,
           r.refund_horse_nos_json AS refundsJson
    FROM rt_races r JOIN rt_public_bets b ON b.race_id=r.race_id
    WHERE r.race_date=?
    ORDER BY b.course,b.race_id,b.id
  `).bind(date).all<CanonicalBetRow>();
  return result.results ?? [];
}

async function targetRaceCount(db: D1Database, date: string): Promise<number> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`final_daily_selection:${date}`).first<{ value: string | null }>();
  if (!row?.value) return 0;
  try {
    const parsed = JSON.parse(row.value) as { selected?: Array<{ raceId?: unknown }> };
    const raceIds = new Set<string>();
    for (const selected of parsed.selected ?? []) {
      const raceId = String(selected?.raceId ?? "");
      if (raceId) raceIds.add(raceId);
    }
    return raceIds.size;
  } catch (error) {
    console.error("TARGET_RACE_COUNT_PARSE_FAILED", date, error);
    return 0;
  }
}

async function historyRows(db: D1Database, today: string): Promise<CanonicalBetRow[]> {
  const result = await db.prepare(`
    WITH recent_dates AS (
      SELECT race_date AS raceDate
      FROM rt_races
      WHERE race_date<=?
      GROUP BY race_date
      ORDER BY race_date DESC
      LIMIT 30
    )
    SELECT r.race_date AS raceDate,b.race_id AS raceId,b.course,b.bet_type AS betType,b.combination,
           b.stake_yen AS stakeYen,b.return_yen AS returnYen,b.settlement_status AS settlementStatus,
           r.refund_horse_nos_json AS refundsJson
    FROM recent_dates d
    JOIN rt_races r ON r.race_date=d.raceDate
    JOIN rt_public_bets b ON b.race_id=r.race_id
    ORDER BY r.race_date DESC,b.course,b.race_id,b.id
  `).bind(today).all<CanonicalBetRow>();
  return result.results ?? [];
}

async function recent30(db: D1Database, today: string): Promise<RecentView | null> {
  const result = await db.prepare(`
    SELECT r.race_date AS raceDate,b.race_id AS raceId,b.course,b.bet_type AS betType,b.combination,
           b.stake_yen AS stakeYen,b.return_yen AS returnYen,b.settlement_status AS settlementStatus,
           r.refund_horse_nos_json AS refundsJson
    FROM rt_races r JOIN rt_public_bets b ON b.race_id=r.race_id
    WHERE r.race_date>=date(?,'-29 days') AND r.race_date<=? AND b.course=?
    ORDER BY r.race_date,b.race_id,b.id
  `).bind(today, today, BASE_COURSE).all<CanonicalBetRow>();
  const stat = summarizeTodayPerformance(result.results ?? [], [BASE_COURSE])[0];
  if (!stat || stat.settledRaces <= 0 || stat.stakeYen <= 0) return null;
  return { races: stat.settledRaces, stakeYen: stat.stakeYen, returnYen: stat.returnYen, roiPct: stat.roiPct };
}

async function canonicalPerformanceResponse(db: D1Database, requestedDate: string): Promise<Response> {
  const today = jstDate();
  const date = validDate(requestedDate) ? requestedDate : today;
  try {
    const [selected, allHistory, recent, targetRaces] = await Promise.all([
      rowsForDate(db, date),
      historyRows(db, today),
      recent30(db, today),
      targetRaceCount(db, date),
    ]);
    const grouped = new Map<string, CanonicalBetRow[]>();
    for (const row of allHistory) {
      const key = String(row.raceDate);
      const list = grouped.get(key) ?? [];
      list.push(row);
      grouped.set(key, list);
    }
    const history = [...grouped.entries()]
      .sort((a, b) => b[0].localeCompare(a[0]))
      .slice(0, 30)
      .map(([d, rows]) => canonicalDay(d, rows));
    return Response.json({
      ok: true,
      version: PERFORMANCE_VERSION,
      today,
      roiBasis: "ライト・2点とも精算完了したレースのみ",
      summary: { ...canonicalDay(date, selected), targetRaces },
      history,
      recent30: recent,
    }, {
      headers: {
        "cache-control": "no-store, max-age=0",
        "x-race-performance-api": PERFORMANCE_VERSION,
      },
    });
  } catch (error) {
    console.error("CANONICAL_DAILY_PERFORMANCE_FAILED", error);
    return Response.json({ ok: false, error: "DAILY_PERFORMANCE_UNAVAILABLE" }, {
      status: 503,
      headers: { "cache-control": "no-store" },
    });
  }
}

function homeStyle(): string {
  return `<style>
    .today-result{display:none!important}
    .daily-summary-top{grid-template-columns:repeat(6,minmax(0,1fr))!important}
    @media(max-width:760px){.daily-summary-top{grid-template-columns:repeat(2,minmax(0,1fr))!important}}
  </style>`;
}

async function canonicalHome(response: Response, db: D1Database, today: string): Promise<Response> {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  let html = await response.text();
  html = html.replace(/<section class="today-result"[^>]*>[\s\S]*?<\/section>/g, "");

  const fromMetric = `<div class="daily-summary-metric"><span>回収率</span><b>'+pct(s.roiPct)+'</b></div></div><div class="daily-summary-note">`;
  const toMetric = `<div class="daily-summary-metric"><span>回収率</span><b>'+pct(s.roiPct)+'</b></div><div class="daily-summary-metric"><span>的中レース数</span><b>'+Number(s.hitRaces||0)+'R</b></div><div class="daily-summary-metric"><span>対象レース数</span><b>'+Number(s.targetRaces||0)+'R</b></div></div><div class="daily-summary-note">`;
  html = html.split(fromMetric).join(toMetric);
  html = html.split("3コース合計（比較用）・").join("ライト基準・");

  try {
    const recent = await recent30(db, today);
    if (recent?.roiPct != null) {
      const replacement = `<div class="recent-roi-strip"><span>直近30日（ライト・精算済）</span><strong>${recent.roiPct.toFixed(1)}%</strong><small>${recent.races}R</small></div>`;
      html = html.replace(/<div class="recent-roi-strip">[\s\S]*?<\/div>/, replacement);
    }
  } catch (error) {
    console.error("HOME_RECENT30_SKIPPED", error);
  }

  html = html.replace("</head>", `${homeStyle()}</head>`);
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-race-ui-version", UI_VERSION);
  headers.set("x-race-roi-basis", "light-complete-settled-races");
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}

function emergencyHome(): Response {
  const html = `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>レース探偵</title><style>body{margin:0;background:#07111f;color:#eaf3ff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:720px;margin:0 auto;padding:32px 20px}.card{margin-top:22px;padding:22px;border:1px solid #28445f;border-radius:18px;background:#0d1d2d}h1{margin:0;font-size:28px}p{line-height:1.8;color:#c7d6e6}.badge{display:inline-block;margin-top:10px;padding:6px 10px;border-radius:999px;background:#153428;color:#aef1d2;font-size:13px;font-weight:700}</style><script>setTimeout(()=>location.reload(),30000)</script></head><body><main class="wrap"><h1>レース探偵</h1><section class="card"><h2>データを再接続しています</h2><p>一時的にデータベースへ接続できないため、表示を自動復旧中です。30秒ごとに再試行します。</p><span class="badge">Workerは稼働中</span></section></main></body></html>`;
  return new Response(html, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-race-ui-version": UI_VERSION,
      "x-race-emergency-fallback": "d1-unavailable",
    },
  });
}

async function runPublicMaintenance(env: Env, now: Date): Promise<void> {
  await runUpcomingCalendarRepair(env, now);
  await runUpcomingEntryWorkerRepair(env, now);
  await runUpcomingEntryDerivedRepair(env, now);
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/_ops/live-tick") return new Response("NOT_FOUND", { status: 404 });
    if (url.pathname === "/api/public/daily-performance") {
      return canonicalPerformanceResponse(env.DB, url.searchParams.get("date") ?? "");
    }
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });

    try {
      let response = await publicSite.fetch(request, env, ctx);
      if (url.pathname === "/") response = await canonicalHome(response, env.DB, jstDate());
      return response;
    } catch (error) {
      console.error("PUBLIC_SITE_FETCH_FAILED", url.pathname, error);
      if (url.pathname === "/") return emergencyHome();
      return new Response("データ取得を一時的に再試行しています。", {
        status: 503,
        headers: {
          "content-type": "text/plain; charset=utf-8",
          "cache-control": "no-store, max-age=0",
          "retry-after": "30",
          "x-race-emergency-fallback": "d1-unavailable",
        },
      });
    }
  },
  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    try {
      await runPublicMaintenance(env, new Date(controller.scheduledTime || Date.now()));
    } catch (error) {
      console.error("PUBLIC_MAINTENANCE_FAILED", error);
    }
  },
} satisfies ExportedHandler<Env>;
