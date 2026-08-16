import publicSite from "./public-site-entry-v29.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v30-clean-home-20260816";

type HomeRaceRow = {
  raceId: string;
  venue: string;
  raceNo: number;
  raceName: string | null;
  startTimeJst: string | null;
  startTimeUtc: string | null;
};

type HomeUx = {
  nextRace: null | {
    raceId: string;
    venue: string;
    raceNo: number;
    startTimeJst: string | null;
    deadlineJst: string | null;
    overdue: boolean;
  };
  recent30: null | { races: number; roiPct: number };
};

type RaceNavRow = { raceId: string; venue: string; raceNo: number; raceDate: string };

function replaceExact(html: string, from: string, to: string): string {
  return html.split(from).join(to);
}

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch] ?? ch));
}

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function jstClock(value: string | null | undefined): string | null {
  if (!value) return null;
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return /^\d{1,2}:\d{2}$/.test(value) ? value.padStart(5, "0") : null;
  return new Date(time + 9 * 60 * 60 * 1000).toISOString().slice(11, 16);
}

function deadlineClock(startTimeUtc: string | null): string | null {
  if (!startTimeUtc) return null;
  const time = Date.parse(startTimeUtc);
  if (!Number.isFinite(time)) return null;
  return new Date(time - 15 * 60 * 1000 + 9 * 60 * 60 * 1000).toISOString().slice(11, 16);
}

function removeTodayHomeHero(input: string): string {
  return input.replace(
    '<section class="hero today-hero"><span class="today-pill">TODAY</span><h1>今日のレース</h1><p>年 → 月 → 日付 → 会場 → レースの順に選ぶだけで、全レースを確認できます。買い目対象・見送り・判定中も同じ画面で分かります。</p></section>',
    "",
  );
}

function collapseHomeTiming(input: string): string {
  return input.replace(
    /<section class="home-publish-flow" aria-label="予想の公開タイミング">([\s\S]*?)<\/section>/,
    (_whole, inner: string) => {
      const steps = inner.replace(/\s*<div class="home-publish-head">[\s\S]*?<\/div>\s*/, "");
      return `<details class="home-publish-flow home-publish-details"><summary class="home-publish-summary"><b>予想の公開タイミング</b><span>日本時間</span></summary>${steps}</details>`;
    },
  );
}

function compactNavigation(input: string, path: string): string {
  const raceCurrent = path === "/" || path.startsWith("/races/") ? ' aria-current="page"' : "";
  const win5Current = path === "/win5" ? ' aria-current="page"' : "";
  const moreCurrent = path === "/conditions" || path === "/guide" ? " current" : "";
  const nav = `<nav class="nav compact-nav"><a href="/"${raceCurrent}>レース</a><a href="/win5"${win5Current}>WIN5</a><details class="nav-more${moreCurrent}"><summary>その他</summary><div class="nav-more-menu"><a href="/conditions">予想のしくみ</a><a href="/guide">使い方</a></div></details></nav>`;
  return input.replace(/<nav class="nav">[\s\S]*?<\/nav>/, nav);
}

