import type { RaceDetail } from "./db.js";
import { renderPhaseARaceDetail } from "./race-detail-phase-a.js";
import { isValidationModel } from "./validation.js";

export function renderPhaseCRaceDetail(detail: RaceDetail): string {
  let html = renderPhaseARaceDetail(detail);
  if (!isValidationModel(detail.prediction?.modelVersion)) return html;

  const notice = `<div style="margin:0 0 12px;padding:11px 13px;border:1px solid #66542c;border-radius:12px;background:#241f13;color:#f3d28a;font-size:11px;line-height:1.6">フェーズC遡及検証：保存済みの出走情報と最新取得オッズで再計算した結果です。本番公開成績には含めていません。</div>`;
  const marks = '<div class="marks">';
  if (html.includes(marks)) html = html.replace(marks, `${notice}${marks}`);
  return html.replace("</main></body></html>", `<div style="text-align:center;color:#5c7084;font-size:10px;padding:0 0 20px">Phase C validation</div></main></body></html>`);
}
