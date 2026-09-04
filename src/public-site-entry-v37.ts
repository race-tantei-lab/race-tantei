import publicSite from "./public-site-entry-v34.js";
import { summarizeTodayPerformance, type TodayPerformanceBetRow } from "./v1/today-performance.js";
import { hasPostAug9SnapshotDate, postAug9DayResponse, postAug9PerformanceResponse } from "./v1/post-aug9-public-fallback.js";
import { runUpcomingCalendarRepair } from "./v1/upcoming-calendar-repair.js";
import { runUpcomingEntryWorkerRepair } from "./v1/upcoming-entry-worker-repair.js";
import { runUpcomingEntryDerivedRepair } from "./v1/upcoming-entry-derived-repair.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v37-resilient-home-20260905";
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
type ResilientRaceRow = {
  raceId: string;
  venue: string;
  raceNo: number;
  startTimeUtc: string | null;
  finalBetCount: number;
};

type SelectionPayload = { selected?: Array<{ raceId?: unknown }> };

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function validDate(value: string | null): value is string {
  return Boolean(value && /^20\d{2}-\d{2}-\d{2}$/.test(value));
}

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function jstTime(value: string | null): string {
  if (!value) return "--:--";
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) return "--:--";
  return new Date(ms).toLocaleTimeString("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
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
    const parsed = JSON.parse(row.value) as SelectionPayload;
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
    return postAug9PerformanceResponse(requestedDate, today);
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

async function resilientHomeFromD1(db: D1Database, today: string): Promise<Response> {
  const [raceResult, selectionRow] = await Promise.all([
    db.prepare(`
      SELECT r.race_id AS raceId,r.venue,r.race_no AS raceNo,r.start_time_utc AS startTimeUtc,
             (SELECT COUNT(*) FROM rt_public_bets b WHERE b.race_id=r.race_id AND b.source_prediction_id=-2) AS finalBetCount
      FROM rt_races r
      WHERE r.race_date=?
      ORDER BY r.start_time_utc,r.venue,r.race_no
    `).bind(today).all<ResilientRaceRow>(),
    db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
      .bind(`final_daily_selection:${today}`).first<{ value: string | null }>(),
  ]);

  const races = raceResult.results ?? [];
  let selectedIds = new Set<string>();
  if (selectionRow?.value) {
    try {
      const parsed = JSON.parse(selectionRow.value) as SelectionPayload;
      selectedIds = new Set((parsed.selected ?? []).map((item) => String(item.raceId ?? "")).filter(Boolean));
    } catch (error) {
      console.error("RESILIENT_HOME_SELECTION_PARSE_FAILED", error);
    }
  }

  const nowMs = Date.now();
  const next = races.find((race) => selectedIds.has(String(race.raceId)) && Number.isFinite(Date.parse(String(race.startTimeUtc || ""))) && Date.parse(String(race.startTimeUtc)) > nowMs)
    ?? races.find((race) => Number.isFinite(Date.parse(String(race.startTimeUtc || ""))) && Date.parse(String(race.startTimeUtc)) > nowMs)
    ?? null;
  const selectedFinals = races.filter((race) => selectedIds.has(String(race.raceId)) && Number(race.finalBetCount) === 6).length;
  const venues = new Map<string, ResilientRaceRow[]>();
  for (const race of races) {
    const venue = String(race.venue || "未定");
    const list = venues.get(venue) ?? [];
    list.push(race);
    venues.set(venue, list);
  }

  const nextHtml = next
    ? `<section class="panel next"><div class="label">${selectedIds.has(String(next.raceId)) ? "次の対象レース" : "次のレース"}</div><h2>${escapeHtml(next.venue)} ${Number(next.raceNo)}R</h2><p>${jstTime(next.startTimeUtc)} 発走予定</p><strong>${Number(next.finalBetCount) === 6 ? "買い目確定済み" : selectedIds.has(String(next.raceId)) ? "買い目作成待ち" : "対象選定待ち"}</strong></section>`
    : `<section class="panel next"><div class="label">本日の進行</div><h2>次のレースはありません</h2></section>`;

  const venueHtml = [...venues.entries()].map(([venue, venueRaces]) => `<section class="venue"><h3>${escapeHtml(venue)}</h3><div class="grid">${venueRaces.map((race) => {
    const selected = selectedIds.has(String(race.raceId));
    const final = Number(race.finalBetCount) === 6;
    return `<div class="race ${selected ? "target" : ""}"><b>${Number(race.raceNo)}R</b><span>${jstTime(race.startTimeUtc)}</span><small>${final ? "買い目確定" : selected ? "対象" : "—"}</small></div>`;
  }).join("")}</div></section>`).join("");

  const selectionState = selectedIds.size === 15
    ? `対象15R / 買い目確定 ${selectedFinals}R`
    : selectedIds.size > 0
      ? `対象 ${selectedIds.size}R（15R確定待ち）`
      : "対象レース選定待ち";
  const html = `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>レース探偵</title><style>
    *{box-sizing:border-box}body{margin:0;background:#07111f;color:#eaf3ff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:860px;margin:0 auto;padding:32px 20px 60px}h1{font-size:30px;margin:0 0 6px}.sub{color:#93aac1;margin:0 0 22px}.panel,.venue{background:#0d1d2d;border:1px solid #28445f;border-radius:18px;padding:18px;margin:14px 0}.next{border-color:#34617e}.label{font-size:12px;color:#8fb1cc;font-weight:700}.next h2{margin:8px 0 4px}.next p{margin:0 0 8px;color:#bccddd}.next strong{color:#7ee7d8}.status{display:inline-flex;padding:7px 11px;border-radius:999px;background:#153428;color:#aef1d2;font-size:13px;font-weight:700}.venue h3{margin:0 0 12px}.grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}.race{padding:10px 8px;border-radius:12px;background:#0a1725;border:1px solid #1b3348;display:flex;flex-direction:column;gap:3px}.race.target{border-color:#4a9f91;background:#0d2829}.race span,.race small{font-size:12px;color:#9db2c6}.race.target small{color:#83e2d4}@media(max-width:680px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
  </style><script>setTimeout(()=>location.reload(),30000)</script></head><body><main class="wrap"><h1>レース探偵</h1><p class="sub">${escapeHtml(today)} / 本日のレース ${races.length}R</p><div class="status">${escapeHtml(selectionState)}</div>${nextHtml}${venueHtml}<p class="sub">表示系の自動復旧モードです。データはD1から直接読み込んでいます。</p></main></body></html>`;
  return new Response(html, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-race-ui-version": UI_VERSION,
      "x-race-resilient-home": "direct-d1",
    },
  });
}

