const token = process.env.CLOUDFLARE_API_TOKEN;
const account = process.env.CLOUDFLARE_ACCOUNT_ID || "3c6d1826b573b2e68cb13ec37e9e8ade";
const database = process.env.CLOUDFLARE_D1_DATABASE_ID || "949b5e8b-d1a4-4c4e-80d1-d031afdc03de";
const endpoint = `https://api.cloudflare.com/client/v4/accounts/${account}/d1/database/${database}/query`;
const requiredHitRatePct = 36.8;
const requiredMonthRoiPct = 100;
const targetRoiPct = 200;
const searchIterations = 12000;

if (!token) throw new Error("CLOUDFLARE_API_TOKEN is not set");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const num = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const round = (value, digits = 1) => Number(value.toFixed(digits));
const chunks = (values, size) => Array.from(
  { length: Math.ceil(values.length / size) },
  (_, index) => values.slice(index * size, (index + 1) * size)
);

async function sql(query, params = []) {
  let lastError;
  for (let attempt = 1; attempt <= 6; attempt += 1) {
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ sql: query, params })
      });
      const payload = await response.json();
      if (!response.ok || payload.success !== true) {
        throw new Error(`D1_${response.status}:${JSON.stringify(payload.errors ?? [])}`);
      }
      await sleep(40);
      return payload.result?.[0]?.results ?? [];
    } catch (error) {
      lastError = error;
      if (attempt === 6) throw error;
      await sleep(attempt * 900);
    }
  }
  throw lastError;
}

function canonical(type, combination) {
  const values = (String(combination).match(/\d{1,2}/g) ?? []).map(Number);
  if (["ワイド", "馬連", "3連複"].includes(type)) values.sort((a, b) => a - b);
  return values.join("-");
}

function bucket(value, boundaries, labels) {
  for (let index = 0; index < boundaries.length; index += 1) {
    if (value < boundaries[index]) return labels[index];
  }
  return labels[labels.length - 1];
}

function percentile(values, p) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = (sorted.length - 1) * p;
  const low = Math.floor(index);
  const high = Math.ceil(index);
  if (low === high) return sorted[low] ?? 0;
  const weight = index - low;
  return (sorted[low] ?? 0) * (1 - weight) + (sorted[high] ?? 0) * weight;
}

function standardDeviation(values) {
  if (values.length < 2) return 0;
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  return Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length);
}

function orderedType(type) {
  return type === "馬単" || type === "3連単";
}

function enrichCandidate(candidate, race, predictions, returnPer100, fold) {
  const byHorse = new Map(predictions.map((row) => [row.horseNo, row]));
  const horses = (candidate.combination.match(/\d{1,2}/g) ?? []).map(Number);
  const ranks = horses.map((horseNo) => byHorse.get(horseNo)?.predictedOrder ?? 99);
  const pops = horses.map((horseNo) => byHorse.get(horseNo)?.popularity ?? 99);
  const rankPattern = orderedType(candidate.betType) ? ranks : [...ranks].sort((a, b) => a - b);
  const popPattern = orderedType(candidate.betType) ? pops : [...pops].sort((a, b) => a - b);
  return {
    raceId: race.raceId,
    raceDate: race.raceDate,
    venue: race.venue,
    raceNo: race.raceNo,
    surface: race.surface || "unknown",
    distanceBucket: bucket(race.distanceM, [1400, 1800, 2200], ["d1", "d2", "d3", "d4"]),
    trackCondition: race.trackCondition || "unknown",
    fieldBucket: bucket(race.fieldSize, [10, 14, 17], ["f1", "f2", "f3", "f4"]),
    raceNoBucket: bucket(race.raceNo, [5, 9], ["early", "middle", "late"]),
    topBucket: bucket(race.topWinProbability, [0.2, 0.3, 0.4, 0.5], ["t1", "t2", "t3", "t4", "t5"]),
    gapBucket: bucket(race.probabilityGap, [0.03, 0.07, 0.12, 0.2], ["g1", "g2", "g3", "g4", "g5"]),
    betType: candidate.betType,
    combination: candidate.combination,
    hitProbability: candidate.hitProbability,
    hitBucket: bucket(candidate.hitProbability, [0.003, 0.007, 0.015, 0.03, 0.06, 0.1, 0.16, 0.25, 0.4], ["h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9", "h10"]),
    maximumRank: candidate.maximumRank,
    rankSum: candidate.rankSum,
    includesFirst: candidate.includesFirst,
    includesFavorite: pops.includes(1),
    rankPattern: rankPattern.join("-"),
    popularityPattern: popPattern.map((value) => Math.min(10, value)).join("-"),
    returnPer100,
    fold
  };
}

