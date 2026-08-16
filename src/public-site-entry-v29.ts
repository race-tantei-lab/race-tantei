import publicSite from "./public-site-entry-v28.js";
import { freezeCompletedWorkerSelectionIfNeeded } from "./v1/completed-selection-runtime.js";
import { runCompletedWorkerDeadlineGuard } from "./v1/completed-worker-deadline-guard.js";
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
    if (final.oddsMode !== "probability_fallback") return response;
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

async function runDeadlineGuard(env: Env, label: string, strict: boolean): Promise<void> {
  const now = new Date();
  try {
    // If the canonical daily selection was not persisted by an earlier cron,
    // reconstruct it from the same canonical D1 selection state before trying
    // to finalize races. This is DB-only and never changes the selection rule.
    const selection = await freezeCompletedWorkerSelectionIfNeeded(env, now);
    console.log(`${label}_SELECTION`, JSON.stringify(selection));
  } catch (error) {
    console.error(`${label}_SELECTION_RECOVERY_FAILED`, error);
  }

  try {
    const audit = await runCompletedWorkerDeadlineGuard(env, now);
    console.log(label, JSON.stringify(audit));
    const due = new Set(audit.dueRaceIds);
    const locked = new Set(audit.lockedRaceIds);
    const unresolved = [...due].filter((raceId) => !locked.has(raceId));
    if (audit.errors.length || unresolved.length) {
      throw new Error(`${label}_DUE_RACE_UNRESOLVED:${unresolved.join(",")}:errors=${JSON.stringify(audit.errors)}`);
    }
  } catch (error) {
    console.error(`${label}_FAILED`, error);
    if (strict) throw error;
  }
}

async function runWin5DeadlineGuard(env: Env, label: string, strict: boolean): Promise<void> {
  const now = new Date();
  try {
    const state = await runCompletedWin5Scheduled(env, now);
    console.log(label, JSON.stringify({ status: state.status, date: state.date, lockedAt: state.snapshot?.lockedAt ?? null, generatedAt: state.snapshot?.generatedAt ?? null }));
    if (state.targets.length === 5) {
      const firstStartMs = Math.min(...state.targets.map((row) => Date.parse(row.startTimeUtc)));
      const deadlineMs = firstStartMs - 15 * 60 * 1000;
      if (Number.isFinite(firstStartMs) && now.getTime() >= deadlineMs && now.getTime() < firstStartMs && state.status !== "final") {
        throw new Error(`${label}_FINAL_MISSING_AT_DEADLINE:${state.date}`);
      }
    }
  } catch (error) {
    console.error(`${label}_FAILED`, error);
    if (strict) throw error;
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    return emergencyFallbackNotice(response, env, new URL(request.url).pathname);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // First pass is deliberately before all external HTTP. Failure here does
    // not block the normal acquisition chain because the second pass retries.
    await runDeadlineGuard(env, "COMPLETED_WORKER_DEADLINE_GUARD_BEFORE", false);
    await runWin5DeadlineGuard(env, "WIN5_DEADLINE_GUARD_BEFORE", false);

    let baseFailed = false;
    try {
      if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
    } catch (error) {
      baseFailed = true;
      console.error("BASE_SCHEDULED_AFTER_DEADLINE_GUARD_FAILED", error);
    }

    // Second pass is the hard post-condition. A cron invocation may not report
    // success while a selected race currently inside the 15-minute pre-start
    // window remains unresolved. This makes missing finalization observable on
    // the same invocation instead of silently looking healthy.
    let finalGuardError: unknown = null;
    try {
      await runDeadlineGuard(env, "COMPLETED_WORKER_DEADLINE_GUARD_AFTER", true);
    } catch (error) {
      finalGuardError = error;
    }

    let win5GuardError: unknown = null;
    try {
      await runWin5DeadlineGuard(env, "WIN5_DEADLINE_GUARD_AFTER", true);
    } catch (error) {
      win5GuardError = error;
    }

    if (finalGuardError) throw finalGuardError;
    if (win5GuardError) throw win5GuardError;
  },
} satisfies ExportedHandler<Env>;
