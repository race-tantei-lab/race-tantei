import publicSite from "./public-site-entry-v21.js";
import {
  COMPLETED_MODEL_SHA256,
  COMPLETED_MODEL_VERSION,
  completedFeatureRecord,
  completedFeatureVector,
  loadCompletedFeatureStateForRace,
} from "./v1/completed-feature-runtime.js";
import { loadCompletedModelRuntime, type CompletedModelRuntime } from "./v1/completed-model-runtime.js";
import { normalizeCompletedWeights, type CompletedTicket } from "./v1/completed-ticket-runtime.js";
import type { Env, RaceRecord, RunnerRecord } from "./v1/types.js";

const SELECTION_PREFIX = "final_daily_selection:";
const FINAL_PREFIX = "worker_live_final:";
const PREVIEW_PREFIX = "worker_live_preview:";

type SelectionRow = {
  raceId?: string;
  venue?: string;
  raceNo?: number;
  raceScore?: number;
};

type SelectionPayload = { selected?: SelectionRow[] };
type FinalPayload = { tickets?: CompletedTicket[] };
type PreviewPayload = { snapshots?: Array<{ tickets?: CompletedTicket[] }> };
type PublicBetEvidence = { betType: string; combination: string; assumedOdds: number | null };
type ModelMetaRow = { key: string; value: string };
type ModelChunkRow = { seq: number; dataB64: string };

type TicketEvidence = {
  betType: string;
  combination: string;
  horses: number[];
  predictedProbability?: number;
  officialOdds?: number;
  valueProduct?: number;
  score?: number;
};

type HorseEvidence = {
  runner: RunnerRecord;
  probability: number;
  record: ReturnType<typeof completedFeatureRecord>;
};

let workerModelPromise: Promise<CompletedModelRuntime> | null = null;

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] ?? ch));
}

function pct(value: number | undefined): string {
  return Number.isFinite(value) ? `${(Number(value) * 100).toFixed(1)}%` : "—";
}

function num(value: number | undefined, digits = 3): string {
  return Number.isFinite(value) ? Number(value).toFixed(digits) : "—";
}

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function loadWorkerModel(db: D1Database): Promise<CompletedModelRuntime> {
  if (workerModelPromise) return workerModelPromise;
  workerModelPromise = (async () => {
    const metaResult = await db.prepare("SELECT key,value FROM rt_ml_model_meta").all<ModelMetaRow>();
    const meta = new Map((metaResult.results ?? []).map((row) => [row.key, row.value]));
    if (meta.get("ready") !== "1") throw new Error("decision evidence model is not ready");
    if (meta.get("modelVersion") !== COMPLETED_MODEL_VERSION || meta.get("sourceSha256") !== COMPLETED_MODEL_SHA256) {
      throw new Error("decision evidence model identity mismatch");
    }
    const generation = meta.get("generation") || "";
    const chunkCount = Number(meta.get("chunkCount") || 0);
    const byteLength = Number(meta.get("byteLength") || 0);
    if (!generation || !Number.isInteger(chunkCount) || chunkCount <= 0 || !Number.isInteger(byteLength) || byteLength <= 0) {
      throw new Error("decision evidence model metadata invalid");
    }
    const chunkResult = await db.prepare("SELECT seq,data_b64 AS dataB64 FROM rt_ml_model_chunk WHERE generation=? ORDER BY seq").bind(generation).all<ModelChunkRow>();
    const chunks = chunkResult.results ?? [];
    if (chunks.length !== chunkCount || chunks.some((row, index) => Number(row.seq) !== index)) throw new Error("decision evidence model chunks incomplete");
    const decoded = chunks.map((row) => decodeBase64(row.dataB64));
    const actualBytes = decoded.reduce((sum, row) => sum + row.byteLength, 0);
    if (actualBytes !== byteLength) throw new Error("decision evidence model byte length mismatch");
    const merged = new Uint8Array(byteLength);
    let offset = 0;
    for (const row of decoded) { merged.set(row, offset); offset += row.byteLength; }
    return loadCompletedModelRuntime(merged.buffer);
  })().catch((error) => {
    workerModelPromise = null;
    throw error;
  });
  return workerModelPromise;
}

