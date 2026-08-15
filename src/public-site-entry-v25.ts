import publicSite from "./public-site-entry-v22.js";
import { freezeCompletedWorkerSelectionIfNeeded } from "./v1/completed-selection-runtime.js";
import {
  ensureCompletedSelectionExplanations,
  type CompletedSelectionExplanation,
  type SelectionHorseEvidence,
  type SelectionProxyTicketEvidence,
} from "./v1/completed-selection-race-explanation.js";
import { COMPLETED_MODEL_VERSION } from "./v1/completed-feature-runtime.js";
import { loadFixedTicketEvidence, type FixedTicketEvidence } from "./v1/completed-fixed-ticket-explanation.js";
import type { Env } from "./v1/types.js";

const CUTOFF = "2026-08-09";
const SELECTION_PREFIX = "final_daily_selection:";
const EXPLANATION_PREFIX = "worker_selection_explanation:";
const EXPLANATION_VERSION = "canonical-selection-trace-v1";

type FrozenSelectedRace = { raceId: string; venue: string; raceNo: number; raceScore: number };
type FrozenSelectionPayload = {
  sourceModel?: string;
  resultDataUsedForTargetDay?: boolean;
  selected?: FrozenSelectedRace[];
};
type FrozenMeta = FrozenSelectedRace & { venueRank: number };

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] ?? ch));
}
function roi(value: number | null | undefined): string { return Number.isFinite(value) ? `${(Number(value) * 100).toFixed(1)}%` : "—"; }
function pct(value: number): string { return `${(Number(value) * 100).toFixed(2)}%`; }
function score(value: number): string { return Number(value).toFixed(6); }
function formLabel(code: number): string { return ["履歴なし", "30%未満", "30〜50%未満", "50〜70%未満", "70%以上"][code] ?? `区分${code}`; }
function rateLabel(code: number): string { return ["15%未満", "15〜25%未満", "25〜35%未満", "35〜45%未満", "45%以上"][code] ?? `区分${code}`; }
function startsLabel(code: number): string { return ["0走", "1〜2走", "3〜5走", "6〜10走", "11走以上"][code] ?? `区分${code}`; }
function jstDate(now = new Date()): string { return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10); }

async function loadStoredSelectionExplanation(db: D1Database, raceId: string, date: string): Promise<CompletedSelectionExplanation | null> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`${EXPLANATION_PREFIX}${date}:${raceId}`)
    .first<{ value: string }>();
  if (!row?.value) return null;
  const parsed = JSON.parse(row.value) as CompletedSelectionExplanation;
  if (parsed.version !== EXPLANATION_VERSION || parsed.sourceModel !== COMPLETED_MODEL_VERSION || parsed.raceId !== raceId || parsed.raceDate !== date || parsed.verifiedAgainstFrozenSelection !== true) {
    throw new Error(`IMMUTABLE_SELECTION_EVIDENCE_INVALID:${raceId}`);
  }
  return parsed;
}

