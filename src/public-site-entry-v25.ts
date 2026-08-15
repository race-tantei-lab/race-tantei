import publicSite from "./public-site-entry-v21.js";
import { loadFixedTicketEvidence, type FixedTicketEvidence } from "./v1/completed-fixed-ticket-explanation.js";
import type { Env } from "./v1/types.js";

const CUTOFF = "2026-08-09";
const UI_VERSION = "ten-year-completed-public-v25-race-detail-tabs-20260815";

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] ?? ch));
}

function pct(value: number): string {
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function num(value: number, digits = 4): string {
  return Number(value).toFixed(digits);
}

function ticketReasonHtml(ticket: FixedTicketEvidence): string {
  const names = ticket.horses.map((horseNo, index) => `${horseNo}番 ${ticket.horseNames[index] || ""}`.trim()).join(" / ");
  return `<article class="ticket-reason-card" data-ticket-reason="${esc(ticket.betType)}:${esc(ticket.combination)}">
    <div class="ticket-reason-head"><div><strong>${esc(ticket.betType)} ${esc(ticket.combination)}</strong><span>${esc(names)}</span></div></div>
    <div class="ticket-reason-metrics">
      <div><span>組合せ予測確率</span><b>${pct(ticket.predictedProbability)}</b></div>
      <div><span>JRA公式オッズ</span><b>${ticket.officialOdds.toFixed(1)}倍</b></div>
      <div><span>確率 × オッズ</span><b>${num(ticket.valueProduct)}</b></div>
      <div><span>最終スコア</span><b>${num(ticket.score, 6)}</b></div>
    </div>
    <p><b>選ばれた理由：</b>この券種の全組合せの中で「予測確率 × 公式オッズ」の上位5候補に残り、その5候補を最終スコアで比べて券種代表になりました。6券種の代表から異なる2券種を選ぶ最終選考でも残ったため、この買い目を採用しています。</p>
  </article>`;
}

function reasonSection(tickets: FixedTicketEvidence[]): string {
  return `<section id="race-panel-reason" class="card ticket-reasons" data-race-panel="reason">
    <div class="section-title ticket-reasons-title"><h2>根拠</h2><span>この2点が選ばれた理由</span></div>
    <p class="ticket-reason-rule">各券種で「予測確率 × JRA公式オッズ」上位5候補 → 最終スコアで券種代表 → 異なる2券種から最終2点、の順で絞っています。</p>
    <div class="ticket-reason-list">${tickets.map(ticketReasonHtml).join("")}</div>
  </section>`;
}

function stripOldPredictionReasons(html: string): string {
  return html
    .replace(/<section class="prediction-reasons(?: [^"]*)?"[^>]*>[\s\S]*?<\/section>/g, "")
    .replace(/<section class="[^\"]*live-prediction-reasons[^\"]*"[^>]*>[\s\S]*?<\/section>/g, "");
}

function injectReasonBeforeRunners(html: string, block: string): string {
  const anchors = [
    `<div class="section-title"><h2>出走馬`,
    `<section class="card"><h2>出走馬`,
    `<section class="runner-table`,
    `</main>`,
  ];
  for (const anchor of anchors) {
    if (html.includes(anchor)) return html.replace(anchor, `${block}${anchor}`);
  }
  return `${html}${block}`;
}

