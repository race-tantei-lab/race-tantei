import { strict as assert } from "node:assert";
import {
  isValidationModel,
  summarizeValidationTickets,
  validationModelForDate
} from "../src/v1/validation.js";

const aug1Model = validationModelForDate("2026-08-01");
assert.equal(aug1Model, "validation-2026-08-01-v3.0.0-value-engine-v1");
assert.equal(validationModelForDate("2026-07-31"), null);
assert.equal(isValidationModel(aug1Model), true);
assert.equal(isValidationModel("v3.0.0-value-engine"), false);

const summaries = summarizeValidationTickets(
  ["race-1", "race-2", "race-3"],
  [
    {
      raceId: "race-1",
      betType: "ライト｜単勝",
      stakeYen: 200,
      returnYen: 500,
      expectedValuePct: 125,
      settlementStatus: "settled"
    },
    {
      raceId: "race-2",
      betType: "ライト｜ワイド",
      stakeYen: 100,
      returnYen: 0,
      expectedValuePct: 110,
      settlementStatus: "settled"
    },
    {
      raceId: "race-1",
      betType: "スタンダード｜馬連",
      stakeYen: 300,
      returnYen: 0,
      expectedValuePct: 118,
      settlementStatus: "settled"
    },
    {
      raceId: "race-3",
      betType: "プレミアム｜3連単",
      stakeYen: 100,
      returnYen: null,
      expectedValuePct: 140,
      settlementStatus: "pending"
    }
  ]
);

const light = summaries.find((row) => row.course === "ライト");
assert.ok(light);
assert.equal(light.processedRaces, 3);
assert.equal(light.selectedRaces, 2);
assert.equal(light.skippedRaces, 1);
assert.equal(light.hitRaces, 1);
assert.equal(light.stakeYen, 300);
assert.equal(light.returnYen, 500);
assert.equal(light.profitYen, 200);
assert.ok(Math.abs((light.roiPct ?? 0) - 166.6666666667) < 0.001);
assert.equal(light.byTicketType.length, 2);

const standard = summaries.find((row) => row.course === "スタンダード");
assert.ok(standard);
assert.equal(standard.selectedRaces, 1);
assert.equal(standard.skippedRaces, 2);

const premium = summaries.find((row) => row.course === "プレミアム");
assert.ok(premium);
assert.equal(premium.pendingTickets, 1);
assert.equal(premium.returnYen, 0);
assert.equal(premium.expectedReturnYen, 140);

console.log("race-tantei Phase C validation tests passed");
