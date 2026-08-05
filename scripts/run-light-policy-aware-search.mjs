import { readFile, writeFile, unlink } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const basePath = new URL("./train-payout-segment-ensemble.mjs", import.meta.url);
const generatedPath = new URL("./.generated-light-policy-aware-search.mjs", import.meta.url);
let source = await readFile(basePath, "utf8");

function replaceRequired(search, replacement, label) {
  if (!source.includes(search)) throw new Error(`LIGHT_POLICY_PATCH_MISSING:${label}`);
  source = source.replace(search, replacement);
}

function replaceBetween(startMarker, endMarker, replacement, label) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  if (start < 0 || end < 0) throw new Error(`LIGHT_POLICY_PATCH_MISSING:${label}`);
  source = source.slice(0, start) + replacement + source.slice(end);
}

replaceRequired(
  'const courses = ["ライト", "スタンダード", "プレミアム"];\nconst requiredHitRatePct = 36.8;\nconst beamSize = 20;',
  'const courses = ["ライト"];\nconst requiredHitRatePct = 36.8;\nconst requiredValidationMonthRoiPct = 100;\nconst beamSize = 64;',
  "constants"
);

replaceRequired(
  '  all: new Set(["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"])\n};',
  '  all: new Set(["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"]),\n  lightSingleTrio: new Set(["単勝", "3連複"]),\n  lightWideTrio: new Set(["ワイド", "3連複"]),\n  lightPairExotics: new Set(["馬連", "馬単", "3連複"]),\n  lightUpside: new Set(["馬単", "3連複", "3連単"]),\n  lightAll: new Set(["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"])\n};',
  "profiles"
);

replaceRequired(
`  const allowedPool = race.candidates.filter((row) => allowed.has(row.betType));
  const pool = eligible.length ? eligible : allowedPool.length ? allowedPool : race.candidates;
  return [...pool].sort((a, b) => b.stableScore - a.stableScore || b.stableRoi - a.stableRoi);`,
`  return [...eligible].sort((a, b) => b.stableScore - a.stableScore || b.stableRoi - a.stableRoi);`,
  "strict-candidates"
);

replaceRequired(
`  if (policy.hedge === "single") add([...race.candidates].filter((row) => row.betType === "単勝").sort((a, b) => b.stableHit - a.stableHit)[0]);
  if (policy.hedge === "wide") add([...race.candidates].filter((row) => row.betType === "ワイド").sort((a, b) => b.stableHit - a.stableHit)[0]);
  if (policy.hedge === "hit") add([...race.candidates].sort((a, b) => b.stableHit - a.stableHit)[0]);`,
`  if (policy.hedge === "single") add([...ranked].filter((row) => row.betType === "単勝").sort((a, b) => b.stableHit - a.stableHit)[0]);
  if (policy.hedge === "wide") add([...ranked].filter((row) => row.betType === "ワイド").sort((a, b) => b.stableHit - a.stableHit)[0]);
  if (policy.hedge === "hit") add([...ranked].sort((a, b) => b.stableHit - a.stableHit)[0]);`,
  "strict-hedges"
);

replaceRequired(
  '  if (!chosen.length) add(race.candidates[0]);\n  return chosen.slice(0, policy.ticketCount);',
  '  return chosen.slice(0, policy.ticketCount);',
  "remove-portfolio-fallback"
);

replaceRequired(
`function allocate(rows, target, policy) {`,
`function selectPolicyRaces(records, policy) {
  const groups = new Map();
  for (const race of records) {
    const key = \`${'${race.raceDate}:${race.venue}'}\`;
    groups.set(key, [...(groups.get(key) ?? []), race]);
  }
  const selected = [];
  for (const rows of groups.values()) {
    const ranked = rows
      .map((race) => {
        const tickets = portfolio(race, policy);
        const best = tickets[0];
        if (!best) return null;
        const score = policy.raceMode === "roi" ? best.stableRoi
          : policy.raceMode === "hit" ? best.stableHit * 100
            : policy.raceMode === "confidence" ? best.segmentConfidence * 100
              : best.stableScore;
        return { race, score };
      })
      .filter(Boolean)
      .sort((a, b) => b.score - a.score || a.race.raceNo - b.race.raceNo);
    if (ranked.length < 5) return [];
    selected.push(...ranked.slice(0, Math.max(5, policy.raceCount)).map((row) => row.race));
  }
  return selected;
}

function allocate(rows, target, policy) {`,
  "policy-aware-race-selection"
);