async function loadHomeUx(db: D1Database, now = new Date()): Promise<HomeUx> {
  const date = jstDate(now);
  try {
    const [races, selection, locked, recent30] = await Promise.all([
      db.prepare(`
        SELECT race_id AS raceId,venue,race_no AS raceNo,race_name AS raceName,
               start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc
        FROM rt_races
        WHERE race_date=?
        ORDER BY start_time_utc,race_no,race_id
      `).bind(date).all<HomeRaceRow>(),
      db.prepare(`SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1`)
        .bind(`final_daily_selection:${date}`).first<{ value: string | null }>(),
      db.prepare(`
        SELECT DISTINCT b.race_id AS raceId
        FROM rt_public_bets b
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE r.race_date=? AND b.source_prediction_id=-2
      `).bind(date).all<{ raceId: string }>(),
      db.prepare(`
        SELECT COUNT(DISTINCT b.race_id) AS races,
               COALESCE(SUM(b.stake_yen),0) AS stakeYen,
               COALESCE(SUM(COALESCE(b.return_yen,0)),0) AS returnYen
        FROM rt_public_bets b
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE r.race_date>=date(?,'-29 days') AND r.race_date<=?
          AND b.source_prediction_id=-2
          AND b.settlement_status='settled'
      `).bind(date, date).first<{ races: number; stakeYen: number; returnYen: number }>(),
    ]);

    const lockedIds = new Set(locked.results.map((row) => String(row.raceId)));
    const selectedIds = new Set<string>();
    if (selection?.value) {
      try {
        const parsed = JSON.parse(selection.value) as { selected?: Array<{ raceId?: unknown }> };
        for (const row of parsed.selected ?? []) {
          const raceId = String(row?.raceId ?? "");
          if (raceId) selectedIds.add(raceId);
        }
      } catch { /* no frozen selection yet */ }
    }

    const nowMs = now.getTime();
    const next = races.results
      .filter((row) => selectedIds.has(String(row.raceId)) && !lockedIds.has(String(row.raceId)))
      .map((row) => ({ row, startMs: Date.parse(String(row.startTimeUtc ?? "")) }))
      .filter((item) => Number.isFinite(item.startMs) && item.startMs > nowMs)
      .sort((a, b) => a.startMs - b.startMs)[0];

    const nextRace = next ? {
      raceId: String(next.row.raceId),
      venue: String(next.row.venue),
      raceNo: Number(next.row.raceNo),
      startTimeJst: jstClock(next.row.startTimeUtc) ?? next.row.startTimeJst,
      deadlineJst: deadlineClock(next.row.startTimeUtc),
      overdue: nowMs >= next.startMs - 15 * 60 * 1000,
    } : null;

    const recentRaces = Number(recent30?.races ?? 0);
    const recentStake = Number(recent30?.stakeYen ?? 0);
    const recentReturn = Number(recent30?.returnYen ?? 0);

    return {
      nextRace,
      recent30: recentRaces > 0 && recentStake > 0 ? { races: recentRaces, roiPct: recentReturn / recentStake * 100 } : null,
    };
  } catch (error) {
    console.error("HOME_UX_LOAD_FAILED", error);
    return { nextRace: null, recent30: null };
  }
}

function homeTopTools(ux: HomeUx): string {
  if (!ux.nextRace) return "";
  return `<section class="home-next-release${ux.nextRace.overdue ? " overdue" : ""}">
    <span>${ux.nextRace.overdue ? "買い目確定待ち" : "次の買い目"}</span>
    <a href="/races/${encodeURIComponent(ux.nextRace.raceId)}"><b>${esc(ux.nextRace.venue)} ${ux.nextRace.raceNo}R</b><strong>${ux.nextRace.overdue ? "未確定" : `${esc(ux.nextRace.deadlineJst ?? "--:--")}までに公開`}</strong></a>
    <small>${esc(ux.nextRace.startTimeJst ?? "--:--")}発走</small>
  </section>`;
}

function recent30Html(ux: HomeUx): string {
  if (!ux.recent30) return "";
  return `<div class="recent-roi-strip"><span>直近30日</span><strong>${ux.recent30.roiPct.toFixed(1)}%</strong><small>${ux.recent30.races}R</small></div>`;
}

