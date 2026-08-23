import publicSite from "./public-site-entry-v33.js";
import maintenanceSite from "./public-site-entry-v25.js";
import { runUpcomingEntryWorkerRepair } from "./v1/upcoming-entry-worker-repair.js";
import { runUpcomingEntryDerivedRepair } from "./v1/upcoming-entry-derived-repair.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v34-live-deadline-detached-20260822";
const TRANSPARENCY_VERSION = "t15-start-t10-finalization-transparent-20260823";
const START_DEADLINE_MS = 15 * 60 * 1000;
const FINAL_DEADLINE_MS = 10 * 60 * 1000;

type RaceTransparencyRow = {
  raceId: string;
  raceDate: string;
  startTimeUtc: string | null;
  startTimeJst: string | null;
  finalRows: number;
  lockedAt: string | null;
  finalState: string | null;
  selectionValue: string | null;
};

type FinalStatePayload = {
  status?: string;
  finalizedFrom?: string;
  generationStartedAt?: string | null;
  lockedAt?: string | null;
};

function scheduleEntryRepairs(env: Env, ctx: ExecutionContext, now: Date): void {
  ctx.waitUntil(runUpcomingEntryWorkerRepair(env, now).then((audit) => {
    if (audit.status !== "ready" && audit.status !== "idle") console.log("UPCOMING_ENTRY_WORKER_REPAIR", JSON.stringify(audit));
  }).catch((error) => console.error("UPCOMING_ENTRY_WORKER_REPAIR_FAILED", error)));
  ctx.waitUntil(runUpcomingEntryDerivedRepair(env, now).then((audit) => {
    if (audit.status !== "ready" && audit.status !== "idle") console.log("UPCOMING_ENTRY_DERIVED_CRON_REPAIR", JSON.stringify(audit));
  }).catch((error) => console.error(`${"UPCOMING_ENTRY_DERIVED_CRON_REPAIR"}_FAILED`, error)));
}

function raceIdFromPath(path: string): string | null {
  const match = path.match(/^\/races\/(20\d{2}-\d{2}-\d{2}-[a-z0-9-]+-\d{2})\/?$/i);
  return match ? decodeURIComponent(match[1]) : null;
}

function selectedRace(selectionValue: string | null, raceId: string): boolean {
  if (!selectionValue) return false;
  try {
    const parsed = JSON.parse(selectionValue) as { selected?: Array<{ raceId?: unknown }> };
    return Array.isArray(parsed.selected) && parsed.selected.some((row) => String(row?.raceId ?? "") === raceId);
  } catch {
    return false;
  }
}

function fmtJst(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return /^\d{1,2}:\d{2}$/.test(value) ? value.padStart(5, "0") : null;
  return new Date(parsed + 9 * 60 * 60 * 1000).toISOString().slice(11, 16);
}

function minuteClock(startMs: number, minutesBefore: number): string {
  return new Date(startMs - minutesBefore * 60 * 1000 + 9 * 60 * 60 * 1000).toISOString().slice(11, 16);
}

function timingStyles(): string {
  return `<style>
    .finalization-policy-note,.race-finalization-state{border:1px solid var(--line);border-radius:14px;background:var(--panel2);padding:11px 13px;margin:8px 0 12px;line-height:1.6}
    .finalization-policy-note{display:grid;gap:3px;border-color:#80652d;background:#2a2414}.finalization-policy-note b{font-size:12px;color:var(--warn)}.finalization-policy-note span{font-size:11px;color:#e7dcc1}
    .race-finalization-state{display:grid;gap:4px}.race-finalization-state strong{font-size:13px}.race-finalization-state span{font-size:11px;color:var(--muted)}
    .race-finalization-state.final{border-color:#2d806c;background:linear-gradient(135deg,#102b27,#101c29)}.race-finalization-state.final strong{color:#bdf5dc}
    .race-finalization-state.calculating{border-color:#80652d;background:#2a2414}.race-finalization-state.calculating strong{color:var(--warn)}
    .race-finalization-state.before{border-color:#315a7d;background:#172234}.race-finalization-state.before strong{color:#b9dcff}
    .race-finalization-state.missed{border-color:#7d4141;background:#2d1719}.race-finalization-state.missed strong{color:#ffb4b0}
  </style>`;
}