const featureFamilies = [
  { name: "type", minCount: 150, prior: 450, weight: 0.4, key: (r) => r.betType },
  { name: "rank", minCount: 40, prior: 80, weight: 1.2, key: (r) => `${r.betType}|${r.rankPattern}` },
  { name: "pop", minCount: 40, prior: 80, weight: 1.0, key: (r) => `${r.betType}|${r.popularityPattern}|${r.includesFavorite}` },
  { name: "prob", minCount: 50, prior: 100, weight: 1.0, key: (r) => `${r.betType}|${r.hitBucket}|${r.maximumRank}|${r.includesFirst}` },
  { name: "context", minCount: 35, prior: 80, weight: 0.8, key: (r) => `${r.betType}|${r.fieldBucket}|${r.topBucket}|${r.gapBucket}|${r.raceNoBucket}` },
  { name: "condition", minCount: 30, prior: 70, weight: 0.7, key: (r) => `${r.betType}|${r.venue}|${r.surface}|${r.distanceBucket}|${r.trackCondition}` },
  { name: "cell", minCount: 20, prior: 45, weight: 1.45, key: (r) => `${r.betType}|${r.rankPattern}|${r.hitBucket}|${r.fieldBucket}|${r.raceNoBucket}` }
];

function buildModel(rows) {
  const stats = new Map();
  for (const row of rows) {
    for (const family of featureFamilies) {
      const mapKey = `${family.name}:${family.key(row)}`;
      const stat = stats.get(mapKey) ?? {
        count: 0,
        returned: 0,
        hits: 0,
        folds: Array.from({ length: 4 }, () => ({ count: 0, returned: 0, hits: 0 }))
      };
      stat.count += 1;
      stat.returned += row.returnPer100;
      stat.hits += row.returnPer100 > 0 ? 1 : 0;
      const fold = stat.folds[row.fold];
      fold.count += 1;
      fold.returned += row.returnPer100;
      fold.hits += row.returnPer100 > 0 ? 1 : 0;
      stats.set(mapKey, stat);
    }
  }

  const model = new Map();
  for (const family of featureFamilies) {
    for (const [mapKey, stat] of stats) {
      if (!mapKey.startsWith(`${family.name}:`) || stat.count < family.minCount) continue;
      const validFolds = stat.folds.filter((fold) => fold.count >= Math.max(5, Math.floor(family.minCount / 8)));
      if (validFolds.length < 3) continue;
      const foldRois = validFolds.map((fold) => fold.returned / fold.count);
      const foldHits = validFolds.map((fold) => fold.hits / fold.count);
      const rawRoi = stat.returned / stat.count;
      const rawHit = stat.hits / stat.count;
      const lowerRoi = percentile(foldRois, 0.25);
      const medianRoi = percentile(foldRois, 0.5);
      const volatility = standardDeviation(foldRois);
      const robustRoi = rawRoi * 0.25 + medianRoi * 0.3 + lowerRoi * 0.45 - volatility * 0.18;
      const robustHit = rawHit * 0.55 + percentile(foldHits, 0.25) * 0.45;
      const confidence = Math.min(1, Math.log1p(stat.count) / Math.log1p(family.minCount * 10)) * (validFolds.length / 4);
      model.set(mapKey, {
        robustRoi,
        robustHit,
        confidence,
        count: stat.count,
        foldRois,
        familyWeight: family.weight
      });
    }
  }

  return {
    size: model.size,
    score(candidate) {
      const matches = [];
      for (const family of featureFamilies) {
        const row = model.get(`${family.name}:${family.key(candidate)}`);
        if (row) matches.push(row);
      }
      matches.sort((a, b) => b.confidence * b.familyWeight - a.confidence * a.familyWeight);
      const selected = matches.slice(0, 5);
      const totalWeight = selected.reduce((sum, row) => sum + row.confidence * row.familyWeight, 0);
      const stableRoi = totalWeight > 0
        ? selected.reduce((sum, row) => sum + row.robustRoi * row.confidence * row.familyWeight, 0) / totalWeight
        : 65;
      const stableHit = totalWeight > 0
        ? selected.reduce((sum, row) => sum + row.robustHit * row.confidence * row.familyWeight, 0) / totalWeight
        : 0.02;
      const confidence = selected.length
        ? selected.reduce((sum, row) => sum + row.confidence, 0) / selected.length
        : 0;
      return {
        ...candidate,
        stableRoi,
        stableHit,
        confidence,
        anchorScore: stableHit * 260 + Math.max(0, stableRoi - 70) * 0.45 + confidence * 12,
        upsideScore: Math.max(0, stableRoi - 80) * (0.65 + confidence * 0.35) + stableHit * 40
      };
    }
  };
}