function homeUxStyles(): string {
  return `<style>
    .compact-nav{overflow:visible!important;align-items:center}.compact-nav>a[aria-current="page"]{border-color:var(--green);background:var(--green2);color:#c7f8e5;font-weight:900}
    .nav-more{position:relative;flex:0 0 auto}.nav-more>summary{list-style:none;cursor:pointer;white-space:nowrap;padding:8px 11px;border:1px solid var(--line);border-radius:999px;background:var(--panel);font-size:13px}.nav-more>summary::-webkit-details-marker{display:none}.nav-more.current>summary{border-color:var(--green);background:var(--green2);color:#c7f8e5;font-weight:900}.nav-more-menu{position:absolute;right:0;top:calc(100% + 6px);z-index:80;display:grid;min-width:145px;padding:6px;border:1px solid var(--line);border-radius:12px;background:var(--panel);box-shadow:0 12px 28px rgba(0,0,0,.35)}.nav-more-menu a{border:0!important;border-radius:8px!important;background:transparent!important;padding:9px 10px!important;font-size:12px!important}.nav-more-menu a:hover{background:var(--panel2)!important}
    .home-wrap>.top{background:rgba(7,17,27,.98)!important;border-bottom:1px solid rgba(43,61,82,.65);padding-bottom:12px!important;box-shadow:0 8px 14px rgba(7,17,27,.96)}
    .home-next-release{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:10px;align-items:center;margin:4px 0 10px;padding:11px 13px;border:1px solid var(--green);border-radius:14px;background:linear-gradient(135deg,#102b27,#101c29)}.home-next-release>span{font-size:10px;font-weight:900;color:var(--green)}.home-next-release>a{display:flex;align-items:baseline;justify-content:space-between;gap:9px;min-width:0}.home-next-release b{font-size:15px}.home-next-release strong{font-size:12px;color:#bdf5dc;white-space:nowrap}.home-next-release small{font-size:10px;color:var(--muted);white-space:nowrap}.home-next-release.overdue{border-color:#80652d;background:#2a2414}.home-next-release.overdue>span,.home-next-release.overdue strong{color:var(--warn)}
    .home-publish-details{margin-top:0!important}.home-publish-summary{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;cursor:pointer;list-style:none}.home-publish-summary::-webkit-details-marker{display:none}.home-publish-summary b{font-size:13px}.home-publish-summary span{font-size:10px;color:var(--muted)}.home-publish-summary:after{content:"＋";margin-left:auto;color:var(--muted);font-weight:900}.home-publish-details[open] .home-publish-summary:after{content:"−"}.home-publish-details>.home-publish-steps{border-top:1px solid var(--line)}
    .recent-roi-strip{display:flex;align-items:baseline;gap:9px;margin:7px 0 2px;padding:9px 11px;border:1px solid var(--line);border-radius:12px;background:var(--panel2)}.recent-roi-strip span{font-size:10px;color:var(--muted)}.recent-roi-strip strong{font-size:18px;color:var(--green)}.recent-roi-strip small{margin-left:auto;color:var(--muted);font-size:10px}
    .race-filter{display:flex;gap:5px;margin:3px 0 7px}.race-filter button{appearance:none;border:1px solid var(--line);border-radius:999px;background:var(--panel2);color:var(--muted);padding:6px 9px;font:inherit;font-size:10px;cursor:pointer}.race-filter button.active{border-color:var(--green);background:var(--green2);color:#c7f8e5;font-weight:800}.race-filter-empty{padding:18px 4px;color:var(--muted);font-size:11px}
    .race-card{border-left-width:4px!important}.race-card.state-buy,.race-card.state-hit{border-left-color:var(--green)!important}.race-card.state-target,.race-card.state-pending{border-left-color:var(--warn)!important}.race-card.state-skip{border-left-color:#526477!important}.race-card.state-miss,.race-card.state-overdue,.race-card.state-missing{border-left-color:var(--red)!important}.race-card.state-refund{border-left-color:var(--blue)!important}
    .race-sequence-nav{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin:0 0 10px}.race-sequence-nav a,.race-sequence-nav span{display:block;padding:8px 10px;border:1px solid var(--line);border-radius:10px;background:var(--panel2);font-size:11px}.race-sequence-nav a:last-child,.race-sequence-nav span:last-child{text-align:right}.race-sequence-nav span{color:var(--muted);opacity:.55}
    @media(max-width:760px){.top{overflow:visible}.home-next-release{grid-template-columns:auto 1fr}.home-next-release small{grid-column:2}.home-next-release>a{display:grid;gap:2px}.nav-more>summary{padding:7px 9px;font-size:12px}.nav-more-menu{right:0}.race-sequence-nav{margin-top:2px}}
  </style>`;
}

