import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  COMPLETED_FEATURE_NAMES,
  completedFeatureRecord,
  hydrateCompletedFeatureState,
  type SerializedCompletedFeatureState,
} from "../src/v1/completed-feature-runtime";
import type { RaceRecord, RunnerRecord } from "../src/v1/types";

type Fixture = {
  date: string;
  frozenThroughDate: string;
  advancedThroughDate: string;
  deltaRaceCount: number;
  raceCount: number;
  runnerCount: number;
  state: SerializedCompletedFeatureState;
  bundles: Array<{ race: RaceRecord; runners: RunnerRecord[] }>;
  expected: Array<{ raceId: string; horseNo: number; features: Record<string, number> }>;
};

const path = resolve(process.argv[2] ?? "worker-feature-parity.json");
const fixture = JSON.parse(readFileSync(path, "utf8")) as Fixture;
const state = hydrateCompletedFeatureState(fixture.state);
const expected = new Map(fixture.expected.map((row) => [`${row.raceId}:${row.horseNo}`, row.features]));

let checked = 0;
let maxAbsError = 0;
let worst = "";
for (const bundle of fixture.bundles) {
  const field = bundle.runners.filter((runner) => (runner.runnerStatus || "active") === "active").length;
  for (const runner of bundle.runners) {
    const key = `${bundle.race.raceId}:${runner.horseNo}`;
    const want = expected.get(key);
    if (!want) throw new Error(`missing Python feature fixture for ${key}`);
    const got = completedFeatureRecord(state, bundle.race, runner, field);
    for (const name of COMPLETED_FEATURE_NAMES) {
      const error = Math.abs(got[name] - Number(want[name]));
      if (error > maxAbsError) {
        maxAbsError = error;
        worst = `${key}:${name}:worker=${got[name]}:python=${want[name]}`;
      }
    }
    checked += 1;
  }
}

if (checked !== fixture.runnerCount) throw new Error(`runner parity count mismatch: checked=${checked}, fixture=${fixture.runnerCount}`);
const tolerance = 1e-12;
if (!Number.isFinite(maxAbsError) || maxAbsError > tolerance) {
  throw new Error(`WORKER_FEATURE_PARITY_FAILED maxAbsError=${maxAbsError} worst=${worst} tolerance=${tolerance}`);
}
console.log(JSON.stringify({
  status: "WORKER_FEATURE_PARITY_OK",
  date: fixture.date,
  frozenThroughDate: fixture.frozenThroughDate,
  advancedThroughDate: fixture.advancedThroughDate,
  deltaRaceCount: fixture.deltaRaceCount,
  races: fixture.raceCount,
  runners: checked,
  featuresPerRunner: COMPLETED_FEATURE_NAMES.length,
  maxAbsError,
  tolerance,
}));
