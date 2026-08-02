import { getPhaseDDashboard as getBasePhaseDDashboard } from "./phase-d-dashboard.js";
import { getAuditedRaceArchiveIndex, renderAuditedRaceArchiveIndex } from "./race-archive-audited.js";

export async function getAuditedPhaseDDashboard(
  db: D1Database,
  liveModel: string,
  auditFrozen: boolean
): Promise<string> {
  const [html, rows] = await Promise.all([
    getBasePhaseDDashboard(db, liveModel),
    getAuditedRaceArchiveIndex(db, liveModel)
  ]);
  const archive = renderAuditedRaceArchiveIndex(rows, auditFrozen);
  const pattern = /<section class="archive-home" id="race-archive">[\s\S]*?<\/section>/;
  return pattern.test(html) ? html.replace(pattern, archive) : html.replace("</main>", `${archive}</main>`);
}
