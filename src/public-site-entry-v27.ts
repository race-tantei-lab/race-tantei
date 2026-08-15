import publicSite from "./public-site-entry-v26.js";
import { loadWin5PublicState, WIN5_PAGE_URL, type Win5Profile, type Win5PublicState, type Win5RacePrediction } from "./v1/completed-win5.js";
import { shell } from "./v1/public-ui.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v27-win5-top-nav-20260816";

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] ?? ch));
}

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function fmtPct(value: number): string {
  return `${(Number(value) * 100).toFixed(value >= 0.1 ? 1 : 2)}%`;
}

function fmtYen(value: number): string {
  return `${Math.round(Number(value)).toLocaleString("ja-JP")}円`;
}

function fmtJst(value: string | null | undefined): string {
  if (!value) return "--:--";
  const parsed = Date.parse(value);
  if (Number.isFinite(parsed)) return new Date(parsed + 9 * 60 * 60 * 1000).toISOString().slice(11, 16);
  return /^\d{2}:\d{2}$/.test(value) ? value : "--:--";
}

function statusMeta(state: Win5PublicState): { label: string; detail: string; className: string } {
  if (state.status === "final") return { label: "確定", detail: "T-15で固定済み", className: "final" };
  if (state.status === "preview") return { label: "暫定", detail: "T-15まで更新", className: "preview" };
  if (state.status === "targets_only") return { label: "準備中", detail: "対象5R取得済み", className: "waiting" };
  return { label: "取得待ち", detail: "JRA公式を再確認中", className: "waiting" };
}

function orderedProfiles(state: Win5PublicState): Win5Profile[] {
  const order = new Map([["堅実", 0], ["標準", 1], ["一撃", 2]]);
  return [...(state.snapshot?.profiles ?? [])].sort((a, b) => (order.get(a.name) ?? 9) - (order.get(b.name) ?? 9));
}

function planDescription(profile: Win5Profile): string {
  if (profile.name === "堅実") return "広めに押さえて通過率を優先";
  if (profile.name === "一撃") return "点数を絞って高配当を狙う";
  return "点数と通過率のバランス型";
}

function targetList(state: Win5PublicState): string {
  if (!state.targets.length) return `<div class="win5-empty">JRA公式から対象5レースを取得しています。</div>`;
  const raceByLeg = new Map((state.snapshot?.races ?? []).map((race) => [race.leg, race]));
  return `<div class="win5-target-list">${state.targets.map((target) => {
    const race = raceByLeg.get(target.leg);
    const raceName = race?.raceName || target.raceName || "";
    return `<div class="win5-target-row">
      <span class="win5-leg">WIN${target.leg}</span>
      <div class="win5-target-main"><b>${esc(target.venue)} ${target.raceNo}R</b>${raceName ? `<span>${esc(raceName)}</span>` : ""}</div>
      <strong>${fmtJst(target.startTimeUtc)}</strong>
    </div>`;
  }).join("")}</div>`;
}

function profileSummary(profile: Win5Profile): string {
  const tone = profile.name === "堅実" ? "steady" : profile.name === "標準" ? "standard" : "shot";
  return `<article class="win5-plan-summary ${tone}">
    <div><span>${profile.name}</span><b>${profile.points}点</b><small>${planDescription(profile)}</small></div>
    <div class="win5-plan-money"><strong>${fmtYen(profile.purchaseYen)}</strong><span>5R通過 ${fmtPct(profile.estimatedFiveLegHitProbability)}</span></div>
  </article>`;
}

function selectedHorseChips(profile: Win5Profile): string {
  return profile.legs.map((leg) => {
    const chips = leg.selected.map((runner) => `<span class="win5-horse"><b>${runner.horseNo}</b><span>${esc(runner.horseName)}</span></span>`).join("");
    return `<div class="win5-ticket-row">
      <div class="win5-ticket-race"><span>WIN${leg.leg}</span><b>${esc(leg.venue)} ${leg.raceNo}R</b><small>${leg.selected.length}頭</small></div>
      <div class="win5-horses">${chips}</div>
    </div>`;
  }).join("");
}

function profileDetail(profile: Win5Profile, open: boolean): string {
  const tone = profile.name === "堅実" ? "steady" : profile.name === "標準" ? "standard" : "shot";
  return `<details class="win5-plan ${tone}" ${open ? "open" : ""}>
    <summary>
      <div><span class="win5-plan-name">${profile.name}</span><b>${profile.points}点・${fmtYen(profile.purchaseYen)}</b><small>${planDescription(profile)}</small></div>
      <div class="win5-plan-hit"><span>5R通過</span><strong>${fmtPct(profile.estimatedFiveLegHitProbability)}</strong></div>
    </summary>
    <div class="win5-plan-body">${selectedHorseChips(profile)}<p>上限 ${profile.maxPoints}点 / ${fmtYen(profile.maxBudgetYen)}。1組100円で自動構成。</p></div>
  </details>`;
}

