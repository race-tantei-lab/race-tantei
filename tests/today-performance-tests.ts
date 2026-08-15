import { strict as assert } from "node:assert";
import { summarizeTodayPerformance, type TodayPerformanceBetRow } from "../src/v1/today-performance.js";

const COURSES = ["ライト", "スタンダード", "プレミアム"] as const;

function ticket(
  raceId: string,
  course: string,
  combination: string,
  stakeYen: number,
  returnYen: number,
  settlementStatus = "settled",
  refundsJson = "[]",
): TodayPerformanceBetRow {
  return { raceId, course, betType: "単勝", combination, stakeYen, returnYen, settlementStatus, refundsJson };
}

function pair(
  raceId: string,
  course = "ライト",
  returns: [number, number] = [0, 0],
  statuses: [string, string] = ["settled", "settled"],
  refunds: [string, string] = ["[]", "[]"],
  stakes: [number, number] = [1000, 1000],
): TodayPerformanceBetRow[] {
  return [
    ticket(raceId, course, "1", stakes[0], returns[0], statuses[0], refunds[0]),
    { ...ticket(raceId, course, "1-2", stakes[1], returns[1], statuses[1], refunds[1]), betType: "ワイド" },
  ];
}

// A canonical two-row settled race is included in ROI.
let summary = summarizeTodayPerformance(pair("r1", "ライト", [4500, 0]), COURSES)[0];
assert.equal(summary.totalRaces, 1);
assert.equal(summary.settledRaces, 1);
assert.equal(summary.stakeYen, 2000);
assert.equal(summary.returnYen, 4500);
assert.equal(summary.hitRaces, 1);
assert.equal(summary.roiPct, 225);
assert.equal(summary.complete, true);

// One settled ticket plus one pending ticket must not leak a partial stake/return into ROI.
summary = summarizeTodayPerformance(pair("r2", "ライト", [5000, 0], ["settled", "pending"]), COURSES)[0];
assert.equal(summary.totalRaces, 1);
assert.equal(summary.settledRaces, 0);
assert.equal(summary.stakeYen, 0);
assert.equal(summary.returnYen, 0);
assert.equal(summary.roiPct, null);
assert.equal(summary.complete, false);

// Missing or duplicate rows are malformed and fail closed.
summary = summarizeTodayPerformance(pair("r3").slice(0, 1), COURSES)[0];
assert.equal(summary.settledRaces, 0);
assert.equal(summary.complete, false);
summary = summarizeTodayPerformance([...pair("r4"), ticket("r4", "ライト", "3", 1000, 9000)], COURSES)[0];
assert.equal(summary.settledRaces, 0);
assert.equal(summary.stakeYen, 0);

// Refund cash belongs in return/ROI, but a refund-only race is not a genuine hit.
summary = summarizeTodayPerformance(pair("r5", "ライト", [1000, 0], ["settled", "settled"], ["[1]", "[]"]), COURSES)[0];
assert.equal(summary.returnYen, 1000);
assert.equal(summary.refundRaces, 1);
assert.equal(summary.hitRaces, 0);
assert.equal(summary.roiPct, 50);

// A genuine winning ticket plus a refunded sibling is one hit and one refund race.
summary = summarizeTodayPerformance(pair("r6", "ライト", [2100, 1000], ["settled", "settled"], ["[8]", "[8]"]).map((row, index) => index === 0 ? { ...row, combination: "3" } : { ...row, combination: "5-8" }), COURSES)[0];
assert.equal(summary.returnYen, 3100);
assert.equal(summary.hitRaces, 1);
assert.equal(summary.refundRaces, 1);

// Recreate today's Light totals: 15 races x ¥2,000 = ¥30,000, return ¥9,400.
const todayRows: TodayPerformanceBetRow[] = [];
for (let i = 1; i <= 15; i += 1) todayRows.push(...pair(`today-${i}`));
todayRows.find((row) => row.raceId === "today-1" && row.combination === "1")!.returnYen = 2100;
todayRows.find((row) => row.raceId === "today-1" && row.combination === "1-2")!.combination = "5-8";
todayRows.find((row) => row.raceId === "today-1" && row.combination === "5-8")!.returnYen = 1000;
todayRows.find((row) => row.raceId === "today-1" && row.combination === "5-8")!.refundsJson = "[8,10]";
todayRows.find((row) => row.raceId === "today-2" && row.combination === "1")!.returnYen = 4500;
todayRows.find((row) => row.raceId === "today-3" && row.combination === "1")!.returnYen = 1800;
summary = summarizeTodayPerformance(todayRows, COURSES)[0];
assert.equal(summary.totalRaces, 15);
assert.equal(summary.settledRaces, 15);
assert.equal(summary.stakeYen, 30000);
assert.equal(summary.returnYen, 9400);
assert.equal(summary.hitRaces, 3);
assert.equal(summary.refundRaces, 1);
assert.ok(Math.abs(Number(summary.roiPct) - 31.333333333333336) < 1e-12);
assert.equal(summary.complete, true);

console.log("today performance tests passed");
