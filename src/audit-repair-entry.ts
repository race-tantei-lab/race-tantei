import base from "./entry.js";
import { renderCoursePerformance } from "./v1/course-ui.js";
import { ensureSchema } from "./v1/db.js";
import { getDisplayRaceDetail } from "./v1/display-detail.js";
import { getHistoricalAuditState } from "./v1/historical-audit-state.js";
import { getAuditedPhaseDDashboard } from "./v1/phase-d-dashboard-audited.js";
import { historyDateFromPath, renderAuditedRaceArchiveDate } from "./v1/race-archive-audited.js";
import { renderPhaseCRaceDetail } from "./v1/race-detail-phase-c.js";
import {
  getCorrectedThreeMonthPerformance,
  getLiveCourseMetricsOutsideThreeMonthScope,
  getLiveMonthlyMetricsOutsideThreeMonthScope
} from "./v1/three-month-evaluation.js";
import {
  runThreeMonthFixedStakeRepair,
  type ThreeMonthFixedStakeRepairResult
} from "./v1/three-month-repair.js";
import { isThreeMonthTuningDate } from "./v1/three-month-scope.js";
import type { Env } from "./v1/types.js";

let repairRunning: Promise<ThreeMonthFixedStakeRepairResult> | null = null;

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-content-type-options": "nosniff",
      "x-robots-tag": "noindex, nofollow"
    }
  });
}

function page(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-content-type-options": "nosniff",
      "x-race-ui-version": "phase-d-audited"
    }
  });
}

function runRepair(env: Env, maximumVenues = 2): Promise<ThreeMonthFixedStakeRepairResult> {
  if (repairRunning) return repairRunning;
  repairRunning = runThreeMonthFixedStakeRepair(env.DB, env.MODEL_VERSION, maximumVenues)
    .then((result) => {
      console.log("AUDITED_THREE_MONTH_REPAIR", JSON.stringify({
        complete: result.complete,
        repairedVenues: result.repairedVenues,
        addedRaces: result.addedRaces,
        replacedRaces: result.replacedRaces,
        removedRaces: result.removedRaces,
        findings: result.audit.findings
      }));
      return result;
    })
    .catch((error) => {
      console.error("AUDITED_THREE_MONTH_REPAIR_FAILED", error);
      throw error;
    })
    .finally(() => {
      repairRunning = null;
    });
  return repairRunning;
}

function findingValue(findings: Record<string, unknown>, key: string): number {
  return Number(findings[key] ?? 0);
}

function repairStatusMarkup(findings: Record<string, unknown>): string {
  const fixed = findingValue(findings, "stakeViolationRaceCourses");
  const pending = findingValue(findings, "pendingRaceCourses");
  const quotas = findingValue(findings, "venueQuotaViolations");
  const details = findingValue(findings, "individualDetailMismatchRaces");
  const selections = findingValue(findings, "courseSelectionMismatchRaces");
  const missing = findingValue(findings, "missingModelRaces");
  return `<section id="audit-live-repair" style="margin:14px 0 22px;padding:16px;border:1px solid #80652d;border-radius:16px;background:#241f13;color:#f3e4bd">
    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px"><b style="font-size:17px">修復処理を実行中</b><span id="audit-repair-round" style="color:#b9aa82;font-size:12px">開始中</span></div>
    <p id="audit-repair-message" style="margin:9px 0 12px;color:#d8c99f;line-height:1.7">画面を開いている間に、会場単位で固定購入額へ再構築しています。監査合格後に自動で正しい成績へ切り替わります。</p>
    <div style="height:8px;border-radius:999px;background:#111923;overflow:hidden"><div id="audit-repair-bar" style="width:8%;height:100%;background:#4fd1a1;transition:width .25s ease"></div></div>
    <div id="audit-repair-findings" style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:13px;font-size:12px">
      <span>固定額違反 <b data-finding="stakeViolationRaceCourses">${fixed}</b></span>
      <span>未精算 <b data-finding="pendingRaceCourses">${pending}</b></span>
      <span>会場5R違反 <b data-finding="venueQuotaViolations">${quotas}</b></span>
      <span>個別表示不一致 <b data-finding="individualDetailMismatchRaces">${details}</b></span>
      <span>コース選出不一致 <b data-finding="courseSelectionMismatchRaces">${selections}</b></span>
      <span>予想未生成 <b data-finding="missingModelRaces">${missing}</b></span>
    </div>
  </section>`;
}

