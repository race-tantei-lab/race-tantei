import {
  CALIBRATION_COURSES,
  type WorkerCalibrationState
} from "./learned-calibration-state.js";
import type { WalkForwardTrainingProgress } from "./walk-forward-training.js";

export type CalibrationPanelState = WorkerCalibrationState & {
  trainingProgress?: WalkForwardTrainingProgress;
};

function formatSignedYen(value: number): string {
  return `${value >= 0 ? "+" : ""}${Math.round(value).toLocaleString("ja-JP")}円`;
}

export function renderWorkerCalibrationPanel(state: CalibrationPanelState): string {
  const phaseLabels: Record<WorkerCalibrationState["phase"], string> = {
    "waiting-data": "公式過去データを取得中",
    score: "勝率予測を学習中",
    holdout: "未使用期間で精度を検証中",
    apply: "新モデルで過去レースを再予想中",
    quota: "各会場5Rを固定額で再精算中",
    complete: state.active ? "新モデル反映済み" : "検証完了・現行モデルを維持",
    failed: "学習処理でエラー"
  };
  const history = state.trainingProgress?.history;
  const progressText = state.phase === "waiting-data" && state.trainingProgress
    ? history?.phase === "discovery"
      ? `月別探索 ${history.discoveredMonths}/${history.totalMonths}・保存済み${history.storedRaces}R`
      : history?.phase === "import" || history?.phase === "retry"
        ? `公式結果 ${history.importedUrls}/${history.resultUrls}件・保存済み${history.storedRaces}R`
        : `基礎予想 ${state.trainingProgress.generatedRaces}/${state.trainingProgress.targetRaces}R`
    : `学習${state.scoredRaces}R・再予想${state.appliedRaces}R`;
  const metricCards = state.metrics.map((row) => `
    <div style="padding:12px;border:1px solid #315f55;border-radius:12px;background:#10231f">
      <b>${row.course}</b>
      <strong style="display:block;font-size:24px;margin-top:4px">${row.roiPct.toFixed(1)}%</strong>
      <span style="font-size:12px;opacity:.8">${row.selectedRaces}R・的中率${row.hitRatePct.toFixed(1)}%・平均${Math.round(row.averageStakeYen).toLocaleString("ja-JP")}円</span>
    </div>`).join("");
  const months = [...new Set(state.monthlyMetrics.map((row) => row.month))];
  const monthRows = months.map((month) => {
    const cells = CALIBRATION_COURSES.map((course) => {
      const row = state.monthlyMetrics.find((item) => item.month === month && item.course === course);
      return row
        ? `<td style="padding:8px;border-top:1px solid #29463f"><b>${row.roiPct.toFixed(1)}%</b><small style="display:block;opacity:.75">${formatSignedYen(row.profitYen)}・${row.selectedRaces}R</small></td>`
        : `<td style="padding:8px;border-top:1px solid #29463f">—</td>`;
    }).join("");
    return `<tr><th style="padding:8px;text-align:left;border-top:1px solid #29463f">${month}</th>${cells}</tr>`;
  }).join("");
  const accuracy = state.selected && state.holdout
    ? `<p style="margin:8px 0 0;font-size:13px">検証log loss ${state.selected.validationLogLoss.toFixed(4)}（旧${state.selected.baselineValidationLogLoss.toFixed(4)}）／未使用期間1着的中 ${state.holdout.top1AccuracyPct.toFixed(1)}%（旧${state.holdout.baselineTop1AccuracyPct.toFixed(1)}%）</p>`
    : `<p style="margin:8px 0 0;font-size:13px">結果や払戻を買い目選択に使わず、勝ち馬への予測確率を学習しています。</p>`;
  return `<section id="learned-model-status" style="margin:0 0 16px;padding:15px;border:1px solid ${state.phase === "failed" ? "#8d3d3d" : "#315f55"};border-radius:16px;background:#0d1d1a;color:#e7f6f1;line-height:1.55">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:center">
      <div><b style="font-size:16px">12か月学習モデル</b><div style="font-size:13px;opacity:.85">${phaseLabels[state.phase]}</div></div>
      <span style="font-size:12px;text-align:right">${progressText}</span>
    </div>
    ${accuracy}
    ${metricCards ? `<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:12px">${metricCards}</div>` : ""}
    ${monthRows ? `<div style="overflow:auto;margin-top:12px"><table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr><th style="padding:8px;text-align:left">月</th>${CALIBRATION_COURSES.map((course) => `<th style="padding:8px">${course}</th>`).join("")}</tr></thead><tbody>${monthRows}</tbody></table></div>` : ""}
    ${state.selectionMismatchRaces > 0 ? `<p style="color:#ffb1b1">コース間の選出不一致 ${state.selectionMismatchRaces}R</p>` : ""}
    ${state.error ? `<p style="color:#ffb1b1">${state.error}</p>` : ""}
  </section>`;
}
