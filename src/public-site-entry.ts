import { runPublicDataSync } from "./public-data-sync.js";
import { ensurePublicHistory, getPublicBets } from "./v1/public-history-db.js";
import {
  FROZEN_PUBLIC_METRICS,
  FROZEN_PUBLIC_MONTHLY,
  isFrozenSelectedRace,
  type FrozenMetric,
  type FrozenMonthlyMetric
} from "./v1/frozen-public-data.js";
import type { Env } from "./v1/types.js";
import { escapeHtml, formatYen } from "./v1/utils.js";
import { conditionsPage, guidePage, json, redirect, response, shell } from "./v1/public-ui.js";

const COURSE_NAMES = ["ライト", "スタンダード", "プレミアム"] as const;
const COURSE_BUDGETS = [2000, 5000, 10000] as const;

type CalendarRow = { raceDate: string; venue: string; raceCount: number };
type RaceIndexRow = {
  raceId: string; raceDate: string; venue: string; raceNo: number; raceName: string;
  startTimeJst: string | null; startTimeUtc: string | null; surface: string | null;
  distanceM: number | null; status: string;
};
type RaceDetailRow = RaceIndexRow & {
  conditions: string | null; direction: string | null; weather: string | null; trackCondition: string | null;
};
type RunnerRow = {
  horseNo: number; frameNo: number | null; horseName: string; sexAge: string | null;
  horseWeight: number | null; weightChange: number | null; jockey: string | null;
  assignedWeight: number | null; trainer: string | null; stable: string | null;
  winOdds: number | null; popularity: number | null; runnerStatus: string;
  finishPosition: number | null; resultStatus: string | null;
};