function injectInteractiveRepair(html: string, findings: Record<string, unknown>): string {
  const status = repairStatusMarkup(findings);
  const auditSection = /<section style="margin:20px 0;padding:18px;border:1px solid #c76767[\s\S]*?<\/section>/;
  let next = auditSection.test(html)
    ? html.replace(auditSection, (match) => `${match}${status}`)
    : html.replace(/<main\b[^>]*>/, (match) => `${match}${status}`);
  const script = `<script>(()=>{
    const endpoint='/api/audit/three-months/repair-public';
    const keys=['stakeViolationRaceCourses','pendingRaceCourses','venueQuotaViolations','individualDetailMismatchRaces','courseSelectionMismatchRaces','missingModelRaces'];
    let round=0;
    let stopped=false;
    const text=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value};
    const update=(data)=>{
      const findings=(data&&data.audit&&data.audit.findings)||{};
      keys.forEach(key=>document.querySelectorAll('[data-finding="'+key+'"]').forEach(el=>{el.textContent=String(Number(findings[key]||0))}));
      const repaired=Number(data&&data.repairedVenues||0);
      const changed=Number(data&&data.addedRaces||0)+Number(data&&data.replacedRaces||0)+Number(data&&data.removedRaces||0);
      text('audit-repair-round','処理 '+round+'回目');
      text('audit-repair-message','今回 '+repaired+'会場を確認し、'+changed+'レースを再構築しました。監査が全項目0になるまで続行します。');
      const total=keys.reduce((sum,key)=>sum+Number(findings[key]||0),0);
      const bar=document.getElementById('audit-repair-bar');
      if(bar)bar.style.width=(total===0?'100%':String(Math.max(10,Math.min(92,92-Math.log10(total+1)*18)))+'%');
    };
    const step=async()=>{
      if(stopped)return;
      round+=1;
      try{
        const response=await fetch(endpoint,{method:'POST',headers:{'accept':'application/json'},cache:'no-store'});
        if(!response.ok)throw new Error('HTTP '+response.status);
        const data=await response.json();
        update(data);
        if(data.complete===true){
          stopped=true;
          text('audit-repair-round','監査合格');
          text('audit-repair-message','固定購入額・未精算・会場5R・個別表示の全監査に合格しました。正しい成績へ切り替えます。');
          setTimeout(()=>location.replace('/?audit=complete'),700);
          return;
        }
        setTimeout(step,900);
      }catch(error){
        text('audit-repair-round','再試行中');
        text('audit-repair-message','修復処理の応答を待っています。画面を閉じずにこのままお待ちください。');
        setTimeout(step,2500);
      }
    };
    step();
  })();</script>`;
  next = next.replace("</body>", `${script}</body>`);
  return next;
}

function addMethodologyNotice(html: string): string {
  const notice = `<section style="margin:0 0 16px;padding:14px;border:1px solid #315f55;border-radius:14px;background:#10231f;color:#d9f3ec;line-height:1.7"><b>監査済み成績</b><br>主要回収率は2026年5月2日〜7月26日の固定購入額検証です。モデル調整に使った8月1日・2日は累計から除外しています。個別レースと累計は同じ予想ID・同じ買い目を参照します。</section>`;
  const corrected = html
    .replace("過去3ヶ月と本番公開分の合算", "主要検証期間と本番公開分の合算")
    .replace("過去3ヶ月分はJRA結果ページに残る最終人気から市場確率を固定式で復元しています。", "過去検証分はJRA結果ページに残る最終人気から市場確率を固定式で復元しています。");
  return corrected.replace(/<main\b[^>]*>/, (match) => `${match}${notice}`);
}

function addTuningNotice(html: string): string {
  const notice = `<div style="margin:12px 0;padding:11px;border:1px solid #80652d;border-radius:12px;background:#2a2414;color:#f2d48d;line-height:1.6"><b>調整期間</b>　このレースはモデル調整に使用した8月1日・2日のデータです。買い目は表示しますが、主要な累計回収率には含めません。</div>`;
  return html.replace(/<main\b[^>]*>/, (match) => `${match}${notice}`);
}

async function correctedPerformancePayload(env: Env): Promise<Record<string, unknown>> {
  const [performance, live] = await Promise.all([
    getCorrectedThreeMonthPerformance(env.DB),
    getLiveCourseMetricsOutsideThreeMonthScope(env.DB, env.MODEL_VERSION)
  ]);
  return {
    auditFrozen: false,
    live,
    historical: performance.evaluation.combined,
    threeMonth: {
      evaluation: performance.evaluation,
      tuningReference: performance.tuning,
      fullScope: {
        startDate: performance.full.startDate,
        endDate: performance.full.endDate,
        totalRaces: performance.full.totalRaces,
        processedRaces: performance.full.processedRaces,
        complete: performance.full.complete
      }
    }
  };
}

