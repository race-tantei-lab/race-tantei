import { strict as assert } from "node:assert";
import { chooseCompletedProbabilityFallbackTickets, emergencyRunnerWeights } from "../src/v1/completed-ticket-fallback.js";
import { completedCourseBets } from "../src/v1/completed-ticket-runtime.js";

const horseNos = [1, 2, 3, 4, 5, 6];
const weights = [0.34, 0.23, 0.17, 0.12, 0.08, 0.06];
const tickets = chooseCompletedProbabilityFallbackTickets(horseNos, weights);
assert.equal(tickets.length, 2);
assert.equal(new Set(tickets.map((row) => row.betType)).size, 2);
assert.ok(tickets.every((row) => row.oddsMode === "probability_fallback"));
assert.ok(tickets.every((row) => row.officialOdds === 1));
assert.ok(tickets.every((row) => row.predictedProbability > 0));

const bets = completedCourseBets(tickets);
assert.equal(bets.length, 6);
for (const course of ["ライト", "スタンダード", "プレミアム"] as const) {
  const rows = bets.filter((row) => row.course === course);
  assert.equal(rows.length, 2);
  assert.equal(new Set(rows.map((row) => row.betType)).size, 2);
}

const market = emergencyRunnerWeights([2, 4, 8, 16]);
assert.ok(Math.abs(market.reduce((sum, value) => sum + value, 0) - 1) < 1e-12);
assert.ok(market[0] > market[1] && market[1] > market[2]);
const uniform = emergencyRunnerWeights([null, null, null, null]);
assert.ok(uniform.every((value) => Math.abs(value - 0.25) < 1e-12));

console.log("COMPLETED_TICKET_FALLBACK_OK", JSON.stringify({ tickets: tickets.map((row) => `${row.betType}:${row.combination}`), betRows: bets.length }));
