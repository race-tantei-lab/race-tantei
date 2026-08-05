import { readFile, writeFile, unlink } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const basePath = new URL("./train-payout-segment-ensemble.mjs", import.meta.url);
const generatedPath = new URL("./.generated-light-specialized-search.mjs", import.meta.url);
let source = await readFile(basePath, "utf8");

function replaceRequired(search, replacement, label) {
  if (!source.includes(search)) throw new Error(`LIGHT_SEARCH_PATCH_MISSING:${label}`);
  source = source.replace(search, replacement);
}

replaceRequired(
  'const courses = ["ライト", "スタンダード", "プレミアム"];\nconst requiredHitRatePct = 36.8;\nconst beamSize = 20;',
  'const courses = ["ライト"];\nconst requiredHitRatePct = 36.8;\nconst requiredValidationMonthRoiPct = 100;\nconst beamSize = 128;',
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
  "remove-candidate-fallback"
);

replaceRequired(
  '  if (!chosen.length) add(race.candidates[0]);\n  return chosen.slice(0, policy.ticketCount);',
  '  return chosen.slice(0, policy.ticketCount);',
  "remove-portfolio-fallback"
);

replaceRequired(
  '  for (const race of records) {\n    const tickets = allocate(portfolio(race, policy), target, policy);',
  '  for (const race of records) {\n    const tickets = allocate(portfolio(race, policy), target, policy);\n    if (!tickets.length) return { races: 0, roi: 0, hit: 0, minMonth: 0, volatility: 999, profit: 0, objective: -1000000000 };',
  "require-ticket-every-selected-race"
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
`    ["minStableRoi", [0, 70, 80, 90, 100, 110, 125, 145, 175]],
    ["minStableHit", [0, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15]],
    ["minConfidence", [0, 0.25, 0.4, 0.55, 0.7]],
    ["maxRank", [2, 3, 4, 5, 6, 7]],
    ["includesFirst", ["any", "yes", "no"]],
    ["ticketCount", [1, 2, 3, 4, 6]],`,
`    ["minStableRoi", [0, 70, 80, 90, 100, 110, 125, 145, 175, 210, 260]],
    ["minStableHit", [0, 0.003, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.25]],
    ["minConfidence", [0, 0.2, 0.3, 0.4, 0.55, 0.7, 0.82]],
    ["maxRank", [2, 3, 4, 5, 6, 7]],
    ["includesFirst", ["any", "yes", "no"]],
    ["ticketCount", [1, 2, 3, 4, 5, 6]],`,
  "dimensions"
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
  "final-monthly-gate"
);

replaceRequired(
  '  const finalists = raceConfigs.slice(0, 5);',
  '  const finalists = raceConfigs;',
  "all-race-configurations"
);

replaceRequired(
`    for (const course of courses) {
      const winner = searchPolicy(selected, budget.COURSE_TARGET_STAKES[course], course);
      if (!winner) throw new Error(\`NO_SEGMENT_POLICY:\${course}\`);
      policies[course] = winner;
      console.log(\`\${course}: validation ROI \${round(winner.result.roi)}% / hit \${round(winner.result.hit)}% / minMonth \${round(winner.result.minMonth)}%\`);
    }`,
`    for (const course of courses) {
      const policyWinner = searchPolicy(selected, budget.COURSE_TARGET_STAKES[course], course);
      if (!policyWinner) {
        policies[course] = null;
        console.log(\`\${course}: rejected for \${config.mode}/\${config.count}R\`);
        continue;
      }
      policies[course] = policyWinner;
      console.log(\`\${course}: validation ROI \${round(policyWinner.result.roi)}% / hit \${round(policyWinner.result.hit)}% / minMonth \${round(policyWinner.result.minMonth)}%\`);
    }
    if (courses.some((course) => !policies[course])) continue;`,
  "course-rejection"
);

replaceRequired(
`  searched.sort((a, b) => b.aggregate - a.aggregate);
  const winner = searched[0];
  if (!winner) throw new Error("NO_SEGMENT_WINNER");
  const holdoutRows = selectRaces(holdout, winner.count, winner.mode);`,
`  searched.sort((a, b) => b.aggregate - a.aggregate);
  const winner = searched[0];
  if (!winner) {
    const rejectedReport = {
      generatedAt: new Date().toISOString(),
      targetRoiPct: 200,
      requiredValidationMonthRoiPct,
      minimumRacesPerVenueDay: 5,
      course: "ライト",
      method: "Exact payouts, expanded ticket types, strict filters and no weak-ticket fallback.",
      selectedRaceConfiguration: null,
      validation: {},
      holdout: {},
      promotionEligible: false,
      rejectionReason: "NO_LIGHT_POLICY_PROFITABLE_IN_EVERY_VALIDATION_MONTH"
    };
    await writeFile("light-specialized-search.json", JSON.stringify(rejectedReport, null, 2) + "\\n");
    console.log("No light policy passed both validation months. Holdout was not opened.");
    return;
  }
  const holdoutRows = selectRaces(holdout, winner.count, winner.mode);`,
  "no-winner-report"
);

replaceRequired(
`    targetRoiPct: 200,
    minimumRacesPerVenueDay: 5,
    method: "Mine payout segments on four chronological training folds using exact payout_yen/zero returns. Select race count and ticket policy on validation only; evaluate holdout once.",`,
`    targetRoiPct: 200,
    requiredValidationMonthRoiPct,
    minimumRacesPerVenueDay: 5,
    course: "ライト",
    method: "Exact payouts, expanded ticket types, strict filters and no weak-ticket fallback. Require both validation months at 100% or better before opening holdout.",`,
  "report-method"
);

source = source.replaceAll("payout-segment-ensemble.json", "light-specialized-search.json");
source = source.replaceAll("Promotion eligible:", "Light promotion eligible:");

await writeFile(generatedPath, source, "utf8");
try {
  await import(`${pathToFileURL(generatedPath.pathname).href}?v=${Date.now()}`);
} finally {
  await unlink(generatedPath).catch(() => {});
}
