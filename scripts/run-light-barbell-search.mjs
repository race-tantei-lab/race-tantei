import { readFile, writeFile, unlink } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const basePath = new URL("./run-light-policy-aware-search.mjs", import.meta.url);
const generatedPath = new URL("./.generated-run-light-barbell-search.mjs", import.meta.url);
let source = await readFile(basePath, "utf8");

function replaceRequired(search, replacement, label) {
  if (!source.includes(search)) throw new Error(`LIGHT_BARBELL_PATCH_MISSING:${label}`);
  source = source.replace(search, replacement);
}

replaceRequired(
  'const generatedPath = new URL("./.generated-light-policy-aware-search.mjs", import.meta.url);',
  'const generatedPath = new URL("./.generated-light-barbell-search.mjs", import.meta.url);',
  "temporary-file"
);

source = source.replaceAll("light-policy-aware-search", "light-barbell-search");
source = source.replace(
  'const beamSize = 64;',
  'const beamSize = 80;'
);
source = source.replace(
  '    await writeFile("light-barbell-search.json", JSON.stringify(rejectedReport, null, 2) + "\\\\n");',
  '    await (await import("node:fs/promises")).writeFile("light-barbell-search.json", JSON.stringify(rejectedReport, null, 2) + "\\\\n");'
);

const preOuterMarker = `replaceBetween(
  '  const raceConfigs = [];',`;
const preOuterPatch = String.raw`
replaceBetween(
  'function portfolio(race, policy) {',
  'function selectPolicyRaces(records, policy) {',
\`function portfolio(race, policy) {
  const ranked = filteredCandidates(race, policy);
  const chosen = [];
  const add = (row, role = "core") => {
    if (!row) return;
    const key = \\\`\\\${row.betType}:\\\${row.combination}\\\`;
    if (!chosen.some((item) => \\\`\\\${item.betType}:\\\${item.combination}\\\` === key)) {
      chosen.push({ ...row, portfolioRole: role });
    }
  };
  const byRoi = [...ranked].sort((a, b) => b.stableRoi - a.stableRoi || b.stableScore - a.stableScore);
  const byHit = [...ranked].sort((a, b) => b.stableHit - a.stableHit || b.stableScore - a.stableScore);
  const anchors = byHit.filter((row) => ["単勝", "ワイド", "馬連"].includes(row.betType));
  const upsides = byRoi.filter((row) => ["馬単", "3連複", "3連単"].includes(row.betType));

  if (policy.portfolioMode === "oneRoi") {
    add(byRoi[0], "upside");
  } else if (policy.portfolioMode === "twoRoi") {
    add(byRoi[0], "upside");
    add(byRoi[1], "upside");
  } else if (policy.portfolioMode === "hitRoi") {
    add(byHit[0], "anchor");
    add(byRoi[0], "upside");
  } else if (policy.portfolioMode === "anchorUpside") {
    add(anchors[0] ?? byHit[0], "anchor");
    add(upsides[0] ?? byRoi.find((row) => row !== chosen[0]), "upside");
    if (policy.ticketCount >= 3) add(upsides[1], "upside");
  } else if (policy.portfolioMode === "diversified") {
    const bestByType = new Map();
    for (const row of ranked) {
      if (!bestByType.has(row.betType)) bestByType.set(row.betType, row);
    }
    for (const row of [...bestByType.values()].sort((a, b) => b.stableScore - a.stableScore)) {
      add(row, ["単勝", "ワイド", "馬連"].includes(row.betType) ? "anchor" : "upside");
      if (chosen.length >= policy.ticketCount) break;
    }
  }

  for (const row of ranked) {
    if (chosen.length >= policy.ticketCount) break;
    add(row, ["単勝", "ワイド", "馬連"].includes(row.betType) ? "anchor" : "upside");
  }
  return chosen.slice(0, policy.ticketCount);
}

\`,
  "barbell-portfolio"
);

replaceRequired(
\`  const weights = rows.map((row) => {
    if (policy.stakeMode === "equal") return 1;
    if (policy.stakeMode === "roi") return Math.max(0.01, row.stableRoi - 50);
    if (policy.stakeMode === "hit") return Math.max(0.001, row.stableHit);
    return Math.max(0.01, row.stableScore);
  });\`,
\`  const anchorCount = rows.filter((row) => row.portfolioRole === "anchor").length;
  const upsideCount = rows.filter((row) => row.portfolioRole === "upside").length;
  const weights = rows.map((row) => {
    if (policy.portfolioMode === "anchorUpside" && anchorCount > 0 && upsideCount > 0) {
      if (row.portfolioRole === "anchor") return Math.max(0.01, policy.anchorShare / anchorCount);
      return Math.max(0.01, (1 - policy.anchorShare) / upsideCount);
    }
    if (policy.stakeMode === "equal") return 1;
    if (policy.stakeMode === "roi") return Math.max(0.01, row.stableRoi - 50);
    if (policy.stakeMode === "hit") return Math.max(0.001, row.stableHit);
    return Math.max(0.01, row.stableScore);
  });\`,
  "barbell-allocation"
);

replaceRequired(
\`        raceCount: 5,
        raceMode: "stable"\`,
\`        raceCount: 5,
        raceMode: "stable",
        portfolioMode: "ranked",
        anchorShare: 0.55\`,
  "barbell-policy-defaults"
);

replaceRequired(
\`    ["raceCount", [5, 6, 7, 8, 9, 10, 11, 12]],
    ["raceMode", ["stable", "roi", "hit", "confidence"]],\`,
\`    ["raceCount", [5, 6, 7, 8, 9, 10, 11, 12]],
    ["raceMode", ["stable", "roi", "hit", "confidence"]],
    ["portfolioMode", ["ranked", "oneRoi", "twoRoi", "hitRoi", "anchorUpside", "diversified"]],
    ["anchorShare", [0.25, 0.4, 0.55, 0.7, 0.85]],\`,
  "barbell-policy-dimensions"
);

replaceRequired(
\`  const eligible = beam
    .filter((row) => row.result.hit >= requiredHitRatePct
      && row.result.minMonth >= requiredValidationMonthRoiPct)
    .sort((a, b) => b.result.roi - a.result.roi || b.result.minMonth - a.result.minMonth);
  return eligible[0];\`,
\`  const candidates = beam
    .filter((row) => row.result.hit >= requiredHitRatePct)
    .sort((a, b) => {
      const aGate = a.result.minMonth >= requiredValidationMonthRoiPct ? 1 : 0;
      const bGate = b.result.minMonth >= requiredValidationMonthRoiPct ? 1 : 0;
      return bGate - aGate
        || b.result.minMonth - a.result.minMonth
        || b.result.roi - a.result.roi
        || b.result.objective - a.result.objective;
    });
  const best = candidates[0];
  return best ? {
    ...best,
    validationGatePassed: best.result.minMonth >= requiredValidationMonthRoiPct
  } : undefined;\`,
  "retain-best-near-miss"
);

`;
replaceRequired(preOuterMarker, preOuterPatch + preOuterMarker, "insert-pre-outer-patches");

