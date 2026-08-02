import type { CourseMetric } from "./course-db.js";
import { renderDashboard } from "./home-dashboard.js";

type DashboardRace = Parameters<typeof renderDashboard>[0][number];

export function renderClearDashboard(races: DashboardRace[], metrics: CourseMetric[]): string {
  return renderDashboard(races, metrics)
    .replaceAll(
      '<div class="state skip">見送り</div><small>固定買い目なし</small>',
      '<div class="state wait">検証対象外</div><small>現行モデルの固定買い目なし</small>'
    )
    .replaceAll(
      '<div class="state skip">見送り</div><small>購入条件を満たす券なし</small>',
      '<div class="state wait">買い目調整中</div><small>発走15分前まで更新</small>'
    );
}