async function loadRaceAndRunners(db: D1Database, raceId: string): Promise<{ race: RaceRecord; runners: RunnerRecord[] } | null> {
  const race = await db.prepare(`
    SELECT race_id AS raceId,race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,race_no AS raceNo,
           race_name AS raceName,conditions,surface,distance_m AS distanceM,direction,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,
           weather,track_condition AS trackCondition,entry_url AS entryUrl,result_url AS resultUrl,status
    FROM rt_races WHERE race_id=? LIMIT 1
  `).bind(raceId).first<RaceRecord>();
  if (!race) return null;
  const result = await db.prepare(`
    SELECT horse_no AS horseNo,frame_no AS frameNo,horse_name AS horseName,sex_age AS sexAge,coat_color AS coatColor,
           horse_weight AS horseWeight,weight_change AS weightChange,jockey,assigned_weight AS assignedWeight,trainer,stable,
           win_odds AS winOdds,popularity,runner_status AS runnerStatus
    FROM rt_runners WHERE race_id=? ORDER BY horse_no
  `).bind(raceId).all<RunnerRecord>();
  const runners = (result.results ?? []).filter((runner) => (runner.runnerStatus || "active") === "active" && Number.isInteger(Number(runner.horseNo)));
  return { race, runners };
}

function parseTickets(value: string | undefined, kind: "final" | "preview"): TicketEvidence[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value) as FinalPayload | PreviewPayload;
    const rows = kind === "final"
      ? (parsed as FinalPayload).tickets
      : (parsed as PreviewPayload).snapshots?.[0]?.tickets;
    if (!Array.isArray(rows) || rows.length !== 2) return [];
    return rows.map((row) => ({
      betType: String(row.betType || ""),
      combination: String(row.combination || ""),
      horses: Array.isArray(row.horses) ? row.horses.map(Number).filter(Number.isFinite) : String(row.combination || "").split("-").map(Number).filter(Number.isFinite),
      predictedProbability: Number(row.predictedProbability),
      officialOdds: Number(row.officialOdds),
      valueProduct: Number(row.valueProduct),
      score: Number(row.score),
    })).filter((row) => row.betType && row.combination);
  } catch {
    return [];
  }
}

async function loadTicketEvidence(db: D1Database, raceId: string): Promise<{ tickets: TicketEvidence[]; source: string }> {
  const states = await db.prepare("SELECT state_key AS stateKey,state_value AS value FROM rt_system_state WHERE state_key IN (?,?)")
    .bind(`${FINAL_PREFIX}${raceId}`, `${PREVIEW_PREFIX}${raceId}`).all<{ stateKey: string; value: string }>();
  const byKey = new Map((states.results ?? []).map((row) => [row.stateKey, row.value]));
  const finalTickets = parseTickets(byKey.get(`${FINAL_PREFIX}${raceId}`), "final");
  if (finalTickets.length === 2) return { tickets: finalTickets, source: "fixed-snapshot" };
  const previewTickets = parseTickets(byKey.get(`${PREVIEW_PREFIX}${raceId}`), "preview");
  if (previewTickets.length === 2) return { tickets: previewTickets, source: "preview-snapshot" };

  const rows = await db.prepare(`
    SELECT bet_type AS betType,combination,AVG(assumed_odds) AS assumedOdds
    FROM rt_public_bets WHERE race_id=? GROUP BY bet_type,combination ORDER BY bet_type,combination
  `).bind(raceId).all<PublicBetEvidence>();
  const tickets = (rows.results ?? []).map((row) => ({
    betType: String(row.betType || ""),
    combination: String(row.combination || ""),
    horses: String(row.combination || "").split("-").map(Number).filter(Number.isFinite),
    officialOdds: Number(row.assumedOdds),
  })).filter((row) => row.betType && row.combination);
  return { tickets: tickets.slice(0, 2), source: "public-bets" };
}

async function selectionEvidence(db: D1Database, race: RaceRecord): Promise<{ score?: number; rank?: number; selectedCount?: number }> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(`${SELECTION_PREFIX}${race.raceDate}`).first<{ value: string }>();
  if (!row?.value) return {};
  try {
    const payload = JSON.parse(row.value) as SelectionPayload;
    const selected = (payload.selected ?? []).filter((item) => String(item.venue || "") === String(race.venue || ""));
    const ordered = selected.slice().sort((a, b) => (Number(b.raceScore) - Number(a.raceScore)) || (Number(a.raceNo) - Number(b.raceNo)));
    const index = ordered.findIndex((item) => String(item.raceId || "") === String(race.raceId));
    const current = selected.find((item) => String(item.raceId || "") === String(race.raceId));
    return {
      score: current && Number.isFinite(Number(current.raceScore)) ? Number(current.raceScore) : undefined,
      rank: index >= 0 ? index + 1 : undefined,
      selectedCount: selected.length || undefined,
    };
  } catch {
    return {};
  }
}

