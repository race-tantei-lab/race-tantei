import { readFile, writeFile, unlink } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const basePath = new URL("./train-direct-barbell-search.mjs", import.meta.url);
const generatedPath = new URL("./.generated-elite-barbell-search.mjs", import.meta.url);
let source = await readFile(basePath, "utf8");

function replaceRequired(search, replacement, label) {
  if (!source.includes(search)) throw new Error(`ELITE_PATCH_MISSING:${label}`);
  source = source.replace(search, replacement);
}

replaceRequired(
`      model.set(mapKey, {
        robustRoi,
        robustHit,
        confidence,
        count: stat.count,
        foldRois,
        familyWeight: family.weight
      });`,
`      model.set(mapKey, {
        robustRoi,
        robustHit,
        confidence,
        count: stat.count,
        foldRois,
        minFoldRoi: Math.min(...foldRois),
        positiveFolds: foldRois.filter((value) => value >= 100).length,
        familyWeight: family.weight
      });`,
  "segment-fold-fields"
);

const scoreStart = source.indexOf("    score(candidate) {");
const scoreEnd = source.indexOf("    }\n  };\n}", scoreStart);
if (scoreStart < 0 || scoreEnd < 0) throw new Error("ELITE_PATCH_MISSING:model-score");
const scoreReplacement = `    score(candidate) {
      const matches = [];
      for (const family of featureFamilies) {
        const row = model.get(\`${"${family.name}:${family.key(candidate)}"}\`);
        if (row) matches.push(row);
      }
      const anchorLeader = [...matches]
        .sort((a, b) => b.robustHit * b.confidence - a.robustHit * a.confidence
          || b.robustRoi - a.robustRoi)[0];
      const upsideLeader = [...matches]
        .filter((row) => row.positiveFolds >= 3)
        .sort((a, b) => b.robustRoi * b.confidence - a.robustRoi * a.confidence
          || b.minFoldRoi - a.minFoldRoi)[0]
        ?? [...matches].sort((a, b) => b.robustRoi * b.confidence - a.robustRoi * a.confidence)[0];
      const anchorRoi = anchorLeader?.robustRoi ?? 65;
      const anchorHit = anchorLeader?.robustHit ?? 0.02;
      const anchorConfidence = anchorLeader?.confidence ?? 0;
      const upsideRoi = upsideLeader?.robustRoi ?? 65;
      const upsideHit = upsideLeader?.robustHit ?? 0.01;
      const upsideConfidence = upsideLeader?.confidence ?? 0;
      const upsideMinFoldRoi = upsideLeader?.minFoldRoi ?? 0;
      const upsidePositiveFolds = upsideLeader?.positiveFolds ?? 0;
      return {
        ...candidate,
        stableRoi: Math.max(anchorRoi, upsideRoi),
        stableHit: anchorHit,
        confidence: Math.max(anchorConfidence, upsideConfidence),
        anchorRoi,
        anchorHit,
        anchorConfidence,
        upsideRoi,
        upsideHit,
        upsideConfidence,
        upsideMinFoldRoi,
        upsidePositiveFolds,
        anchorScore: anchorHit * 300 + Math.max(0, anchorRoi - 65) * 0.35 + anchorConfidence * 15,
        upsideScore: Math.max(0, upsideRoi - 85) * (0.65 + upsideConfidence * 0.35)
          + Math.max(0, upsideMinFoldRoi - 60) * 0.45
          + upsidePositiveFolds * 8
      };
    }
`;
source = source.slice(0, scoreStart) + scoreReplacement + source.slice(scoreEnd + 5);

replaceRequired(
`    upsideMinRoi: pick(random, [80, 100, 120, 145, 175, 210, 260, 320]),
    minConfidence: pick(random, [0, 0.25, 0.4, 0.55, 0.7, 0.82]),`,
`    upsideMinRoi: pick(random, [80, 100, 120, 145, 175, 210, 260, 320]),
    upsideMinFoldRoi: pick(random, [0, 50, 70, 90, 100, 120, 150]),
    upsideMinPositiveFolds: pick(random, [2, 3, 4]),
    minConfidence: pick(random, [0, 0.25, 0.4, 0.55, 0.7, 0.82]),`,
  "policy-fold-dimensions"
);

replaceRequired(
`      && row.stableRoi >= policy.anchorMinRoi
      && row.stableHit >= policy.anchorMinHit;
  }
  return policy.upsideTypes.includes(row.betType) && row.stableRoi >= policy.upsideMinRoi;`,
`      && row.anchorRoi >= policy.anchorMinRoi
      && row.anchorHit >= policy.anchorMinHit;
  }
  return policy.upsideTypes.includes(row.betType)
    && row.upsideRoi >= policy.upsideMinRoi
    && row.upsideMinFoldRoi >= policy.upsideMinFoldRoi
    && row.upsidePositiveFolds >= policy.upsideMinPositiveFolds;`,
  "role-specific-filters"
);

source = source.replaceAll("direct-barbell-search", "elite-barbell-search");
source = source.replace(
  "Standalone direct barbell search using exact payouts. Separate anchor and upside tickets; jointly optimize race count, filters and stake split on validation only.",
  "Elite-segment barbell search using exact payouts. Anchor tickets use the strongest hit segment; upside tickets require fold-stable high-return segments."
);

await writeFile(generatedPath, source, "utf8");
try {
  await import(`${pathToFileURL(generatedPath.pathname).href}?v=${Date.now()}`);
} finally {
  await unlink(generatedPath).catch(() => {});
}
