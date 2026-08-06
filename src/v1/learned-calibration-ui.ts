import {
  APPROVED_PRODUCTION_COURSE_METRICS,
  APPROVED_PRODUCTION_MODEL_ACTIVE,
  APPROVED_PRODUCTION_MODEL_VERSION,
  APPROVED_PRODUCTION_PROMOTION_ELIGIBLE,
  APPROVED_PRODUCTION_REQUIRED_HIT_RATE_PCT,
  APPROVED_PRODUCTION_SELECTED_RACES_PER_VENUE_DAY,
  APPROVED_PRODUCTION_TARGET_ROI_PCT,
  APPROVED_PRODUCTION_VALIDATION
} from "./approved-production-model.js";
import type { WalkForwardTrainingProgress } from "./walk-forward-training.js";
import type { WorkerCalibrationState } from "./learned-calibration-state.js";

export type WorkerCalibrationPanelState = WorkerCalibrationState & {
  trainingProgress?: WalkForwardTrainingProgress;
};

function signedPoints(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}pt`;
}

function renderFinalV5Panel(): string {
  const cards = APPROVED_PRODUCTION_COURSE_METRICS.map((row) => {
    const gap = row.roiPct - APPROVED_PRODUCTION_TARGET_ROI_PCT;
    const passed = gap >= 0 && row.hitRatePct >= APPROVED_PRODUCTION_REQUIRED_HIT_RATE_PCT;
    return `<div style="padding:12px;border:1px solid ${passed ? "#315f55" : "#805151"};border-radius:12px;background:#10231f">
      <b>${row.course}</b>
      <strong style="display:block;font-size:24px;margin-top:4px">${row.roiPct.toFixed(1)}%</strong>
      <span style="display:block;font-size:12px;opacity:.8">7月固定検証 ${row.selectedRaces}R・的中率${row.hitRatePct.toFixed(1)}%</span>
      <span style="display:block;font-size:12px;opacity:.8">購入 ${row.targetStakeYen.toLocaleString("ja-JP")}円/R</span>
      <small style="display:block;margin-top:4px;color:${passed ? "#8ff0cb" : "#ffb1b1"}">${gap >= 0 ? `目標超過 ${signedPoints(gap)}` : `目標まで ${Math.abs(gap).toFixed(1)}pt`}</small>
    </div>`;
  }).join("");

  const validationRows = APPROVED_PRODUCTION_COURSE_METRICS.map((row) => `<tr>
    <th style="padding:8px;text-align:left;border-top:1px solid #29463f">${row.course}</th>
    <td style="padding:8px;border-top:1px solid #29463f">${row.validationRoiPct.toFixed(1)}%</td>
    <td style="padding:8px;border-top:1px solid #29463f">${row.minimumValidationMonthRoiPct.toFixed(1)}%</td>
    <td style="padding:8px;border-top:1px solid #29463f">${row.validationHitRatePct.toFixed(1)}%</td>
  </tr>`).join("");

  return `<section id="learned-model-status" style="margin:0 0 16px;padding:15px;border:1px solid ${APPROVED_PRODUCTION_PROMOTION_ELIGIBLE ? "#315f55" : "#805151"};border-radius:16px;background:#0d1d1a;color:#e7f6f1;line-height:1.55">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:center">
      <div><b style="font-size:16px">最終v5コース別モデル</b><div style="font-size:13px;color:${APPROVED_PRODUCTION_PROMOTION_ELIGIBLE ? "#8ff0cb" : "#ffb1b1"}">${APPROVED_PRODUCTION_PROMOTION_ELIGIBLE ? "全コース200%基準達成" : "ライトのみ200%基準未達"}</div></div>
      <span style="font-size:12px;text-align:right">${APPROVED_PRODUCTION_MODEL_VERSION}<br>会場ごと${APPROVED_PRODUCTION_SELECTED_RACES_PER_VENUE_DAY}R</span>
    </div>
    <p style="margin:8px 0 0;font-size:13px">${APPROVED_PRODUCTION_VALIDATION.method}</p>
    <p style="margin:8px 0 0;font-size:12px;opacity:.82">検証期間 ${APPROVED_PRODUCTION_VALIDATION.validationStartDate}〜${APPROVED_PRODUCTION_VALIDATION.validationEndDate}、固定確認期間 ${APPROVED_PRODUCTION_VALIDATION.holdoutStartDate}〜${APPROVED_PRODUCTION_VALIDATION.holdoutEndDate}。目標回収率${APPROVED_PRODUCTION_TARGET_ROI_PCT.toFixed(0)}%、的中率基準${APPROVED_PRODUCTION_REQUIRED_HIT_RATE_PCT.toFixed(1)}%。</p>
    <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:12px">${cards}</div>
    <div style="overflow:auto;margin-top:12px"><table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr><th style="padding:8px;text-align:left">コース</th><th>5–6月</th><th>月別最低</th><th>的中率</th></tr></thead><tbody>${validationRows}</tbody></table></div>
    <div style="margin-top:12px;padding:11px;border:1px solid #5f4a33;border-radius:12px;background:#211b12;font-size:12px;color:#f2d48d">${APPROVED_PRODUCTION_VALIDATION.note} 8月の実績は成績ページだけに表示し、検証値とは合算しません。</div>
  </section>`;
}

export function renderWorkerCalibrationPanel(state: WorkerCalibrationPanelState): string {
  if (APPROVED_PRODUCTION_MODEL_ACTIVE) return renderFinalV5Panel();
  return `<section id="learned-model-status" style="margin:0 0 16px;padding:15px;border:1px solid #805151;border-radius:16px;background:#0d1d1a;color:#e7f6f1"><b>学習モデル停止中</b><p>${state.error ?? "有効な本番モデルがありません。"}</p></section>`;
}
