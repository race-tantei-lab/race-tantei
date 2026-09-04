type CurrentRaceRow = {
  raceId: string;
  raceDate: string;
  venue: string;
  raceNo: number;
  raceName: string | null;
  startTimeJst: string | null;
  startTimeUtc: string | null;
  surface: string | null;
  distanceM: number | null;
  status: string;
};

type CurrentBetRow = {
  raceId: string;
  course: string;
  betType: string;
  combination: string;
  returnYen: number | null;
  settlementStatus: string;
  refundsJson: string | null;
};

type FrozenSelectionPayload = {
  selected?: Array<{ raceId?: unknown }>;
};

export type CurrentPublicState = {
  code: "buy" | "hit" | "miss" | "refund" | "target" | "skip" | "overdue" | "missing" | "pending";
  label: string;
  deadline: string | null;
};

const COURSES = ["ライト", "スタンダード", "プレミアム"] as const;
const START_DEADLINE_MS = 15 * 60 * 1000;
const FINAL_DEADLINE_MS = 10 * 60 * 1000;

function selectedIds(raw: string | null | undefined): Set<string> | null {
  if (!raw) return null;
  try {
    const payload = JSON.parse(raw) as FrozenSelectionPayload;
    if (!Array.isArray(payload.selected)) return null;
    const ids = payload.selected.map((row) => String(row?.raceId ?? "")).filter(Boolean);
    return ids.length ? new Set(ids) : null;
  } catch {
    return null;
  }
}

function horseNos(combination: string): number[] {
  return (combination.match(/\d{1,2}/g) ?? []).map(Number).filter((value) => value >= 1 && value <= 18);
}

function refundNos(raw: string | null): Set<number> {
  try {
    const parsed = JSON.parse(String(raw ?? "[]"));
    return new Set(Array.isArray(parsed) ? parsed.map(Number).filter((value) => Number.isInteger(value)) : []);
  } catch {
    return new Set();
  }
}

function completeFinal(rows: CurrentBetRow[]): boolean {
  if (rows.length !== 6) return false;
  const counts = new Map<string, number>();
  for (const row of rows) counts.set(row.course, (counts.get(row.course) ?? 0) + 1);
  return COURSES.every((course) => counts.get(course) === 2) && counts.size === COURSES.length;
}

function finalState(rows: CurrentBetRow[]): CurrentPublicState | null {
  if (!completeFinal(rows)) return null;
  if (rows.some((row) => row.settlementStatus !== "settled")) {
    return { code: "buy", label: "買い目確定", deadline: "確定済み・以後変更なし" };
  }
  let genuineHit = false;
  let hasRefund = false;
  for (const row of rows) {
    const refunds = refundNos(row.refundsJson);
    const refunded = horseNos(row.combination).some((horseNo) => refunds.has(horseNo));
    if (refunded) hasRefund = true;
    if (!refunded && Number(row.returnYen ?? 0) > 0) genuineHit = true;
  }
  if (genuineHit) return { code: "hit", label: "的中", deadline: null };
  if (hasRefund) return { code: "refund", label: "返還", deadline: null };
  return { code: "miss", label: "不的中", deadline: null };
}

function raceStartMs(race: Pick<CurrentRaceRow, "raceDate" | "startTimeJst" | "startTimeUtc">): number | null {
  const utc = Date.parse(String(race.startTimeUtc ?? ""));
  if (Number.isFinite(utc)) return utc;
  const match = String(race.startTimeJst ?? "").match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return null;
  const fallback = Date.parse(`${race.raceDate}T${match[1].padStart(2, "0")}:${match[2]}:00+09:00`);
  return Number.isFinite(fallback) ? fallback : null;
}

