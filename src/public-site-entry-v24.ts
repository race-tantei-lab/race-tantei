import publicSite from "./public-site-entry-v23.js";
import {
  ensureCompletedSelectionExplanations,
  loadCompletedSelectionExplanation,
  type CompletedSelectionExplanation,
  type SelectionHorseEvidence,
  type SelectionProxyTicketEvidence,
} from "./v1/completed-selection-race-explanation.js";
import { loadFixedTicketEvidence, type FixedTicketEvidence } from "./v1/completed-fixed-ticket-explanation.js";
import type { Env } from "./v1/types.js";

const CUTOFF = "2026-08-09";
const SELECTION_PREFIX = "final_daily_selection:";

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] ?? ch));
}
function roi(value: number | null | undefined): string { return Number.isFinite(value) ? `${(Number(value) * 100).toFixed(1)}%` : "—"; }
function pct(value: number): string { return `${(Number(value) * 100).toFixed(2)}%`; }
function score(value: number): string { return Number(value).toFixed(6); }
function formLabel(code: number): string { return ["履歴なし", "30%未満", "30〜50%未満", "50〜70%未満", "70%以上"][code] ?? `区分${code}`; }
function rateLabel(code: number): string { return ["15%未満", "15〜25%未満", "25〜35%未満", "35〜45%未満", "45%以上"][code] ?? `区分${code}`; }
function startsLabel(code: number): string { return ["0走", "1〜2走", "3〜5走", "6〜10走", "11走以上"][code] ?? `区分${code}`; }

function selectionHorseHtml(horse: SelectionHorseEvidence): string {
  return `<article class="selection-horse-evidence"><div class="selection-horse-head"><strong>${horse.horseNo}番 ${esc(horse.horseName)}</strong><span>選定用候補上位</span></div><div class="selection-factor-chips">
    <span>近走着順指数 ${esc(formLabel(horse.formCode))}</span><span>近走速度指数 ${esc(formLabel(horse.speedCode))}</span>
    <span>${esc(horse.jockey)} 騎手3着内率 ${esc(rateLabel(horse.jockeyCode))}</span><span>${esc(horse.trainer)} 調教師3着内率 ${esc(rateLabel(horse.trainerCode))}</span>
    <span>過去出走 ${esc(startsLabel(horse.startsCode))}</span><span>直近3走3着内 ${horse.recentTop3Count}回</span>
  </div></article>`;
}

function proxyTicketHtml(ticket: SelectionProxyTicketEvidence, index: number): string {
  const components = ticket.topComponents.map((component, componentIndex) => `<div class="selection-component-row"><div><b>${componentIndex + 1}. ${esc(component.label)}</b><span>この条件の過去サンプル ${component.sampleN.toLocaleString("ja-JP")}件</span></div><div class="selection-component-values"><span>補正後ROI</span><strong>${roi(component.smoothedRoi)}</strong><small>有効重み ${(component.effectiveWeight * 100).toFixed(1)}%</small></div></div>`).join("");
  const local = ticket.usedFallback ? "局所条件なし（global×0.95）" : roi(ticket.localWeightedRoi);
  return `<article class="selection-proxy-ticket"><div class="selection-proxy-head"><div><span>レース選定用 仮買い目${index + 1}</span><strong>${esc(ticket.betType)} ${esc(ticket.combination)}</strong></div><b>score ${score(ticket.finalScore)}</b></div><div class="selection-score-grid">
    <div><span>${esc(ticket.betType)}全体</span><b>${roi(ticket.globalSmoothedRoi)}</b><small>過去 ${ticket.globalSampleN.toLocaleString("ja-JP")}件</small></div>
    <div><span>局所条件の加重ROI</span><b>${local}</b><small>候補 ${ticket.eligibleComponentCount}条件から上位${ticket.topComponents.length}条件</small></div>
    <div><span>最終仮買い目score</span><b>${score(ticket.finalScore)}</b><small>global 40% + local 60%</small></div>
  </div><div class="selection-component-list">${components || `<p class="muted">500件以上の局所条件がなく、券種全体の補正値を使用。</p>`}</div></article>`;
}