function distanceBucket(distance: number): string {
  if (distance <= 1200) return "〜1200m";
  if (distance <= 1500) return "1201〜1500m";
  if (distance <= 1800) return "1501〜1800m";
  if (distance <= 2200) return "1801〜2200m";
  if (distance <= 2600) return "2201〜2600m";
  return "2601m〜";
}

function fieldBucket(field: number): string {
  if (field <= 8) return "8頭以下";
  if (field <= 11) return "9〜11頭";
  if (field <= 13) return "12〜13頭";
  if (field <= 16) return "14〜16頭";
  return "17頭以上";
}

function raceNoBucket(raceNo: number): string {
  if (raceNo <= 3) return "1〜3R";
  if (raceNo <= 6) return "4〜6R";
  if (raceNo <= 9) return "7〜9R";
  return "10〜12R";
}

function classBucket(race: RaceRecord): string {
  const text = `${race.raceName || ""} ${race.conditions || ""}`.replace(/\s/g, "");
  if (/(GI|GⅠ|ＧⅠ)/.test(text)) return "G1";
  if (/(GII|GⅡ|ＧⅡ)/.test(text)) return "G2";
  if (/(GIII|GⅢ|ＧⅢ)/.test(text)) return "G3";
  if (text.includes("新馬")) return "新馬";
  if (text.includes("未勝利")) return "未勝利";
  if (text.includes("1勝") || text.includes("500万下")) return "1勝クラス";
  if (text.includes("2勝") || text.includes("1000万下")) return "2勝クラス";
  if (text.includes("3勝") || text.includes("1600万下")) return "3勝クラス";
  if (text.includes("(L)") || text.includes("オープン") || text.includes("OP")) return "オープン/L";
  return "その他クラス";
}

function ticketHtml(ticket: TicketEvidence, horseNames: Map<number, string>): string {
  const names = ticket.horses.map((horseNo) => `${horseNo} ${horseNames.get(horseNo) || ""}`.trim()).join(" / ");
  const metrics: string[] = [];
  if (Number.isFinite(ticket.predictedProbability)) metrics.push(`<div><span>組合せ予測確率</span><b>${pct(ticket.predictedProbability)}</b></div>`);
  if (Number.isFinite(ticket.officialOdds)) metrics.push(`<div><span>JRA公式オッズ</span><b>${Number(ticket.officialOdds).toFixed(1)}倍</b></div>`);
  if (Number.isFinite(ticket.valueProduct)) metrics.push(`<div><span>確率 × オッズ</span><b>${num(ticket.valueProduct)}</b></div>`);
  if (Number.isFinite(ticket.score)) metrics.push(`<div><span>最終スコア</span><b>${num(ticket.score)}</b></div>`);
  const algorithm = Number.isFinite(ticket.predictedProbability) && Number.isFinite(ticket.score)
    ? "この券種の全組合せを『予測確率×公式オッズ』で順位付けして上位5候補を残し、その5候補を最終スコアで再順位付け。この組合せが券種代表になり、6券種の代表候補の中から最終2券種に残りました。"
    : "この組合せは固定済みの公開買い目です。固定スナップショットの詳細値が取得できない場合は、公開時オッズのみ表示します。";
  return `<article class="decision-ticket"><div class="decision-ticket-head"><strong>${esc(ticket.betType)} ${esc(ticket.combination)}</strong><span>${esc(names)}</span></div><div class="decision-metrics">${metrics.join("")}</div><p>${esc(algorithm)}</p></article>`;
}