replaceRequired(
`function evaluate(records, policy, target) {
  let stake = 0;`,
`function evaluate(records, policy, target) {
  const evaluationRecords = selectPolicyRaces(records, policy);
  if (!evaluationRecords.length) {
    return { races: 0, roi: 0, hit: 0, minMonth: 0, volatility: 999, profit: 0, objective: -1000000000 };
  }
  let stake = 0;`,
  "evaluate-selection"
);

replaceRequired(
  '  for (const race of records) {\n    const tickets = allocate(portfolio(race, policy), target, policy);',
  '  for (const race of evaluationRecords) {\n    const tickets = allocate(portfolio(race, policy), target, policy);\n    if (!tickets.length) return { races: 0, roi: 0, hit: 0, minMonth: 0, volatility: 999, profit: 0, objective: -1000000000 };',
  "evaluate-records"
);

replaceRequired(
  '  const hit = records.length > 0 ? hitRaces / records.length * 100 : 0;',
  '  const hit = evaluationRecords.length > 0 ? hitRaces / evaluationRecords.length * 100 : 0;',
  "evaluate-hit"
);

replaceRequired(
  '    races: records.length,',
  '    races: evaluationRecords.length,',
  "evaluate-races"
);

replaceRequired(
`function retain(rows) {
  const unique = new Map();
  for (const row of rows) {
    const key = policyKey(row.policy);
    const current = unique.get(key);
    if (!current || row.result.objective > current.result.objective) unique.set(key, row);
  }
  const values = [...unique.values()];
  const eligible = values.filter((row) => row.result.hit >= requiredHitRatePct);
  return (eligible.length ? eligible : values)
    .sort((a, b) => b.result.objective - a.result.objective || b.result.roi - a.result.roi)
    .slice(0, beamSize);
}`,
`function retain(rows) {
  const unique = new Map();
  for (const row of rows) {
    const key = policyKey(row.policy);
    const current = unique.get(key);
    if (!current || row.result.objective > current.result.objective) unique.set(key, row);
  }
  const values = [...unique.values()].filter((row) => row.result.races > 0);
  const hitEligible = values.filter((row) => row.result.hit >= requiredHitRatePct);
  return (hitEligible.length ? hitEligible : values)
    .sort((a, b) => {
      const aGate = a.result.minMonth >= requiredValidationMonthRoiPct ? 1 : 0;
      const bGate = b.result.minMonth >= requiredValidationMonthRoiPct ? 1 : 0;
      return bGate - aGate
        || b.result.minMonth - a.result.minMonth
        || b.result.roi - a.result.roi
        || b.result.objective - a.result.objective;
    })
    .slice(0, beamSize);
}`,
  "retain"
);

replaceRequired(
`  const courseProfiles = course === "ライト"
    ? ["single", "wide", "singleWide", "stable", "all"]`,
`  const courseProfiles = course === "ライト"
    ? ["single", "wide", "singleWide", "stable", "trio", "exotics", "noTrifecta", "lightSingleTrio", "lightWideTrio", "lightPairExotics", "lightUpside", "lightAll", "all"]`,
  "light-profiles"
);

replaceRequired(
`        ticketCount: 2,
        hedge: "none"`,
`        ticketCount: 2,
        hedge: "none",
        raceCount: 5,
        raceMode: "stable"`,
  "initial-race-policy"
);