async function handledAfterAudit(
  request: Request,
  env: Env,
  ctx: ExecutionContext
): Promise<Response | null> {
  const url = new URL(request.url);
  const pathname = url.pathname;

  if (pathname === "/api/audit/three-months/public-status") {
    const state = await getHistoricalAuditState(env.DB, env.MODEL_VERSION);
    return json({ auditFrozen: !state.valid, state });
  }
  if (pathname === "/api/history/three-months/status") {
    const performance = await getCorrectedThreeMonthPerformance(env.DB);
    return json({
      auditFrozen: false,
      evaluation: performance.evaluation,
      tuningReference: performance.tuning,
      fullScope: {
        startDate: performance.full.startDate,
        endDate: performance.full.endDate,
        totalRaces: performance.full.totalRaces,
        processedRaces: performance.full.processedRaces,
        complete: performance.full.complete
      }
    });
  }
  if (pathname === "/api/performance/three-months/read-only") {
    const performance = await getCorrectedThreeMonthPerformance(env.DB);
    return json({
      auditFrozen: false,
      evaluation: performance.evaluation,
      tuningReference: performance.tuning,
      fullScope: performance.full
    });
  }
  if (pathname === "/api/performance/courses" || pathname === "/api/performance/courses/read-only") {
    return json(await correctedPerformancePayload(env));
  }
  if (pathname === "/") {
    return page(await getAuditedPhaseDDashboard(env.DB, env.MODEL_VERSION, false));
  }
  const historyDate = historyDateFromPath(pathname);
  if (historyDate) {
    const body = await renderAuditedRaceArchiveDate(env.DB, historyDate, env.MODEL_VERSION, false);
    if (!body) return page("指定された開催日のレースが見つかりません。", 404);
    return page(isThreeMonthTuningDate(historyDate) ? addTuningNotice(body) : body);
  }
  if (pathname.startsWith("/races/")) {
    const raceId = decodeURIComponent(pathname.slice("/races/".length));
    const detail = await getDisplayRaceDetail(env.DB, raceId, env.MODEL_VERSION);
    if (!detail) return page("レースが見つかりません。", 404);
    const body = renderPhaseCRaceDetail(detail);
    return page(isThreeMonthTuningDate(detail.race.raceDate) ? addTuningNotice(body) : body);
  }
  if (pathname === "/performance") {
    const [performance, live, liveMonthly] = await Promise.all([
      getCorrectedThreeMonthPerformance(env.DB),
      getLiveCourseMetricsOutsideThreeMonthScope(env.DB, env.MODEL_VERSION),
      getLiveMonthlyMetricsOutsideThreeMonthScope(env.DB, env.MODEL_VERSION)
    ]);
    return page(addMethodologyNotice(renderCoursePerformance(
      live,
      liveMonthly,
      performance.evaluation.combined,
      performance.evaluation.monthly,
      {
        startDate: performance.evaluation.startDate,
        endDate: performance.evaluation.endDate,
        complete: performance.evaluation.complete,
        totalRaces: performance.evaluation.totalRaces
      }
    )));
  }

  void ctx;
  return null;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    await ensureSchema(env.DB);
    const url = new URL(request.url);
    const pathname = url.pathname;
    const state = await getHistoricalAuditState(env.DB, env.MODEL_VERSION);

    if (!state.valid) {
      if (pathname === "/api/audit/three-months/public-status") {
        return json({ auditFrozen: true, state });
      }
      if (pathname === "/api/audit/three-months/repair-public" && request.method === "POST") {
        try {
          const result = await runRepair(env, 2);
          return json(result);
        } catch (error) {
          return json({
            ok: false,
            complete: false,
            error: error instanceof Error ? error.message : String(error),
            audit: { findings: state.findings }
          }, 500);
        }
      }
      if (pathname === "/") {
        try {
          const result = await runRepair(env, 1);
          if (result.complete) {
            const handled = await handledAfterAudit(request, env, ctx);
            if (handled) return handled;
          }
          if (!base.fetch) return new Response("NOT_FOUND", { status: 404 });
          const response = await base.fetch(request, env, ctx);
          const html = await response.text();
          return page(injectInteractiveRepair(html, result.audit.findings ?? {}));
        } catch (error) {
          console.error("AUDIT_ROOT_REPAIR_FAILED", error);
          if (!base.fetch) return new Response("NOT_FOUND", { status: 404 });
          const response = await base.fetch(request, env, ctx);
          const html = await response.text();
          return page(injectInteractiveRepair(html, state.findings));
        }
      }
      ctx.waitUntil(runRepair(env, 1).catch(() => undefined));
      if (!base.fetch) return new Response("NOT_FOUND", { status: 404 });
      return base.fetch(request, env, ctx);
    }

    const handled = await handledAfterAudit(request, env, ctx);
    if (handled) return handled;
    if (!base.fetch) return new Response("NOT_FOUND", { status: 404 });
    return base.fetch(request, env, ctx);
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    await ensureSchema(env.DB);
    const state = await getHistoricalAuditState(env.DB, env.MODEL_VERSION);
    if (!state.valid) ctx.waitUntil(runRepair(env, 2).catch(() => undefined));
    if (base.scheduled) await base.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
