import publicSite from "./public-site-entry-v19.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v20-refund-aware-20260815";

type BetRow = {
  raceId: string;
  betType: string;
  combination: string;
  stakeYen: number;
  returnYen: number | null;
  settlementStatus: string;
  refundsJson: string | null;
};

type SettlementView = {
  hasBets: boolean;
  allSettled: boolean;
  genuineHit: boolean;
  hasRefund: boolean;
  refundTickets: string[];
};

function horseNos(combination: string): number[] {
  return (combination.match(/\d{1,2}/g) ?? []).map(Number).filter((value) => value >= 1 && value <= 18);
}

function refundSet(raw: string | null): Set<number> {
  try {
    const parsed = JSON.parse(String(raw ?? "[]"));
    return new Set(Array.isArray(parsed) ? parsed.map(Number).filter((value) => Number.isInteger(value)) : []);
  } catch {
    return new Set();
  }
}

function classify(rows: BetRow[]): SettlementView {
  if (!rows.length) return { hasBets: false, allSettled: false, genuineHit: false, hasRefund: false, refundTickets: [] };
  const refunded = new Set<string>();
  let genuineHit = false;
  let settled = 0;
  for (const row of rows) {
    const refunds = refundSet(row.refundsJson);
    const isRefund = horseNos(row.combination).some((horseNo) => refunds.has(horseNo));
    if (isRefund) refunded.add(`${row.betType} ${row.combination}`);
    if (row.settlementStatus === "settled") {
      settled += 1;
      if (!isRefund && Number(row.returnYen ?? 0) > 0) genuineHit = true;
    }
  }
  return {
    hasBets: true,
    allSettled: settled === rows.length,
    genuineHit,
    hasRefund: refunded.size > 0,
    refundTickets: [...refunded]
  };
}

async function settlementViews(db: D1Database, raceIds: string[]): Promise<Map<string, SettlementView>> {
  const out = new Map<string, SettlementView>();
  if (!raceIds.length) return out;
  const placeholders = raceIds.map(() => "?").join(",");
  const rows = await db.prepare(`
    SELECT b.race_id AS raceId,b.bet_type AS betType,b.combination,b.stake_yen AS stakeYen,
           b.return_yen AS returnYen,b.settlement_status AS settlementStatus,
           r.refund_horse_nos_json AS refundsJson
    FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
    WHERE b.race_id IN (${placeholders})
    ORDER BY b.race_id,b.id
  `).bind(...raceIds).all<BetRow>();
  const grouped = new Map<string, BetRow[]>();
  for (const row of rows.results) {
    const list = grouped.get(row.raceId) ?? [];
    list.push({ ...row, stakeYen: Number(row.stakeYen), returnYen: row.returnYen === null ? null : Number(row.returnYen) });
    grouped.set(row.raceId, list);
  }
  for (const raceId of raceIds) out.set(raceId, classify(grouped.get(raceId) ?? []));
  return out;
}

function publicCode(view: SettlementView): { code: string; label: string } | null {
  if (!view.hasBets || !view.allSettled) return null;
  if (view.genuineHit) return { code: "hit", label: "的中" };
  if (view.hasRefund) return { code: "refund", label: "返還" };
  return { code: "miss", label: "不的中" };
}

async function fixDayApi(db: D1Database, response: Response): Promise<Response> {
  if (!response.ok) return response;
  try {
    const data = await response.clone().json() as { races?: Array<Record<string, any>>; [key: string]: any };
    const races = Array.isArray(data.races) ? data.races : [];
    const ids = races.map((race) => String(race.raceId ?? "")).filter(Boolean);
    const views = await settlementViews(db, ids);
    data.races = races.map((race) => {
      const view = views.get(String(race.raceId ?? ""));
      const state = view ? publicCode(view) : null;
      if (!state) return race;
      return { ...race, publicState: { ...(race.publicState ?? {}), ...state, deadline: null } };
    });
    const headers = new Headers(response.headers);
    headers.set("content-type", "application/json; charset=utf-8");
    headers.delete("content-length");
    return new Response(JSON.stringify(data), { status: response.status, headers });
  } catch {
    return response;
  }
}

async function fixRaceDetail(db: D1Database, path: string, response: Response): Promise<Response> {
  if (!path.startsWith("/races/") || !response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  try {
    const raceId = decodeURIComponent(path.slice("/races/".length));
    const view = (await settlementViews(db, [raceId])).get(raceId);
    if (!view?.hasBets) return response;
    const state = publicCode(view);
    let html = await response.text();
    if (state) {
      html = html.replace(/<span class="status (?:buy|hit|miss|refund)">[^<]*<\/span>/g, `<span class="status ${state.code}">${state.label}</span>`);
    }
    if (view.hasRefund && !html.includes("refund-settlement-note")) {
      const tickets = view.refundTickets.map((ticket) => `<b>${ticket}</b>`).join("、");
      const note = `<div class="notice refund-settlement-note">返還対象：${tickets}。除外・取消を含む買い目は購入額を全額返還として払戻に反映します。</div>`;
      html = html.replace(/(<div class="section-title"><h2>(?:確定買い目|買い目)<\/h2><span class="status [^"]+">[^<]*<\/span><\/div>)/, `$1${note}`);
    }
    const css = `<style>.status.refund{background:#243b52;color:#cce6ff;border:1px solid #466a8f}.refund-settlement-note{font-size:12px;line-height:1.6}</style>`;
    html = html.replace("</head>", `${css}<meta name="race-tantei-ui" content="${UI_VERSION}"></head>`);
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    return new Response(html, { status: response.status, headers });
  } catch {
    return response;
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const path = new URL(request.url).pathname;
    let response = await publicSite.fetch(request, env, ctx);
    if (path === "/api/public/day") response = await fixDayApi(env.DB, response);
    response = await fixRaceDetail(env.DB, path, response);
    return response;
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