function exactSelectionHtml(explanation: CompletedSelectionExplanation): string {
  return `<div class="decision-section exact-selection-evidence" data-selection-trace="${esc(explanation.version)}"><h3>1. なぜこのレースを選んだか</h3>
    <div class="selection-summary-grid">
      <div><span>選定結果</span><b>${esc(explanation.venue)}の上位5Rに採用</b><small>採用5R内 ${explanation.venueRank}位</small></div>
      <div><span>raceScore</span><b>${score(explanation.raceScore)}</b><small>下の仮買い目3点の平均</small></div>
      <div><span>再現検証</span><b>凍結済みraceScoreと一致</b><small>一致しないレースにはこの内訳を出しません</small></div>
    </div>
    <p class="selection-explain-copy">このレースは「1つの条件を満たしたから」選んだのではありません。選定用上位5頭から6券種の仮買い目を作り、各仮買い目について過去${explanation.scoreFormula.minSampleN.toLocaleString("ja-JP")}件以上ある条件だけを評価。補正後ROIが高い上位${explanation.scoreFormula.topComponents}条件をサンプル数に応じて加重し、「券種全体40% + 局所条件60%」で仮買い目scoreを出し、その上位3点の平均をraceScoreにしています。</p>
    <details class="selection-math"><summary>ROI補正のルール</summary><p>局所条件は過去${explanation.scoreFormula.keyPriorN.toLocaleString("ja-JP")}件分の事前値で平滑化。券種全体は${explanation.scoreFormula.betPriorN.toLocaleString("ja-JP")}件分・事前ROI ${(explanation.scoreFormula.priorRoi * 100).toFixed(0)}%で平滑化。2条件の組合せは複雑度0.92を重みに掛けています。</p></details>
    <div class="selection-subhead"><b>選定用の上位候補5頭</b><span>実際の選定入力</span></div><div class="selection-horse-list">${explanation.topHorses.map(selectionHorseHtml).join("")}</div>
    <div class="selection-subhead"><b>raceScoreを作った3つの仮買い目</b><span>実際に使った上位ROI条件</span></div>${explanation.proxyTickets.map(proxyTicketHtml).join("")}
  </div>`;
}

function ticketHtml(ticket: FixedTicketEvidence): string {
  const names = ticket.horses.map((horseNo, index) => `${horseNo} ${ticket.horseNames[index] || ""}`.trim()).join(" / ");
  return `<article class="decision-ticket exact-ticket-evidence"><div class="decision-ticket-head"><strong>${esc(ticket.betType)} ${esc(ticket.combination)}</strong><span>${esc(names)}</span></div><div class="decision-metrics">
    <div><span>組合せ予測確率</span><b>${pct(ticket.predictedProbability)}</b></div><div><span>JRA公式オッズ</span><b>${ticket.officialOdds.toFixed(1)}倍</b></div>
    <div><span>確率 × オッズ</span><b>${ticket.valueProduct.toFixed(4)}</b></div><div><span>最終スコア</span><b>${score(ticket.score)}</b></div>
  </div><p>最終スコア = ln(組合せ予測確率) + 0.4 × ln(JRA公式オッズ)</p></article>`;
}

function exactTicketsHtml(tickets: FixedTicketEvidence[]): string {
  const exact = tickets.every((ticket) => ticket.evidenceSource === "fixed-snapshot");
  const source = exact ? "固定時スナップショット" : "公開固定買い目から再計算";
  const note = exact
    ? "固定時に保存したモデル確率・JRA公式オッズ・評価値をそのまま表示しています。6券種の全候補から各券種上位5候補を残し、最終スコアで券種代表を決め、その中から異なる2券種が最終買い目になりました。"
    : "このレースはWorkerの固定時スナップショットが残っていないため、公開済みの最終2点と固定オッズは変更せず、同じ凍結モデル・同じcanonical特徴量ルールから各組合せの確率と評価値を再計算しています。過去の買い目を書き換えてはいません。";
  return `<div class="decision-section exact-fixed-ticket-section" data-ticket-evidence="${exact ? "fixed-snapshot" : "recomputed-public-lock"}"><h3>2. なぜこの2点になったか</h3><div class="ticket-evidence-source"><b>${source}</b></div>${tickets.map(ticketHtml).join("")}<p class="ticket-evidence-note">${esc(note)}</p></div>`;
}

function replaceSection(html: string, number: 1 | 2, replacement: string): string {
  const next = number + 1;
  const pattern = new RegExp(`<div class="decision-section(?: [^"]*)?"><h3>${number}\\. [\\s\\S]*?<\\/h3>[\\s\\S]*?(?=<div class="decision-section(?: [^"]*)?"><h3>${next}\\. )`);
  return pattern.test(html) ? html.replace(pattern, replacement) : html;
}

