import type { BudgetCourse } from "./types.js";

const CUTOVER_DATE = "2026-08-08";
const AUG8_BETS = [["2026-08-08-sapporo-01","ライト","馬連","2-9",700,132.1,0],["2026-08-08-sapporo-01","ライト","馬連","2-11",700,141.7,0],["2026-08-08-sapporo-01","ライト","馬連","8-9",600,101.6,0],["2026-08-08-sapporo-01","スタンダード","馬連","2-9",1700,132.1,0],["2026-08-08-sapporo-01","スタンダード","馬連","2-11",1700,141.7,0],["2026-08-08-sapporo-01","スタンダード","馬連","8-9",1600,101.6,0],["2026-08-08-sapporo-01","プレミアム","馬連","2-9",3400,132.1,0],["2026-08-08-sapporo-01","プレミアム","馬連","2-11",3300,141.7,0],["2026-08-08-sapporo-01","プレミアム","馬連","8-9",3300,101.6,0],["2026-08-08-sapporo-02","ライト","3連複","2-9-11",1000,139.6,0],["2026-08-08-sapporo-02","ライト","3連単","3-2-9",1000,147.9,0],["2026-08-08-sapporo-02","スタンダード","3連複","2-9-11",2500,139.6,0],["2026-08-08-sapporo-02","スタンダード","3連単","3-2-9",2500,147.9,0],["2026-08-08-sapporo-02","プレミアム","3連複","2-9-11",5000,139.6,0],["2026-08-08-sapporo-02","プレミアム","3連単","3-2-9",5000,147.9,0],["2026-08-08-sapporo-06","ライト","馬連","4-16",2000,54.8,0],["2026-08-08-sapporo-06","スタンダード","馬連","4-16",5000,54.8,0],["2026-08-08-sapporo-06","プレミアム","馬連","4-16",10000,54.8,0],["2026-08-08-sapporo-08","ライト","馬連","2-15",2000,383.2,0],["2026-08-08-sapporo-08","スタンダード","馬連","2-15",5000,383.2,0],["2026-08-08-sapporo-08","プレミアム","馬連","2-15",10000,383.2,0],["2026-08-08-sapporo-09","ライト","3連複","4-10-13",2000,179.5,0],["2026-08-08-sapporo-09","スタンダード","3連複","4-10-13",5000,179.5,0],["2026-08-08-sapporo-09","プレミアム","3連複","4-10-13",10000,179.5,0],["2026-08-08-niigata-01","ライト","3連複","1-5-10",1000,118.7,0],["2026-08-08-niigata-01","ライト","3連複","5-9-10",1000,100.6,0],["2026-08-08-niigata-01","スタンダード","3連複","1-5-10",2500,118.7,0],["2026-08-08-niigata-01","スタンダード","3連複","5-9-10",2500,100.6,0],["2026-08-08-niigata-01","プレミアム","3連複","1-5-10",5000,118.7,0],["2026-08-08-niigata-01","プレミアム","3連複","5-9-10",5000,100.6,0],["2026-08-08-niigata-03","ライト","3連複","4-7-12",2000,27.2,0],["2026-08-08-niigata-03","スタンダード","3連複","4-7-12",5000,27.2,0],["2026-08-08-niigata-03","プレミアム","3連複","4-7-12",10000,27.2,0],["2026-08-08-niigata-04","ライト","馬連","5-11",2000,367.5,0],["2026-08-08-niigata-04","スタンダード","馬連","5-11",5000,367.5,0],["2026-08-08-niigata-04","プレミアム","馬連","5-11",10000,367.5,0],["2026-08-08-niigata-05","ライト","馬連","1-10",2000,445.1,0],["2026-08-08-niigata-05","スタンダード","馬連","1-10",5000,445.1,0],["2026-08-08-niigata-05","プレミアム","馬連","1-10",10000,445.1,0],["2026-08-08-niigata-12","ライト","単勝","15",700,32.3,0],["2026-08-08-niigata-12","ライト","ワイド","3-5",700,32.75,0],["2026-08-08-niigata-12","ライト","ワイド","3-10",600,44.95,0],["2026-08-08-niigata-12","スタンダード","単勝","15",1700,32.3,0],["2026-08-08-niigata-12","スタンダード","ワイド","3-5",1700,32.75,0],["2026-08-08-niigata-12","スタンダード","ワイド","3-10",1600,44.95,0],["2026-08-08-niigata-12","プレミアム","単勝","15",3400,32.3,0],["2026-08-08-niigata-12","プレミアム","ワイド","3-5",3300,32.75,0],["2026-08-08-niigata-12","プレミアム","ワイド","3-10",3300,44.95,0],["2026-08-08-chukyo-03","ライト","3連複","9-13-15",2000,430.7,0],["2026-08-08-chukyo-03","スタンダード","3連複","9-13-15",5000,430.7,0],["2026-08-08-chukyo-03","プレミアム","3連複","9-13-15",10000,430.7,0],["2026-08-08-chukyo-04","ライト","3連単","7-5-6",1000,96.9,0],["2026-08-08-chukyo-04","ライト","3連単","7-12-5",1000,98.0,0],["2026-08-08-chukyo-04","スタンダード","3連単","7-5-6",2500,96.9,0],["2026-08-08-chukyo-04","スタンダード","3連単","7-12-5",2500,98.0,0],["2026-08-08-chukyo-04","プレミアム","3連単","7-5-6",5000,96.9,0],["2026-08-08-chukyo-04","プレミアム","3連単","7-12-5",5000,98.0,0],["2026-08-08-chukyo-06","ライト","3連単","3-7-5",700,378.3,0],["2026-08-08-chukyo-06","ライト","3連単","3-11-5",700,375.7,0],["2026-08-08-chukyo-06","ライト","3連単","11-3-5",600,382.5,0],["2026-08-08-chukyo-06","スタンダード","3連単","3-7-5",1700,378.3,0],["2026-08-08-chukyo-06","スタンダード","3連単","3-11-5",1700,375.7,0],["2026-08-08-chukyo-06","スタンダード","3連単","11-3-5",1600,382.5,0],["2026-08-08-chukyo-06","プレミアム","3連単","3-7-5",3400,378.3,0],["2026-08-08-chukyo-06","プレミアム","3連単","3-11-5",3300,375.7,0],["2026-08-08-chukyo-06","プレミアム","3連単","11-3-5",3300,382.5,0],["2026-08-08-chukyo-09","ライト","馬単","3-5",1000,281.3,0],["2026-08-08-chukyo-09","ライト","馬単","6-10",1000,266.3,0],["2026-08-08-chukyo-09","スタンダード","馬単","3-5",2500,281.3,0],["2026-08-08-chukyo-09","スタンダード","馬単","6-10",2500,266.3,0],["2026-08-08-chukyo-09","プレミアム","馬単","3-5",5000,281.3,0],["2026-08-08-chukyo-09","プレミアム","馬単","6-10",5000,266.3,0],["2026-08-08-chukyo-10","ライト","馬単","4-1",2000,47.1,0],["2026-08-08-chukyo-10","スタンダード","馬単","4-1",5000,47.1,0],["2026-08-08-chukyo-10","プレミアム","馬単","4-1",10000,47.1,0]] as const;