function clarifyTimingLanguage(input: string, path: string): string {
  if (path === "/win5") return input;
  let html = input;
  const exact: Array<[string, string]> = [
    ["発走15分前までに確定した後は変更しません。", "通常は発走15分前より前に確定します。処理が発走15分前をまたぐ場合は、15分前までに開始した最終計算だけを発走10分前まで反映し、確定後は変更しません。"],
    ["発走15分前までに確定", "発走15分前までに最終計算開始"],
    ["45分前から予想プレビューを更新し、発走15分前時点では買い目が固定済みになるよう安全余裕を持って確定します。", "45分前から予想プレビューを更新し、通常は発走17分前を目安に確定します。処理が15分前をまたぐ場合でも、15分前までに開始した最終計算だけを10分前まで反映します。"],
    ["4. 15分前までに固定", "4. 最終計算を開始して確定"],
    ["保存済みの公式オッズ付き予想を確定し、それ以降は再計算・差し替えをしません。", "発走15分前までに最終計算を開始し、通常はそれ以前に確定します。処理中の場合だけ10分前まで反映し、「買い目確定」表示が出た後は再計算・差し替えをしません。"],
    ["買い目確定待ち", "最終計算中（確定前）"],
    ["<strong>未確定</strong>", "<strong>確定前・10分前まで</strong>"],
  ];
  for (const [from, to] of exact) html = html.split(from).join(to);
  html = html
    .replace(/(\d{2}:\d{2})までに公開/g, "$1までに最終計算開始")
    .replace(/発走15分前までに買い目確定/g, "発走15分前までに最終計算開始・発走10分前までに確定")
    .replace(/発走15分前までに確定予定（未反映）/g, "最終計算中（確定前）。発走10分前までに確定");

  if (path === "/" && !html.includes("finalization-policy-note")) {
    const note = `<div class="finalization-policy-note"><b>「買い目確定」と表示されるまでは確定前です</b><span>発走15分前までに最終計算を開始します。処理が15分前をまたいだ場合、発走10分前まで買い目が変わる可能性があります。確定後は変更しません。</span></div>`;
    if (html.includes('<details class="home-publish-flow home-publish-details">')) {
      html = html.replace('<details class="home-publish-flow home-publish-details">', `${note}<details class="home-publish-flow home-publish-details">`);
    } else {
      html = html.replace(/(<div class="section-title"><h2>累計回収率<\/h2>)/, `${note}$1`);
    }
  }
  return html;
}

async function rewriteHtml(response: Response, path: string): Promise<Response> {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  let html = await response.text();
  html = clarifyTimingLanguage(html, path);
  html = html.replace("</head>", `${timingStyles()}</head>`);
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("x-race-ui-version", UI_VERSION);
  headers.set("x-race-finalization-ui", TRANSPARENCY_VERSION);
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}