function enhance(html: string, selection: CompletedSelectionExplanation, tickets: FixedTicketEvidence[]): string {
  let out = replaceSection(html, 1, exactSelectionHtml(selection));
  out = replaceSection(out, 2, exactTicketsHtml(tickets));
  out = out.replaceAll("○○条件に合致", "曖昧な単一条件").replaceAll("条件に合致", "具体的な数値で評価").replaceAll("条件合致", "具体的な数値で評価");
  const css = `<style>
    .selection-summary-grid,.selection-score-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.selection-summary-grid>div,.selection-score-grid>div{display:grid;gap:3px;padding:9px 10px;border:1px solid var(--line);border-radius:10px;background:var(--panel2)}.selection-summary-grid span,.selection-score-grid span{font-size:10px;color:var(--muted)}.selection-summary-grid b,.selection-score-grid b{font-size:13px}.selection-summary-grid small,.selection-score-grid small{font-size:9px;color:var(--muted)}
    .selection-explain-copy{margin:10px 0!important;color:var(--text)!important;font-size:11px!important;line-height:1.75}.selection-math{margin:8px 0 12px;border:1px solid var(--line);border-radius:10px;padding:8px 10px}.selection-math summary{cursor:pointer;font-size:11px;font-weight:800}.selection-math p{margin:7px 0 0;color:var(--muted);font-size:10px;line-height:1.7}
    .selection-subhead{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:13px 0 7px}.selection-subhead b{font-size:12px}.selection-subhead span{font-size:9px;color:var(--muted)}.selection-horse-list{display:grid;gap:6px}.selection-horse-evidence{padding:9px 10px;border:1px solid var(--line);border-radius:10px;background:var(--panel2)}.selection-horse-head{display:flex;justify-content:space-between;gap:8px}.selection-horse-head strong{font-size:12px}.selection-horse-head span{font-size:9px;color:var(--muted)}.selection-factor-chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}.selection-factor-chips span{padding:4px 7px;border:1px solid var(--line);border-radius:999px;font-size:9px;background:var(--panel)}
    .selection-proxy-ticket{margin-top:9px;padding:11px;border:1px solid var(--line);border-radius:12px;background:var(--panel2)}.selection-proxy-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.selection-proxy-head>div{display:grid;gap:2px}.selection-proxy-head span{font-size:9px;color:var(--muted)}.selection-proxy-head strong{font-size:13px}.selection-proxy-head>b{font-size:11px;color:var(--green);white-space:nowrap}.selection-score-grid{margin-top:8px}.selection-component-list{display:grid;gap:5px;margin-top:8px}.selection-component-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:7px 8px;border-top:1px solid var(--line)}.selection-component-row>div:first-child{display:grid;gap:2px}.selection-component-row b{font-size:10px}.selection-component-row span,.selection-component-row small{font-size:9px;color:var(--muted)}.selection-component-values{display:grid;grid-template-columns:auto auto;gap:1px 7px;text-align:right;white-space:nowrap}.selection-component-values strong{font-size:12px}.selection-component-values small{grid-column:1 / span 2}
    .ticket-evidence-source{margin:0 0 8px}.ticket-evidence-source b{font-size:10px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:4px 7px}.ticket-evidence-note{margin:9px 0 0!important;color:var(--muted)!important;font-size:10px!important;line-height:1.7}.exact-ticket-evidence .decision-metrics{grid-template-columns:repeat(4,minmax(0,1fr))}
    @media(max-width:760px){.selection-summary-grid,.selection-score-grid{grid-template-columns:1fr}.selection-proxy-head{display:grid}.selection-component-row{align-items:flex-start}.selection-component-values{min-width:88px}.exact-ticket-evidence .decision-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
  </style>`;
  return out.replace("</head>", `${css}</head>`);
}

function jstDate(now = new Date()): string { return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10); }

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    const path = new URL(request.url).pathname;
    if (!path.startsWith("/races/") || !response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
    const raceId = decodeURIComponent(path.slice("/races/".length));
    const date = raceId.slice(0, 10);
    if (date <= CUTOFF || !/^20\d{2}-\d{2}-\d{2}$/.test(date)) return response;
    try {
      const [selection, tickets] = await Promise.all([
        loadCompletedSelectionExplanation(env.DB, raceId, date),
        loadFixedTicketEvidence(env.DB, raceId),
      ]);
      if (!selection || tickets.length !== 2) return response;
      const headers = new Headers(response.headers);
      headers.delete("content-length");
      headers.delete("x-selection-evidence-error");
      headers.set("cache-control", "no-store, max-age=0");
      headers.set("x-race-ui-version", "ten-year-completed-public-v24-verified-decision-evidence");
      return new Response(enhance(await response.text(), selection, tickets), { status: response.status, headers });
    } catch {
      return response;
    }
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
    const date = jstDate();
    if (date <= CUTOFF) return;
    try {
      const frozen = await env.DB.prepare("SELECT 1 AS ok FROM rt_system_state WHERE state_key=? LIMIT 1").bind(`${SELECTION_PREFIX}${date}`).first<{ ok: number }>();
      if (frozen?.ok) ctx.waitUntil(ensureCompletedSelectionExplanations(env.DB, date).catch(() => undefined));
    } catch {/* evidence generation must never break betting */}
  },
} satisfies ExportedHandler<Env>;
