import { readFile, writeFile, unlink } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const basePath = new URL("./train-payout-segment-ensemble.mjs", import.meta.url);
const generatedPath = new URL("./.generated-train-payout-segment-monthly.mjs", import.meta.url);
let source = await readFile(basePath, "utf8");

function replaceRequired(search, replacement, label) {
  if (!source.includes(search)) {
    throw new Error(`MONTHLY_GATE_PATCH_MISSING:${label}`);
  }
  source = source.replace(search, replacement);
}

replaceRequired(
  'const requiredHitRatePct = 36.8;\nconst beamSize = 20;',
  'const requiredHitRatePct = 36.8;\nconst requiredValidationMonthRoiPct = 100;\nconst beamSize = 32;',
  "constants"
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
  const values = [...unique.values()];
  const hitEligible = values.filter((row) => row.result.hit >= requiredHitRatePct);
  return (hitEligible.length ? hitEligible : values)
    .sort((a, b) => {
      const aMonthlyGate = a.result.minMonth >= requiredValidationMonthRoiPct ? 1 : 0;
      const bMonthlyGate = b.result.minMonth >= requiredValidationMonthRoiPct ? 1 : 0;
      return bMonthlyGate - aMonthlyGate
        || b.result.minMonth - a.result.minMonth
        || b.result.objective - a.result.objective
        || b.result.roi - a.result.roi;
    })
    .slice(0, beamSize);
}`,
  "retain"
);

replaceRequired(
`  return beam[0];
}

async function main() {`,
`  const monthlyEligible = beam
    .filter((row) => row.result.hit >= requiredHitRatePct
      && row.result.minMonth >= requiredValidationMonthRoiPct)
    .sort((a, b) => b.result.objective - a.result.objective || b.result.roi - a.result.roi);
  return monthlyEligible[0];
}

async function main() {`,
  "final-policy-gate"
);

replaceRequired(
`  raceConfigs.sort((a, b) => b.result.objective - a.result.objective);
  const finalists = raceConfigs.slice(0, 5);`,
`  raceConfigs.sort((a, b) => b.result.objective - a.result.objective);
  const finalists = raceConfigs.slice(0, 12);`,
  "finalists"
);

replaceRequired(
`    for (const course of courses) {
      const winner = searchPolicy(selected, budget.COURSE_TARGET_STAKES[course], course);
      if (!winner) throw new Error(\`NO_SEGMENT_POLICY:\${course}\`);
      policies[course] = winner;
      console.log(\`\${course}: validation ROI \${round(winner.result.roi)}% / hit \${round(winner.result.hit)}% / minMonth \${round(winner.result.minMonth)}%\`);
    }
    const minimumRoi = Math.min(...courses.map((course) => policies[course].result.roi));`,
`    for (const course of courses) {
      const policyWinner = searchPolicy(selected, budget.COURSE_TARGET_STAKES[course], course);
      if (!policyWinner) {
        policies[course] = null;
        console.log(\`\${course}: rejected — no policy kept every validation month at or above \${requiredValidationMonthRoiPct}% while preserving hit rate\`);
        continue;
      }
      policies[course] = policyWinner;
      console.log(\`\${course}: validation ROI \${round(policyWinner.result.roi)}% / hit \${round(policyWinner.result.hit)}% / minMonth \${round(policyWinner.result.minMonth)}%\`);
    }
    if (courses.some((course) => !policies[course])) {
      console.log(\`Rejected \${config.mode}/\${config.count}R by monthly validation gate.\`);
      continue;
    }
    const minimumRoi = Math.min(...courses.map((course) => policies[course].result.roi));`,
  "course-gate"
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
      method: "Use exact payout_yen/zero returns and reject every policy with any validation month below 100%.",
      training: {
        races: model.trainingRaces,
        tickets: model.trainingTickets,
        months: trainMonths,
        stableSegments: model.rows.size
      },
      selectedRaceConfiguration: null,
      validation: {},
      holdout: {},
      validationMonthlyGatePassed: false,
      promotionEligible: false,
      rejectionReason: "NO_POLICY_PROFITABLE_IN_EVERY_VALIDATION_MONTH"
    };
    await (await import("node:fs/promises")).writeFile(
      "payout-segment-monthly.json",
      JSON.stringify(rejectedReport, null, 2) + "\\n"
    );
    console.log("No policy passed the all-validation-months profitability gate. Holdout was not opened.");
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
    method: "Mine payout segments on four chronological training folds using exact payout_yen/zero returns. Require every validation month to reach at least 100% before evaluating holdout once.",`,
  "report-method"
);

replaceRequired(
`      hitRequirementMet: winner.policies[course].result.hit >= requiredHitRatePct
    }])),`,
`      hitRequirementMet: winner.policies[course].result.hit >= requiredHitRatePct,
      monthlyGatePassed: winner.policies[course].result.minMonth >= requiredValidationMonthRoiPct
    }])),`,
  "validation-gate-field"
);

replaceRequired(
`    promotionEligible: courses.every((course) =>
      holdoutMetrics[course].roi >= 200 && holdoutMetrics[course].hit >= requiredHitRatePct
    )`,
`    validationMonthlyGatePassed: courses.every((course) =>
      winner.policies[course].result.minMonth >= requiredValidationMonthRoiPct
    ),
    promotionEligible: courses.every((course) =>
      winner.policies[course].result.minMonth >= requiredValidationMonthRoiPct
      && holdoutMetrics[course].roi >= 200
      && holdoutMetrics[course].hit >= requiredHitRatePct
    )`,
  "promotion-gate"
);

source = source.replaceAll("payout-segment-ensemble.json", "payout-segment-monthly.json");

await writeFile(generatedPath, source, "utf8");
try {
  await import(`${pathToFileURL(generatedPath.pathname).href}?v=${Date.now()}`);
} finally {
  await unlink(generatedPath).catch(() => {});
}
