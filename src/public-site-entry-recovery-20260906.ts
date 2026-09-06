import publicSite from "./public-site-entry-v37.js";
import { loadConfiguredOfficialRace, runConfiguredEntrySeedWriteOnly } from "./v1/configured-entry-seed-write-only.js";
import { runUpcomingCalendarRepair } from "./v1/upcoming-calendar-repair.js";
import { runUpcomingEntryWorkerRepair } from "./v1/upcoming-entry-worker-repair.js";
import { runUpcomingEntryDerivedRepair } from "./v1/upcoming-entry-derived-repair.js";
import type { Env, RaceBundle } from "./v1/types.js";

const RECOVERY_PATH = "/_ops/entry-seed-sync-20260906-7f4c9d2a";
const HOME_PATHS = new Set(["/", "/index.html", "/races", "/races/"]);

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch] ?? ch));
}

function jstToday(): string {
  return new Date(Date.now() + (9 * 60 * 60 * 1000)).toISOString().slice(0, 10);
}

async function retargetFallbackHome(response: Response): Promise<Response> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("text/html")) return response;

  const html = await response.text();
  const today = jstToday();
  if (!html.includes(`"raceDate":"${today}"`)) {
    return new Response(html, { status: response.status, statusText: response.statusText, headers: response.headers });
  }

  const monthDay = `${Number(today.slice(5, 7))}/${Number(today.slice(8, 10))}`;
  const retargeted = html
    .replace(/const today="\d{4}-\d{2}-\d{2}";/, `const today="${today}";`)
    .replace(/本日の集計（\d{1,2}\/\d{1,2}）/, `本日の集計（${monthDay}）`);

  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-race-recovery-home-date", today);
  return new Response(retargeted, { status: response.status, statusText: response.statusText, headers });
}

function runnerPanel(bundle: RaceBundle): string {
  const rows = [...bundle.runners]
    .sort((a, b) => Number(a.horseNo) - Number(b.horseNo))
    .map((runner) => {
      const status = runner.runnerStatus === "active" ? "" : ` <span class="muted">(${esc(runner.runnerStatus)})</span>`;
      const odds = runner.winOdds == null ? "-" : Number(runner.winOdds).toFixed(1);
      const popularity = runner.popularity == null ? "-" : `${Number(runner.popularity)}番人気`;
      return `<tr><td><span class="horse-no">${Number(runner.horseNo)}</span></td><td><b>${esc(runner.horseName)}</b>${status}</td><td>${esc(runner.sexAge || "-")}</td><td>${esc(runner.jockey || "-")}</td><td>${runner.assignedWeight == null ? "-" : `${Number(runner.assignedWeight).toFixed(1)}kg`}</td><td>${esc(runner.trainer || "-")}</td><td>${odds}</td><td>${popularity}</td></tr>`;
    }).join("");
  return `<section class="panel" id="official-runners"><h2>出走馬</h2><div class="runner-table"><table><thead><tr><th>馬番</th><th>馬名</th><th>性齢</th><th>騎手</th><th>斤量</th><th>厩舎</th><th>単勝</th><th>人気</th></tr></thead><tbody>${rows}</tbody></table></div><p class="locked-note">JRA公式出馬表の現在情報</p></section>`;
}

async function enrichRaceDetail(request: Request, env: Env, ctx: ExecutionContext, raceId: string): Promise<Response> {
  if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
  const [baseResult, official] = await Promise.all([
    publicSite.fetch(request, env, ctx).catch(() => null),
    loadConfiguredOfficialRace(env, raceId).catch(() => null),
  ]);
  if (!official) return baseResult ?? new Response("NOT_FOUND", { status: 404 });
  const base = baseResult;
  if (!base || !base.headers.get("content-type")?.includes("text/html")) return base ?? new Response("NOT_FOUND", { status: 404 });
  let html = await base.text();
  if (!html.includes('class="runner-table"') && !html.includes('id="official-runners"')) {
    html = html.replace("</main>", `${runnerPanel(official)}</main>`);
  }
  const headers = new Headers(base.headers);
  headers.delete("content-length");
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-race-official-runners", String(official.runners.length));
  return new Response(html, { status: 200, headers });
}

async function runBoundedPublicMaintenance(env: Env, now: Date): Promise<void> {
  // Deliberately bypass the legacy public scheduler: v37 core still contains
  // per-cron schema-index creation. Persistent indexes are deploy-time schema.
  // These three bounded repairs are the normal automatic maintenance duties.
  const errors: string[] = [];
  try { await runUpcomingCalendarRepair(env, now); } catch (error) { errors.push(`calendar:${String(error)}`); }
  try { await runUpcomingEntryWorkerRepair(env, now); } catch (error) { errors.push(`entry:${String(error)}`); }
  try { await runUpcomingEntryDerivedRepair(env, now); } catch (error) { errors.push(`derived:${String(error)}`); }
  if (errors.length) console.error("PUBLIC_MAINTENANCE_PARTIAL", JSON.stringify(errors));
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === RECOVERY_PATH) {
      const audit = await runConfiguredEntrySeedWriteOnly(env, "2026-09-06");
      return Response.json(audit, {
        status: audit.status === "failed" ? 503 : 200,
        headers: { "cache-control": "no-store, max-age=0" },
      });
    }
    if (url.pathname === RECOVERY_PATH) return new Response("NOT_FOUND", { status: 404 });
    const match = url.pathname.match(/^\/races\/(2026-09-06-[a-z0-9-]+-\d{2})\/?$/i);
    if (request.method === "GET" && match) return enrichRaceDetail(request, env, ctx, match[1]);
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    if (request.method === "GET" && HOME_PATHS.has(url.pathname)) return retargetFallbackHome(response);
    return response;
  },
  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const now = Number.isFinite(controller.scheduledTime) ? new Date(controller.scheduledTime) : new Date();
    await runBoundedPublicMaintenance(env, now);
  },
} satisfies ExportedHandler<Env>;