function homeUxScript(): string {
  return `<script>(()=>{
    const rail=document.getElementById('races');
    if(!rail)return;
    let activeFilter='all';
    const stateOf=(card)=>{
      const status=card.querySelector('.status');
      if(!status)return 'unknown';
      return ['buy','hit','miss','refund','target','pending','skip','overdue','missing'].find((name)=>status.classList.contains(name))||'unknown';
    };
    const apply=()=>{
      const cards=[...rail.querySelectorAll('.race-card')];
      let visible=0;
      cards.forEach((card)=>{
        [...card.classList].filter((name)=>name.startsWith('state-')).forEach((name)=>card.classList.remove(name));
        const state=stateOf(card);card.classList.add('state-'+state);
        const hasBet=['buy','hit','miss','refund'].includes(state);
        const show=activeFilter==='all'||(activeFilter==='buy'&&hasBet)||(activeFilter==='skip'&&state==='skip');
        card.style.display=show?'':'none';if(show)visible++;
      });
      const existingEmpty=rail.querySelector('.race-filter-empty');
      if(cards.length&&visible===0){
        if(!existingEmpty){const empty=document.createElement('div');empty.className='race-filter-empty';empty.textContent='この条件のレースはありません。';rail.append(empty);}
      }else{
        existingEmpty?.remove();
      }
    };
    const step=rail.closest('.nav-step');
    if(step&&!step.querySelector('.race-filter')){
      const filter=document.createElement('div');filter.className='race-filter';filter.innerHTML='<button type="button" class="active" data-race-filter="all">すべて</button><button type="button" data-race-filter="buy">買い目あり</button><button type="button" data-race-filter="skip">見送り</button>';
      step.insertBefore(filter,rail);
      filter.addEventListener('click',(event)=>{const button=event.target.closest('[data-race-filter]');if(!button)return;activeFilter=button.getAttribute('data-race-filter')||'all';filter.querySelectorAll('button').forEach((node)=>node.classList.toggle('active',node===button));apply();});
    }
    new MutationObserver(apply).observe(rail,{childList:true,subtree:true});apply();
  })();</script>`;
}

async function enhanceHome(response: Response, env: Env): Promise<Response> {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  try {
    const ux = await loadHomeUx(env.DB);
    let html = await response.text();
    html = html.replace('<main class="wrap">','<main class="wrap home-wrap">');
    html = removeTodayHomeHero(html);
    html = collapseHomeTiming(html);
    const tools = homeTopTools(ux);
    if (tools) {
      if (html.includes('<details class="home-publish-flow home-publish-details">')) html = html.replace('<details class="home-publish-flow home-publish-details">', `${tools}<details class="home-publish-flow home-publish-details">`);
      else html = html.replace(/(<div class="section-title"><h2>累計回収率<\/h2>)/, `${tools}$1`);
    }
    const recent = recent30Html(ux);
    if (recent) html = html.replace(/(<section class="metrics">[\s\S]*?<\/section>)/, `$1${recent}`);
    html = html.replace("</head>", `${homeUxStyles()}</head>`).replace("</body>", `${homeUxScript()}</body>`);
    const headers = new Headers(response.headers);headers.delete("content-length");
    return new Response(html,{status:response.status,statusText:response.statusText,headers});
  } catch (error) {
    console.error("HOME_UX_ENHANCE_FAILED", error);
    return response;
  }
}

