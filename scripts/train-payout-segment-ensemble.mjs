const token = process.env.CLOUDFLARE_API_TOKEN;
const account = process.env.CLOUDFLARE_ACCOUNT_ID || "3c6d1826b573b2e68cb13ec37e9e8ade";
const database = process.env.CLOUDFLARE_D1_DATABASE_ID || "949b5e8b-d1a4-4c4e-80d1-d031afdc03de";
const endpoint = `https://api.cloudflare.com/client/v4/accounts/${account}/d1/database/${database}/query`;
const courses = ["ライト", "スタンダード", "プレミアム"];
const requiredHitRatePct = 36.8;
const beamSize = 20;

if (!token) throw new Error("CLOUDFLARE_API_TOKEN is not set");

const profiles = {
  single: new Set(["単勝"]),
  wide: new Set(["ワイド"]),
  singleWide: new Set(["単勝", "ワイド"]),
  stable: new Set(["単勝", "ワイド", "馬連"]),
  trio: new Set(["3連複"]),
  exotics: new Set(["馬連", "馬単", "3連複", "3連単"]),
  noTrifecta: new Set(["単勝", "ワイド", "馬連", "馬単", "3連複"]),
  all: new Set(["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"])
};

const familyConfig = {
  type: { minCount: 180, prior: 500, weight: 0.55 },
  rankPattern: { minCount: 48, prior: 90, weight: 1.2 },
  probability: { minCount: 70, prior: 130, weight: 1.05 },
  popularity: { minCount: 55, prior: 110, weight: 0.9 },
  raceContext: { minCount: 60, prior: 120, weight: 0.85 },
  condition: { minCount: 45, prior: 100, weight: 0.8 },
  cell: { minCount: 28, prior: 65, weight: 1.35 },
  venueCell: { minCount: 22, prior: 55, weight: 1.05 }
};

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
      await sleep(50);
      return payload.result?.[0]?.results ?? [];
    } catch (error) {
      lastError = error;
      if (attempt === 6) throw error;
      await sleep(attempt * 1200);
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

function standardDeviation(values) {
  if (values.length < 2) return 0;
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  return Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length);
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

function foldForDate(date, monthIndex, monthCount) {
  const month = date.slice(0, 7);
  const index = monthIndex.get(month) ?? 0;
  return Math.min(3, Math.floor(index * 4 / Math.max(1, monthCount)));
}

function orderedType(type) {
  return ["馬単", "3連単"].includes(type);
}

function enrichCandidate(candidate, race, predictions, returnPer100, fold) {
  const byHorse = new Map(predictions.map((row) => [row.horseNo, row]));
  const horses = (candidate.combination.match(/\d{1,2}/g) ?? []).map(Number);
  const ranks = horses.map((horseNo) => byHorse.get(horseNo)?.predictedOrder ?? 99);
  const popularities = horses.map((horseNo) => byHorse.get(horseNo)?.popularity ?? 99);
  const normalizedRanks = orderedType(candidate.betType) ? ranks : [...ranks].sort((a, b) => a - b);
  const normalizedPops = orderedType(candidate.betType) ? popularities : [...popularities].sort((a, b) => a - b);
  return {
    raceId: race.raceId,
    raceDate: race.raceDate,
    venue: race.venue,
    raceNo: race.raceNo,
    surface: race.surface || "unknown",
    distanceBucket: bucket(race.distanceM, [1400, 1800, 2200], ["d1", "d2", "d3", "d4"]),
    trackCondition: race.trackCondition || "unknown",
    fieldBucket: bucket(race.fieldSize, [10, 14, 17], ["f1", "f2", "f3", "f4"]),
    topBucket: bucket(race.topWinProbability, [0.2, 0.3, 0.4, 0.5], ["t1", "t2", "t3", "t4", "t5"]),
    gapBucket: bucket(race.probabilityGap, [0.03, 0.07, 0.12, 0.2], ["g1", "g2", "g3", "g4", "g5"]),
    raceNoBucket: bucket(race.raceNo, [5, 9], ["early", "middle", "late"]),
    betType: candidate.betType,
    combination: candidate.combination,
    hitProbability: candidate.hitProbability,
    hitBucket: bucket(candidate.hitProbability, [0.003, 0.007, 0.015, 0.03, 0.06, 0.1, 0.16, 0.25, 0.4], ["h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9", "h10"]),
    rankSum: candidate.rankSum,
    rankBucket: bucket(candidate.rankSum, [3, 5, 8, 12, 17], ["r1", "r2", "r3", "r4", "r5", "r6"]),
    maximumRank: candidate.maximumRank,
    includesFirst: candidate.includesFirst,
    rankPattern: normalizedRanks.join("-"),
    popularityPattern: normalizedPops.map((value) => Math.min(value, 10)).join("-"),
    includesMarketFavorite: popularities.includes(1),
    returnPer100,
    fold
  };
}

function segmentKeys(row) {
  const type = row.betType;
  return [
    ["type", type],
    ["rankPattern", `${type}|${row.rankPattern}`],
    ["probability", `${type}|${row.hitBucket}|${row.rankBucket}|${row.maximumRank}|${row.includesFirst}`],
    ["popularity", `${type}|${row.popularityPattern}|${row.includesMarketFavorite}`],
    ["raceContext", `${type}|${row.fieldBucket}|${row.topBucket}|${row.gapBucket}|${row.raceNoBucket}`],
    ["condition", `${type}|${row.surface}|${row.distanceBucket}|${row.trackCondition}`],
    ["cell", `${type}|${row.rankPattern}|${row.hitBucket}|${row.fieldBucket}|${row.raceNoBucket}`],
    ["venueCell", `${type}|${row.rankPattern}|${row.venue}|${row.surface}|${row.distanceBucket}`]
  ];
}

function addStat(map, key, row) {
  const stat = map.get(key) ?? {
    count: 0,
    returned: 0,
    hits: 0,
    folds: Array.from({ length: 4 }, () => ({ count: 0, returned: 0, hits: 0 }))
  };
  stat.count += 1;
  stat.returned += row.returnPer100;
  stat.hits += row.returnPer100 > 0 ? 1 : 0;
  const fold = stat.folds[row.fold] ?? stat.folds[0];
  fold.count += 1;
  fold.returned += row.returnPer100;
  fold.hits += row.returnPer100 > 0 ? 1 : 0;
  map.set(key, stat);
}

function buildSegmentModel(rows) {
  const stats = new Map();
  for (const row of rows) {
    for (const [family, key] of segmentKeys(row)) addStat(stats, `${family}:${key}`, row);
  }

  const typeStats = new Map();
  for (const type of Object.keys(Object.fromEntries(rows.map((row) => [row.betType, true])))) {
    typeStats.set(type, stats.get(`type:${type}`));
  }

  const scored = new Map();
  for (const [mapKey, stat] of stats) {
    const family = mapKey.slice(0, mapKey.indexOf(":"));
    const rawKey = mapKey.slice(mapKey.indexOf(":") + 1);
    const type = rawKey.split("|")[0];
    const config = familyConfig[family];
    if (!config || stat.count < config.minCount) continue;
    const parent = typeStats.get(type) ?? stat;
    const parentRoi = parent.count > 0 ? parent.returned / parent.count : 65;
    const parentHit = parent.count > 0 ? parent.hits / parent.count : 0.02;
    const foldRows = stat.folds.filter((row) => row.count >= Math.max(5, Math.floor(config.minCount / 10)));
    if (foldRows.length < 3) continue;
    const foldRois = foldRows.map((row) => row.returned / row.count);
    const foldHits = foldRows.map((row) => row.hits / row.count);
    const shrunkRoi = (stat.returned + parentRoi * config.prior) / (stat.count + config.prior);
    const shrunkHit = (stat.hits + parentHit * config.prior) / (stat.count + config.prior);
    const medianRoi = percentile(foldRois, 0.5);
    const lowerRoi = percentile(foldRois, 0.25);
    const volatility = standardDeviation(foldRois);
    const positiveFolds = foldRois.filter((value) => value >= 100).length;
    const robustRoi = shrunkRoi * 0.45 + medianRoi * 0.35 + lowerRoi * 0.2 - volatility * 0.28;
    const confidence = Math.min(1, Math.log1p(stat.count) / Math.log1p(config.minCount * 8)) * (foldRows.length / 4);
    const stabilityBonus = positiveFolds * 2.5;
    const score = robustRoi + stabilityBonus;
    scored.set(mapKey, {
      family,
      key: rawKey,
      count: stat.count,
      roi: stat.returned / stat.count,
      hit: stat.hits / stat.count,
      foldRois,
      foldHits,
      positiveFolds,
      robustRoi,
      confidence,
      score,
      weight: config.weight
    });
  }

  const topSegments = [...scored.values()]
    .filter((row) => row.family !== "type")
    .sort((a, b) => b.score * b.confidence - a.score * a.confidence)
    .slice(0, 80);

  return {
    rows: scored,
    trainingRaces: new Set(rows.map((row) => row.raceId)).size,
    trainingTickets: rows.length,
    topSegments,
    score(candidate) {
      const matches = [];
      for (const [family, key] of segmentKeys(candidate)) {
        const row = scored.get(`${family}:${key}`);
        if (row) matches.push(row);
      }
      matches.sort((a, b) => b.confidence * b.weight - a.confidence * a.weight);
      const selected = matches.slice(0, 6);
      const totalWeight = selected.reduce((sum, row) => sum + row.confidence * row.weight, 0);
      const fallback = scored.get(`type:${candidate.betType}`);
      const stableRoi = totalWeight > 0
        ? selected.reduce((sum, row) => sum + row.robustRoi * row.confidence * row.weight, 0) / totalWeight
        : fallback?.robustRoi ?? 65;
      const stableHit = totalWeight > 0
        ? selected.reduce((sum, row) => sum + row.hit * row.confidence * row.weight, 0) / totalWeight
        : fallback?.hit ?? 0.02;
      const confidence = selected.length
        ? selected.reduce((sum, row) => sum + row.confidence, 0) / selected.length
        : 0;
      return {
        ...candidate,
        stableRoi,
        stableHit,
        segmentConfidence: confidence,
        stableScore: stableRoi * Math.pow(Math.max(0.001, stableHit), 0.16) * (0.7 + confidence * 0.3),
        matchedSegments: selected.map((row) => `${row.family}:${row.key}`)
      };
    }
  };
}

function raceRank(race, mode) {
  const best = race.candidates[0];
  if (mode === "roi") return best?.stableRoi ?? 0;
  if (mode === "confidence") return (best?.segmentConfidence ?? 0) * 100 + race.topWinProbability * 20;
  if (mode === "hit") return (best?.stableHit ?? 0) * 100;
  return (best?.stableScore ?? 0) + race.modelScore * 2 + race.probabilityGap * 30;
}

function selectRaces(records, count, mode) {
  const groups = new Map();
  for (const row of records) {
    const key = `${row.raceDate}:${row.venue}`;
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  return [...groups.values()].flatMap((rows) => [...rows]
    .sort((a, b) => raceRank(b, mode) - raceRank(a, mode) || a.raceNo - b.raceNo)
    .slice(0, Math.max(5, count)));
}

function filteredCandidates(race, policy) {
  const allowed = profiles[policy.profile] ?? profiles.all;
  const eligible = race.candidates.filter((row) =>
    allowed.has(row.betType)
    && row.stableRoi >= policy.minStableRoi
    && row.stableHit >= policy.minStableHit
    && row.segmentConfidence >= policy.minConfidence
    && row.maximumRank <= policy.maxRank
    && (policy.includesFirst === "any"
      || (policy.includesFirst === "yes" && row.includesFirst)
      || (policy.includesFirst === "no" && !row.includesFirst))
  );
  const allowedPool = race.candidates.filter((row) => allowed.has(row.betType));
  const pool = eligible.length ? eligible : allowedPool.length ? allowedPool : race.candidates;
  return [...pool].sort((a, b) => b.stableScore - a.stableScore || b.stableRoi - a.stableRoi);
}

function portfolio(race, policy) {
  const ranked = filteredCandidates(race, policy);
  const chosen = [];
  const add = (row) => {
    if (!row) return;
    const key = `${row.betType}:${row.combination}`;
    if (!chosen.some((item) => `${item.betType}:${item.combination}` === key)) chosen.push(row);
  };
  if (policy.hedge === "single") add([...race.candidates].filter((row) => row.betType === "単勝").sort((a, b) => b.stableHit - a.stableHit)[0]);
  if (policy.hedge === "wide") add([...race.candidates].filter((row) => row.betType === "ワイド").sort((a, b) => b.stableHit - a.stableHit)[0]);
  if (policy.hedge === "hit") add([...race.candidates].sort((a, b) => b.stableHit - a.stableHit)[0]);
  for (const row of ranked) {
    if (chosen.length >= policy.ticketCount) break;
    add(row);
  }
  if (!chosen.length) add(race.candidates[0]);
  return chosen.slice(0, policy.ticketCount);
}

function allocate(rows, target, policy) {
  if (!rows.length) return [];
  const units = Math.max(rows.length, Math.floor(target / 100));
  let remaining = units - rows.length;
  const weights = rows.map((row) => {
    if (policy.stakeMode === "equal") return 1;
    if (policy.stakeMode === "roi") return Math.max(0.01, row.stableRoi - 50);
    if (policy.stakeMode === "hit") return Math.max(0.001, row.stableHit);
    return Math.max(0.01, row.stableScore);
  });
  const total = weights.reduce((sum, value) => sum + value, 0);
  const exact = weights.map((value) => remaining * value / total);
  const additions = exact.map(Math.floor);
  remaining -= additions.reduce((sum, value) => sum + value, 0);
  for (const item of exact
    .map((value, index) => ({ index, fraction: value - Math.floor(value) }))
    .sort((a, b) => b.fraction - a.fraction)) {
    if (remaining <= 0) break;
    additions[item.index] += 1;
    remaining -= 1;
  }
  return rows.map((row, index) => ({ ...row, stakeYen: (1 + (additions[index] ?? 0)) * 100 }));
}

function evaluate(records, policy, target) {
  let stake = 0;
  let returned = 0;
  let hitRaces = 0;
  const months = new Map();
  for (const race of records) {
    const tickets = allocate(portfolio(race, policy), target, policy);
    let raceReturn = 0;
    for (const ticket of tickets) {
      const value = Math.round(ticket.stakeYen / 100 * ticket.returnPer100);
      stake += ticket.stakeYen;
      returned += value;
      raceReturn += value;
    }
    if (raceReturn > 0) hitRaces += 1;
    const month = race.raceDate.slice(0, 7);
    const row = months.get(month) ?? { stake: 0, returned: 0 };
    row.stake += tickets.reduce((sum, ticket) => sum + ticket.stakeYen, 0);
    row.returned += raceReturn;
    months.set(month, row);
  }
  const roi = stake > 0 ? returned / stake * 100 : 0;
  const hit = records.length > 0 ? hitRaces / records.length * 100 : 0;
  const monthRois = [...months.values()].map((row) => row.stake > 0 ? row.returned / row.stake * 100 : 0);
  const minMonth = monthRois.length ? Math.min(...monthRois) : 0;
  const volatility = standardDeviation(monthRois);
  return {
    races: records.length,
    roi,
    hit,
    minMonth,
    volatility,
    profit: returned - stake,
    objective: roi * 0.44 + minMonth * 0.34 + hit * 0.18 - volatility * 0.04
  };
}

function policyKey(policy) {
  return JSON.stringify(policy);
}

function retain(rows) {
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
}

function searchPolicy(records, target, course) {
  const courseProfiles = course === "ライト"
    ? ["single", "wide", "singleWide", "stable", "all"]
    : course === "スタンダード"
      ? ["singleWide", "stable", "trio", "noTrifecta", "exotics", "all"]
      : ["stable", "trio", "noTrifecta", "exotics", "all"];
  let beam = [];
  for (const profile of courseProfiles) {
    for (const stakeMode of ["equal", "score", "roi", "hit"]) {
      const policy = {
        profile,
        stakeMode,
        minStableRoi: 0,
        minStableHit: 0,
        minConfidence: 0,
        maxRank: 5,
        includesFirst: "any",
        ticketCount: 2,
        hedge: "none"
      };
      beam.push({ policy, result: evaluate(records, policy, target) });
    }
  }
  beam = retain(beam);
  const dimensions = [
    ["minStableRoi", [0, 70, 80, 90, 100, 110, 125, 145, 175]],
    ["minStableHit", [0, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15]],
    ["minConfidence", [0, 0.25, 0.4, 0.55, 0.7]],
    ["maxRank", [2, 3, 4, 5, 6, 7]],
    ["includesFirst", ["any", "yes", "no"]],
    ["ticketCount", [1, 2, 3, 4, 6]],
    ["hedge", ["none", "hit", "single", "wide"]]
  ];
  for (const [field, values] of dimensions) {
    const expanded = [];
    for (const row of beam) {
      for (const value of values) {
        const policy = { ...row.policy, [field]: value };
        expanded.push({ policy, result: evaluate(records, policy, target) });
      }
    }
    beam = retain(expanded);
  }
  return beam[0];
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
    const fold = foldForDate(race.raceDate, monthIndex, trainMonths.length);
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

  const model = buildSegmentModel(trainingCandidates);
  for (const record of records) {
    record.candidates = record.candidates
      .map((candidate) => model.score(candidate))
      .sort((a, b) => b.stableScore - a.stableScore || b.stableRoi - a.stableRoi);
  }

  const validation = records.filter((row) => row.split === "validation");
  const holdout = records.filter((row) => row.split === "holdout");
  const raceConfigs = [];
  const defaultPolicy = {
    profile: "all",
    stakeMode: "equal",
    minStableRoi: 0,
    minStableHit: 0,
    minConfidence: 0,
    maxRank: 7,
    includesFirst: "any",
    ticketCount: 2,
    hedge: "hit"
  };
  for (const mode of ["stable", "roi", "confidence", "hit"]) {
    for (const count of [5, 6, 7, 8, 9, 10, 11, 12]) {
      const selected = selectRaces(validation, count, mode);
      raceConfigs.push({ mode, count, result: evaluate(selected, defaultPolicy, 100) });
    }
  }
  raceConfigs.sort((a, b) => b.result.objective - a.result.objective);
  const finalists = raceConfigs.slice(0, 5);
  const searched = [];

  for (const config of finalists) {
    console.log(`Searching stable payout segments for ${config.mode}/${config.count}R...`);
    const selected = selectRaces(validation, config.count, config.mode);
    const policies = {};
    for (const course of courses) {
      const winner = searchPolicy(selected, budget.COURSE_TARGET_STAKES[course], course);
      if (!winner) throw new Error(`NO_SEGMENT_POLICY:${course}`);
      policies[course] = winner;
      console.log(`${course}: validation ROI ${round(winner.result.roi)}% / hit ${round(winner.result.hit)}% / minMonth ${round(winner.result.minMonth)}%`);
    }
    const minimumRoi = Math.min(...courses.map((course) => policies[course].result.roi));
    const minimumHit = Math.min(...courses.map((course) => policies[course].result.hit));
    const minimumMonth = Math.min(...courses.map((course) => policies[course].result.minMonth));
    const volatility = Math.max(...courses.map((course) => policies[course].result.volatility));
    searched.push({
      ...config,
      policies,
      aggregate: minimumRoi * 0.44 + minimumMonth * 0.34 + minimumHit * 0.18 - volatility * 0.04
    });
  }

  searched.sort((a, b) => b.aggregate - a.aggregate);
  const winner = searched[0];
  if (!winner) throw new Error("NO_SEGMENT_WINNER");
  const holdoutRows = selectRaces(holdout, winner.count, winner.mode);
  const holdoutMetrics = Object.fromEntries(courses.map((course) => [
    course,
    evaluate(holdoutRows, winner.policies[course].policy, budget.COURSE_TARGET_STAKES[course])
  ]));

  const report = {
    generatedAt: new Date().toISOString(),
    targetRoiPct: 200,
    minimumRacesPerVenueDay: 5,
    method: "Mine payout segments on four chronological training folds using exact payout_yen/zero returns. Select race count and ticket policy on validation only; evaluate holdout once.",
    training: {
      races: model.trainingRaces,
      tickets: model.trainingTickets,
      months: trainMonths,
      stableSegments: model.rows.size,
      topSegments: model.topSegments.slice(0, 30).map((row) => ({
        family: row.family,
        key: row.key,
        count: row.count,
        roi: round(row.roi),
        hitPct: round(row.hit * 100),
        foldRois: row.foldRois.map((value) => round(value)),
        robustRoi: round(row.robustRoi),
        confidence: round(row.confidence, 3)
      }))
    },
    selectedRaceConfiguration: { mode: winner.mode, count: winner.count },
    validation: Object.fromEntries(courses.map((course) => [course, {
      policy: winner.policies[course].policy,
      roi: round(winner.policies[course].result.roi),
      hit: round(winner.policies[course].result.hit),
      minMonth: round(winner.policies[course].result.minMonth),
      volatility: round(winner.policies[course].result.volatility),
      profit: winner.policies[course].result.profit,
      hitRequirementMet: winner.policies[course].result.hit >= requiredHitRatePct
    }])),
    holdout: Object.fromEntries(courses.map((course) => [course, {
      roi: round(holdoutMetrics[course].roi),
      hit: round(holdoutMetrics[course].hit),
      profit: holdoutMetrics[course].profit,
      pass200: holdoutMetrics[course].roi >= 200,
      hitRequirementMet: holdoutMetrics[course].hit >= requiredHitRatePct
    }])),
    promotionEligible: courses.every((course) =>
      holdoutMetrics[course].roi >= 200 && holdoutMetrics[course].hit >= requiredHitRatePct
    )
  };

  await (await import("node:fs/promises")).writeFile(
    "payout-segment-ensemble.json",
    JSON.stringify(report, null, 2) + "\n"
  );
  console.log(`Winner: ${winner.mode}/${winner.count}R`);
  console.log(`Training: ${report.training.races} races / ${report.training.tickets} tickets / ${report.training.stableSegments} stable segments`);
  for (const course of courses) {
    console.log(`${course}: validation ${report.validation[course].roi}% / holdout ${report.holdout[course].roi}% / hit ${report.holdout[course].hit}% / 200% ${report.holdout[course].pass200 ? "PASS" : "FAIL"}`);
  }
  console.log(`Promotion eligible: ${report.promotionEligible ? "YES" : "NO"}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