export interface PublicCourseMetric {
  course: BudgetCourse; settledRaces: number; stakeYen: number; returnYen: number; roiPct: number | null;
}
export interface PublicMonthlyMetric extends PublicCourseMetric { month: string; }
export interface PublicBetRow {
  course: BudgetCourse; betType: string; combination: string; stakeYen: number; assumedOdds: number | null; returnYen: number | null; settlementStatus: string;
}

let readyPromise: Promise<void> | null = null;

async function initialize(db: D1Database): Promise<void> {
  await db.prepare(`CREATE TABLE IF NOT EXISTS rt_public_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, race_id TEXT NOT NULL, course TEXT NOT NULL, bet_type TEXT NOT NULL, combination TEXT NOT NULL,
    stake_yen INTEGER NOT NULL, assumed_odds REAL, return_yen INTEGER, settlement_status TEXT NOT NULL, locked_at TEXT, source_prediction_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(race_id, course, bet_type, combination)
  )`).run();
  await db.prepare(`CREATE INDEX IF NOT EXISTS rt_idx_public_bets_race ON rt_public_bets(race_id, course)`).run();
  await db.prepare(`CREATE INDEX IF NOT EXISTS rt_idx_public_bets_settled ON rt_public_bets(settlement_status, course)`).run();

  await db.prepare(`INSERT OR IGNORE INTO rt_public_bets (race_id,course,bet_type,combination,stake_yen,assumed_odds,return_yen,settlement_status,locked_at,source_prediction_id)
    SELECT b.race_id,
      CASE WHEN b.bet_type LIKE 'ライト｜%' THEN 'ライト' WHEN b.bet_type LIKE 'スタンダード｜%' THEN 'スタンダード' ELSE 'プレミアム' END,
      substr(b.bet_type, instr(b.bet_type,'｜')+1), b.combination, b.stake_yen, b.assumed_odds, b.return_yen, b.settlement_status, p.locked_at, p.id
    FROM rt_bets b JOIN rt_predictions p ON p.id=b.prediction_id JOIN rt_races r ON r.race_id=b.race_id
    JOIN (
      SELECT p2.race_id, MAX(p2.id) AS prediction_id
      FROM rt_predictions p2 JOIN rt_bets b2 ON b2.prediction_id=p2.id JOIN rt_races r2 ON r2.race_id=p2.race_id
      WHERE p2.status='locked' AND r2.race_date<=?
        AND (b2.bet_type LIKE 'ライト｜%' OR b2.bet_type LIKE 'スタンダード｜%' OR b2.bet_type LIKE 'プレミアム｜%')
      GROUP BY p2.race_id
    ) latest ON latest.prediction_id=p.id
    WHERE p.status='locked' AND r.race_date<=?
      AND (b.bet_type LIKE 'ライト｜%' OR b.bet_type LIKE 'スタンダード｜%' OR b.bet_type LIKE 'プレミアム｜%')`).bind(CUTOVER_DATE,CUTOVER_DATE).run();

  const seeded = await db.prepare(`SELECT state_value AS value FROM rt_system_state WHERE state_key='public_aug8_seeded_v1'`).first<{value:string}>();
  if (!seeded) {
    await db.prepare(`DELETE FROM rt_public_bets WHERE race_id LIKE '2026-08-08-%'`).run();
    const statements = AUG8_BETS.map((row) => db.prepare(`INSERT OR REPLACE INTO rt_public_bets
      (race_id,course,bet_type,combination,stake_yen,assumed_odds,return_yen,settlement_status,locked_at,source_prediction_id)
      VALUES (?,?,?,?,?,?,?,'settled','2026-08-08T00:00:00Z',-1)`).bind(...row));
    if (statements.length) await db.batch(statements);
    await db.prepare(`INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES('public_aug8_seeded_v1','1',CURRENT_TIMESTAMP)
      ON CONFLICT(state_key) DO UPDATE SET state_value='1',updated_at=CURRENT_TIMESTAMP`).run();
  }
}

