import publicSite from "./public-site-entry-v25.js";
import { loadWin5PublicState, runCompletedWin5Scheduled, WIN5_PAGE_URL, type Win5PublicState, type Win5Profile } from "./v1/completed-win5.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v26-win5-20260816";

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] ?? ch));
}

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function fmtPct(value: number): string { return `${(value * 100).toFixed(value >= 0.1 ? 1 : 2)}%`; }
function fmtYen(value: number): string { return `${Math.round(value).toLocaleString("ja-JP")}円`; }
function fmtJst(value: string): string {
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return "--:--";
  return new Date(time + 9 * 60 * 60 * 1000).toISOString().slice(11, 16);
}
function validDate(value: string | null): string | null { return value && /^20\d{2}-\d{2}-\d{2}$/.test(value) ? value : null; }

function statusMeta(state: Win5PublicState): { label: string; detail: string; className: string } {
  if (state.status === "final") return { label: "T-15 確定", detail: "この買い目は固定済みです", className: "final" };
  if (state.status === "preview") return { label: "暫定予測", detail: "直近結果を反映しながら更新中", className: "preview" };
  if (state.status === "targets_only") return { label: "予測準備中", detail: "JRA対象5レースは取得済み", className: "waiting" };
  return { label: "対象レース取得待ち", detail: "JRA公式ページを再取得します", className: "waiting" };
}

function profileCard(profile: Win5Profile): string {
  const tone = profile.name === "堅実" ? "steady" : profile.name === "標準" ? "standard" : "shot";
  const legs = profile.legs.map((leg) => {
    const horses = leg.selected.map((runner) => `<span class="horse-chip"><b>${runner.horseNo}</b><span>${esc(runner.horseName)}</span><em>${fmtPct(runner.probability)}</em></span>`).join("");
    return `<div class="profile-leg">
      <div class="profile-leg-head"><b>WIN${leg.leg}　${esc(leg.venue)}${leg.raceNo}R</b><span>${leg.selected.length}頭 / カバー ${fmtPct(leg.coverageProbability)}</span></div>
      <div class="horse-chips">${horses}</div>
    </div>`;
  }).join("");
  return `<article class="profile ${tone}">
    <div class="profile-head"><div><span class="profile-tag">${profile.name}</span><h2>${profile.points}点・${fmtYen(profile.purchaseYen)}</h2></div><div class="hit"><span>5R通過確率</span><b>${fmtPct(profile.estimatedFiveLegHitProbability)}</b></div></div>
    <div class="profile-sub">上限 ${profile.maxPoints}点 / ${fmtYen(profile.maxBudgetYen)}　・　100円/組</div>
    <div class="profile-legs">${legs}</div>
  </article>`;
}

function raceProbabilityCards(state: Win5PublicState): string {
  if (!state.snapshot) return "";
  return state.snapshot.races.map((race) => {
    const rows = race.runners.map((runner, index) => `<div class="prob-row ${index < 3 ? "top" : ""}"><span class="rank">${index + 1}</span><b class="no">${runner.horseNo}</b><span class="name">${esc(runner.horseName)}</span><span class="odds">${runner.winOdds == null ? "" : `${runner.winOdds.toFixed(1)}倍`}</span><strong>${fmtPct(runner.probability)}</strong></div>`).join("");
    const audit = race.onlineLearning;
    return `<details class="race-prob" ${race.leg === 1 ? "open" : ""}>
      <summary><div><b>WIN${race.leg}　${esc(race.venue)}${race.raceNo}R</b><span>${fmtJst(race.startTimeUtc)}発走　${esc(race.raceName)}</span></div><em>1着確率を見る</em></summary>
      <div class="learning-strip"><span>直近30日学習</span><b>当日 ${audit.sameDayFinishedRaces}R</b><b>前日 ${audit.previousDayFinishedRaces}R</b><b>7日内 ${audit.last7DaysFinishedRaces}R</b>${race.bodyWeightApplied ? `<b>馬体重反映済</b>` : ""}</div>
      <div class="prob-list">${rows}</div>
    </details>`;
  }).join("");
}

function targetCards(state: Win5PublicState): string {
  if (!state.targets.length) return `<div class="empty">JRA公式のWIN5対象レースを取得しています。</div>`;
  return `<div class="target-grid">${state.targets.map((target) => `<div class="target"><span>WIN${target.leg}</span><b>${esc(target.venue)} ${target.raceNo}R</b><em>${fmtJst(target.startTimeUtc)}</em></div>`).join("")}</div>`;
}