function horseHtml(item: HorseEvidence): string {
  const r = item.record;
  const runner = item.runner;
  const chips = [
    `近3走3着内 ${Math.round(r.top3Last3)}/3`,
    `馬3着内率 ${pct(r.horseTop3Rate)}`,
    `${String(runner.horseName || "")}×${String(runner.jockey || "騎手")} ${pct(r.pairTop3Rate)} (${Math.round(r.pairStarts)}走)`,
    `${String(runner.jockey || "騎手")} 3着内 ${pct(r.jockeyTop3Rate)} (${Math.round(r.jockeyStarts)}走)`,
    `${String(runner.trainer || "調教師")} 3着内 ${pct(r.trainerTop3Rate)} (${Math.round(r.trainerStarts)}走)`,
    `同${String(runner.runnerStatus || "")}ではなく同馬場 ${pct(r.sameSurfaceTop3Rate)} (${Math.round(r.sameSurfaceStarts)}走)`,
    `同距離帯 ${pct(r.sameDistTop3Rate)} (${Math.round(r.sameDistStarts)}走)`,
    `同会場 ${pct(r.sameVenueTop3Rate)} (${Math.round(r.sameVenueStarts)}走)`,
    `近3走着順指数 ${(r.avg3FinishPct * 100).toFixed(1)}/100`,
    `近3走上がり指数 ${(r.avg3Final3fPct * 100).toFixed(1)}/100`,
    r.avg3SpeedMps > 0 ? `近3走平均速度 ${r.avg3SpeedMps.toFixed(2)}m/s` : "",
    r.daysSinceLast < 999 ? `前走から ${Math.round(r.daysSinceLast)}日` : "初出走/履歴なし",
  ].filter(Boolean);
  return `<article class="decision-horse"><div class="decision-horse-head"><div><span>${Number(runner.horseNo)}番</span><strong>${esc(runner.horseName || "")}</strong></div><b>モデル予測勝率 ${pct(item.probability)}</b></div><div class="decision-chip-list">${chips.map((chip) => `<span>${esc(chip)}</span>`).join("")}</div></article>`;
}

async function buildDecisionEvidence(db: D1Database, raceId: string): Promise<string> {
  const ticketEvidence = await loadTicketEvidence(db, raceId);
  if (ticketEvidence.tickets.length !== 2) return "";
  const loaded = await loadRaceAndRunners(db, raceId);
  if (!loaded || loaded.runners.length < 3) return "";
  const { race, runners } = loaded;
  if (race.raceDate <= "2026-08-09") return "";

  const [selection, featureState, model] = await Promise.all([
    selectionEvidence(db, race),
    loadCompletedFeatureStateForRace(db, race, runners),
    loadWorkerModel(db),
  ]);
  const vectors = runners.map((runner) => completedFeatureVector(featureState, race, runner, runners.length));
  const weights = normalizeCompletedWeights(vectors.map((vector) => model.predict(vector)));
  const probabilityByHorse = new Map<number, number>();
  runners.forEach((runner, index) => probabilityByHorse.set(Number(runner.horseNo), weights[index]));
  const horseNames = new Map(runners.map((runner) => [Number(runner.horseNo), String(runner.horseName || "")]));

  const ticketHorseNos = [...new Set(ticketEvidence.tickets.flatMap((ticket) => ticket.horses))];
  const horseRows: HorseEvidence[] = [];
  for (const horseNo of ticketHorseNos) {
    const runner = runners.find((row) => Number(row.horseNo) === horseNo);
    if (!runner) continue;
    horseRows.push({
      runner,
      probability: probabilityByHorse.get(horseNo) ?? 0,
      record: completedFeatureRecord(featureState, race, runner, runners.length),
    });
  }

  const raceConditions = [
    String(race.venue || ""),
    String(race.surface || "障害"),
    distanceBucket(Number(race.distanceM || 0)),
    fieldBucket(runners.length),
    raceNoBucket(Number(race.raceNo || 0)),
    classBucket(race),
  ];
  const rankText = selection.rank ? `${esc(race.venue)}12R中 ${selection.rank}位 → 上位5Rとして採用` : "上位5Rとして採用";
  const scoreText = Number.isFinite(selection.score) ? num(selection.score, 6) : "—";
  const ticketRows = ticketEvidence.tickets.map((ticket) => ticketHtml(ticket, horseNames)).join("");
  const horses = horseRows.map(horseHtml).join("");

  return `<section class="prediction-reasons live-prediction-reasons decision-evidence" data-decision-evidence="canonical-live-v1"><div class="decision-title"><div><h2>予想根拠</h2><p>実際に選定・予測・買い目決定で使った値</p></div><span>${esc(ticketEvidence.source)}</span></div>
    <div class="decision-section"><h3>1. なぜこのレースを選んだか</h3><div class="decision-race-grid"><div><span>会場内順位</span><b>${rankText}</b></div><div><span>レース選定スコア</span><b>${scoreText}</b></div></div><div class="decision-chip-list race-condition-list">${raceConditions.map((condition) => `<span>${esc(condition)}</span>`).join("")}</div><p>レース選定では、候補馬上位5頭から仮買い目を作り、上のレース条件に加えて「近走の着順傾向・速度傾向・騎手3着内率・調教師3着内率・経験数・直近3着内」を組み合わせた過去ROIを平滑化して採点します。3つの仮買い目の平均がレース選定スコアで、このレースは会場12Rの上位5Rに入りました。</p></div>
    <div class="decision-section"><h3>2. なぜこの2点になったか</h3>${ticketRows}</div>
    <div class="decision-section"><h3>3. 買い目に入った馬の実データ</h3><p class="decision-note">下はLightGBMに実際に入った56項目のうち、意味が読み取りやすい主要値です。単一条件で馬を採用しているわけではないため、架空の「○○条件に合致」とは表示しません。</p>${horses}</div>
  </section>`;
}