replaceRequired(
`    ["minStableRoi", [0, 70, 80, 90, 100, 110, 125, 145, 175]],
    ["minStableHit", [0, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15]],
    ["minConfidence", [0, 0.25, 0.4, 0.55, 0.7]],
    ["maxRank", [2, 3, 4, 5, 6, 7]],
    ["includesFirst", ["any", "yes", "no"]],
    ["ticketCount", [1, 2, 3, 4, 6]],
    ["hedge", ["none", "hit", "single", "wide"]]`,
`    ["raceCount", [5, 6, 7, 8, 9, 10, 11, 12]],
    ["raceMode", ["stable", "roi", "hit", "confidence"]],
    ["minStableRoi", [0, 70, 80, 90, 100, 110, 125, 145, 175, 210, 260]],
    ["minStableHit", [0, 0.003, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.25]],
    ["minConfidence", [0, 0.2, 0.3, 0.4, 0.55, 0.7, 0.82]],
    ["maxRank", [2, 3, 4, 5, 6, 7]],
    ["includesFirst", ["any", "yes", "no"]],
    ["ticketCount", [1, 2, 3, 4, 5, 6]],
    ["hedge", ["none", "hit", "single", "wide"]]`,
  "policy-dimensions"
);

replaceRequired(
`  return beam[0];
}

async function main() {`,
`  const eligible = beam
    .filter((row) => row.result.hit >= requiredHitRatePct
      && row.result.minMonth >= requiredValidationMonthRoiPct)
    .sort((a, b) => b.result.roi - a.result.roi || b.result.minMonth - a.result.minMonth);
  return eligible[0];
}

async function main() {`,
  "final-gate"
);

replaceBetween(
  '  const raceConfigs = [];',
  '  const report = {',
`  const policyWinner = searchPolicy(validation, budget.COURSE_TARGET_STAKES.ライト, "ライト");
  if (!policyWinner) {
    const rejectedReport = {
      generatedAt: new Date().toISOString(),
      targetRoiPct: 200,
      requiredValidationMonthRoiPct,
      minimumRacesPerVenueDay: 5,
      course: "ライト",
      method: "Jointly search race count, race selection, ticket types, filters, ticket count and stake allocation using exact payouts.",
      selectedRaceConfiguration: null,
      validation: {},
      holdout: {},
      promotionEligible: false,
      rejectionReason: "NO_POLICY_AWARE_LIGHT_POLICY_PASSED_VALIDATION"
    };
    await writeFile("light-policy-aware-search.json", JSON.stringify(rejectedReport, null, 2) + "\\n");
    console.log("No policy-aware light policy passed both validation months. Holdout was not opened.");
    return;
  }
  const winner = {
    mode: policyWinner.policy.raceMode,
    count: policyWinner.policy.raceCount,
    policies: { ライト: policyWinner }
  };
  const holdoutMetrics = {
    ライト: evaluate(holdout, policyWinner.policy, budget.COURSE_TARGET_STAKES.ライト)
  };

`,
  "replace-outer-search"
);

replaceRequired(
`    targetRoiPct: 200,
    minimumRacesPerVenueDay: 5,
    method: "Mine payout segments on four chronological training folds using exact payout_yen/zero returns. Select race count and ticket policy on validation only; evaluate holdout once.",`,
`    targetRoiPct: 200,
    requiredValidationMonthRoiPct,
    minimumRacesPerVenueDay: 5,
    course: "ライト",
    method: "Jointly search race count, policy-aware race selection, ticket types, filters, ticket count and stake allocation using exact payouts. Require both validation months at 100% or better before opening holdout.",`,
  "report-method"
);

source = source.replaceAll("payout-segment-ensemble.json", "light-policy-aware-search.json");
source = source.replaceAll("Promotion eligible:", "Policy-aware light promotion eligible:");

await writeFile(generatedPath, source, "utf8");
try {
  await import(`${pathToFileURL(generatedPath.pathname).href}?v=${Date.now()}`);
} finally {
  await unlink(generatedPath).catch(() => {});
}
