import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { chooseCompletedTwoTickets, type OfficialOddsRow } from "../src/v1/completed-ticket-runtime";

type ExpectedTicket = {
  betType: string;
  combination: string;
  horses: number[];
  predictedProbability: number;
  officialOdds: number;
  valueProduct: number;
  score: number;
};
type Case = { id: string; horseNos: number[]; weights: number[]; odds: OfficialOddsRow[]; expected: ExpectedTicket[] };
const payload = JSON.parse(readFileSync(resolve(process.argv[2] ?? "worker-ticket-parity.json"), "utf8")) as { cases: Case[] };

let maxError = 0;
let checked = 0;
for (const fixture of payload.cases) {
  const actual = chooseCompletedTwoTickets(fixture.horseNos, fixture.weights, fixture.odds);
  if (actual.length !== fixture.expected.length) throw new Error(`${fixture.id}: ticket count mismatch`);
  for (let i = 0; i < actual.length; i += 1) {
    const got = actual[i];
    const want = fixture.expected[i];
    if (got.betType !== want.betType || got.combination !== want.combination || JSON.stringify(got.horses) !== JSON.stringify(want.horses)) {
      throw new Error(`${fixture.id}: chosen ticket mismatch index=${i} got=${got.betType}:${got.combination} want=${want.betType}:${want.combination}`);
    }
    for (const key of ["predictedProbability", "officialOdds", "valueProduct", "score"] as const) {
      const error = Math.abs(got[key] - want[key]);
      if (error > maxError) maxError = error;
      if (!Number.isFinite(error) || error > 1e-12) throw new Error(`${fixture.id}:${key} mismatch error=${error}`);
    }
    checked += 1;
  }
}
console.log(JSON.stringify({ status: "WORKER_TICKET_PARITY_OK", cases: payload.cases.length, tickets: checked, maxAbsError: maxError, tolerance: 1e-12 }));