function serviceUnavailableHome(): Response {
  const html = `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>レース探偵</title><style>body{margin:0;background:#07111f;color:#eaf3ff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:720px;margin:0 auto;padding:32px 20px}.card{margin-top:22px;padding:22px;border:1px solid #28445f;border-radius:18px;background:#0d1d2d}p{line-height:1.8;color:#c7d6e6}</style><script>setTimeout(()=>location.reload(),30000)</script></head><body><main class="wrap"><h1>レース探偵</h1><section class="card"><h2>データ取得を再試行しています</h2><p>表示データの読み込みに失敗しました。30秒後に自動で再試行します。</p></section></main></body></html>`;
  return new Response(html, {
    status: 503,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "retry-after": "30",
      "x-race-ui-version": UI_VERSION,
      "x-race-emergency-fallback": "data-read-failed",
    },
  });
}

async function ensureRaceDayIndexes(db: D1Database): Promise<void> {
  await db.batch([
    db.prepare("CREATE INDEX IF NOT EXISTS rt_idx_races_date ON rt_races(race_date DESC, venue, race_no)"),
    db.prepare("CREATE INDEX IF NOT EXISTS rt_idx_public_bets_race ON rt_public_bets(race_id, id)"),
    db.prepare("CREATE INDEX IF NOT EXISTS rt_idx_public_bets_settlement ON rt_public_bets(settlement_status, course, race_id)"),
  ]);
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
    if (url.pathname === "/api/public/day") {
      const requestedDate = url.searchParams.get("date") ?? "";
      if (hasPostAug9SnapshotDate(requestedDate)) {
        const frozen = postAug9DayResponse(requestedDate);
        if (frozen) return frozen;
      }
    }
    if (url.pathname === "/api/public/daily-performance") {
      const requestedDate = url.searchParams.get("date") ?? "";
      if (hasPostAug9SnapshotDate(requestedDate)) return postAug9PerformanceResponse(requestedDate, jstDate());
      return canonicalPerformanceResponse(env.DB, requestedDate);
    }
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });

    let response: Response;
    try {
      response = await publicSite.fetch(request, env, ctx);
    } catch (error) {
      console.error("PUBLIC_SITE_UPSTREAM_FETCH_FAILED", url.pathname, error);
      if (url.pathname === "/") {
        try {
          return await resilientHomeFromD1(env.DB, jstDate());
        } catch (fallbackError) {
          console.error("PUBLIC_RESILIENT_HOME_FAILED", fallbackError);
          return serviceUnavailableHome();
        }
      }
      return new Response("データ取得を一時的に再試行しています。", {
        status: 503,
        headers: {
          "content-type": "text/plain; charset=utf-8",
          "cache-control": "no-store, max-age=0",
          "retry-after": "30",
          "x-race-emergency-fallback": "upstream-render-failed",
        },
      });
    }

    if (url.pathname === "/") {
      try {
        return await canonicalHome(response, env.DB, jstDate());
      } catch (error) {
        console.error("PUBLIC_HOME_ENHANCEMENT_FAILED", error);
        return response;
      }
    }
    return response;
  },
  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    try {
      await ensureRaceDayIndexes(env.DB);
    } catch (error) {
      console.error("PUBLIC_RACE_DAY_INDEX_REPAIR_FAILED", error);
    }
    try {
      await runPublicMaintenance(env, new Date(controller.scheduledTime || Date.now()));
    } catch (error) {
      console.error("PUBLIC_MAINTENANCE_FAILED", error);
    }
  },
} satisfies ExportedHandler<Env>;