function renderWin5Page(state: Win5PublicState): string {
  const meta = statusMeta(state);
  const snapshot = state.snapshot;
  const lockTime = snapshot ? fmtJst(snapshot.lockDeadlineUtc) : state.targets.length ? fmtJst(new Date(Math.min(...state.targets.map((row) => Date.parse(row.startTimeUtc))) - 15 * 60 * 1000).toISOString()) : "--:--";
  const generated = snapshot ? fmtJst(snapshot.generatedAt) : "--:--";
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>WIN5予想 | レース探偵</title>
  <style>
    :root{--bg:#0a0c10;--panel:#11151b;--panel2:#171c24;--line:#282f3a;--text:#f5f7fa;--muted:#9aa5b4;--accent:#d5ff3f;--blue:#8cc8ff;--orange:#ffb46a}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Yu Gothic",sans-serif}.wrap{width:min(920px,100%);margin:auto;padding:18px 14px 80px}a{color:inherit}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px}.brand{display:flex;align-items:baseline;gap:9px;text-decoration:none;font-weight:900}.brand b{font-size:18px}.brand span{font-size:11px;color:var(--muted)}.back{font-size:12px;color:var(--muted);text-decoration:none;border:1px solid var(--line);padding:8px 10px;border-radius:10px}.hero{padding:18px;border:1px solid var(--line);border-radius:20px;background:linear-gradient(145deg,#151a21,#0f1318)}.hero-line{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.eyebrow{font-size:11px;color:var(--accent);font-weight:900;letter-spacing:.08em}.hero h1{font-size:30px;line-height:1.05;margin:5px 0 7px}.hero p{margin:0;color:var(--muted);font-size:12px;line-height:1.7}.status{flex:0 0 auto;text-align:right}.status b{display:inline-block;padding:7px 9px;border-radius:999px;font-size:11px;border:1px solid var(--line)}.status.final b{background:var(--accent);color:#0a0c10;border-color:var(--accent)}.status.preview b{background:#172234;color:var(--blue);border-color:#29486a}.status span{display:block;font-size:9px;color:var(--muted);margin-top:5px}.hero-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:15px}.metric{padding:10px;border:1px solid var(--line);border-radius:12px;background:#0d1116}.metric span{display:block;font-size:9px;color:var(--muted)}.metric b{display:block;font-size:14px;margin-top:3px}.section{margin-top:22px}.section-head{display:flex;justify-content:space-between;align-items:end;gap:8px;margin-bottom:9px}.section-head h2{margin:0;font-size:17px}.section-head span,.source{font-size:10px;color:var(--muted)}.source a{text-decoration:underline}.target-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}.target{padding:10px 8px;border:1px solid var(--line);border-radius:12px;background:var(--panel);display:grid;gap:2px}.target span{font-size:9px;color:var(--muted)}.target b{font-size:12px}.target em{font-style:normal;font-weight:900;font-size:14px}.profiles{display:grid;gap:12px}.profile{padding:15px;border:1px solid var(--line);border-radius:18px;background:var(--panel)}.profile.steady{border-top:3px solid var(--blue)}.profile.standard{border-top:3px solid var(--accent)}.profile.shot{border-top:3px solid var(--orange)}.profile-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.profile-tag{font-size:10px;font-weight:900;color:var(--muted)}.profile h2{font-size:21px;margin:2px 0 0}.hit{text-align:right}.hit span{display:block;font-size:9px;color:var(--muted)}.hit b{font-size:18px}.profile-sub{font-size:9px;color:var(--muted);margin:6px 0 12px}.profile-legs{display:grid;gap:8px}.profile-leg{padding:10px;border:1px solid var(--line);border-radius:12px;background:var(--panel2)}.profile-leg-head{display:flex;justify-content:space-between;gap:8px}.profile-leg-head b{font-size:11px}.profile-leg-head span{font-size:9px;color:var(--muted)}.horse-chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}.horse-chip{display:inline-flex;align-items:center;gap:5px;border:1px solid #343d49;border-radius:999px;padding:5px 7px;font-size:10px;background:#10151b}.horse-chip b{display:grid;place-items:center;width:18px;height:18px;border-radius:50%;background:#f5f7fa;color:#080a0d;font-size:10px}.horse-chip em{font-style:normal;color:var(--muted);font-size:9px}.race-prob{border:1px solid var(--line);border-radius:14px;background:var(--panel);margin-bottom:8px;overflow:hidden}.race-prob summary{list-style:none;cursor:pointer;padding:12px 13px;display:flex;justify-content:space-between;gap:8px;align-items:center}.race-prob summary::-webkit-details-marker{display:none}.race-prob summary div{display:grid;gap:2px}.race-prob summary b{font-size:12px}.race-prob summary span{font-size:9px;color:var(--muted)}.race-prob summary em{font-size:9px;color:var(--muted);font-style:normal}.learning-strip{display:flex;flex-wrap:wrap;gap:5px;padding:8px 12px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);font-size:9px;color:var(--muted)}.learning-strip b{color:var(--text)}.prob-list{padding:5px 12px 10px}.prob-row{display:grid;grid-template-columns:22px 26px minmax(0,1fr) 48px 58px;align-items:center;gap:4px;padding:7px 0;border-bottom:1px solid #20262e;font-size:10px}.prob-row:last-child{border-bottom:0}.prob-row .rank{color:var(--muted)}.prob-row .no{font-size:12px}.prob-row .name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.prob-row .odds{color:var(--muted);text-align:right}.prob-row strong{text-align:right;font-size:11px}.prob-row.top strong{color:var(--accent)}.empty{padding:22px;text-align:center;border:1px dashed var(--line);border-radius:14px;color:var(--muted);font-size:11px}.note{padding:13px;border:1px solid var(--line);border-radius:14px;color:var(--muted);font-size:10px;line-height:1.7}.note b{color:var(--text)}
    @media(max-width:650px){.wrap{padding:14px 10px 70px}.hero{padding:14px}.hero h1{font-size:25px}.hero-line{display:block}.status{text-align:left;margin-top:11px}.target-grid{grid-template-columns:repeat(5,minmax(58px,1fr));overflow-x:auto}.target{min-width:58px;padding:9px 6px}.target b{font-size:10px}.target em{font-size:12px}.profile{padding:12px}.profile-leg-head{display:grid;gap:2px}.hero-metrics{gap:5px}.metric{padding:8px 7px}.metric b{font-size:12px}.horse-chip span{max-width:88px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
  </style></head><body><main class="wrap">
    <header class="top"><a class="brand" href="/"><b>レース探偵</b><span>WIN5</span></a><a class="back" href="/">通常予想へ</a></header>
    <section class="hero"><div class="hero-line"><div><div class="eyebrow">WIN5 PREDICTION</div><h1>${esc(state.date)} WIN5</h1><p>10年モデル＋直近・当日学習で5レースの1着確率を算出し、予算内で通過確率が最大になる組み合わせを自動構成。</p></div><div class="status ${meta.className}"><b>${meta.label}</b><span>${meta.detail}</span></div></div>
      <div class="hero-metrics"><div class="metric"><span>最終確定</span><b>${lockTime} JST</b></div><div class="metric"><span>予測更新</span><b>${generated} JST</b></div><div class="metric"><span>方式</span><b>5レース1着</b></div></div>
    </section>
    <section class="section"><div class="section-head"><h2>対象5レース</h2><span>JRA公式から自動取得</span></div>${targetCards(state)}<p class="source">取得元: <a href="${esc(state.targetSourceUrl || WIN5_PAGE_URL)}" rel="noreferrer">JRA WIN5対象レース</a>${state.targetFetchedAt ? `　取得 ${fmtJst(state.targetFetchedAt)} JST` : ""}</p></section>
    <section class="section"><div class="section-head"><h2>買い目</h2><span>堅実 / 標準 / 一撃</span></div>${snapshot ? `<div class="profiles">${snapshot.profiles.map(profileCard).join("")}</div>` : `<div class="empty">出馬表と学習データが揃い次第、自動で3パターンを生成します。</div>`}</section>
    ${snapshot ? `<section class="section"><div class="section-head"><h2>5レース 1着確率</h2><span>各レースをタップで展開</span></div>${raceProbabilityCards(state)}</section>` : ""}
    <section class="section note"><b>表示の考え方：</b>各レースの上位馬を何頭残すかを全組み合わせで探索し、点数上限内で5レースすべてを通過するモデル確率が最大になる構成を採用しています。WIN5は事前に組合せごとの確定オッズがないため、架空の期待値は表示しません。5R通過確率は各レースを独立としたモデル上の近似値です。</section>
  </main></body></html>`;
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store, max-age=0", "x-race-ui-version": UI_VERSION } });
}

function addWin5Link(response: Response): Promise<Response> | Response {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  return response.text().then((html) => {
    if (html.includes('href="/win5"')) return new Response(html, response);
    const inject = `<style>.win5-global-link{position:fixed;right:12px;bottom:14px;z-index:90;padding:9px 12px;border-radius:999px;background:#d5ff3f;color:#090b0e!important;text-decoration:none!important;font:900 11px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;box-shadow:0 5px 22px #0008}</style><a class="win5-global-link" href="/win5">WIN5</a>`;
    const out = html.includes("</body>") ? html.replace("</body>", `${inject}</body>`) : `${html}${inject}`;
    const headers = new Headers(response.headers); headers.delete("content-length"); headers.set("x-race-ui-version", UI_VERSION);
    return new Response(out, { status: response.status, statusText: response.statusText, headers });
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/win5") {
      const date = validDate(url.searchParams.get("date")) ?? jstDate();
      return jsonResponse(await loadWin5PublicState(env.DB, date));
    }
    if (url.pathname === "/win5" || url.pathname === "/win5/") {
      const date = validDate(url.searchParams.get("date")) ?? jstDate();
      const state = await loadWin5PublicState(env.DB, date);
      return new Response(renderWin5Page(state), { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store, max-age=0", "x-race-ui-version": UI_VERSION } });
    }
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    return addWin5Link(await publicSite.fetch(request, env, ctx));
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
    try {
      await runCompletedWin5Scheduled(env, new Date(controller.scheduledTime || Date.now()));
    } catch (error) {
      console.error("WIN5_SCHEDULED_FAILED", error);
    }
  },
} satisfies ExportedHandler<Env>;