const anchorProfiles = [
  ["単勝"],
  ["ワイド"],
  ["単勝", "ワイド"],
  ["単勝", "ワイド", "馬連"],
  ["ワイド", "馬連"]
];
const upsideProfiles = [
  ["3連複"],
  ["馬単", "3連複"],
  ["3連複", "3連単"],
  ["馬単", "3連複", "3連単"],
  ["馬連", "馬単", "3連複", "3連単"]
];

function mulberry32(seed) {
  let state = seed >>> 0;
  return () => {
    state += 0x6D2B79F5;
    let value = state;
    value = Math.imul(value ^ value >>> 15, value | 1);
    value ^= value + Math.imul(value ^ value >>> 7, value | 61);
    return ((value ^ value >>> 14) >>> 0) / 4294967296;
  };
}

function pick(random, values) {
  return values[Math.floor(random() * values.length)];
}

function randomPolicy(random) {
  return {
    raceCount: pick(random, [5, 6, 7, 8, 9, 10, 11, 12]),
    anchorTypes: pick(random, anchorProfiles),
    upsideTypes: pick(random, upsideProfiles),
    anchorCount: pick(random, [1, 1, 1, 2]),
    upsideCount: pick(random, [1, 1, 2, 2, 3]),
    anchorShare: pick(random, [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]),
    anchorMinRoi: pick(random, [0, 60, 70, 80, 90, 100, 110, 125]),
    anchorMinHit: pick(random, [0, 0.04, 0.08, 0.12, 0.18, 0.25, 0.35]),
    upsideMinRoi: pick(random, [80, 100, 120, 145, 175, 210, 260, 320]),
    minConfidence: pick(random, [0, 0.25, 0.4, 0.55, 0.7, 0.82]),
    maxRank: pick(random, [3, 4, 5, 6, 7]),
    includeFirstMode: pick(random, ["any", "anchor", "none"]),
    raceMode: pick(random, ["balanced", "anchor", "upside"])
  };
}

function policyKey(policy) {
  return JSON.stringify(policy);
}

function candidateAllowed(row, policy, role) {
  if (row.maximumRank > policy.maxRank || row.confidence < policy.minConfidence) return false;
  if (policy.includeFirstMode === "anchor" && role === "anchor" && !row.includesFirst) return false;
  if (policy.includeFirstMode === "none" && row.includesFirst) return false;
  if (role === "anchor") {
    return policy.anchorTypes.includes(row.betType)
      && row.stableRoi >= policy.anchorMinRoi
      && row.stableHit >= policy.anchorMinHit;
  }
  return policy.upsideTypes.includes(row.betType) && row.stableRoi >= policy.upsideMinRoi;
}

