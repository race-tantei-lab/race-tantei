import core from "./public-site-entry-v37-core.js";
import { NORMAL_HOME_SNAPSHOT } from "./normal-home-snapshot.js";
import { RECENT_HOME_CALENDAR_SNAPSHOT } from "./recent-home-calendar-snapshot.js";
import { RECENT_PUBLIC_DAY_SNAPSHOT } from "./recent-public-day-snapshot.js";
import { RECENT_PUBLIC_FINAL_EVIDENCE } from "./recent-public-final-evidence.js";
import { projectCurrentPublicState } from "./v1/current-day-public-api.js";
import { quotaFreeOfficialResultResponse } from "./v1/quota-free-jra-result-20260919.js";
import { fastCurrentDayRaceDetailResponse } from "./v1/current-day-race-detail-fast.js";
import { shell } from "./v1/public-ui.js";
import { readPublicCalendarCache } from "./v1/public-calendar-cache.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v37-instant-home-20260921";
const FORBIDDEN_RECOVERY_TEXT = [
  "データ取得を一時的に再試行しています",
  "データ取得を再試行しています",
  "データを再接続しています",
  "データベースへ接続できない",
  "表示データの読み込みに失敗しました",
  "表示系の自動復旧モードです",
  "一時的にページを表示できません。",
] as const;

type CalendarRow = { raceDate: string; venue: string; raceCount: number };
type SnapshotRace = {
  raceId: string; raceDate: string; venue: string; raceNo: number; raceName: string | null;
  startTimeJst: string | null; startTimeUtc: string | null; surface: string | null;
  distanceM: number | null; status: string; refundsJson: string | null;
};
type SnapshotBet = {
  raceId: string; course: string; betType: string; combination: string;
  returnYen: number | null; settlementStatus: string;
  stakeYen?: number; assumedOdds?: number; lockedAt?: string; sourcePredictionId?: number;
};
type SnapshotDay = { selection: string | null; races: SnapshotRace[]; bets: SnapshotBet[] };
const DAY_SNAPSHOT = RECENT_PUBLIC_DAY_SNAPSHOT as unknown as Record<string, SnapshotDay>;
const FINAL_EVIDENCE = RECENT_PUBLIC_FINAL_EVIDENCE as unknown as Record<string, { tickets: Array<{ betType:string; combination:string; horses:number[]; predictedProbability:number; officialOdds:number; valueProduct:number; score:number }>; horseNames: Record<string,string> }>;

// Public scheduled work remains maintenance-only. Race-bet generation is
// owned exclusively by the isolated primary/backup live-deadline Workers.

function hasForbidden(text: string): boolean {
  return FORBIDDEN_RECOVERY_TEXT.some((value) => text.includes(value))
    || /データ.{0,16}(?:再試行|再接続)/.test(text)
    || /(?:再試行|再接続).{0,16}(?:しています|中です)/.test(text);
}

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch] ?? ch));
}

function staticRecentCalendar(): CalendarRow[] {
  const byKey = new Map<string, CalendarRow>();
  for (const row of RECENT_HOME_CALENDAR_SNAPSHOT) {
    const normalized = {
      raceDate: String(row.raceDate),
      venue: String(row.venue),
      raceCount: Number(row.raceCount),
    };
    byKey.set(`${normalized.raceDate}\u0000${normalized.venue}`, normalized);
  }

  // The current/recent day snapshot is the quota-free source of truth when D1
  // reads are blocked. Let it update stale calendar counts and add missing
  // venues (for example the second venue on the current race day).
  for (const [raceDate, day] of Object.entries(DAY_SNAPSHOT)) {
    const counts = new Map<string, number>();
    for (const race of day?.races ?? []) {
      const venue = String(race.venue ?? "");
      if (!venue) continue;
      counts.set(venue, (counts.get(venue) ?? 0) + 1);
    }
    for (const [venue, raceCount] of counts) {
      byKey.set(`${raceDate}\u0000${venue}`, { raceDate, venue, raceCount });
    }
  }

  return [...byKey.values()].sort((a, b) => a.raceDate.localeCompare(b.raceDate) || a.venue.localeCompare(b.venue, "ja"));
}