function enhanceHtml(html: string, block: string): string {
  if (!block) return html;
  let out = html.replace(/<section class="prediction-reasons(?: [^"]*)?">[\s\S]*?<\/section>/, "");
  const css = `<style>
    .decision-evidence{margin:14px 0 18px;padding:16px;border:1px solid var(--line);border-radius:16px;background:var(--panel)}
    .decision-title{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:14px}.decision-title h2{margin:0;font-size:19px}.decision-title p{margin:4px 0 0;color:var(--muted);font-size:11px}.decision-title>span{font-size:10px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:4px 7px}
    .decision-section{padding:14px 0;border-top:1px solid var(--line)}.decision-section:first-of-type{border-top:0;padding-top:0}.decision-section h3{margin:0 0 9px;font-size:14px}.decision-section>p{margin:9px 0 0;color:var(--muted);font-size:11px;line-height:1.75}
    .decision-race-grid,.decision-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.decision-race-grid>div,.decision-metrics>div{display:grid;gap:3px;padding:9px 10px;border:1px solid var(--line);border-radius:10px;background:var(--panel2)}.decision-race-grid span,.decision-metrics span{font-size:10px;color:var(--muted)}.decision-race-grid b,.decision-metrics b{font-size:13px}
    .decision-chip-list{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}.decision-chip-list>span{display:inline-flex;padding:5px 8px;border:1px solid var(--line);border-radius:999px;background:var(--panel2);font-size:10px;font-weight:700}.race-condition-list>span{font-size:11px}
    .decision-ticket,.decision-horse{margin-top:9px;padding:11px;border:1px solid var(--line);border-radius:12px;background:var(--panel2)}.decision-ticket-head,.decision-horse-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.decision-ticket-head strong{font-size:14px}.decision-ticket-head span{font-size:10px;color:var(--muted);text-align:right}.decision-ticket p{margin:8px 0 0;color:var(--muted);font-size:10px;line-height:1.7}.decision-metrics{margin-top:8px;grid-template-columns:repeat(4,minmax(0,1fr))}
    .decision-horse-head>div{display:flex;align-items:center;gap:7px}.decision-horse-head span{font-size:10px;color:var(--muted)}.decision-horse-head strong{font-size:14px}.decision-horse-head>b{font-size:12px;color:var(--green);white-space:nowrap}.decision-note{margin-top:0!important}
    @media(max-width:760px){.decision-evidence{padding:13px}.decision-race-grid{grid-template-columns:1fr}.decision-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.decision-ticket-head,.decision-horse-head{display:grid}.decision-ticket-head span{text-align:left}.decision-horse-head>b{white-space:normal}}
  </style>`;
  out = out.replace("</head>", `${css}</head>`);
  const anchors = [
    `<div class="section-title"><h2>出走馬`,
    `<section class="card"><h2>出走馬`,
    `<section class="runner-table`,
    `</main>`,
  ];
  for (const anchor of anchors) {
    if (!out.includes(anchor)) continue;
    return out.replace(anchor, `${block}${anchor}`);
  }
  return `${out}${block}`;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    const path = new URL(request.url).pathname;
    if (!path.startsWith("/races/") || !response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
    try {
      const raceId = decodeURIComponent(path.slice("/races/".length));
      const block = await buildDecisionEvidence(env.DB, raceId);
      if (!block) return response;
      const headers = new Headers(response.headers);
      headers.delete("content-length");
      headers.set("cache-control", "no-store, max-age=0");
      headers.set("x-race-ui-version", "ten-year-completed-public-v22-decision-evidence");
      return new Response(enhanceHtml(await response.text(), block), { status: response.status, headers });
    } catch {
      return response;
    }
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