function portfolioForRace(race, policy) {
  const anchors = race.candidates
    .filter((row) => candidateAllowed(row, policy, "anchor"))
    .sort((a, b) => b.anchorScore - a.anchorScore || b.stableRoi - a.stableRoi)
    .slice(0, policy.anchorCount);
  const anchorKeys = new Set(anchors.map((row) => `${row.betType}:${row.combination}`));
  const upsides = race.candidates
    .filter((row) => candidateAllowed(row, policy, "upside"))
    .filter((row) => !anchorKeys.has(`${row.betType}:${row.combination}`))
    .sort((a, b) => b.upsideScore - a.upsideScore || b.stableRoi - a.stableRoi)
    .slice(0, policy.upsideCount);
  if (!anchors.length || !upsides.length) return null;
  const anchorValue = anchors[0]?.anchorScore ?? 0;
  const upsideValue = upsides[0]?.upsideScore ?? 0;
  const raceScore = policy.raceMode === "anchor"
    ? anchorValue * 1.3 + upsideValue * 0.35
    : policy.raceMode === "upside"
      ? anchorValue * 0.35 + upsideValue * 1.3
      : anchorValue * 0.75 + upsideValue * 0.75;
  return { anchors, upsides, raceScore };
}

function selectPolicyRaces(records, policy) {
  const groups = new Map();
  for (const race of records) {
    const key = `${race.raceDate}:${race.venue}`;
    groups.set(key, [...(groups.get(key) ?? []), race]);
  }
  const selected = [];
  for (const rows of groups.values()) {
    const ranked = rows
      .map((race) => {
        const portfolio = portfolioForRace(race, policy);
        return portfolio ? { race, portfolio } : null;
      })
      .filter(Boolean)
      .sort((a, b) => b.portfolio.raceScore - a.portfolio.raceScore || a.race.raceNo - b.race.raceNo);
    if (ranked.length < policy.raceCount) return [];
    selected.push(...ranked.slice(0, policy.raceCount));
  }
  return selected;
}

function splitUnits(totalUnits, count) {
  if (count <= 0) return [];
  const base = Math.floor(totalUnits / count);
  let remaining = totalUnits - base * count;
  return Array.from({ length: count }, () => {
    const units = base + (remaining > 0 ? 1 : 0);
    if (remaining > 0) remaining -= 1;
    return units;
  });
}

function allocatePortfolio(portfolio, targetYen, policy) {
  const totalUnits = Math.max(portfolio.anchors.length + portfolio.upsides.length, Math.floor(targetYen / 100));
  let anchorUnits = Math.round(totalUnits * policy.anchorShare);
  anchorUnits = Math.max(portfolio.anchors.length, Math.min(totalUnits - portfolio.upsides.length, anchorUnits));
  const upsideUnits = totalUnits - anchorUnits;
  const anchorSplit = splitUnits(anchorUnits, portfolio.anchors.length);
  const upsideWeights = portfolio.upsides.map((row) => Math.max(1, row.upsideScore));
  const upsideWeightTotal = upsideWeights.reduce((sum, value) => sum + value, 0);
  const upsideRaw = upsideWeights.map((value) => upsideUnits * value / upsideWeightTotal);
  const upsideSplit = upsideRaw.map((value) => Math.max(1, Math.floor(value)));
  let assigned = upsideSplit.reduce((sum, value) => sum + value, 0);
  while (assigned > upsideUnits) {
    const index = upsideSplit.findIndex((value) => value > 1);
    if (index < 0) break;
    upsideSplit[index] -= 1;
    assigned -= 1;
  }
  while (assigned < upsideUnits) {
    let bestIndex = 0;
    let bestFraction = -1;
    for (let index = 0; index < upsideRaw.length; index += 1) {
      const fraction = upsideRaw[index] - Math.floor(upsideRaw[index]);
      if (fraction > bestFraction) {
        bestFraction = fraction;
        bestIndex = index;
      }
    }
    upsideSplit[bestIndex] += 1;
    assigned += 1;
  }
  return [
    ...portfolio.anchors.map((row, index) => ({ ...row, stakeYen: (anchorSplit[index] ?? 1) * 100 })),
    ...portfolio.upsides.map((row, index) => ({ ...row, stakeYen: (upsideSplit[index] ?? 1) * 100 }))
  ];
}