async function loadRecentCalendar(env: Env): Promise<CalendarRow[]> {
  const today = new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const byKey = new Map<string, CalendarRow>();
  for (const row of staticRecentCalendar()) {
    byKey.set(`${row.raceDate}\u0000${row.venue}`, row);
  }

  try {
    // One indexed system-state read on the normal path. The public maintenance
    // cron refreshes this cache, so the home page does not scan historical races.
    const cached = await readPublicCalendarCache(env.DB);
    for (const row of cached) {
      if (!row.raceDate || !row.venue || Number(row.raceCount) <= 0) continue;
      byKey.set(`${row.raceDate}\u0000${row.venue}`, {
        raceDate: String(row.raceDate),
        venue: String(row.venue),
        raceCount: Number(row.raceCount),
      });
    }

    // If the cache was refreshed before today's card was loaded, repair only
    // today's two/three venue rows. This keeps the request bounded and makes the
    // current race day visible immediately instead of waiting for a 6h cache TTL.
    const hasToday = [...byKey.values()].some((row) => row.raceDate === today);
    if (!hasToday) {
      const result = await env.DB.prepare(`
        SELECT race_date AS raceDate, venue, COUNT(*) AS raceCount
        FROM rt_races
        WHERE race_date=?
        GROUP BY race_date, venue
        ORDER BY venue
      `).bind(today).all<CalendarRow>();
      for (const row of result.results ?? []) {
        if (!row.raceDate || !row.venue || Number(row.raceCount) <= 0) continue;
        byKey.set(`${row.raceDate}\u0000${row.venue}`, {
          raceDate: String(row.raceDate),
          venue: String(row.venue),
          raceCount: Number(row.raceCount),
        });
      }
    }

    return [...byKey.values()].sort((a, b) => a.raceDate.localeCompare(b.raceDate) || a.venue.localeCompare(b.venue, "ja"));
  } catch (error) {
    console.error("V37_RECENT_CALENDAR_DB_FAILED", error);
    return [...byKey.values()].sort((a, b) => a.raceDate.localeCompare(b.raceDate) || a.venue.localeCompare(b.venue, "ja"));
  }
}

function mergeRecentCalendar(html: string, rows: CalendarRow[]): string {
  const marker = "const calendar=";
  const start = html.indexOf(marker);
  const end = html.indexOf(";const today=", start);
  if (start < 0 || end < 0 || !rows.length) return html;

  // Keep the initial document small. The legacy snapshot embeds ~10 years of
  // calendar rows in the first blocking script; current-day rendering only
  // needs the recent/current rows. Older years are restored lazily after the
  // first paint from /api/public/calendar-archive.
  const byKey = new Map<string, CalendarRow>();
  for (const row of rows) {
    const normalized = {
      raceDate: String(row.raceDate),
      venue: String(row.venue),
      raceCount: Number(row.raceCount),
    };
    if (!normalized.raceDate || !normalized.venue || normalized.raceCount <= 0) continue;
    byKey.set(`${normalized.raceDate}\u0000${normalized.venue}`, normalized);
  }
  const recent = [...byKey.values()].sort((a, b) => a.raceDate.localeCompare(b.raceDate) || a.venue.localeCompare(b.venue, "ja"));
  return `${html.slice(0, start + marker.length)}${JSON.stringify(recent)}${html.slice(end)}`;
}

function calendarArchiveResponse(): Response {
  const marker = "const calendar=";
  const start = NORMAL_HOME_SNAPSHOT.indexOf(marker);
  const end = NORMAL_HOME_SNAPSHOT.indexOf(";const today=", start);
  const raw = start >= 0 && end > start
    ? NORMAL_HOME_SNAPSHOT.slice(start + marker.length, end)
    : "[]";
  return new Response(raw, {
    status: 200,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=86400, stale-while-revalidate=604800",
      "x-race-calendar-path": "snapshot-archive-v1",
    },
  });
}

function lazyCalendarArchiveScript(): string {
  return `<script>(()=>{let started=false;async function hydrate(){if(started)return;started=true;try{const r=await fetch("/api/public/calendar-archive",{cache:"force-cache"});if(!r.ok)return;const old=await r.json();if(!Array.isArray(old)||!old.length)return;const seen=new Set(calendar.map(x=>x.raceDate+"\\u0000"+x.venue));for(const x of old){const d=String(x&&x.raceDate||""),v=String(x&&x.venue||""),n=Number(x&&x.raceCount||0);const k=d+"\\u0000"+v;if(d&&v&&n>0&&!seen.has(k)){calendar.push({raceDate:d,venue:v,raceCount:n});seen.add(k)}}calendar.sort((a,b)=>a.raceDate.localeCompare(b.raceDate)||a.venue.localeCompare(b.venue,"ja"));const p=parts(selectedDate),years=uniq(calendar.map(x=>x.raceDate.slice(0,4))).sort((a,b)=>b.localeCompare(a)),yr=byId("years");if(yr){yr.replaceChildren();years.forEach(y=>yr.append(button(y+"年",y===p.y,()=>{const ds=calendar.filter(x=>x.raceDate.startsWith(y+"-")).map(x=>x.raceDate);selectedDate=ds.at(-1);selectedVenue="";renderHierarchy();})))}}catch(_){}}const kick=()=>hydrate();const yr=byId("years");if(yr){yr.addEventListener("pointerenter",kick,{once:true});yr.addEventListener("touchstart",kick,{once:true,passive:true});yr.addEventListener("focusin",kick,{once:true})}if("requestIdleCallback"in window){window.requestIdleCallback(kick,{timeout:8000})}else{setTimeout(kick,5000)}})();</script>`;
}