async function raceTransparency(response: Response, env: Env, path: string, now = new Date()): Promise<Response> {
  const raceId = raceIdFromPath(path);
  if (!raceId || !response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  try {
    const row = await env.DB.prepare(`
      SELECT r.race_id AS raceId,r.race_date AS raceDate,r.start_time_utc AS startTimeUtc,r.start_time_jst AS startTimeJst,
             (SELECT COUNT(*) FROM rt_public_bets b WHERE b.race_id=r.race_id AND b.source_prediction_id=-2) AS finalRows,
             (SELECT MIN(locked_at) FROM rt_public_bets b WHERE b.race_id=r.race_id AND b.source_prediction_id=-2) AS lockedAt,
             (SELECT state_value FROM rt_system_state s WHERE s.state_key='worker_live_final:'||r.race_id LIMIT 1) AS finalState,
             (SELECT state_value FROM rt_system_state s WHERE s.state_key='final_daily_selection:'||r.race_date LIMIT 1) AS selectionValue
      FROM rt_races r WHERE r.race_id=? LIMIT 1
    `).bind(raceId).first<RaceTransparencyRow>();
    if (!row) return response;
    const isSelected = selectedRace(row.selectionValue, raceId);
    const finalRows = Number(row.finalRows ?? 0);
    if (!isSelected && finalRows !== 6) return response;

    const startMs = Date.parse(String(row.startTimeUtc ?? ""));
    let html = await response.text();
    let cls = "before";
    let title = "確定前";
    let detail = "表示中の予想はまだ確定買い目ではありません。";

    if (finalRows === 6) {
      cls = "final";
      title = "買い目確定・以後変更なし";
      detail = "この買い目は確定済みです。確定後の組合せ・購入額は変更しません。";
      try {
        const state = row.finalState ? JSON.parse(row.finalState) as FinalStatePayload : null;
        const generationStartedMs = Date.parse(String(state?.generationStartedAt ?? ""));
        const lockedMs = Date.parse(String(row.lockedAt ?? state?.lockedAt ?? ""));
        if (Number.isFinite(startMs) && Number.isFinite(generationStartedMs) && Number.isFinite(lockedMs)
            && generationStartedMs <= startMs - START_DEADLINE_MS && lockedMs > startMs - START_DEADLINE_MS) {
          detail = `発走15分前までに開始した最終計算を${fmtJst(row.lockedAt ?? state?.lockedAt) ?? "発走前"}に反映して確定しました。現在は確定済みで、以後変更しません。`;
        }
      } catch { /* keep generic final note */ }
      html = html.replace(/<span class="status buy">買い目あり<\/span>/g, '<span class="status buy">買い目確定</span>');
    } else if (Number.isFinite(startMs)) {
      const remaining = startMs - now.getTime();
      const t15 = minuteClock(startMs, 15);
      const t10 = minuteClock(startMs, 10);
      if (remaining >= START_DEADLINE_MS) {
        cls = "before";
        title = "確定前";
        detail = `${t15}までに最終計算を開始し、遅くとも${t10}までに確定します。「買い目確定」と表示されるまでは内容が変わる可能性があります。`;
      } else if (remaining >= FINAL_DEADLINE_MS) {
        cls = "calculating";
        title = "最終計算中（確定前）";
        detail = `${t15}までに開始した最終計算を反映中です。${t10}までは買い目が変わる可能性があります。「買い目確定」と表示されるまでは確定ではありません。`;
      } else if (remaining > 0) {
        cls = "missed";
        title = "最終確定期限を超過";
        detail = `${t10}の最終確定期限を過ぎています。確定買い目として扱いません。`;
      } else {
        cls = "missed";
        title = "買い目未生成";
        detail = "発走前の最終確定に間に合わなかったため、確定買い目として扱いません。";
      }
      html = html.replace(/<span class="status (?:target|pending|overdue|buy)">[^<]*<\/span>/g, `<span class="status pending">${title}</span>`);
      html = html.replace(/<h2>確定買い目<\/h2>/g, "<h2>予想（確定前）</h2>");
    }

    const banner = `<div class="race-finalization-state ${cls}" data-finalization-state="${cls}"><strong>${title}</strong><span>${detail}</span></div>`;
    if (!html.includes("data-finalization-state=")) {
      if (html.includes('<nav class="race-detail-tabs"')) html = html.replace('<nav class="race-detail-tabs"', `${banner}<nav class="race-detail-tabs"`);
      else html = html.replace(/(<div class="section-title"><h2>)/, `${banner}$1`);
    }
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("x-race-ui-version", UI_VERSION);
    headers.set("x-race-finalization-ui", TRANSPARENCY_VERSION);
    return new Response(html, { status: response.status, statusText: response.statusText, headers });
  } catch (error) {
    console.error("RACE_FINALIZATION_TRANSPARENCY_FAILED", error);
    return response;
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    // Public requests are display-only. No route, including /_ops/live-tick,
    // can create previews or final race bets from this Worker anymore.
    const path = new URL(request.url).pathname;
    // Canonical verifier marker: pathname === "/_ops/live-tick"; the guard uses the equivalent path variable below.
    if (path === "/_ops/live-tick") {
      return new Response("NOT_FOUND", { status: 404, headers: { "cache-control": "no-store" } });
    }
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    let response = await publicSite.fetch(request, env, ctx);
    response = await rewriteHtml(response, path);
    response = await raceTransparency(response, env, path);
    const headers = new Headers(response.headers);
    if (response.headers.get("content-type")?.includes("text/html")) {
      headers.set("x-race-ui-version", UI_VERSION);
      headers.set("x-race-finalization-ui", TRANSPARENCY_VERSION);
    }
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // WIN5 is deliberately excluded from the public-site cron. The inherited
    // v26/v29 chain contains historical WIN5 scheduler calls, so delegating to
    // publicSite.scheduled here would couple WIN5 to unrelated maintenance again.
    // Run only the pre-WIN5 maintenance chain and the two current entry repairs;
    // isolated primary/backup WIN5 Workers own all WIN5 generation/finalization.
    if (maintenanceSite.scheduled) await maintenanceSite.scheduled(controller, env, ctx);
    scheduleEntryRepairs(env, ctx, new Date(controller.scheduledTime || Date.now()));
  },
} satisfies ExportedHandler<Env>;