function probabilityRace(race: Win5RacePrediction): string {
  const rows = race.runners.map((runner, index) => `<div class="win5-prob-row ${index < 3 ? "top" : ""}">
    <span>${index + 1}</span><b>${runner.horseNo}</b><em>${esc(runner.horseName)}</em><small>${runner.winOdds == null ? "—" : `${runner.winOdds.toFixed(1)}倍`}</small><strong>${fmtPct(runner.probability)}</strong>
  </div>`).join("");
  return `<details class="win5-race-detail">
    <summary><div><b>WIN${race.leg}　${esc(race.venue)} ${race.raceNo}R</b><span>${fmtJst(race.startTimeUtc)}　${esc(race.raceName)}</span></div><strong>1着確率</strong></summary>
    <div class="win5-learning">直近30日学習：当日 ${race.onlineLearning.sameDayFinishedRaces}R / 前日 ${race.onlineLearning.previousDayFinishedRaces}R / 7日内 ${race.onlineLearning.last7DaysFinishedRaces}R${race.bodyWeightApplied ? " / 馬体重反映済" : ""}</div>
    <div class="win5-prob-list">${rows}</div>
  </details>`;
}

function win5Styles(): string {
  return `<style>
    .nav a[aria-current="page"]{border-color:var(--green);background:var(--green2);color:#c7f8e5;font-weight:900}
    .win5-hero{padding:18px 20px}.win5-hero-top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.win5-eyebrow{font-size:11px;font-weight:900;letter-spacing:.08em;color:var(--green);margin-bottom:4px}.win5-hero h1{margin:0 0 5px;font-size:28px}.win5-hero p{margin:0;max-width:720px;font-size:12px}.win5-status{text-align:right;flex:0 0 auto}.win5-status b{display:inline-block;padding:6px 10px;border:1px solid var(--line);border-radius:999px;font-size:12px}.win5-status.final b{background:var(--green);color:#06100c;border-color:var(--green)}.win5-status.preview b{background:#17324b;color:#b9dcff;border-color:#315a7d}.win5-status span{display:block;margin-top:4px;font-size:10px;color:var(--muted)}
    .win5-quick{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:14px}.win5-quick>div{padding:9px 11px;border:1px solid var(--line);border-radius:12px;background:var(--panel2)}.win5-quick span{display:block;font-size:10px;color:var(--muted)}.win5-quick b{display:block;margin-top:2px;font-size:15px}
    .win5-section{margin-top:20px}.win5-section-title{display:flex;justify-content:space-between;align-items:end;gap:10px;margin-bottom:9px}.win5-section-title h2{margin:0;font-size:19px}.win5-section-title span{font-size:10px;color:var(--muted)}
    .win5-target-list{border:1px solid var(--line);border-radius:16px;overflow:hidden;background:var(--panel)}.win5-target-row{display:grid;grid-template-columns:58px minmax(0,1fr) 54px;gap:10px;align-items:center;padding:11px 13px;border-bottom:1px solid var(--line)}.win5-target-row:last-child{border-bottom:0}.win5-leg{display:inline-grid;place-items:center;min-height:29px;border-radius:9px;background:var(--green2);color:#c7f8e5;font-size:11px;font-weight:900}.win5-target-main{display:grid;gap:2px}.win5-target-main b{font-size:14px}.win5-target-main span{font-size:11px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.win5-target-row>strong{text-align:right;font-size:15px}.win5-source{margin:7px 2px 0;color:var(--muted);font-size:10px}.win5-source a{text-decoration:underline;color:var(--blue)}
    .win5-plan-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.win5-plan-summary{display:flex;justify-content:space-between;gap:8px;padding:13px;border:1px solid var(--line);border-radius:14px;background:var(--panel)}.win5-plan-summary>div:first-child{display:grid;gap:2px}.win5-plan-summary span{font-size:10px;color:var(--muted)}.win5-plan-summary b{font-size:18px}.win5-plan-summary small{font-size:9px;color:var(--muted);line-height:1.4}.win5-plan-summary.standard{border-top:3px solid var(--green)}.win5-plan-summary.steady{border-top:3px solid var(--blue)}.win5-plan-summary.shot{border-top:3px solid var(--warn)}.win5-plan-money{text-align:right}.win5-plan-money strong{display:block;font-size:14px}.win5-plan-money span{display:block;margin-top:5px;font-size:10px;color:var(--text)}
    .win5-plan-list{display:grid;gap:9px}.win5-plan{border:1px solid var(--line);border-radius:16px;background:var(--panel);overflow:hidden}.win5-plan.standard{border-left:3px solid var(--green)}.win5-plan.steady{border-left:3px solid var(--blue)}.win5-plan.shot{border-left:3px solid var(--warn)}.win5-plan summary{list-style:none;cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:12px;padding:13px 14px}.win5-plan summary::-webkit-details-marker{display:none}.win5-plan summary>div:first-child{display:grid;gap:2px}.win5-plan-name{font-size:10px;color:var(--muted);font-weight:900}.win5-plan summary b{font-size:16px}.win5-plan summary small{font-size:10px;color:var(--muted)}.win5-plan-hit{text-align:right}.win5-plan-hit span{display:block;font-size:9px;color:var(--muted)}.win5-plan-hit strong{font-size:16px;color:var(--green)}.win5-plan-body{padding:0 13px 13px;border-top:1px solid var(--line)}.win5-plan-body>p{margin:10px 1px 0;color:var(--muted);font-size:9px}.win5-ticket-row{display:grid;grid-template-columns:106px minmax(0,1fr);gap:10px;align-items:start;padding:10px 0;border-bottom:1px solid rgba(43,61,82,.65)}.win5-ticket-row:last-of-type{border-bottom:0}.win5-ticket-race{display:grid;gap:1px}.win5-ticket-race span{font-size:9px;color:var(--green);font-weight:900}.win5-ticket-race b{font-size:12px}.win5-ticket-race small{font-size:9px;color:var(--muted)}.win5-horses{display:flex;flex-wrap:wrap;gap:6px}.win5-horse{display:inline-flex;align-items:center;gap:5px;padding:5px 7px 5px 5px;border:1px solid var(--line);border-radius:999px;background:var(--panel2);min-width:0}.win5-horse b{display:grid;place-items:center;width:23px;height:23px;border-radius:50%;background:var(--text);color:var(--bg);font-size:12px}.win5-horse span{font-size:10px;max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .win5-tech{border:1px solid var(--line);border-radius:16px;background:var(--panel);overflow:hidden}.win5-tech>summary{list-style:none;cursor:pointer;padding:13px 14px;font-weight:800}.win5-tech>summary::-webkit-details-marker{display:none}.win5-tech-body{padding:0 12px 12px}.win5-race-detail{border-top:1px solid var(--line)}.win5-race-detail summary{list-style:none;cursor:pointer;display:flex;justify-content:space-between;gap:9px;align-items:center;padding:11px 2px}.win5-race-detail summary::-webkit-details-marker{display:none}.win5-race-detail summary div{display:grid;gap:2px}.win5-race-detail summary b{font-size:12px}.win5-race-detail summary span{font-size:9px;color:var(--muted)}.win5-race-detail summary>strong{font-size:9px;color:var(--blue)}.win5-learning{padding:8px 3px;color:var(--muted);font-size:9px;border-top:1px dashed var(--line)}.win5-prob-list{padding:0 3px 5px}.win5-prob-row{display:grid;grid-template-columns:20px 25px minmax(0,1fr) 48px 55px;gap:5px;align-items:center;padding:6px 0;border-bottom:1px solid rgba(43,61,82,.5);font-size:10px}.win5-prob-row:last-child{border-bottom:0}.win5-prob-row>span,.win5-prob-row>small{color:var(--muted)}.win5-prob-row>em{font-style:normal;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.win5-prob-row>small,.win5-prob-row>strong{text-align:right}.win5-prob-row.top>strong{color:var(--green)}
    .win5-note{margin-top:12px;padding:12px 14px;border:1px solid var(--line);border-radius:14px;background:var(--panel2);font-size:10px;line-height:1.7;color:var(--muted)}.win5-note b{color:var(--text)}.win5-empty{padding:20px;border:1px dashed var(--line);border-radius:14px;color:var(--muted);text-align:center;font-size:11px}
    @media(max-width:760px){.top{align-items:center}.nav{gap:5px}.nav a{padding:7px 9px;font-size:11px}.win5-hero{padding:15px}.win5-hero-top{display:block}.win5-hero h1{font-size:24px}.win5-status{text-align:left;margin-top:10px}.win5-quick{grid-template-columns:1fr 1fr}.win5-quick>div:last-child{grid-column:1/-1}.win5-plan-grid{grid-template-columns:1fr}.win5-plan-summary{padding:11px 12px}.win5-target-row{grid-template-columns:52px minmax(0,1fr) 48px;padding:10px}.win5-ticket-row{grid-template-columns:82px minmax(0,1fr);gap:8px}.win5-horse span{max-width:82px}.win5-section-title h2{font-size:17px}}
  </style>`;
}