function normalResponse(response: Response, html: string, path: string): Response {
  const headers = new Headers(response.headers);
  headers.delete("x-race-resilient-home");
  headers.delete("x-race-emergency-fallback");
  headers.delete("content-length");
  headers.set("content-type", "text/html; charset=utf-8");
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-race-ui-version", UI_VERSION);
  headers.set("x-race-home-path", path);
  return new Response(html, { status: 200, headers });
}

function rewriteEmbeddedToday(html: string): string {
  const today = new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const [, month, day] = today.split("-").map(Number);
  return html
    .replace(/const today="20\d{2}-\d{2}-\d{2}";/g, `const today="${today}";`)
    .replace(/const TODAY="20\d{2}-\d{2}-\d{2}";/g, `const TODAY="${today}";`)
    .replace(/本日の集計（\d{1,2}\/\d{1,2}）/g, `本日の集計（${month}/${day}）`);
}

function embeddedTodayResultsHtml(): string {
  const today = new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 10);
  const day = DAY_SNAPSHOT[today];
  if (!day?.bets?.length) return "";
  const courses = ["ライト", "スタンダード", "プレミアム"];
  const rows = courses.map((course) => {
    const bets = day.bets.filter((bet) => bet.course === course);
    const raceIds = [...new Set(bets.map((bet) => bet.raceId))];
    const settledIds = raceIds.filter((raceId) => {
      const rowsForRace = bets.filter((bet) => bet.raceId === raceId);
      return rowsForRace.length > 0 && rowsForRace.every((bet) => bet.settlementStatus === "settled");
    });
    const hitIds = settledIds.filter((raceId) => bets.some((bet) => bet.raceId === raceId && Number(bet.returnYen ?? 0) > 0));
    const stake = bets.filter((bet) => settledIds.includes(bet.raceId)).reduce((sum, bet) => sum + Number(bet.stakeYen ?? 0), 0);
    const returned = bets.filter((bet) => settledIds.includes(bet.raceId)).reduce((sum, bet) => sum + Number(bet.returnYen ?? 0), 0);
    const roi = stake > 0 ? returned / stake * 100 : 0;
    return '<div class="today-result-row"><b>' + esc(course) + '</b><span>' + settledIds.length + '/' + raceIds.length + 'R精算　的中' + hitIds.length + 'R</span><strong>' + roi.toFixed(1) + '%</strong></div>';
  }).join("");
  return '<section class="card today-results"><div class="section-title"><h2>今日の結果</h2><span class="muted">精算済み時点</span></div>' + rows + '</section>';
}

function embeddedNormalHome(calendarRows: CalendarRow[] = staticRecentCalendar()): Response {
  let html = rewriteEmbeddedToday(mergeRecentCalendar(NORMAL_HOME_SNAPSHOT, calendarRows));
  const canonicalBase = '<base href="https://race-tantei-phase0.race-tantei.workers.dev/"><link rel="canonical" href="https://race-tantei-phase0.race-tantei.workers.dev/">';
  if (!html.includes('<base href=')) html = html.replace('<head>', '<head>' + canonicalBase);
  const todayResults = embeddedTodayResultsHtml();
  if (todayResults && !html.includes("今日の結果")) {
    html = html.replace('<div class="section-title"><h2>累計回収率</h2>', todayResults + '<div class="section-title"><h2>累計回収率</h2>');
  }
  html = html.replace("</body>", `${lazyCalendarArchiveScript()}</body>`);
  return new Response(html, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-race-ui-version": UI_VERSION,
      "x-race-home-path": "v37-normal-snapshot",
    },
  });
}