function evaluate(records, policy, targetYen) {
  const selections = selectPolicyRaces(records, policy);
  if (!selections.length) {
    return { valid: false, races: 0, roi: 0, hit: 0, minMonth: 0, volatility: 999, profit: -1e9, stake: 0, returned: 0 };
  }
  let stake = 0;
  let returned = 0;
  let hitRaces = 0;
  const months = new Map();
  for (const { race, portfolio } of selections) {
    const tickets = allocatePortfolio(portfolio, targetYen, policy);
    let raceReturn = 0;
    for (const ticket of tickets) {
      const value = Math.round(ticket.stakeYen / 100 * ticket.returnPer100);
      stake += ticket.stakeYen;
      returned += value;
      raceReturn += value;
    }
    if (raceReturn > 0) hitRaces += 1;
    const month = race.raceDate.slice(0, 7);
    const monthRow = months.get(month) ?? { stake: 0, returned: 0 };
    monthRow.stake += tickets.reduce((sum, ticket) => sum + ticket.stakeYen, 0);
    monthRow.returned += raceReturn;
    months.set(month, monthRow);
  }
  const roi = stake > 0 ? returned / stake * 100 : 0;
  const hit = selections.length ? hitRaces / selections.length * 100 : 0;
  const monthRois = [...months.values()].map((row) => row.stake > 0 ? row.returned / row.stake * 100 : 0);
  const minMonth = monthRois.length ? Math.min(...monthRois) : 0;
  return {
    valid: true,
    races: selections.length,
    roi,
    hit,
    minMonth,
    volatility: standardDeviation(monthRois),
    profit: returned - stake,
    stake,
    returned,
    monthlyRois: Object.fromEntries([...months.entries()].map(([month, row]) => [month, row.stake > 0 ? row.returned / row.stake * 100 : 0]))
  };
}

function validationScore(result) {
  if (!result.valid) return -1e12;
  const hitPenalty = Math.max(0, requiredHitRatePct - result.hit) * 80;
  const monthPenalty = Math.max(0, requiredMonthRoiPct - result.minMonth) * 45;
  const gateBonus = result.hit >= requiredHitRatePct && result.minMonth >= requiredMonthRoiPct ? 1e6 : 0;
  return gateBonus + result.minMonth * 60 + result.roi * 20 + result.hit * 8 - result.volatility * 2 - hitPenalty - monthPenalty;
}

function searchCourse(validation, targetYen, seed) {
  const random = mulberry32(seed);
  const best = [];
  const seen = new Set();
  for (let iteration = 0; iteration < searchIterations; iteration += 1) {
    const policy = randomPolicy(random);
    const key = policyKey(policy);
    if (seen.has(key)) continue;
    seen.add(key);
    const result = evaluate(validation, policy, targetYen);
    const score = validationScore(result);
    if (best.length < 40 || score > best[best.length - 1].score) {
      best.push({ policy, result, score });
      best.sort((a, b) => b.score - a.score);
      if (best.length > 40) best.pop();
    }
  }
  const eligible = best
    .filter((row) => row.result.hit >= requiredHitRatePct && row.result.minMonth >= requiredMonthRoiPct)
    .sort((a, b) => b.result.minMonth - a.result.minMonth || b.result.roi - a.result.roi);
  return { winner: eligible[0] ?? null, nearMisses: best.slice(0, 10), tried: seen.size };
}