const reportPatchMarker = `replaceRequired(
\`    targetRoiPct: 200,`;
const postOuterPatch = String.raw`
replaceRequired(
  '  if (!policyWinner) {',
  '  if (!policyWinner || !policyWinner.validationGatePassed) {',
  "barbell-validation-condition"
);

replaceRequired(
\`      selectedRaceConfiguration: null,
      validation: {},
      holdout: {},\`,
\`      selectedRaceConfiguration: policyWinner ? {
        mode: policyWinner.policy.raceMode,
        count: policyWinner.policy.raceCount
      } : null,
      validation: policyWinner ? {
        ライト: {
          policy: policyWinner.policy,
          roi: round(policyWinner.result.roi),
          hit: round(policyWinner.result.hit),
          minMonth: round(policyWinner.result.minMonth),
          volatility: round(policyWinner.result.volatility),
          profit: policyWinner.result.profit,
          monthlyGatePassed: policyWinner.result.minMonth >= requiredValidationMonthRoiPct
        }
      } : {},
      bestNearMiss: policyWinner ? {
        roi: round(policyWinner.result.roi),
        hit: round(policyWinner.result.hit),
        minMonth: round(policyWinner.result.minMonth),
        policy: policyWinner.policy
      } : null,
      holdout: {},\`,
  "barbell-near-miss-report"
);

replaceRequired(
  '      method: "Jointly search race count, race selection, ticket types, filters, ticket count and stake allocation using exact payouts.",',
  '      method: "Barbell light portfolio: jointly search race selection, defensive anchors, upside tickets and stake split using exact payouts.",',
  "barbell-rejection-method"
);

replaceRequired(
  '      rejectionReason: "NO_POLICY_AWARE_LIGHT_POLICY_PASSED_VALIDATION"',
  '      rejectionReason: "NO_LIGHT_BARBELL_POLICY_PASSED_BOTH_VALIDATION_MONTHS"',
  "barbell-rejection-reason"
);

`;
replaceRequired(reportPatchMarker, postOuterPatch + reportPatchMarker, "insert-post-outer-patches");

source = source.replaceAll(
  "Jointly search race count, policy-aware race selection, ticket types, filters, ticket count and stake allocation using exact payouts.",
  "Barbell light portfolio: jointly search race count, race selection, defensive anchors, upside tickets, filters and stake split using exact payouts."
);
source = source.replaceAll(
  "Policy-aware light promotion eligible:",
  "Barbell light promotion eligible:"
);

await writeFile(generatedPath, source, "utf8");
try {
  await import(`${pathToFileURL(generatedPath.pathname).href}?v=${Date.now()}`);
} finally {
  await unlink(generatedPath).catch(() => {});
}