export function ensurePublicHistory(db: D1Database): Promise<void> {
  readyPromise ??= initialize(db).catch((error) => { readyPromise=null; throw error; });
  return readyPromise;
}

const COURSES: BudgetCourse[] = ["ライト","スタンダード","プレミアム"];

export async function getPublicCourseMetrics(db: D1Database): Promise<PublicCourseMetric[]> {
  await ensurePublicHistory(db);
  const rows = await db.prepare(`SELECT course,COUNT(DISTINCT race_id) AS settledRaces,COALESCE(SUM(stake_yen),0) AS stakeYen,COALESCE(SUM(return_yen),0) AS returnYen
    FROM rt_public_bets WHERE settlement_status='settled' GROUP BY course`).all<{course:BudgetCourse;settledRaces:number;stakeYen:number;returnYen:number}>();
  const map=new Map<BudgetCourse,{course:BudgetCourse;settledRaces:number;stakeYen:number;returnYen:number}>(rows.results.map(r=>[r.course,r] as const));
  return COURSES.map(course=>{const r=map.get(course);const stake=Number(r?.stakeYen??0),ret=Number(r?.returnYen??0);return {course,settledRaces:Number(r?.settledRaces??0),stakeYen:stake,returnYen:ret,roiPct:stake>0?ret/stake*100:null};});
}

export async function getPublicMonthlyMetrics(db: D1Database): Promise<PublicMonthlyMetric[]> {
  await ensurePublicHistory(db);
  const rows=await db.prepare(`SELECT substr(r.race_date,1,7) AS month,b.course,COUNT(DISTINCT b.race_id) AS settledRaces,COALESCE(SUM(b.stake_yen),0) AS stakeYen,COALESCE(SUM(b.return_yen),0) AS returnYen
    FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id WHERE b.settlement_status='settled' GROUP BY month,b.course ORDER BY month DESC,b.course`).all<{month:string;course:BudgetCourse;settledRaces:number;stakeYen:number;returnYen:number}>();
  return rows.results.map(r=>{const stake=Number(r.stakeYen),ret=Number(r.returnYen);return {month:r.month,course:r.course,settledRaces:Number(r.settledRaces),stakeYen:stake,returnYen:ret,roiPct:stake>0?ret/stake*100:null};});
}

export async function getPublicBets(db: D1Database,raceId:string): Promise<PublicBetRow[]> {
  await ensurePublicHistory(db);
  const rows=await db.prepare(`SELECT course,bet_type AS betType,combination,stake_yen AS stakeYen,assumed_odds AS assumedOdds,return_yen AS returnYen,settlement_status AS settlementStatus
    FROM rt_public_bets WHERE race_id=? ORDER BY CASE course WHEN 'ライト' THEN 1 WHEN 'スタンダード' THEN 2 ELSE 3 END,id`).bind(raceId).all<PublicBetRow>();
  return rows.results.map(r=>({...r,stakeYen:Number(r.stakeYen),assumedOdds:r.assumedOdds===null?null:Number(r.assumedOdds),returnYen:r.returnYen===null?null:Number(r.returnYen)}));
}

export async function getPublicBetRaceIds(db: D1Database,raceIds:string[]): Promise<Set<string>> {
  await ensurePublicHistory(db); if(!raceIds.length)return new Set();
  const placeholders=raceIds.map(()=>'?').join(',');
  const rows=await db.prepare(`SELECT DISTINCT race_id AS raceId FROM rt_public_bets WHERE race_id IN (${placeholders})`).bind(...raceIds).all<{raceId:string}>();
  return new Set(rows.results.map(r=>r.raceId));
}