async function enhanceRaceNavigation(response: Response, env: Env, path: string): Promise<Response> {
  if (!path.startsWith("/races/") || !response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  try {
    const raceId = decodeURIComponent(path.slice("/races/".length));
    const current = await env.DB.prepare(`SELECT race_id AS raceId,venue,race_no AS raceNo,race_date AS raceDate FROM rt_races WHERE race_id=? LIMIT 1`).bind(raceId).first<RaceNavRow>();
    if (!current) return response;
    const [previous, next] = await Promise.all([
      env.DB.prepare(`SELECT race_id AS raceId,venue,race_no AS raceNo,race_date AS raceDate FROM rt_races WHERE race_date=? AND venue=? AND race_no<? ORDER BY race_no DESC LIMIT 1`).bind(current.raceDate,current.venue,current.raceNo).first<RaceNavRow>(),
      env.DB.prepare(`SELECT race_id AS raceId,venue,race_no AS raceNo,race_date AS raceDate FROM rt_races WHERE race_date=? AND venue=? AND race_no>? ORDER BY race_no ASC LIMIT 1`).bind(current.raceDate,current.venue,current.raceNo).first<RaceNavRow>(),
    ]);
    const prevHtml = previous ? `<a href="/races/${encodeURIComponent(previous.raceId)}">← ${esc(previous.venue)} ${Number(previous.raceNo)}R</a>` : `<span>← 前のレースなし</span>`;
    const nextHtml = next ? `<a href="/races/${encodeURIComponent(next.raceId)}">${esc(next.venue)} ${Number(next.raceNo)}R →</a>` : `<span>次のレースなし →</span>`;
    const nav = `<nav class="race-sequence-nav" aria-label="前後のレース">${prevHtml}${nextHtml}</nav>`;
    let html = await response.text();
    if (!html.includes("race-sequence-nav")) {
      if (/<a class="back"[^>]*>[\s\S]*?<\/a>/.test(html)) html = html.replace(/(<a class="back"[^>]*>[\s\S]*?<\/a>)/, `$1${nav}`);
      else html = html.replace(/(<div class="race-title">)/, `${nav}$1`);
    }
    html = html.replace("</head>", `${homeUxStyles()}</head>`);
    const headers = new Headers(response.headers);headers.delete("content-length");
    return new Response(html,{status:response.status,statusText:response.statusText,headers});
  } catch (error) {
    console.error("RACE_SEQUENCE_NAV_FAILED", error);
    return response;
  }
}

function clarifyCommonLanguage(input: string): string {
  let html = input;

  const exact: Array<[string, string]> = [
    ["非常用T-15確定", "通常と異なる方法で買い目を確定"],
    ["JRA公式オッズ取得失敗のため、モデル確率優先のフォールバックで買い目を固定しました。成績集計には通常どおり含めます。", "JRA公式オッズを取得できなかったため、発走15分前の時点で利用できた予測データを使って買い目を確定しました。この買い目も通常どおり成績に集計します。"],
    ["取得失敗・確率優先", "取得できませんでした"],
    ["非常用選定", "買い目の決め方"],
    ["モデル確率優先", "予測した当たりやすさを優先"],
    ["JRA公式オッズの取得に失敗したため、買い目未生成を防ぐ非常用経路で確定しました。利用可能なモデル確率と直近学習を優先して2券種を選定しています。オッズは捏造せず表示しません。", "JRA公式オッズを取得できなかったため、発走15分前の時点で利用できた予測データから2種類の買い目を選びました。取得できていないオッズは表示していません。"],
    ["組合せ予測確率", "この組合せが当たる推定確率"],
    ["確率 × オッズ", "推定確率 × 公式オッズ"],
    ["最終スコア", "買い目の評価点"],
    ["各券種で「予測確率 × JRA公式オッズ」上位5候補 → 最終スコアで券種代表 → 異なる2券種から最終2点、の順で絞っています。", "まず各券種で「推定確率 × JRA公式オッズ」が高い5候補に絞り、評価点で各券種から1つを選びます。その後、異なる券種から最終的に2点を採用します。"],
    ["この券種の全組合せの中で「予測確率 × 公式オッズ」の上位5候補に残り、その5候補を最終スコアで比べて券種代表になりました。6券種の代表から異なる2券種を選ぶ最終選考でも残ったため、この買い目を採用しています。", "この券種の全組合せから「推定確率 × JRA公式オッズ」が高い5候補に絞り、その中で評価点が最も高かったため採用候補になりました。最後に6券種の候補を比較し、異なる2券種の中で評価が高かったため、この買い目を採用しています。"],
    [">根拠<", ">買い目の理由<"],
    [">馬一覧<", ">出走馬<"],
    ["直近30日学習：", "最近30日間のレース結果を反映："],
    ["直近30日学習", "最近30日間のレース結果を反映"],
    ["直近学習", "最近のレース結果の反映"],
    ["学習情報", "最近の結果の反映状況"],
    ["モデル1着確率", "1着になる推定確率"],
    ["1着確率を見る", "1着になる推定確率を見る"],
    ["1着確率", "1着になる推定確率"],
    ["馬体重反映済", "最新の馬体重を反映済み"],
    ["7日内", "過去7日"],
    ["対象5R取得済み", "対象5レースを取得済み"],
    ["JRA対象5レースは取得済み", "JRA公式サイトから対象5レースを取得済み"],
    ["JRA公式を再確認中", "JRA公式サイトから対象レースを確認しています"],
    ["JRA公式ページを再取得します", "JRA公式サイトから対象レースを確認しています"],
    ["5R通過確率", "5レースすべて的中する推定確率"],
    ["5R通過", "5レースすべて的中（推定）"],
    ["広めに押さえて通過率を優先", "選ぶ馬を広めにして、5レースすべて当たる可能性を優先"],
    ["点数と通過率のバランス型", "購入点数と、5レースすべて当たる可能性のバランス型"],
    ["カバー ", "選んだ馬が1着になる合計確率 "],
    ["条件一致スコア", "買い目の評価点"],
    ["市場との乖離", "人気・オッズと予測の差"],
    ["市場評価順位", "オッズから見た人気順位"],
    ["直近好走回数", "最近の好走回数"],
  ];

  for (const [from, to] of exact) html = replaceExact(html, from, to);

  html = html
    .replace(/T[-–](\d+)/g, (_match, minutes) => `発走${minutes}分前`)
    .replace(/(\d{2}:\d{2}) JST/g, "$1（日本時間）")
    .replace(/>予想ロジック</g, ">予想のしくみ<")
    .replace(/>条件詳細</g, ">予想のしくみ<")
    .replace(/>見方</g, ">使い方<");

  return html;
}

function clarifyWin5Language(input: string): string {
  let html = input;
  const exact: Array<[string, string]> = [
    ["T-15で固定済み", "最初の対象レースの発走15分前に確定済み"],
    ["T-15まで更新", "最初の対象レースの発走15分前まで更新"],
    ["最終確定", "買い目の確定時刻"],
    ["最終更新", "予想の更新時刻"],
    ["予測更新", "予想の更新時刻"],
    ["上から順にWIN1 → WIN5", "上から順に1レース目 → 5レース目"],
    ["更新時刻・1着確率・直近学習の詳細", "予想の更新時刻・各馬が1着になる推定確率・最近のレース結果の反映状況"],
    ["各レースの1着確率・学習情報", "各レースの1着予想と、最近の結果の反映状況"],
    ["10年モデル＋直近・当日学習で5レースの1着確率を算出し、予算内で通過確率が最大になる組み合わせを自動構成。", "過去10年のデータに加えて、最近と当日のレース結果も反映して各馬が1着になる可能性を予測し、予算内で5レースすべてが当たる可能性が高くなる組み合わせを選びます。"],
    ["まず買い目を見て、必要なときだけ確率や学習情報を開ける構成にしています。", "最初に買い目を表示します。詳しい1着予想や、最近のレース結果の反映状況は「その他」で確認できます。"],
  ];
  for (const [from, to] of exact) html = replaceExact(html, from, to);

  if (html.includes("WIN5 PREDICTION")) {
    html = replaceExact(html, "WIN5 PREDICTION", "WIN5予想");
    html = html.replace("</body>", "<!-- WIN5 PREDICTION --></body>");
  }
  return html;
}

async function clarifyHtmlResponse(response: Response, path: string): Promise<Response> {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  let html = await response.text();
  if (path === "/win5") html = clarifyWin5Language(html);
  html = clarifyCommonLanguage(html);
  html = compactNavigation(html, path);
  if (path !== "/" && !path.startsWith("/races/")) html = html.replace("</head>", `${homeUxStyles()}</head>`);
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("x-race-ui-version", UI_VERSION);
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const path = new URL(request.url).pathname;
    let response = await publicSite.fetch(request, env, ctx);
    response = await clarifyHtmlResponse(response, path);
    if (path === "/") response = await enhanceHome(response, env);
    else if (path.startsWith("/races/")) response = await enhanceRaceNavigation(response, env, path);
    return response;
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