async function loadFrozenMeta(db: D1Database, raceId: string, date: string): Promise<FrozenMeta | null> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`${SELECTION_PREFIX}${date}`)
    .first<{ value: string }>();
  if (!row?.value) return null;
  const payload = JSON.parse(row.value) as FrozenSelectionPayload;
  if (payload.sourceModel !== COMPLETED_MODEL_VERSION || payload.resultDataUsedForTargetDay !== false || !Array.isArray(payload.selected)) return null;
  const target = payload.selected.find((item) => String(item.raceId) === raceId);
  if (!target) return null;
  const venueRows = payload.selected
    .filter((item) => String(item.venue) === String(target.venue))
    .slice()
    .sort((a, b) => Number(b.raceScore) - Number(a.raceScore) || Number(a.raceNo) - Number(b.raceNo));
  const venueRank = venueRows.findIndex((item) => String(item.raceId) === raceId) + 1;
  return { ...target, venueRank };
}

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
    <div><span>最終仮買い目score</span><b>${score(ticket.finalScore)}</b><small>券種全体40% + 局所条件60%</small></div>
  </div><div class="selection-component-list">${components || `<p class="muted">500件以上の局所条件がなく、券種全体の補正値を使用。</p>`}</div></article>`;
}

function exactSelectionHtml(explanation: CompletedSelectionExplanation): string {
  return `<div class="decision-section exact-selection-evidence" data-selection-trace="${esc(explanation.version)}"><h3>1. なぜこのレースを選んだか</h3>
    <div class="selection-summary-grid">
      <div><span>会場内順位</span><b>${esc(explanation.venue)} 12R中 ${explanation.venueRank}位</b><small>上位5Rを購入対象</small></div>
      <div><span>raceScore</span><b>${score(explanation.raceScore)}</b><small>下の仮買い目3点の平均</small></div>
      <div><span>検証</span><b>凍結済み選定と一致</b><small>raceId・raceScore一致時だけ表示</small></div>
    </div>
    <p class="selection-explain-copy">このレースは単一条件で採用していません。選定用上位5頭から6券種の仮買い目を作り、各仮買い目で過去${explanation.scoreFormula.minSampleN.toLocaleString("ja-JP")}件以上ある条件だけを評価。補正後ROIが高い上位${explanation.scoreFormula.topComponents}条件をサンプル数に応じて加重し、「券種全体40% + 局所条件60%」で仮買い目scoreを計算。その上位3点の平均をraceScoreにしています。</p>
    <details class="selection-math"><summary>ROI補正のルール</summary><p>局所条件は過去${explanation.scoreFormula.keyPriorN.toLocaleString("ja-JP")}件分の事前値で平滑化。券種全体は${explanation.scoreFormula.betPriorN.toLocaleString("ja-JP")}件分・事前ROI ${(explanation.scoreFormula.priorRoi * 100).toFixed(0)}%で平滑化し、2条件の組合せには複雑度0.92を掛けています。</p></details>
    <div class="selection-subhead"><b>選定用の上位候補5頭</b><span>選定時の保存済み根拠</span></div><div class="selection-horse-list">${explanation.topHorses.map(selectionHorseHtml).join("")}</div>
    <div class="selection-subhead"><b>raceScoreを作った3つの仮買い目</b><span>実際に使った上位ROI条件</span></div>${explanation.proxyTickets.map(proxyTicketHtml).join("")}
  </div>`;
}

function unavailableSelectionHtml(meta: FrozenMeta): string {
  return `<div class="decision-section unavailable-selection-evidence" data-selection-trace="freeze-snapshot-unavailable"><h3>1. なぜこのレースを選んだか</h3>
    <div class="selection-summary-grid">
      <div><span>会場内順位</span><b>${esc(meta.venue)} 採用5R内 ${meta.venueRank}位</b><small>対象レース自体は凍結済み</small></div>
      <div><span>raceScore</span><b>${score(meta.raceScore)}</b><small>凍結値は保存済み</small></div>
      <div><span>詳細内訳</span><b>厳密復元不可</b><small>推測値は表示しません</small></div>
    </div>
    <p class="selection-explain-copy"><b>このレースは、選定時点の入力スナップショットを保存していなかったため、馬別の選定入力・3つの仮買い目・各ROI条件を厳密には復元できません。</b> 凍結済みの対象レースとraceScoreは残っていますが、現在の出走情報を使って後付けした説明は選定時の根拠ではないため表示しません。次回以降は凍結と同時にraceScore一致を確認した具体内訳だけを保存します。</p>
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
    ? "固定時に保存したモデル確率・JRA公式オッズ・評価値をそのまま表示しています。"
    : "固定時スナップショットが残っていないため、公開済み最終2点と固定オッズは変更せず、同じ凍結モデル・canonical特徴量ルールから説明値だけ再計算しています。公開済み買い目は書き換えていません。";
  return `<div class="decision-section exact-fixed-ticket-section" data-ticket-evidence="${exact ? "fixed-snapshot" : "recomputed-public-lock"}"><h3>2. なぜこの2点になったか</h3><div class="ticket-evidence-source"><b>${source}</b></div>${tickets.map(ticketHtml).join("")}<p class="ticket-evidence-note">${esc(note)}</p></div>`;
}

function replaceSection(html: string, number: 1 | 2, replacement: string): string {
  const next = number + 1;
  const pattern = new RegExp(`<div class="decision-section(?: [^"]*)?"><h3>${number}\\. [\\s\\S]*?<\\/h3>[\\s\\S]*?(?=<div class="decision-section(?: [^"]*)?"><h3>${next}\\. )`);
  return pattern.test(html) ? html.replace(pattern, replacement) : html;
}