function addTopWin5Tab(html: string, active = false): string {
  let out = html
    .replace(/<style>\.win5-global-link\{[\s\S]*?<\/style>/g, "")
    .replace(/<a class="win5-global-link" href="\/win5">WIN5<\/a>/g, "");
  if (!out.includes('class="nav-win5"') && out.includes('<nav class="nav"><a href="/">レース</a>')) {
    const tab = `<a class="nav-win5" href="/win5"${active ? ' aria-current="page"' : ""}>WIN5</a>`;
    out = out.replace('<nav class="nav"><a href="/">レース</a>', `<nav class="nav"><a href="/">レース</a>${tab}`);
  }
  return out;
}

function renderWin5Page(state: Win5PublicState): string {
  const meta = statusMeta(state);
  const profiles = orderedProfiles(state);
  const firstStart = state.targets.length ? Math.min(...state.targets.map((row) => Date.parse(row.startTimeUtc)).filter(Number.isFinite)) : NaN;
  const lockTime = state.snapshot?.lockDeadlineUtc ? fmtJst(state.snapshot.lockDeadlineUtc) : Number.isFinite(firstStart) ? fmtJst(new Date(firstStart - 15 * 60 * 1000).toISOString()) : "--:--";
  const updated = state.snapshot?.generatedAt ? fmtJst(state.snapshot.generatedAt) : state.targetFetchedAt ? fmtJst(state.targetFetchedAt) : "--:--";
  const body = `
    <section class="hero win5-hero">
      <div class="win5-hero-top"><div><div class="win5-eyebrow">WIN5 PREDICTION</div><h1>今日のWIN5予想</h1><p>${esc(state.date)}。まず買い目を見て、必要なときだけ確率や学習情報を開ける構成にしています。</p></div><div class="win5-status ${meta.className}"><b>${meta.label}</b><span>${meta.detail}</span></div></div>
      <div class="win5-quick"><div><span>最終確定</span><b>${lockTime} JST</b></div><div><span>最終更新</span><b>${updated} JST</b></div><div><span>ルール</span><b>5レースすべて1着</b></div></div>
    </section>

    <section class="win5-section"><div class="win5-section-title"><h2>対象5レース</h2><span>上から順にWIN1 → WIN5</span></div>${targetList(state)}<p class="win5-source">JRA公式から自動取得${state.targetFetchedAt ? `・${fmtJst(state.targetFetchedAt)}更新` : ""}　<a href="${esc(state.targetSourceUrl || WIN5_PAGE_URL)}" rel="noreferrer">対象レース確認</a></p></section>

    <section class="win5-section"><div class="win5-section-title"><h2>3パターン比較</h2><span>金額・点数・通過率だけ先に比較</span></div>${profiles.length ? `<div class="win5-plan-grid">${profiles.map(profileSummary).join("")}</div>` : `<div class="win5-empty">買い目を計算しています。対象レース取得後に自動表示します。</div>`}</section>

    <section class="win5-section"><div class="win5-section-title"><h2>買い目</h2><span>標準を最初に開いています</span></div>${profiles.length ? `<div class="win5-plan-list">${profiles.map((profile) => profileDetail(profile, profile.name === "標準")).join("")}</div>` : `<div class="win5-empty">予測準備中です。</div>`}</section>

    ${state.snapshot ? `<section class="win5-section"><details class="win5-tech"><summary>各レースの1着確率・学習情報を見る</summary><div class="win5-tech-body">${state.snapshot.races.map(probabilityRace).join("")}</div></details></section>` : ""}

    <div class="win5-note"><b>表示の考え方：</b>WIN5は5レースすべての1着馬を当てるため、通常予想とは別に5レース全体の通過確率を最大化して組み合わせます。確定後の買い目は変更しません。</div>`;

  let html = shell("WIN5予想", body);
  html = html.replace("</head>", `${win5Styles()}</head>`);
  html = addTopWin5Tab(html, true);
  return html;
}

async function enhanceGlobalNavigation(response: Response): Promise<Response> {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  const html = addTopWin5Tab(await response.text(), false);
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("x-race-ui-version", UI_VERSION);
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/win5") {
      const requested = url.searchParams.get("date");
      const date = requested && /^20\d{2}-\d{2}-\d{2}$/.test(requested) ? requested : jstDate();
      const state = await loadWin5PublicState(env.DB, date);
      return new Response(renderWin5Page(state), { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store, max-age=0", "x-race-ui-version": UI_VERSION } });
    }
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    return enhanceGlobalNavigation(await publicSite.fetch(request, env, ctx));
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
