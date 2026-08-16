import publicSite from "./public-site-entry-v28.js";
import { runCompletedWorkerEmergencyLock } from "./v1/completed-worker-emergency-lock.js";
import { runCompletedWin5Scheduled } from "./v1/completed-win5.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v29-guaranteed-t15-fallback-20260816";

async function emergencyFallbackNotice(response: Response, env: Env, path: string): Promise<Response> {
  if (!path.startsWith("/races/") || !response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  const raceId = decodeURIComponent(path.slice("/races/".length));
  try {
    const row = await env.DB.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
      .bind(`worker_live_final:${raceId}`).first<{ value: string }>();
    if (!row?.value) return response;
    const final = JSON.parse(row.value) as { finalizedFrom?: string; oddsMode?: string };
    if (final.finalizedFrom !== "probability_fallback_emergency" && final.oddsMode !== "probability_fallback") return response;
    let html = await response.text();
    html = html
      .replace(/<div><span>JRA公式オッズ<\/span><b>1\.0倍<\/b><\/div>/g, '<div><span>オッズ</span><b>取得失敗・確率優先</b></div>')
      .replace(/<div><span>確率 × オッズ<\/span><b>[^<]*<\/b><\/div>/g, '<div><span>非常用選定</span><b>モデル確率優先</b></div>')
      .replace(/<p><b>選ばれた理由：<\/b>[\s\S]*?<\/p>/g, '<p><b>選ばれた理由：</b>JRA公式オッズの取得に失敗したため、買い目未生成を防ぐ非常用経路で確定しました。利用可能なモデル確率と直近学習を優先して2券種を選定しています。オッズは捏造せず表示しません。</p>');
    if (!html.includes("emergency-lock-notice")) {
      const notice = '<div class="notice emergency-lock-notice" style="margin:0 0 12px;padding:11px 13px;border:1px solid #80652d;border-radius:12px;background:#2a2414;color:#f2d48d;font-size:11px;line-height:1.6"><b>非常用T-15確定</b>　JRA公式オッズ取得失敗のため、モデル確率優先のフォールバックで買い目を固定しました。成績集計には通常どおり含めます。</div>';
      html = html.replace(/<main\b[^>]*>/, (match) => `${match}${notice}`);
    }
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("x-race-ui-version", UI_VERSION);
    return new Response(html, { status: response.status, statusText: response.statusText, headers });
  } catch {
    return response;
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    return emergencyFallbackNotice(response, env, new URL(request.url).pathname);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // Hard T-15 deadline guard must be the first scheduled operation. It does
    // zero external network I/O: a recent validated JRA preview is promoted
    // immediately, otherwise the probability-only emergency writer is used.
    // This prevents unrelated JRA latency from pushing a lock past T-15.
    try {
      const audit = await runCompletedWorkerEmergencyLock(env, new Date());
      console.log("COMPLETED_WORKER_DEADLINE_GUARD", JSON.stringify(audit));
    } catch (error) {
      console.error("COMPLETED_WORKER_DEADLINE_GUARD_FAILED", error);
    }

    let baseFailed = false;
    try {
      if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
    } catch (error) {
      baseFailed = true;
      console.error("BASE_SCHEDULED_AFTER_DEADLINE_GUARD_FAILED", error);
    }

    // A normal-race SLA throw in v21 can prevent v26 from reaching WIN5.
    // Recover that independent scheduled job when the delegated chain failed.
    if (baseFailed) {
      try {
        await runCompletedWin5Scheduled(env, new Date());
      } catch (error) {
        console.error("WIN5_SCHEDULED_RECOVERY_FAILED", error);
      }
    }
  },
} satisfies ExportedHandler<Env>;