function addEvidenceCss(html: string): string {
  if (html.includes("data-v25-selection-evidence-css")) return html;
  const css = `<style data-v25-selection-evidence-css>
    .selection-summary-grid,.selection-score-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.selection-summary-grid>div,.selection-score-grid>div{display:grid;gap:3px;padding:9px 10px;border:1px solid var(--line);border-radius:10px;background:var(--panel2)}.selection-summary-grid span,.selection-score-grid span{font-size:10px;color:var(--muted)}.selection-summary-grid b,.selection-score-grid b{font-size:13px}.selection-summary-grid small,.selection-score-grid small{font-size:9px;color:var(--muted)}
    .selection-explain-copy{margin:10px 0!important;color:var(--text)!important;font-size:11px!important;line-height:1.75}.selection-math{margin:8px 0 12px;border:1px solid var(--line);border-radius:10px;padding:8px 10px}.selection-math summary{cursor:pointer;font-size:11px;font-weight:800}.selection-math p{margin:7px 0 0;color:var(--muted);font-size:10px;line-height:1.7}
    .selection-subhead{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:13px 0 7px}.selection-subhead b{font-size:12px}.selection-subhead span{font-size:9px;color:var(--muted)}.selection-horse-list{display:grid;gap:6px}.selection-horse-evidence{padding:9px 10px;border:1px solid var(--line);border-radius:10px;background:var(--panel2)}.selection-horse-head{display:flex;justify-content:space-between;gap:8px}.selection-horse-head strong{font-size:12px}.selection-horse-head span{font-size:9px;color:var(--muted)}.selection-factor-chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}.selection-factor-chips span{padding:4px 7px;border:1px solid var(--line);border-radius:999px;font-size:9px;background:var(--panel)}
    .selection-proxy-ticket{margin-top:9px;padding:11px;border:1px solid var(--line);border-radius:12px;background:var(--panel2)}.selection-proxy-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.selection-proxy-head>div{display:grid;gap:2px}.selection-proxy-head span{font-size:9px;color:var(--muted)}.selection-proxy-head strong{font-size:13px}.selection-proxy-head>b{font-size:11px;color:var(--green);white-space:nowrap}.selection-score-grid{margin-top:8px}.selection-component-list{display:grid;gap:5px;margin-top:8px}.selection-component-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:7px 8px;border-top:1px solid var(--line)}.selection-component-row>div:first-child{display:grid;gap:2px}.selection-component-row b{font-size:10px}.selection-component-row span,.selection-component-row small{font-size:9px;color:var(--muted)}.selection-component-values{display:grid;grid-template-columns:auto auto;gap:1px 7px;text-align:right;white-space:nowrap}.selection-component-values strong{font-size:12px}.selection-component-values small{grid-column:1 / span 2}
    .ticket-evidence-source{margin:0 0 8px}.ticket-evidence-source b{font-size:10px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:4px 7px}.ticket-evidence-note{margin:9px 0 0!important;color:var(--muted)!important;font-size:10px!important;line-height:1.7}.exact-ticket-evidence .decision-metrics{grid-template-columns:repeat(4,minmax(0,1fr))}.unavailable-selection-evidence{border-color:#6b5526!important}
    @media(max-width:760px){.selection-summary-grid,.selection-score-grid{grid-template-columns:1fr}.selection-proxy-head{display:grid}.selection-component-row{align-items:flex-start}.selection-component-values{min-width:88px}.exact-ticket-evidence .decision-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
  </style>`;
  return html.replace("</head>", `${css}</head>`);
}

async function selectionExistedBefore(db: D1Database, date: string): Promise<boolean> {
  const row = await db.prepare("SELECT 1 AS ok FROM rt_system_state WHERE state_key=? LIMIT 1").bind(`${SELECTION_PREFIX}${date}`).first<{ ok: number }>();
  return Boolean(row?.ok);
}

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
      const [selection, frozen, tickets] = await Promise.all([
        loadStoredSelectionExplanation(env.DB, raceId, date),
        loadFrozenMeta(env.DB, raceId, date),
        loadFixedTicketEvidence(env.DB, raceId),
      ]);
      if (!frozen) return response;
      let html = await response.text();
      html = replaceSection(html, 1, selection ? exactSelectionHtml(selection) : unavailableSelectionHtml(frozen));
      if (tickets.length === 2) html = replaceSection(html, 2, exactTicketsHtml(tickets));
      html = html.replaceAll("○○条件に合致", "具体的な数値で評価").replaceAll("条件に合致", "具体的な数値で評価").replaceAll("条件合致", "具体的な数値で評価");
      html = addEvidenceCss(html);
      const headers = new Headers(response.headers);
      headers.delete("content-length");
      headers.delete("x-selection-evidence-error");
      headers.set("cache-control", "no-store, max-age=0");
      headers.set("x-race-ui-version", "ten-year-completed-public-v25-immutable-freeze-evidence");
      headers.set("x-selection-evidence", selection ? "immutable-exact" : "freeze-snapshot-unavailable");
      return new Response(html, { status: response.status, headers });
    } catch {
      return response;
    }
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const now = new Date(controller.scheduledTime || Date.now());
    const date = jstDate(now);
    const existed = date > CUTOFF ? await selectionExistedBefore(env.DB, date).catch(() => false) : true;

    // Keep the production selection/live-lock path unchanged. Evidence is only
    // attempted after the lower canonical scheduler creates today's first frozen
    // selection. If the race rows have already changed and raceScore parity fails,
    // the evidence helper writes nothing for that race rather than approximating.
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);

    if (date <= CUTOFF || existed) return;
    try {
      const frozenNow = await selectionExistedBefore(env.DB, date);
      if (frozenNow) await ensureCompletedSelectionExplanations(env.DB, date);
    } catch {/* explanation must never break selection, live lock, or settlement */}
  },
} satisfies ExportedHandler<Env>;