async function main() {
  const [universe, budget, betting, scope] = await Promise.all([
    import("../dist-test/src/v1/betting-candidate-universe.js"),
    import("../dist-test/src/v1/budget-courses.js"),
    import("../dist-test/src/v1/learned-betting-policy.js"),
    import("../dist-test/src/v1/walk-forward-scope.js")
  ]);

  const races = await sql(`
    SELECT r.race_id raceId,r.race_date raceDate,r.venue,r.race_no raceNo,
           r.surface,r.distance_m distanceM,r.track_condition trackCondition,
           r.refund_horse_nos_json refunds,p.id predictionId
    FROM rt_races r
    JOIN rt_predictions p ON p.race_id=r.race_id
    WHERE p.model_version=? AND p.status='locked'
      AND r.race_date BETWEEN ? AND ?
    ORDER BY r.race_date,r.venue,r.race_no
  `, [
    scope.WALK_FORWARD_BASE_MODEL_VERSION,
    scope.WALK_FORWARD_TRAIN_START_DATE,
    scope.WALK_FORWARD_HOLDOUT_END_DATE
  ]);

  const runnersByRace = new Map();
  const payoutsByRace = new Map();
  for (const predictionIds of chunks(races.map((row) => num(row.predictionId)), 80)) {
    for (const row of await sql(`
      SELECT p.race_id raceId,pr.horse_no horseNo,pr.horse_name horseName,
             pr.win_probability winProbability,pr.place_probability placeProbability,
             pr.fair_odds fairOdds,pr.current_odds currentOdds,
             pr.expected_value_pct expectedValuePct,pr.predicted_order predictedOrder,
             pr.explanation,rr.popularity
      FROM rt_prediction_runners pr
      JOIN rt_predictions p ON p.id=pr.prediction_id
      LEFT JOIN rt_runners rr ON rr.race_id=p.race_id AND rr.horse_no=pr.horse_no
      WHERE pr.prediction_id IN (SELECT value FROM json_each(?))
      ORDER BY p.race_id,pr.predicted_order
    `, [JSON.stringify(predictionIds)])) {
      const rows = runnersByRace.get(row.raceId) ?? [];
      rows.push({
        horseNo: num(row.horseNo),
        horseName: row.horseName,
        winProbability: num(row.winProbability),
        placeProbability: num(row.placeProbability),
        fairOdds: num(row.fairOdds),
        currentOdds: row.currentOdds === null ? null : num(row.currentOdds),
        expectedValuePct: row.expectedValuePct === null ? null : num(row.expectedValuePct),
        predictedOrder: num(row.predictedOrder),
        explanation: row.explanation ?? "",
        popularity: row.popularity === null ? null : num(row.popularity)
      });
      runnersByRace.set(row.raceId, rows);
    }
  }

  for (const raceIds of chunks(races.map((row) => row.raceId), 100)) {
    for (const row of await sql(`
      SELECT race_id raceId,bet_type betType,combination,payout_yen payoutYen
      FROM rt_payouts
      WHERE race_id IN (SELECT value FROM json_each(?))
    `, [JSON.stringify(raceIds)])) {
      payoutsByRace.set(row.raceId, [...(payoutsByRace.get(row.raceId) ?? []), row]);
    }
  }

  const trainMonths = [...new Set(races
    .filter((row) => row.raceDate <= scope.WALK_FORWARD_TRAIN_END_DATE)
    .map((row) => row.raceDate.slice(0, 7)))].sort();
  const monthIndex = new Map(trainMonths.map((month, index) => [month, index]));
  const records = [];
  const trainingCandidates = [];

  for (const rawRace of races) {
    const predictions = runnersByRace.get(rawRace.raceId) ?? [];
    if (predictions.length < 3) continue;
    const ranked = [...predictions].sort((a, b) => a.predictedOrder - b.predictedOrder);
    const modelScore = betting.learnedPredictionRaceScore(predictions);
    if (!Number.isFinite(modelScore)) continue;
    const race = {
      raceId: rawRace.raceId,
      raceDate: rawRace.raceDate,
      venue: rawRace.venue,
      raceNo: num(rawRace.raceNo),
      surface: rawRace.surface,
      distanceM: num(rawRace.distanceM),
      trackCondition: rawRace.trackCondition,
      fieldSize: predictions.length,
      topWinProbability: ranked[0]?.winProbability ?? 0,
      probabilityGap: (ranked[0]?.winProbability ?? 0) - (ranked[1]?.winProbability ?? 0),
      modelScore
    };
    const refunds = new Set(JSON.parse(rawRace.refunds || "[]"));
    const payoutMap = new Map((payoutsByRace.get(rawRace.raceId) ?? []).map((row) => [
      `${row.betType}:${canonical(row.betType, row.combination)}`,
      num(row.payoutYen)
    ]));
    const month = race.raceDate.slice(0, 7);
    const monthPosition = monthIndex.get(month) ?? 0;
    const fold = Math.min(3, Math.floor(monthPosition * 4 / Math.max(1, trainMonths.length)));
    const candidates = universe.buildBettingCandidateUniverse(predictions, 7).map((candidate) => {
      const horses = (candidate.combination.match(/\d{1,2}/g) ?? []).map(Number);
      const returnPer100 = horses.some((horse) => refunds.has(horse))
        ? 100
        : payoutMap.get(`${candidate.betType}:${canonical(candidate.betType, candidate.combination)}`) ?? 0;
      return enrichCandidate(candidate, race, predictions, returnPer100, fold);
    });
    if (!candidates.length) continue;
    const split = race.raceDate <= scope.WALK_FORWARD_TRAIN_END_DATE
      ? "train"
      : race.raceDate <= scope.WALK_FORWARD_VALIDATION_END_DATE
        ? "validation"
        : "holdout";
    const record = { ...race, split, candidates };
    records.push(record);
    if (split === "train") trainingCandidates.push(...candidates);
  }

  const model = buildModel(trainingCandidates);
  for (const record of records) {
    record.candidates = record.candidates.map((candidate) => model.score(candidate));
  }

  const validation = records.filter((row) => row.split === "validation");
  const holdout = records.filter((row) => row.split === "holdout");
  const courses = ["ライト", "スタンダード", "プレミアム"];
  const validationReport = {};
  const holdoutReport = {};

  for (let index = 0; index < courses.length; index += 1) {
    const course = courses[index];
    const target = budget.COURSE_TARGET_STAKES[course];
    console.log(`Searching direct barbell policy for ${course}...`);
    const search = searchCourse(validation, target, 20260806 + index * 97);
    if (!search.winner) {
      validationReport[course] = {
        passed: false,
        triedPolicies: search.tried,
        bestNearMisses: search.nearMisses.map((row) => ({
          policy: row.policy,
          roi: round(row.result.roi),
          hit: round(row.result.hit),
          minMonth: round(row.result.minMonth),
          monthlyRois: Object.fromEntries(Object.entries(row.result.monthlyRois ?? {}).map(([key, value]) => [key, round(value)]))
        }))
      };
      holdoutReport[course] = null;
      console.log(`${course}: no validation policy passed both monthly ROI and hit-rate gates.`);
      continue;
    }
    const winner = search.winner;
    validationReport[course] = {
      passed: true,
      policy: winner.policy,
      roi: round(winner.result.roi),
      hit: round(winner.result.hit),
      minMonth: round(winner.result.minMonth),
      monthlyRois: Object.fromEntries(Object.entries(winner.result.monthlyRois).map(([key, value]) => [key, round(value)])),
      races: winner.result.races,
      triedPolicies: search.tried
    };
    const holdoutResult = evaluate(holdout, winner.policy, target);
    holdoutReport[course] = {
      roi: round(holdoutResult.roi),
      hit: round(holdoutResult.hit),
      profit: holdoutResult.profit,
      races: holdoutResult.races,
      pass200: holdoutResult.roi >= targetRoiPct,
      hitRequirementMet: holdoutResult.hit >= requiredHitRatePct
    };
    console.log(`${course}: validation ${round(winner.result.roi)}% / min month ${round(winner.result.minMonth)}% / holdout ${round(holdoutResult.roi)}% / hit ${round(holdoutResult.hit)}%`);
  }

  const promotionEligible = courses.every((course) =>
    validationReport[course]?.passed
    && holdoutReport[course]?.pass200
    && holdoutReport[course]?.hitRequirementMet
  );

  const report = {
    generatedAt: new Date().toISOString(),
    method: "Standalone direct barbell search using exact payouts. Separate anchor and upside tickets; jointly optimize race count, filters and stake split on validation only.",
    targetRoiPct,
    requiredHitRatePct,
    requiredValidationMonthRoiPct: requiredMonthRoiPct,
    minimumRacesPerVenueDay: 5,
    training: {
      races: new Set(trainingCandidates.map((row) => row.raceId)).size,
      tickets: trainingCandidates.length,
      segments: model.size,
      months: trainMonths
    },
    validation: validationReport,
    holdout: holdoutReport,
    promotionEligible
  };

  await (await import("node:fs/promises")).writeFile(
    "direct-barbell-search.json",
    JSON.stringify(report, null, 2) + "\n"
  );
  console.log(`Promotion eligible: ${promotionEligible ? "YES" : "NO"}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