function parseSelection(raw: string | null): Set<string> | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { selected?: Array<{ raceId?: unknown }> };
    const ids = Array.isArray(parsed.selected) ? parsed.selected.map((row) => String(row?.raceId ?? "")).filter(Boolean) : [];
    return ids.length ? new Set(ids) : null;
  } catch { return null; }
}

function snapshotBetsForRace(day: SnapshotDay, race: SnapshotRace): Array<SnapshotBet & { refundsJson: string | null }> {
  return day.bets
    .filter((bet) => String(bet.raceId) === String(race.raceId))
    .map((bet) => ({ ...bet, refundsJson: race.refundsJson }));
}

function staticPublicDay(date: string): Response | null {
  const day = DAY_SNAPSHOT[date];
  if (!day?.races?.length) return null;
  const frozen = parseSelection(day.selection);
  const refundByRace = new Map(day.races.map((race) => [race.raceId, race.refundsJson]));
  const byRace = new Map<string, Array<SnapshotBet & { refundsJson: string | null }>>();
  for (const bet of day.bets) {
    const list = byRace.get(bet.raceId) ?? [];
    list.push({ ...bet, refundsJson: refundByRace.get(bet.raceId) ?? null });
    byRace.set(bet.raceId, list);
  }
  const nowMs = Date.now();
  const races = day.races.map((race) => ({
    raceId: race.raceId,
    raceDate: race.raceDate,
    venue: race.venue,
    raceNo: Number(race.raceNo),
    raceName: race.raceName,
    startTimeJst: race.startTimeJst,
    startTimeUtc: race.startTimeUtc,
    surface: race.surface,
    distanceM: race.distanceM === null ? null : Number(race.distanceM),
    status: race.status,
    publicState: projectCurrentPublicState(race, frozen, byRace.get(race.raceId) ?? [], nowMs),
  }));
  return Response.json({ ok: true, date, races, betStateAvailable: true, fallbackSource: "recent-public-day-snapshot-v1" }, {
    headers: {
      "cache-control": "no-store, max-age=0",
      "x-race-current-day-path": "recent-public-day-snapshot-v1",
    },
  });
}

function stateCssClass(code: string): string {
  if (code === "buy" || code === "hit") return "buy";
  if (code === "skip") return "skip";
  if (code === "pending" || code === "target" || code === "refund") return "pending";
  return "none";
}

