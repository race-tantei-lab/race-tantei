import fs from "node:fs";
import { summarizeTodayPerformance } from "../dist-test/src/v1/today-performance.js";

const [summaryPath, d1Path] = process.argv.slice(2);
if (!summaryPath || !d1Path) throw new Error("usage: verify-today-performance-response.mjs <summary.json> <d1.json>");

const api = JSON.parse(fs.readFileSync(summaryPath, "utf8"));
const raw = JSON.parse(fs.readFileSync(d1Path, "utf8"));
const blocks = Array.isArray(raw) ? raw : [raw];
const rows = blocks.flatMap((block) => Array.isArray(block?.results) ? block.results : []);
const courses = ["ライト", "スタンダード", "プレミアム"];
const expected = summarizeTodayPerformance(rows, courses);

if (!rows.length) {
  if (api.hasPredictions) throw new Error("TODAY_PERFORMANCE_MISMATCH: API has predictions but D1 has no public bets");
  console.log("TODAY_PERFORMANCE_OK no public bets");
  process.exit(0);
}

for (const exp of expected) {
  const got = (api.courses ?? []).find((row) => row.course === exp.course);
  if (!got) throw new Error(`TODAY_PERFORMANCE_MISMATCH: missing API course ${exp.course}`);
  for (const field of ["totalRaces", "settledRaces", "hitRaces", "refundRaces", "stakeYen", "returnYen", "complete"]) {
    if (got[field] !== exp[field]) throw new Error(`TODAY_PERFORMANCE_MISMATCH ${exp.course}.${field}: api=${got[field]} d1=${exp[field]}`);
  }
  const gotRoi = got.roiPct == null ? null : Number(got.roiPct);
  const expRoi = exp.roiPct == null ? null : Number(exp.roiPct);
  if (gotRoi === null || expRoi === null) {
    if (gotRoi !== expRoi) throw new Error(`TODAY_PERFORMANCE_MISMATCH ${exp.course}.roiPct: api=${gotRoi} d1=${expRoi}`);
  } else if (Math.abs(gotRoi - expRoi) > 1e-10) {
    throw new Error(`TODAY_PERFORMANCE_MISMATCH ${exp.course}.roiPct: api=${gotRoi} d1=${expRoi}`);
  }
}

const expectedHasPredictions = expected.some((row) => row.totalRaces > 0);
const expectedComplete = expectedHasPredictions && expected.every((row) => row.totalRaces === 0 || row.complete);
if (Boolean(api.hasPredictions) !== expectedHasPredictions) throw new Error("TODAY_PERFORMANCE_MISMATCH hasPredictions");
if (Boolean(api.complete) !== expectedComplete) throw new Error("TODAY_PERFORMANCE_MISMATCH complete");

console.log("TODAY_PERFORMANCE_OK", JSON.stringify({
  date: api.date,
  courses: expected.map((row) => ({
    course: row.course,
    totalRaces: row.totalRaces,
    settledRaces: row.settledRaces,
    hitRaces: row.hitRaces,
    refundRaces: row.refundRaces,
    stakeYen: row.stakeYen,
    returnYen: row.returnYen,
    roiPct: row.roiPct,
    complete: row.complete,
  })),
}));