function clockBefore(startTimeJst: string | null, minutesBefore: number): string | null {
  const match = String(startTimeJst ?? "").match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return null;
  const total = (Number(match[1]) * 60 + Number(match[2]) - minutesBefore + 24 * 60) % (24 * 60);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function timingText(startTimeJst: string | null): string {
  const start = clockBefore(startTimeJst, 15);
  const final = clockBefore(startTimeJst, 10);
  if (!start || !final) return "発走15分前までに最終計算開始・発走10分前までに確定";
  return `${start}までに最終計算開始 / ${final}までに確定`;
}

function finalDeadlineText(startTimeJst: string | null): string {
  const final = clockBefore(startTimeJst, 10);
  return final ? `${final}までに確定・それまでは変更の可能性あり` : "発走10分前までに確定・それまでは変更の可能性あり";
}

export function projectCurrentPublicState(
  race: Pick<CurrentRaceRow, "raceId" | "raceDate" | "startTimeJst" | "startTimeUtc">,
  frozenSelection: Set<string> | null,
  betRows: CurrentBetRow[],
  nowMs: number,
): CurrentPublicState {
  const locked = finalState(betRows);
  if (locked) return locked;

  if (frozenSelection) {
    if (!frozenSelection.has(race.raceId)) return { code: "skip", label: "見送り", deadline: null };
    const startMs = raceStartMs(race);
    if (startMs === null) return { code: "target", label: "買い目対象・確定前", deadline: timingText(race.startTimeJst) };
    const startDeadlineMs = startMs - START_DEADLINE_MS;
    const finalDeadlineMs = startMs - FINAL_DEADLINE_MS;
    if (nowMs < startDeadlineMs) {
      return { code: "target", label: "買い目対象・確定前", deadline: timingText(race.startTimeJst) };
    }
    if (nowMs < finalDeadlineMs) {
      return { code: "pending", label: "最終計算中（確定前）", deadline: finalDeadlineText(race.startTimeJst) };
    }
    if (nowMs < startMs) {
      return { code: "overdue", label: "最終確定期限超過", deadline: "確定買い目として扱いません" };
    }
    return { code: "missing", label: "買い目未生成", deadline: null };
  }

  return { code: "pending", label: "判定中", deadline: "対象レースを判定中" };
}

async function selectedBetRows(db: D1Database, raceIds: string[]): Promise<CurrentBetRow[]> {
  if (!raceIds.length) return [];
  const placeholders = raceIds.map(() => "?").join(",");
  const result = await db.prepare(`
    SELECT b.race_id AS raceId,b.course,b.bet_type AS betType,b.combination,b.return_yen AS returnYen,
           b.settlement_status AS settlementStatus,r.refund_horse_nos_json AS refundsJson
    FROM rt_public_bets b
    JOIN rt_races r ON r.race_id=b.race_id
    WHERE b.race_id IN (${placeholders})
    ORDER BY b.race_id,b.id
  `).bind(...raceIds).all<CurrentBetRow>();
  return result.results ?? [];
}

export async function fastCurrentDayResponse(db: D1Database, date: string, now = new Date()): Promise<Response> {
  // The race list and frozen selection are the minimum data required to render a
  // race day. Bet rows are an optional enrichment: a slow/temporarily failing bet
  // lookup must never take the entire current-day API or home screen offline.
  const [raceResult, selectionRow] = await Promise.all([
    db.prepare(`
      SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,race_name AS raceName,
             start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,surface,distance_m AS distanceM,status
      FROM rt_races WHERE race_date=? ORDER BY venue,race_no
    `).bind(date).all<CurrentRaceRow>(),
    db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
      .bind(`final_daily_selection:${date}`).first<{ value: string | null }>(),
  ]);

  const frozen = selectedIds(selectionRow?.value);
  let betRows: CurrentBetRow[] = [];
  let betStateAvailable = true;
  if (frozen) {
    try {
      betRows = await selectedBetRows(db, [...frozen]);
    } catch (error) {
      betStateAvailable = false;
      console.error("CURRENT_DAY_BET_ENRICHMENT_FAILED", date, error);
    }
  }

  const byRace = new Map<string, CurrentBetRow[]>();
  for (const row of betRows) {
    const list = byRace.get(String(row.raceId)) ?? [];
    list.push({ ...row, returnYen: row.returnYen === null ? null : Number(row.returnYen) });
    byRace.set(String(row.raceId), list);
  }
  const races = (raceResult.results ?? []).map((row) => ({
    ...row,
    raceNo: Number(row.raceNo),
    distanceM: row.distanceM === null ? null : Number(row.distanceM),
    publicState: projectCurrentPublicState(row, frozen, byRace.get(String(row.raceId)) ?? [], now.getTime()),
  }));

  return Response.json({
    ok: true,
    date,
    races,
    betStateAvailable: frozen ? betStateAvailable : true,
  }, {
    headers: {
      "cache-control": "no-store, max-age=0",
      "x-race-current-day-path": "direct-d1-v3-resilient-bet-enrichment",
      "x-race-current-day-bet-state": frozen ? (betStateAvailable ? "loaded" : "degraded") : "not-needed",
    },
  });
}