function staticRaceDetail(raceId: string): Response | null {
  const date = raceId.slice(0, 10);
  const day = DAY_SNAPSHOT[date];
  if (!day?.races?.length) return null;
  const race = day.races.find((row) => String(row.raceId) === raceId);
  if (!race) return null;
  const frozen = parseSelection(day.selection);
  const bets = snapshotBetsForRace(day, race);
  const evidence = FINAL_EVIDENCE[raceId] ?? null;
  const state = projectCurrentPublicState(race, frozen, bets, Date.now());
  const stateCode = String(state.code ?? "pending");
  const stateLabel = String(state.label ?? "判定中");
  const meta = [race.raceDate.replaceAll("-", "/"), race.venue, String(Number(race.raceNo))+"R", race.startTimeJst ? race.startTimeJst+"発走" : null, race.surface, race.distanceM == null ? null : String(Number(race.distanceM))+"m"].filter(Boolean).join("　");
  const courseOrder = ["ライト", "スタンダード", "プレミアム"];
  let betPanel = "";
  let reasonPanel = "";
  if (bets.length) {
    const blocks = courseOrder.map((course, index) => {
      const rows = bets.filter((bet) => bet.course === course);
      const body = rows.map((bet) => "<tr><td>"+esc(bet.betType)+"</td><td>"+esc(bet.combination)+"</td><td>"+(Number.isFinite(Number(bet.assumedOdds))?Number(bet.assumedOdds).toFixed(1)+"倍":"—")+"</td><td>"+(Number.isFinite(Number(bet.stakeYen))?Math.round(Number(bet.stakeYen)).toLocaleString("ja-JP")+"円":"—")+"</td><td>"+(bet.settlementStatus==="settled"?Math.round(Number(bet.returnYen??0)).toLocaleString("ja-JP")+"円":"—")+"</td></tr>").join("");
      return "<div class=\"course-view\" data-course=\""+index+"\" style=\""+(index===0?"":"display:none")+"\"><h3 class=\"course-heading\">"+esc(course)+"</h3><div class=\"bet-table\"><table><thead><tr><th>券種</th><th>組合せ</th><th>オッズ</th><th>購入</th><th>払戻</th></tr></thead><tbody>"+body+"</tbody></table></div></div>";
    }).join("");
    betPanel = "<section data-race-panel=\"bets\"><div class=\"section-title\"><h2>確定買い目</h2><span class=\"status buy\">固定済み</span></div>"+blocks+"</section>";
    const tickets = evidence?.tickets ?? [];
    reasonPanel = "<section id=\"race-panel-reason\" data-race-panel=\"reason\" hidden><div class=\"section-title\"><h2>買い目の理由</h2></div><div class=\"ticket-reason-list\">"+tickets.map((ticket) => {
      const names = ticket.horses.map((horseNo) => String(horseNo)+"番 "+String(evidence?.horseNames?.[String(horseNo)] ?? "")).join(" / ");
      return "<article class=\"ticket-reason-card\" data-ticket-reason=\""+esc(ticket.betType)+":"+esc(ticket.combination)+"\"><strong>"+esc(ticket.betType)+" "+esc(ticket.combination)+"</strong><div>"+esc(names)+"</div><div>この組合せが当たる推定確率：<b>"+(ticket.predictedProbability*100).toFixed(2)+"%</b></div><div>JRA公式オッズ：<b>"+ticket.officialOdds.toFixed(1)+"倍</b></div><div>推定確率 × 公式オッズ：<b>"+ticket.valueProduct.toFixed(4)+"</b></div><div>買い目の評価点：<b>"+ticket.score.toFixed(6)+"</b></div><p><b>選ばれた理由：</b>発走前に保存された最終確定時の予測値とJRA公式オッズです。quota-lock中も再計算せず、この固定済み正本を表示しています。</p></article>";
    }).join("")+"</div></section>";
  } else {
    betPanel = "<section data-race-panel=\"bets\"><div class=\"section-title\"><h2>買い目</h2></div><p>"+esc(stateLabel)+"</p></section>";
    reasonPanel = "<section id=\"race-panel-reason\" data-race-panel=\"reason\" hidden><div class=\"section-title\"><h2>買い目の理由</h2></div><p>確定買い目はありません。</p></section>";
  }
  const horseRows = evidence ? Object.entries(evidence.horseNames).sort((a,b)=>Number(a[0])-Number(b[0])).map(([no,name]) => "<tr><td>"+esc(no)+"</td><td>"+esc(name)+"</td></tr>").join("") : "";
  const horses = "<section data-race-panel=\"horses\" hidden><div class=\"section-title\"><h2>出走馬</h2></div><div class=\"runner-table\"><table><thead><tr><th>馬番</th><th>馬名</th></tr></thead><tbody>"+horseRows+"</tbody></table></div></section>";
  const tabs = "<nav class=\"race-detail-tabs\" data-race-tabs><button type=\"button\" data-race-tab=\"bets\">予想買い目</button><button type=\"button\" data-race-tab=\"reason\">根拠</button><button type=\"button\" data-race-tab=\"horses\">出走馬</button></nav>";
  const script = "<script>(function(){var panels={bets:document.querySelector('[data-race-panel=\"bets\"]'),reason:document.querySelector('[data-race-panel=\"reason\"]'),horses:document.querySelector('[data-race-panel=\"horses\"]')};function activate(name){Object.keys(panels).forEach(function(k){if(panels[k])panels[k].hidden=k!==name;});document.querySelectorAll('[data-race-tab]').forEach(function(b){b.setAttribute('aria-selected',b.getAttribute('data-race-tab')===name?'true':'false');});}document.querySelectorAll('[data-race-tab]').forEach(function(b){b.addEventListener('click',function(){activate(b.getAttribute('data-race-tab'));});});activate('bets');})();</script>";
  const body = "<a class=\"back\" href=\"/races/\">← レース一覧へ</a><section class=\"hero\"><div class=\"race-title\"><span class=\"race-no\">"+Number(race.raceNo)+"R</span><h1>"+esc(race.raceName ?? race.venue+" "+race.raceNo+"R")+"</h1><span class=\"status "+stateCssClass(stateCode)+"\">"+esc(stateLabel)+"</span></div><p>"+esc(meta)+"</p></section>"+tabs+betPanel+reasonPanel+horses+script;
  return new Response(shell(race.venue+race.raceNo+"R", body), { status: 200, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store, max-age=0", "x-race-ui-version": UI_VERSION, "x-race-detail-path": "recent-public-day-snapshot-v2-fixed-evidence" } });
}
async function fetchPublicDay(request: Request, env: Env, ctx: ExecutionContext, date: string): Promise<Response> {
  let live: Response | null = null;
  try {
    live = await core.fetch(request, env, ctx);
    const text = await live.text();
    let payload: { races?: unknown } | null = null;
    try { payload = JSON.parse(text) as { races?: unknown }; } catch { /* handled below */ }
    if (live.ok && Array.isArray(payload?.races) && payload.races.length > 0) {
      return new Response(text, { status: live.status, statusText: live.statusText, headers: live.headers });
    }
    const fallback = staticPublicDay(date);
    if (fallback) return fallback;
    return new Response(text, { status: live.status, statusText: live.statusText, headers: live.headers });
  } catch (error) {
    console.error("V37_PUBLIC_DAY_USING_SNAPSHOT", date, error);
    return staticPublicDay(date) ?? new Response("NOT_FOUND", { status: 404 });
  }
}

async function fetchNormalHome(_request: Request, _env: Env, _ctx: ExecutionContext): Promise<Response> {
  // Do not block first paint on D1. Current/recent race days are embedded in the
  // tiny recent snapshot, while historical years remain lazy-loaded.
  return embeddedNormalHome(staticRecentCalendar());
}
async function fetchRaceList(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const homeUrl = new URL(request.url);
  homeUrl.pathname = "/";
  const homeRequest = new Request(homeUrl.toString(), request);
  return fetchNormalHome(homeRequest, env, ctx);
}

async function fetchRaceDetail(request: Request, env: Env, ctx: ExecutionContext, raceId: string): Promise<Response> {
  // Results must stay visible even when the D1 daily rows_read quota is exhausted.
  // For races covered by the quota-free JRA map, prefer the official result page
  // once it exists; before result publication this returns null and normal detail
  // rendering continues.
  try {
    const official = await quotaFreeOfficialResultResponse(raceId);
    if (official) return official;
  } catch (error) {
    console.error("V37_RACE_DETAIL_DIRECT_JRA_FIRST_FAILED", raceId, error);
  }

  try {
    const response = await core.fetch(request, env, ctx);
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("text/html")) {
      const html = await response.text();
      const recoveryHeader = Boolean(response.headers.get("x-race-resilient-home") || response.headers.get("x-race-emergency-fallback"));
      if (response.status < 500 && html && !recoveryHeader && !hasForbidden(html) && !html.includes("レースが見つかりません")) {
        const headers = new Headers(response.headers);
        headers.delete("content-length");
        headers.set("cache-control", "no-store, max-age=0");
        headers.set("x-race-ui-version", UI_VERSION);
        headers.set("x-race-detail-path", "v37-normal");
        return new Response(html, { status: response.status, statusText: response.statusText, headers });
      }
    } else if (response.ok && !hasForbidden(await response.clone().text())) {
      return response;
    }
    console.error("V37_RACE_DETAIL_USING_SNAPSHOT", raceId, response.status);
  } catch (error) {
    console.error("V37_RACE_DETAIL_USING_SNAPSHOT_AFTER_ERROR", raceId, error);
  }
  try {
    const official = await quotaFreeOfficialResultResponse(raceId);
    if (official) return official;
  } catch (error) {
    console.error("V37_RACE_DETAIL_DIRECT_JRA_FAILED", raceId, error);
  }
  return staticRaceDetail(raceId) ?? new Response("NOT_FOUND", { status: 404, headers: { "cache-control": "no-store" } });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const pathname = url.pathname;
    if (pathname === "/_ops/live-tick") return new Response("NOT_FOUND", { status: 404, headers: { "cache-control": "no-store" } });
    if (request.method === "GET" && pathname === "/api/public/calendar-archive") return calendarArchiveResponse();
    if (request.method === "GET" && pathname === "/api/public/day") return fetchPublicDay(request, env, ctx, url.searchParams.get("date") ?? "");
    if (request.method === "GET" && (pathname === "/" || pathname === "/index.html")) return fetchNormalHome(request, env, ctx);
    if (request.method === "GET" && (pathname === "/races" || pathname === "/races/")) return fetchRaceList(request, env, ctx);
    if (request.method === "GET" && /^\/races\/20\d{2}-\d{2}-\d{2}-[a-z0-9-]+-\d{2}\/?$/i.test(pathname)) {
      const raceId = decodeURIComponent(pathname.replace(/^\/races\//, "").replace(/\/$/, ""));
      const direct = await fastCurrentDayRaceDetailResponse(env.DB, raceId);
      if (direct) return direct;
      return fetchRaceDetail(request, env, ctx, raceId);
    }
    return core.fetch(request, env, ctx);
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (core.scheduled) await core.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