function addTabsUi(html: string): string {
  const css = `<style>
    .race-detail-tabs{position:sticky;top:8px;z-index:30;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;margin:12px 0;padding:5px;border:1px solid var(--line);border-radius:14px;background:color-mix(in srgb,var(--panel) 94%,transparent);backdrop-filter:blur(12px)}
    .race-detail-tab{appearance:none;border:0;border-radius:10px;padding:10px 6px;background:transparent;color:var(--muted);font:inherit;font-size:12px;font-weight:800;cursor:pointer;white-space:nowrap}
    .race-detail-tab[aria-selected="true"]{background:var(--text);color:var(--bg)}
    .ticket-reasons{margin:12px 0 18px}.ticket-reasons-title{margin-bottom:8px}.ticket-reasons-title>span{font-size:10px;color:var(--muted)}
    .ticket-reason-rule{margin:0 0 9px;color:var(--muted);font-size:10px;line-height:1.6}.ticket-reason-list{display:grid;gap:8px}
    .ticket-reason-card{padding:12px;border:1px solid var(--line);border-radius:12px;background:var(--panel2)}
    .ticket-reason-head>div{display:grid;gap:2px}.ticket-reason-head strong{font-size:14px}.ticket-reason-head span{font-size:10px;color:var(--muted)}
    .ticket-reason-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin-top:9px}.ticket-reason-metrics>div{display:grid;gap:2px;padding:8px;border:1px solid var(--line);border-radius:9px;background:var(--panel)}.ticket-reason-metrics span{font-size:9px;color:var(--muted)}.ticket-reason-metrics b{font-size:12px}
    .ticket-reason-card p{margin:9px 0 0;font-size:10px;line-height:1.65;color:var(--muted)}.ticket-reason-card p b{color:var(--text)}
    [data-race-panel][hidden]{display:none!important}
    @media(max-width:760px){.race-detail-tabs{top:6px;margin:10px 0}.race-detail-tab{padding:9px 3px;font-size:11px}.ticket-reason-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.ticket-reason-card{padding:10px}}
  </style>`;
  const nav = `<nav class="race-detail-tabs" data-race-tabs aria-label="レース詳細表示"><button type="button" class="race-detail-tab" data-race-tab="bets" aria-selected="true">予想買い目</button><button type="button" class="race-detail-tab" data-race-tab="reason" aria-selected="false">根拠</button><button type="button" class="race-detail-tab" data-race-tab="horses" aria-selected="false">馬一覧</button></nav>`;
  const script = `<script>(function(){
    function text(el){return (el&&el.textContent||'').trim();}
    function panelForHeading(h){
      if(!h)return null;
      if(h.parentElement&&h.parentElement.classList.contains('section-title')&&h.parentElement.parentElement)return h.parentElement.parentElement;
      return h.closest('.card')||h.closest('section')||h.parentElement;
    }
    function init(){
      var reason=document.getElementById('race-panel-reason');
      var nav=document.querySelector('[data-race-tabs]');
      if(!reason||!nav)return;
      var headings=Array.from(document.querySelectorAll('h2'));
      var betHeading=headings.find(function(h){var t=text(h);return !h.closest('#race-panel-reason')&&(t==='確定買い目'||t==='買い目'||t==='予想買い目');});
      var horseHeading=headings.find(function(h){return /^出走馬/.test(text(h));});
      var bets=panelForHeading(betHeading),horses=panelForHeading(horseHeading);
      if(!bets||!horses||bets===horses)return;
      bets.setAttribute('data-race-panel','bets');
      horses.setAttribute('data-race-panel','horses');
      if(bets.parentNode)bets.parentNode.insertBefore(nav,bets);
      var panels={bets:bets,reason:reason,horses:horses};
      function activate(name){
        if(!panels[name])name='bets';
        Object.keys(panels).forEach(function(key){panels[key].hidden=key!==name;});
        nav.querySelectorAll('[data-race-tab]').forEach(function(button){button.setAttribute('aria-selected',button.getAttribute('data-race-tab')===name?'true':'false');});
      }
      nav.addEventListener('click',function(event){var button=event.target.closest('[data-race-tab]');if(!button)return;activate(button.getAttribute('data-race-tab'));});
      var hash=(location.hash||'').replace('#','');
      activate(hash==='reason'||hash==='horses'||hash==='bets'?hash:'bets');
    }
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
  })();</script>`;
  let out = html.replace("</head>", `${css}</head>`);
  out = out.replace("</body>", `${nav}${script}</body>`);
  return out;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    const path = new URL(request.url).pathname;
    if (!path.startsWith("/races/") || !response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
    const raceId = decodeURIComponent(path.slice("/races/".length));
    const date = raceId.slice(0, 10);
    if (!/^20\d{2}-\d{2}-\d{2}$/.test(date) || date <= CUTOFF) return response;
    try {
      const tickets = await loadFixedTicketEvidence(env.DB, raceId);
      if (tickets.length !== 2) return response;
      let html = stripOldPredictionReasons(await response.text());
      html = injectReasonBeforeRunners(html, reasonSection(tickets));
      html = addTabsUi(html);
      const headers = new Headers(response.headers);
      headers.delete("content-length");
      headers.set("cache-control", "no-store, max-age=0");
      headers.set("x-race-ui-version", UI_VERSION);
      return new Response(html, { status: response.status, headers });
    } catch {
      return response;
    }
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
