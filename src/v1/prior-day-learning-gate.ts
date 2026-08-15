const REQUIRED_PAYOUT_TYPES = ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"] as const;

export type PriorLearningRaceRow = {
  raceId: string;
  raceDate: string;
  status: string | null;
  activeRunners: number;
  resultRows: number;
  payoutTypes: number;
};

export type PriorLearningReadiness = {
  ready: boolean;
  targetDate: string;
  baseThroughDate: string;
  priorRaceCount: number;
  completeRaceCount: number;
  incompleteRaceIds: string[];
};

export function assessPriorLearningRows(
  targetDate: string,
  baseThroughDate: string,
  rows: PriorLearningRaceRow[],
): PriorLearningReadiness {
  const incompleteRaceIds: string[] = [];
  let completeRaceCount = 0;
  for (const row of rows) {
    const complete = String(row.status || "") === "finished"
      && Number(row.activeRunners) > 0
      && Number(row.resultRows) >= Number(row.activeRunners)
      && Number(row.payoutTypes) === REQUIRED_PAYOUT_TYPES.length;
    if (complete) completeRaceCount += 1;
    else incompleteRaceIds.push(String(row.raceId));
  }
  return {
    ready: incompleteRaceIds.length === 0,
    targetDate,
    baseThroughDate,
    priorRaceCount: rows.length,
    completeRaceCount,
    incompleteRaceIds,
  };
}

export async function verifyPriorDayLearningReady(
  db: D1Database,
  targetDate: string,
): Promise<PriorLearningReadiness> {
  const metaRows = await db.prepare("SELECT key,value FROM rt_selection_state_meta WHERE key IN ('ready','throughDate','modelVersion')").all<{ key: string; value: string }>();
  const meta = new Map((metaRows.results ?? []).map((row) => [String(row.key), String(row.value)]));
  if (meta.get("ready") !== "1") throw new Error("PRIOR_LEARNING_SELECTION_STATE_NOT_READY");
  const baseThroughDate = meta.get("throughDate") || "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(baseThroughDate)) throw new Error("PRIOR_LEARNING_THROUGH_DATE_INVALID");
  if (baseThroughDate >= targetDate) throw new Error(`PRIOR_LEARNING_THROUGH_DATE_NOT_PRIOR:${baseThroughDate}:${targetDate}`);

  const payoutTypeJson = JSON.stringify(REQUIRED_PAYOUT_TYPES);
  const result = await db.prepare(`
    SELECT
      r.race_id AS raceId,
      r.race_date AS raceDate,
      r.status AS status,
      (SELECT COUNT(*) FROM rt_runners u
        WHERE u.race_id=r.race_id AND COALESCE(u.runner_status,'active')='active') AS activeRunners,
      (SELECT COUNT(DISTINCT x.horse_no) FROM rt_results x
        WHERE x.race_id=r.race_id) AS resultRows,
      (SELECT COUNT(DISTINCT p.bet_type) FROM rt_payouts p
        WHERE p.race_id=r.race_id AND p.bet_type IN (SELECT value FROM json_each(?))) AS payoutTypes
    FROM rt_races r
    WHERE r.race_date>? AND r.race_date<?
    ORDER BY r.race_date,r.venue,r.race_no,r.race_id
  `).bind(payoutTypeJson, baseThroughDate, targetDate).all<PriorLearningRaceRow>();

  return assessPriorLearningRows(
    targetDate,
    baseThroughDate,
    (result.results ?? []).map((row) => ({
      ...row,
      activeRunners: Number(row.activeRunners || 0),
      resultRows: Number(row.resultRows || 0),
      payoutTypes: Number(row.payoutTypes || 0),
    })),
  );
}
