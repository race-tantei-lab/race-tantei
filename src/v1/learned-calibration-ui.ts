import type { WalkForwardTrainingProgress } from "./walk-forward-training.js";
import {
  CALIBRATION_COURSES,
  meetsRoi200AcceptanceGate,
  TARGET_ROI_PCT,
  type WorkerCalibrationState
} from "./learned-calibration-state.js";

export type WorkerCalibrationPanelState = WorkerCalibrationState & {
  trainingProgress?: WalkForwardTrainingProgress;
};

function formatSignedYen(value: number): string {
  return `${value >= 0 ? "+" : ""}${Math.round(value).toLocaleString("ja-JP")}円`;
}

function pct(done: number, total: number): number {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, done / total * 100));
}

function progressRow(label: string, done: number, total: number, suffix = "件"): string {
  const value = pct(done, total);
  return `<div style="display:grid;grid-template-columns:92px minmax(90px,1fr) auto;gap:9px;align-items:center;margin-top:9px">
    <b style="font-size:12px">${label}</b>
    <div style="height:8px;border-radius:999px;background:#203530;overflow:hidden"><div style="height:100%;width:${value.toFixed(1)}%;background:#55d6ad"></div></div>
    <span style="font-size:11px;white-space:nowrap;opacity:.82">${done.toLocaleString("ja-JP")}/${total.toLocaleString("ja-JP")}${suffix}</span>
  </div>`;
}

function trainingProgressRows(state: WorkerCalibrationPanelState): string {
  const training = state.trainingProgress;
  if (!training) return "";

  const history = training.history;
  const modelTarget = training.splitCounts.train + training.splitCounts.validation;
  const scoreFinished = state.phase === "holdout"
    || state.phase === "apply"
    || state.phase === "quota"
    || state.phase === "complete";
  const scoredTarget = scoreFinished ? state.scoredRaces : Math.max(0, modelTarget);
  const applyTarget = training.splitCounts.validation + training.splitCounts.holdout;
  const holdoutTarget = training.splitCounts.holdout;
  const holdoutDone = state.holdout?.races ?? state.holdoutSelected.races;
  const quotaTotal = state.quotaDates.length;

  return `<div style="margin-top:13px;padding:12px;border:1px solid #29463f;border-radius:13px;background:#0b1715">
    ${progressRow("開催月の探索", history.discoveredMonths, history.totalMonths, "か月")}
    ${progressRow("公式結果の保存", history.importedUrls, history.resultUrls, "件")}
    ${progressRow("基礎予想の生成", training.generatedRaces, training.targetRaces, "R")}
    ${progressRow("勝率モデル学習", state.scoredRaces, scoredTarget, "R")}
    ${progressRow("未使用期間検証", holdoutDone, holdoutTarget, "R")}
    ${progressRow("新モデル再予想", state.appliedRaces, applyTarget, "R")}
    ${progressRow("会場5R再精算", state.quotaDateIndex, quotaTotal, "開催日")}
    <p style="margin:10px 0 0;font-size:11px;opacity:.72">保存済み ${history.storedRaces.toLocaleString("ja-JP")}R。履歴計算用データや正解ラベル不足の除外レースを含むため、保存数と学習対象数は一致しません。</p>
  </div>`;
}

export function renderWorkerCalibrationPanel(state: WorkerCalibrationPanelState): string {
  const accepted = state.phase === "complete" && meetsRoi200AcceptanceGate(state);
  const phaseLabels: Record<WorkerCalibrationState["phase"], string> = {
    "waiting-data": "公式過去データと基礎予想を準備中",
    score: "勝率予測を学習中",
    holdout: "未使用期間で精度を検証中",
    apply: "新モデルで過去レースを再予想中",
    quota: "各会場5Rを固定額で再精算中",
    complete: accepted ? "回収率200%基準達成・新モデル反映済み" : "検証不合格・現行モデルを維持",
    failed: "学習処理でエラー"
  };
  const bestRoi = state.metrics.length > 0
    ? Math.max(...state.metrics.map((row) => row.roiPct))
    : null;
  const roiSummary = state.phase === "complete" && bestRoi !== null
    ? `<p style="margin:8px 0 0;font-size:13px;color:${accepted ? "#8ff0cb" : "#ffb1b1"}">回収率目標 ${TARGET_ROI_PCT.toFixed(0)}%／今回最高 ${bestRoi.toFixed(1)}%／${accepted ? "基準達成" : `未達 ${(TARGET_ROI_PCT - bestRoi).toFixed(1)}ポイント`}</p>`
    : `<p style="margin:8px 0 0;font-size:13px">回収率目標 ${TARGET_ROI_PCT.toFixed(0)}%。未使用期間まで完了した結果だけで採否を判定します。</p>`;
  const metricCards = state.metrics.map((row) => {
    const gap = TARGET_ROI_PCT - row.roiPct;
    return `
    <div style="padding:12px;border:1px solid ${row.roiPct >= TARGET_ROI_PCT ? "#315f55" : "#6f4646"};border-radius:12px;background:#10231f">
      <b>${row.course}</b>
      <strong style="display:block;font-size:24px;margin-top:4px">${row.roiPct.toFixed(1)}%</strong>
      <span style="font-size:12px;opacity:.8">${row.selectedRaces}R・的中率${row.hitRatePct.toFixed(1)}%・平均${Math.round(row.averageStakeYen).toLocaleString("ja-JP")}円</span>
      <small style="display:block;margin-top:4px;color:${gap <= 0 ? "#8ff0cb" : "#ffb1b1"}">${gap <= 0 ? `目標超過 ${Math.abs(gap).toFixed(1)}pt` : `目標まで ${gap.toFixed(1)}pt`}</small>
    </div>`;
  }).join("");
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
    : `<p style="margin:8px 0 0;font-size:13px">結果は勝率学習の正解ラベルにのみ使用し、払戻は学習・レース選択・買い目作成には使用しません。</p>`;
  return `<section id="learned-model-status" style="margin:0 0 16px;padding:15px;border:1px solid ${state.phase === "failed" || (state.phase === "complete" && !accepted) ? "#8d3d3d" : "#315f55"};border-radius:16px;background:#0d1d1a;color:#e7f6f1;line-height:1.55">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:center">
      <div><b style="font-size:16px">12か月学習モデル</b><div style="font-size:13px;opacity:.85">${phaseLabels[state.phase]}</div></div>
      <span style="font-size:12px;text-align:right">学習${state.scoredRaces.toLocaleString("ja-JP")}R<br>再予想${state.appliedRaces.toLocaleString("ja-JP")}R</span>
    </div>
    ${roiSummary}
    ${accuracy}
    ${trainingProgressRows(state)}
    ${metricCards ? `<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:12px">${metricCards}</div>` : ""}
    ${monthRows ? `<div style="overflow:auto;margin-top:12px"><table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr><th style="padding:8px;text-align:left">月</th>${CALIBRATION_COURSES.map((course) => `<th style="padding:8px">${course}</th>`).join("")}</tr></thead><tbody>${monthRows}</tbody></table></div>` : ""}
    ${state.selectionMismatchRaces > 0 ? `<p style="color:#ffb1b1">コース間の選出不一致 ${state.selectionMismatchRaces}R</p>` : ""}
    ${state.error ? `<p style="color:#ffb1b1">${state.error}</p>` : ""}
  </section>`;
}
