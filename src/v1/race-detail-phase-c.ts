import type { RaceDetail } from "./db.js";
import { performanceExclusionForRaceId } from "./performance-exclusions.js";
import { renderPhaseARaceDetail } from "./race-detail-phase-a.js";
import { isValidationModel } from "./validation.js";

function injectBeforeMarks(html: string, notice: string): string {
  const marks = '<div class="marks">';
  return html.includes(marks) ? html.replace(marks, `${notice}${marks}`) : html.replace("</main>", `${notice}</main>`);
}

export function renderPhaseCRaceDetail(detail: RaceDetail): string {
  let html = renderPhaseARaceDetail(detail);
  const exclusion = performanceExclusionForRaceId(detail.race.raceId);
  if (exclusion) {
    const notice = `<div style="margin:0 0 12px;padding:11px 13px;border:1px solid #8b4b43;border-radius:12px;background:#2a1716;color:#ffb4ad;font-size:12px;line-height:1.65"><b>成績集計対象外</b><br>${exclusion.displayReason}<br>的中率・回収率・購入額・払戻額の集計には含めません。</div>`;
    html = injectBeforeMarks(html, notice);
  }

  if (!isValidationModel(detail.prediction?.modelVersion)) return html;

  const notice = `<div style="margin:0 0 12px;padding:11px 13px;border:1px solid #66542c;border-radius:12px;background:#241f13;color:#f3d28a;font-size:11px;line-height:1.6">フェーズC遡及検証：保存済みの出走情報と最新取得オッズで再計算した結果です。本番公開成績には含めていません。</div>`;
  html = injectBeforeMarks(html, notice);
  return html.replace("</main></body></html>", `<div style="text-align:center;color:#5c7084;font-size:10px;padding:0 0 20px">Phase C validation</div></main></body></html>`);
}