function jstDateKey(date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function monthlyRows(budget: number, rows: FrozenMonthlyMetric[]): string {
  const course = COURSE_NAMES[COURSE_BUDGETS.indexOf(budget as 2000 | 5000 | 10000)] ?? "ライト";
  return rows.filter((row) => row.course === course).map((row) =>
    `<div class="monthly-row"><b>${escapeHtml(row.month.replace("-", "/"))}</b><span>${row.settledRaces}R　${formatYen(row.stakeYen)} → ${formatYen(row.returnYen)}</span><strong class="${row.roiPct >= 100 ? "plus" : "minus"}">${row.roiPct.toFixed(1)}%</strong></div>`
  ).join("");
}

function metricCards(metrics: FrozenMetric[], monthly: FrozenMonthlyMetric[]): string {
  return `<section class="metrics">${metrics.map((row) => `<details class="card metric"><summary><b>${row.course}</b><strong>${row.roiPct.toFixed(1)}%</strong><small>${row.settledRaces}R　購入 ${formatYen(row.stakeYen)}　払戻 ${formatYen(row.returnYen)}</small></summary><div class="monthly">${monthlyRows(row.budget, monthly)}</div></details>`).join("")}</section>`;
}

async function calendar(db: D1Database): Promise<CalendarRow[]> {
  const rows = await db.prepare(`SELECT race_date AS raceDate, venue, COUNT(*) AS raceCount FROM rt_races GROUP BY race_date, venue ORDER BY race_date, venue`).all<CalendarRow>();
  return rows.results.map((row) => ({ ...row, raceCount: Number(row.raceCount) }));
}

async function racesOnDate(db: D1Database, date: string): Promise<RaceIndexRow[]> {
  const rows = await db.prepare(`SELECT race_id AS raceId, race_date AS raceDate, venue, race_no AS raceNo, race_name AS raceName, start_time_jst AS startTimeJst, start_time_utc AS startTimeUtc, surface, distance_m AS distanceM, status FROM rt_races WHERE race_date=? ORDER BY venue, race_no`).bind(date).all<RaceIndexRow>();
  return rows.results.map((row) => ({ ...row, raceNo: Number(row.raceNo), distanceM: row.distanceM === null ? null : Number(row.distanceM) }));
}

function publicRaceState(row: RaceIndexRow, today: string, selected: boolean): { code: string; label: string; deadline: string | null } {
  if (selected) return { code: "buy", label: "買い目あり", deadline: null };
  if (row.raceDate < today || row.status === "finished") return { code: "skip", label: "見送り", deadline: null };
  let deadline = "発走15分前までに確定";
  const m = row.startTimeJst?.match(/^(\d{1,2}):(\d{2})$/);
  if (m) {
    const total = (Number(m[1]) * 60 + Number(m[2]) - 15 + 24 * 60) % (24 * 60);
    deadline = `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}までに確定`;
  }
  return { code: "pending", label: "判定中", deadline: `買い目対象になった場合は${deadline}` };
}

function homeScript(rows: CalendarRow[], today: string): string {
  const payload = JSON.stringify(rows).replace(/</g, "\\u003c");
  return `
const calendar=${payload};const today=${JSON.stringify(today)};
const byId=(id)=>document.getElementById(id);let selectedDate=(calendar.some(x=>x.raceDate===today)?today:(calendar.at(-1)?.raceDate||today));let selectedVenue="";
const uniq=(a)=>[...new Set(a)];
function button(text,active,onClick,extra){const b=document.createElement("button");b.className="chip"+(active?" active":"")+(extra?" "+extra:"");b.textContent=text;b.onclick=onClick;return b;}
function parts(date){return {y:date.slice(0,4),m:date.slice(5,7)};}
function renderHierarchy(){const p=parts(selectedDate);const years=uniq(calendar.map(x=>x.raceDate.slice(0,4)));const yr=byId("years");yr.replaceChildren();years.forEach(y=>yr.append(button(y+"年",y===p.y,()=>{const ds=calendar.filter(x=>x.raceDate.startsWith(y+"-")).map(x=>x.raceDate);selectedDate=ds.at(-1);selectedVenue="";renderHierarchy();})));
const months=uniq(calendar.filter(x=>x.raceDate.startsWith(p.y+"-")).map(x=>x.raceDate.slice(5,7)));const mo=byId("months");mo.replaceChildren();months.forEach(m=>mo.append(button(Number(m)+"月",m===p.m,()=>{const ds=calendar.filter(x=>x.raceDate.startsWith(p.y+"-"+m+"-")).map(x=>x.raceDate);selectedDate=ds.at(-1);selectedVenue="";renderHierarchy();})));
const dates=uniq(calendar.filter(x=>x.raceDate.startsWith(p.y+"-"+p.m+"-")).map(x=>x.raceDate));const da=byId("dates");da.replaceChildren();dates.forEach(d=>{const label=Number(d.slice(8))+"日"+(d===today?" 今日":"");da.append(button(label,d===selectedDate,()=>{selectedDate=d;selectedVenue="";renderHierarchy();},d===today?"today":""));});
const venues=calendar.filter(x=>x.raceDate===selectedDate).map(x=>x.venue);if(!venues.includes(selectedVenue))selectedVenue=venues[0]||"";const ve=byId("venues");ve.replaceChildren();venues.forEach(v=>ve.append(button(v,v===selectedVenue,()=>{selectedVenue=v;renderVenuesOnly();loadRaces();})));byId("selected-date").textContent=selectedDate===today?"今日のレース":selectedDate.replaceAll("-","/");loadRaces();}
function renderVenuesOnly(){const venues=calendar.filter(x=>x.raceDate===selectedDate).map(x=>x.venue);const ve=byId("venues");ve.replaceChildren();venues.forEach(v=>ve.append(button(v,v===selectedVenue,()=>{selectedVenue=v;renderVenuesOnly();loadRaces();})));}
async function loadRaces(){const rail=byId("races");rail.innerHTML='<div class="empty">レース情報を読み込み中…</div>';try{const res=await fetch("/api/public/day?date="+encodeURIComponent(selectedDate));const data=await res.json();const rows=data.races.filter(x=>x.venue===selectedVenue);rail.replaceChildren();if(!rows.length){rail.innerHTML='<div class="empty">この会場のレース情報はまだありません。</div>';return;}rows.forEach(r=>{const a=document.createElement("a");a.className="race-card"+(r.raceDate===today?" today":"");a.href="/races/"+encodeURIComponent(r.raceId);const meta=[r.surface,r.distanceM?String(r.distanceM)+"m":null].filter(Boolean).join("・");a.innerHTML='<div class="race-head"><span class="race-no">'+r.raceNo+'R</span><span class="race-time">'+(r.startTimeJst||"—")+'</span></div><div class="race-name"></div><div class="race-meta"></div><span class="status '+r.publicState.code+'">'+r.publicState.label+'</span>'+(r.publicState.deadline?'<div class="deadline">'+r.publicState.deadline+'</div>':'');a.querySelector(".race-name").textContent=r.raceName||r.raceNo+"R";a.querySelector(".race-meta").textContent=meta;rail.append(a);});}catch(e){rail.innerHTML='<div class="empty">レース情報を取得できませんでした。再読み込みしてください。</div>';}}
renderHierarchy();`;
}

async function home(env: Env, ctx: ExecutionContext): Promise<string> {
  const today = jstDateKey();
  await ensurePublicHistory(env.DB);
  const rows = await calendar(env.DB);
  ctx.waitUntil(runPublicDataSync(env, "manual"));
  const hasToday = rows.some((row) => row.raceDate === today);
  const intro = hasToday
    ? `<section class="hero today-hero"><span class="today-pill">TODAY</span><h1>今日のレース</h1><p>年 → 月 → 日付 → 会場 → レースの順に選ぶだけで、全レースを確認できます。買い目対象・見送り・判定中も同じ画面で分かります。</p></section>`
    : `<section class="hero"><h1>全レース</h1><p>年 → 月 → 日付 → 会場 → レースの順に選んで、これまでの全開催を確認できます。開催日のデータは自動取得されます。</p></section>`;
  const body = `${intro}<div class="section-title"><h2>累計回収率</h2><span class="muted">タップで月別表示</span></div>${metricCards(FROZEN_PUBLIC_METRICS, FROZEN_PUBLIC_MONTHLY)}<div class="section-title"><h2 id="selected-date">レースを選ぶ</h2><span class="muted">横にスワイプできます</span></div><section class="card navigator"><div class="nav-step"><p class="nav-label">1. 年</p><div class="rail" id="years"></div></div><div class="nav-step"><p class="nav-label">2. 月</p><div class="rail" id="months"></div></div><div class="nav-step"><p class="nav-label">3. 日付</p><div class="rail" id="dates"></div></div><div class="nav-step"><p class="nav-label">4. 会場</p><div class="rail" id="venues"></div></div><div class="nav-step"><p class="nav-label">5. レース</p><div class="race-rail" id="races"></div></div></section>`;
  return shell("レース一覧", body, homeScript(rows, today));
}

async function raceDetail(db: D1Database, raceId: string): Promise<string | null> {
  const race = await db.prepare(`SELECT race_id AS raceId, race_date AS raceDate, venue, race_no AS raceNo, race_name AS raceName, start_time_jst AS startTimeJst, start_time_utc AS startTimeUtc, surface, distance_m AS distanceM, conditions, direction, weather, track_condition AS trackCondition, status FROM rt_races WHERE race_id=? LIMIT 1`).bind(raceId).first<RaceDetailRow>();
  if (!race) return null;
  race.raceNo = Number(race.raceNo); race.distanceM = race.distanceM === null ? null : Number(race.distanceM);
  const runners = await db.prepare(`SELECT r.horse_no AS horseNo, r.frame_no AS frameNo, r.horse_name AS horseName, r.sex_age AS sexAge, r.horse_weight AS horseWeight, r.weight_change AS weightChange, r.jockey, r.assigned_weight AS assignedWeight, r.trainer, r.stable, r.win_odds AS winOdds, r.popularity, r.runner_status AS runnerStatus, x.finish_position AS finishPosition, x.result_status AS resultStatus FROM rt_runners r LEFT JOIN rt_results x ON x.race_id=r.race_id AND x.horse_no=r.horse_no WHERE r.race_id=? ORDER BY r.horse_no`).bind(raceId).all<RunnerRow>();
  const selected = isFrozenSelectedRace(race.raceDate, race.venue, race.raceNo);
  const publicBets = race.raceDate === "2026-08-08" ? await getPublicBets(db, raceId) : [];
  const today = jstDateKey();
  const state = publicRaceState(race, today, selected);
  const meta = [race.raceDate.replaceAll("-","/"), race.venue, `${race.raceNo}R`, race.startTimeJst ? `${race.startTimeJst}発走` : null, race.surface, race.distanceM ? `${race.distanceM}m` : null, race.trackCondition].filter(Boolean).join("　");
  let bets = "";
  if (publicBets.length > 0) {
    const courseBlocks = COURSE_NAMES.map((name, idx) => {
      const rows = publicBets.filter((bet) => bet.course === name);
      const tableRows = rows.map((t) => `<tr><td>${escapeHtml(t.betType)}</td><td>${escapeHtml(t.combination)}</td><td>${t.assumedOdds === null ? "—" : Number(t.assumedOdds).toFixed(1)+"倍"}</td><td>${formatYen(t.stakeYen)}</td><td class="${Number(t.returnYen ?? 0) > 0 ? "plus" : ""}">${t.settlementStatus === "settled" ? formatYen(Number(t.returnYen ?? 0)) : "—"}</td></tr>`).join("");
      return `<div class="course-view" data-course="${idx}" style="${idx===0?"":"display:none"}"><div class="bet-table"><table><thead><tr><th>券種</th><th>組合せ</th><th>オッズ</th><th>購入</th><th>払戻</th></tr></thead><tbody>${tableRows || `<tr><td colspan="5">このコースの買い目記録はありません。</td></tr>`}</tbody></table></div></div>`;
    }).join("");
    bets = `<div class="section-title"><h2>確定買い目</h2><span class="status buy">固定済み</span></div><div class="course-tabs">${COURSE_NAMES.map((name,idx)=>`<button class="course-tab ${idx===0?"active":""}" data-course-tab="${idx}">${name} ${formatYen(COURSE_BUDGETS[idx])}</button>`).join("")}</div>${courseBlocks}<section class="panel" style="margin-top:12px"><h3>買い目について</h3><ul><li>このページに保存された買い目と購入額は、結果が出たあとも変更しません。</li><li>購入対象の判定は、その時点で利用できる情報だけを使って行います。</li><li>新しいレース結果は将来の改善材料に加えますが、このレースの記録には反映しません。</li></ul></section>`;
  } else if (state.code === "buy") {
    bets = `<div class="section-title"><h2>確定買い目</h2><span class="status buy">買い目あり</span></div><div class="notice">このレースは固定購入対象です。累計・月別成績には正本の購入額と払戻を反映済みです。馬番ごとの組合せ明細は、正本データからの移行が完了したものから表示します。</div>`;
  } else if (state.code === "pending") {
    bets = `<div class="section-title"><h2>買い目</h2><span class="status pending">判定中</span></div><div class="notice">${escapeHtml(state.deadline ?? "発走15分前までに確定")}</div>`;
  } else {
    bets = `<div class="section-title"><h2>買い目</h2><span class="status ${state.code}">${state.label}</span></div><section class="panel"><p>このレースは購入対象に選ばれませんでした。</p></section>`;
  }
  const runnerTable = `<div class="section-title"><h2>出走馬</h2><span class="muted">${runners.results.length}頭</span></div><div class="runner-table"><table><thead><tr><th>馬番</th><th>馬名</th><th>性齢</th><th>騎手</th><th>調教師</th><th>馬体重</th><th>単勝</th><th>人気</th><th>結果</th></tr></thead><tbody>${runners.results.map((r)=>`<tr><td><span class="horse-no">${r.horseNo}</span></td><td><b>${escapeHtml(r.horseName)}</b></td><td>${escapeHtml(r.sexAge ?? "—")}</td><td>${escapeHtml(r.jockey ?? "—")}${r.assignedWeight !== null ? `<br><span class="muted">${r.assignedWeight}kg</span>`:""}</td><td>${escapeHtml(r.trainer ?? "—")}</td><td>${r.horseWeight === null ? "—" : `${r.horseWeight}kg${r.weightChange === null ? "" : ` (${r.weightChange>=0?"+":""}${r.weightChange})`}`}</td><td>${r.winOdds === null ? "—" : `${r.winOdds}倍`}</td><td>${r.popularity === null ? "—" : `${r.popularity}番人気`}</td><td>${r.finishPosition === null ? "—" : `${r.finishPosition}着`}</td></tr>`).join("")}</tbody></table></div>`;
  const body = `<a class="back" href="/">← レース一覧へ</a><section class="hero ${race.raceDate===today?"today-hero":""}"><div class="race-title"><span class="race-no">${race.raceNo}R</span><h1>${escapeHtml(race.raceName)}</h1><span class="status ${state.code}">${state.label}</span></div><p>${escapeHtml(meta)}</p>${race.conditions ? `<p>${escapeHtml(race.conditions)}</p>`:""}</section>${bets}${runnerTable}`;
  const script = `<script>document.querySelectorAll('[data-course-tab]').forEach(b=>b.addEventListener('click',()=>{const n=b.getAttribute('data-course-tab');document.querySelectorAll('[data-course-tab]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('[data-course]').forEach(x=>x.style.display=x.getAttribute('data-course')===n?'block':'none');}));</script>`;
  return shell(`${race.venue}${race.raceNo}R`, body).replace("</body></html>", `${script}</body></html>`);
}

async function dayApi(db: D1Database, date: string): Promise<unknown> {
  if (!/^20\d{2}-\d{2}-\d{2}$/.test(date)) return { ok: false, error: "INVALID_DATE" };
  const today = jstDateKey();
  const rows = await racesOnDate(db, date);
  return { ok: true, date, races: rows.map((row) => ({
    ...row,
    publicState: publicRaceState(row, today, isFrozenSelectedRace(row.raceDate, row.venue, row.raceNo))
  })) };
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url); const path = url.pathname;
    if (path === "/") return response(await home(env, ctx));
    if (path === "/conditions") return response(conditionsPage());
    if (path === "/guide") return response(guidePage());
    if (path === "/performance") return redirect("/");
    if (path === "/validation" || path.startsWith("/validation/")) return redirect("/conditions");
    if (path === "/api/public/calendar") return json({ ok: true, calendar: await calendar(env.DB) });
    if (path === "/api/public/day") return json(await dayApi(env.DB, url.searchParams.get("date") ?? ""));
    if (path.startsWith("/races/")) {
      const page = await raceDetail(env.DB, decodeURIComponent(path.slice("/races/".length)));
      return page ? response(page) : response(shell("レースが見つかりません", `<section class="panel"><h1>レースが見つかりません</h1><p><a class="back" href="/">レース一覧へ戻る</a></p></section>`), 404);
    }
    if (path.startsWith("/api/")) return json({ ok: false, error: "NOT_FOUND" }, 404);
    return response(shell("ページが見つかりません", `<section class="panel"><h1>ページが見つかりません</h1><p><a class="back" href="/">レース一覧へ戻る</a></p></section>`), 404);
  },
  async scheduled(_controller: ScheduledController, env: Env, _ctx: ExecutionContext): Promise<void> {
    await runPublicDataSync(env, "cron");
  }
} satisfies ExportedHandler<Env>;
