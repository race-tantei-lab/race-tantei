import { strict as assert } from "node:assert";
import { projectCurrentPublicState } from "../src/v1/current-day-public-api.js";

const race = {
  raceId: "2026-08-15-niigata-05",
  raceDate: "2026-08-15",
  startTimeJst: "10:00",
  startTimeUtc: "2026-08-15T01:00:00.000Z",
};
const selected = new Set([race.raceId]);
const unselected = new Set(["2026-08-15-niigata-01"]);

function rows(status = "pending", returns: number[] = [0, 0, 0, 0, 0, 0], refunds = "[]") {
  return [
    { raceId: race.raceId, course: "ライト", betType: "単勝", combination: "1", returnYen: returns[0] ?? 0, settlementStatus: status, refundsJson: refunds },
    { raceId: race.raceId, course: "ライト", betType: "ワイド", combination: "1-2", returnYen: returns[1] ?? 0, settlementStatus: status, refundsJson: refunds },
    { raceId: race.raceId, course: "スタンダード", betType: "単勝", combination: "1", returnYen: returns[2] ?? 0, settlementStatus: status, refundsJson: refunds },
    { raceId: race.raceId, course: "スタンダード", betType: "ワイド", combination: "1-2", returnYen: returns[3] ?? 0, settlementStatus: status, refundsJson: refunds },
    { raceId: race.raceId, course: "プレミアム", betType: "単勝", combination: "1", returnYen: returns[4] ?? 0, settlementStatus: status, refundsJson: refunds },
    { raceId: race.raceId, course: "プレミアム", betType: "ワイド", combination: "1-2", returnYen: returns[5] ?? 0, settlementStatus: status, refundsJson: refunds },
  ];
}

assert.equal(projectCurrentPublicState(race, selected, [], Date.parse("2026-08-15T00:30:00Z")).code, "target");
assert.equal(projectCurrentPublicState(race, selected, [], Date.parse("2026-08-15T00:45:00Z")).code, "overdue");
assert.equal(projectCurrentPublicState(race, selected, [], Date.parse("2026-08-15T01:00:00Z")).code, "missing");
assert.equal(projectCurrentPublicState(race, unselected, [], Date.parse("2026-08-15T00:30:00Z")).code, "skip");
assert.equal(projectCurrentPublicState(race, null, [], Date.parse("2026-08-15T00:30:00Z")).code, "pending");

assert.equal(projectCurrentPublicState(race, selected, rows("pending"), Date.parse("2026-08-15T00:50:00Z")).code, "buy");
assert.equal(projectCurrentPublicState(race, selected, rows("settled", [5000, 0, 0, 0, 0, 0]), Date.parse("2026-08-15T01:10:00Z")).code, "hit");
assert.equal(projectCurrentPublicState(race, selected, rows("settled"), Date.parse("2026-08-15T01:10:00Z")).code, "miss");
assert.equal(projectCurrentPublicState(race, selected, rows("settled", [1000, 0, 2500, 0, 5000, 0], "[1]"), Date.parse("2026-08-15T01:10:00Z")).code, "refund");

// Partial/mixed final rows are never advertised as a valid lock. They fall back
// to the authoritative frozen-selection state instead of masking an unsafe write.
assert.equal(projectCurrentPublicState(race, selected, rows("pending").slice(0, 5), Date.parse("2026-08-15T00:30:00Z")).code, "target");

console.log("current-day public API tests passed");
