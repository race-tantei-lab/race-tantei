import { saveHistoricalAuditState } from "./historical-audit-state.js";
import { getThreeMonthStakeAuditV2 } from "./three-month-audit-v2.js";
import { THREE_MONTH_VALIDATION_CONFIGS } from "./three-month-scope.js";
import { ensureValidationVenueQuotas } from "./venue-quota.js";

export interface ThreeMonthFixedStakeRepairResult {
  ok: true;
  repairedVenues: number;
  addedRaces: number;
  replacedRaces: number;
  removedRaces: number;
  addedTickets: number;
  complete: boolean;
  audit: Record<string, any>;
}

export async function runThreeMonthFixedStakeRepair(
  db: D1Database,
  liveModel: string,
  maximumVenues = 4
): Promise<ThreeMonthFixedStakeRepairResult> {
  const results = await ensureValidationVenueQuotas(
    db,
    THREE_MONTH_VALIDATION_CONFIGS,
    Math.max(1, Math.min(12, maximumVenues))
  );
  const audit = await getThreeMonthStakeAuditV2(db, liveModel, false);
  const state = await saveHistoricalAuditState(db, liveModel, audit);
  return {
    ok: true,
    repairedVenues: results.reduce((sum, row) => sum + row.normalizedVenues, 0),
    addedRaces: results.reduce((sum, row) => sum + row.addedRaces, 0),
    replacedRaces: results.reduce((sum, row) => sum + row.replacedRaces, 0),
    removedRaces: results.reduce((sum, row) => sum + row.removedRaces, 0),
    addedTickets: results.reduce((sum, row) => sum + row.addedTickets, 0),
    complete: state.valid,
    audit
  };
}
