const token = process.env.CLOUDFLARE_API_TOKEN;
const account = process.env.CLOUDFLARE_ACCOUNT_ID || "3c6d1826b573b2e68cb13ec37e9e8ade";
const database = process.env.CLOUDFLARE_D1_DATABASE_ID || "949b5e8b-d1a4-4c4e-80d1-d031afdc03de";
const endpoint = `https://api.cloudflare.com/client/v4/accounts/${account}/d1/database/${database}/query`;
const courses = ["ライト", "スタンダード", "プレミアム"];
const requiredHitRatePct = 36.8;
const beamSize = 16;

const profiles = {
  single: new Set(["単勝"]),
  wide: new Set(["ワイド"]),
  singleWide: new Set(["単勝", "ワイド"]),
  stable: new Set(["単勝", "ワイド", "馬連"]),
  trio: new Set(["3連複"]),
  noTrifecta: new Set(["単勝", "ワイド", "馬連", "馬単", "3連複"]),
  exotics: new Set(["馬連", "馬単", "3連複", "3連単"]),
  all: new Set(["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"])
};

if (!token) throw new Error("CLOUDFLARE_API_TOKEN is not set");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const num = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const round = (value) => Number(value.toFixed(1));
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
      await sleep(60);
      return payload.result?.[0]?.results ?? [];
    } catch (error) {
      lastError = error;
      if (attempt === 6) throw error;
      await sleep(attempt * 1500);
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

function enrichCandidate(candidate, race, returnPer100) {
  return {
    betType: candidate.betType,
    combination: candidate.combination,
    hitProbability: candidate.hitProbability,
    rankSum: candidate.rankSum,
    maximumRank: candidate.maximumRank,
    includesFirst: candidate.includesFirst,
    returnPer100,
    hitBucket: bucket(candidate.hitProbability, [0.003, 0.007, 0.015, 0.03, 0.06, 0.1, 0.16, 0.25, 0.4], ["h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9", "h10"]),
    rankBucket: bucket(candidate.rankSum, [3, 5, 8, 12, 17], ["r1", "r2", "r3", "r4", "r5", "r6"]),
    fieldBucket: bucket(race.fieldSize, [10, 14, 17], ["f1", "f2", "f3", "f4"]),
    topBucket: bucket(race.topWinProbability, [0.2, 0.3, 0.4, 0.5], ["t1", "t2", "t3", "t4", "t5"]),
    gapBucket: bucket(race.probabilityGap, [0.03, 0.07, 0.12, 0.2], ["g1", "g2", "g3", "g4", "g5"]),
    raceNoBucket: bucket(race.raceNo, [5, 9], ["early", "middle", "late"]),
    surface: race.surface || "unknown",
    distanceBucket: bucket(race.distanceM, [1400, 1800, 2200], ["d1", "d2", "d3", "d4"]),
    trackCondition: race.trackCondition || "unknown"
  };
}

function featureKeys(row) {
  const type = row.betType;
  return [
    ["global", "all", 1200, 0.04],
    ["type", type, 400, 0.18],
    ["typeHit", `${type}|${row.hitBucket}`, 140, 0.16],
    ["typeRank", `${type}|${row.rankBucket}`, 120, 0.12],
    ["typeMaxRank", `${type}|${row.maximumRank}`, 100, 0.08],
    ["typeFirst", `${type}|${row.includesFirst}`, 130, 0.08],
    ["typeField", `${type}|${row.fieldBucket}`, 100, 0.05],
    ["typeTop", `${type}|${row.topBucket}`, 100, 0.05],
    ["typeGap", `${type}|${row.gapBucket}`, 100, 0.05],
    ["typeVenue", `${type}|${row.venue}`, 120, 0.04],
    ["typeRaceNo", `${type}|${row.raceNoBucket}`, 100, 0.04],
    ["typeSurface", `${type}|${row.surface}`, 100, 0.04],
    ["typeDistance", `${type}|${row.distanceBucket}`, 100, 0.04],
    ["typeTrack", `${type}|${row.trackCondition}`, 100, 0.03],
    ["cell", `${type}|${row.hitBucket}|${row.rankBucket}|${row.includesFirst}`, 45, 0.1]
  ];
}

function addStat(stats, family, key, row) {
  const mapKey = `${family}:${key}`;
  const stat = stats.get(mapKey) ?? { count: 0, returned: 0, hits: 0 };
  stat.count += 1;
  stat.returned += row.returnPer100;
  stat.hits += row.returnPer100 > 0 ? 1 : 0;
  stats.set(mapKey, stat);
}

function trainPayoutModel(rows) {
  const stats = new Map();
  for (const row of rows) {
    for (const [family, key] of featureKeys(row)) addStat(stats, family, key, row);
  }
  const global = stats.get("global:all") ?? { count: 0, returned: 0, hits: 0 };
  const globalReturn = global.count > 0 ? global.returned / global.count : 75;
  const globalHit = global.count > 0 ? global.hits / global.count : 0.05;

  function estimate(family, key, priorCount) {
    const stat = stats.get(`${family}:${key}`);
    const typeKey = family === "global" ? "all" : String(key).split("|")[0];
    const parent = family === "global" ? global : stats.get(`type:${typeKey}`);
    const parentReturn = parent?.count ? parent.returned / parent.count : globalReturn;
    const parentHit = parent?.count ? parent.hits / parent.count : globalHit;
    if (!stat?.count) return { roi: parentReturn, hit: parentHit };
    return {
      roi: (stat.returned + parentReturn * priorCount) / (stat.count + priorCount),
      hit: (stat.hits + parentHit * priorCount) / (stat.count + priorCount)
    };
  }

  return {
    trainingTickets: rows.length,
    trainingRaces: new Set(rows.map((row) => row.raceId)).size,
    globalReturn,
    globalHit,
    score(row) {
      let roi = 0;
      let hit = 0;
      let weight = 0;
      for (const [family, key, prior, factorWeight] of featureKeys(row)) {
        const value = estimate(family, key, prior);
        roi += Math.max(5, Math.min(500, value.roi)) * factorWeight;
        hit += Math.max(0.0001, Math.min(0.95, value.hit)) * factorWeight;
        weight += factorWeight;
      }
      row.learnedRoi = weight > 0 ? roi / weight : globalReturn;
      row.learnedHit = weight > 0 ? hit / weight : globalHit;
      row.edgeScore = row.learnedRoi * Math.pow(Math.max(0.001, row.learnedHit), 0.22);
      return row;
    }
  };
}

function raceRank(row, mode) {
  const best = row.candidates[0];
  if (mode === "roi") return best?.learnedRoi ?? 0;
  if (mode === "hit") return best?.learnedHit ?? 0;
  if (mode === "confidence") return row.topWinProbability * 100 + row.probabilityGap * 180;
  return (best?.edgeScore ?? 0) + row.modelScore * 3 + row.topWinProbability * 20;
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
    && row.learnedRoi >= policy.minLearnedRoi
    && row.learnedHit >= policy.minLearnedHit
    && row.maximumRank <= policy.maxRank
    && (policy.includesFirst === "any"
      || (policy.includesFirst === "yes" && row.includesFirst)
      || (policy.includesFirst === "no" && !row.includesFirst))
  );
  const allowedPool = race.candidates.filter((row) => allowed.has(row.betType));
  const pool = eligible.length ? eligible : allowedPool.length ? allowedPool : race.candidates;
  return [...pool].sort((a, b) => b.edgeScore - a.edgeScore || b.learnedRoi - a.learnedRoi);
}

function portfolio(race, policy) {
  const ranked = filteredCandidates(race, policy);
  const chosen = [];
  const add = (row) => {
    if (!row) return;
    const key = `${row.betType}:${row.combination}`;
    if (!chosen.some((item) => `${item.betType}:${item.combination}` === key)) chosen.push(row);
  };
  if (policy.hedge === "hit") add([...race.candidates].sort((a, b) => b.learnedHit - a.learnedHit)[0]);
  if (policy.hedge === "single") add([...race.candidates].filter((row) => row.betType === "単勝").sort((a, b) => b.learnedHit - a.learnedHit)[0]);
  if (policy.hedge === "wide") add([...race.candidates].filter((row) => row.betType === "ワイド").sort((a, b) => b.learnedHit - a.learnedHit)[0]);
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
  const stakes = rows.map(() => 1);
  let remaining = units - rows.length;
  const weights = rows.map((row) => {
    if (policy.stakeMode === "equal") return 1;
    if (policy.stakeMode === "hit") return Math.max(0.0001, row.learnedHit);
    if (policy.stakeMode === "roi") return Math.max(0.0001, row.learnedRoi);
    return Math.max(0.0001, row.edgeScore);
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
  return rows.map((row, index) => ({
    ...row,
    stakeYen: ((stakes[index] ?? 1) + (additions[index] ?? 0)) * 100
  }));
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
    const monthRow = months.get(month) ?? { stake: 0, returned: 0 };
    monthRow.stake += tickets.reduce((sum, ticket) => sum + ticket.stakeYen, 0);
    monthRow.returned += raceReturn;
    months.set(month, monthRow);
  }
  const roi = stake > 0 ? returned / stake * 100 : 0;
  const hit = records.length > 0 ? hitRaces / records.length * 100 : 0;
  const monthRois = [...months.values()].map((row) => row.stake > 0 ? row.returned / row.stake * 100 : 0);
  const minMonth = monthRois.length ? Math.min(...monthRois) : 0;
  return {
    races: records.length,
    roi,
    hit,
    minMonth,
    profit: returned - stake,
    objective: roi * 0.5 + minMonth * 0.3 + hit * 0.2
  };
}

function retain(rows) {
  const unique = new Map();
  for (const row of rows) {
    const key = JSON.stringify(row.policy);
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
    ? ["single", "wide", "singleWide", "stable", "noTrifecta", "all"]
    : course === "スタンダード"
      ? ["singleWide", "stable", "trio", "noTrifecta", "exotics", "all"]
      : ["stable", "trio", "noTrifecta", "exotics", "all"];

  let beam = [];
  for (const profile of courseProfiles) {
    for (const stakeMode of ["equal", "edge", "hit", "roi"]) {
      const policy = {
        profile,
        stakeMode,
        minLearnedRoi: 0,
        minLearnedHit: 0,
        maxRank: 6,
        includesFirst: "any",
        ticketCount: 2,
        hedge: "none"
      };
      beam.push({ policy, result: evaluate(records, policy, target) });
    }
  }
  beam = retain(beam);

  const dimensions = [
    ["minLearnedRoi", [0, 60, 75, 85, 95, 105, 120, 140, 170, 220]],
    ["minLearnedHit", [0, 0.005, 0.01, 0.02, 0.04, 0.07, 0.1, 0.15, 0.25]],
    ["maxRank", [2, 3, 4, 5, 6]],
    ["includesFirst", ["any", "yes", "no"]],
    ["ticketCount", [1, 2, 3, 4, 6, 8]],
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

  const records = [];
  const trainingCandidates = [];
  for (const race of races) {
    const predictions = runnersByRace.get(race.raceId) ?? [];
    if (predictions.length < 3) continue;
    const ranked = [...predictions].sort((a, b) => a.predictedOrder - b.predictedOrder);
    const modelScore = betting.learnedPredictionRaceScore(predictions);
    if (!Number.isFinite(modelScore)) continue;
    const raceContext = {
      raceId: race.raceId,
      raceDate: race.raceDate,
      venue: race.venue,
      raceNo: num(race.raceNo),
      surface: race.surface,
      distanceM: num(race.distanceM),
      trackCondition: race.trackCondition,
      fieldSize: predictions.length,
      topWinProbability: ranked[0]?.winProbability ?? 0,
      probabilityGap: (ranked[0]?.winProbability ?? 0) - (ranked[1]?.winProbability ?? 0),
      modelScore
    };
    const refunds = new Set(JSON.parse(race.refunds || "[]"));
    const payoutMap = new Map((payoutsByRace.get(race.raceId) ?? []).map((row) => [
      `${row.betType}:${canonical(row.betType, row.combination)}`,
      num(row.payoutYen)
    ]));
    const candidates = universe.buildBettingCandidateUniverse(predictions, 6).map((candidate) => {
      const horses = (candidate.combination.match(/\d{1,2}/g) ?? []).map(Number);
      const returnPer100 = horses.some((horse) => refunds.has(horse))
        ? 100
        : payoutMap.get(`${candidate.betType}:${canonical(candidate.betType, candidate.combination)}`) ?? 0;
      return enrichCandidate(candidate, raceContext, returnPer100);
    });
    if (!candidates.length) continue;
    const split = race.raceDate <= scope.WALK_FORWARD_TRAIN_END_DATE
      ? "train"
      : race.raceDate <= scope.WALK_FORWARD_VALIDATION_END_DATE
        ? "validation"
        : "holdout";
    const record = { ...raceContext, split, candidates };
    records.push(record);
    if (split === "train") {
      for (const candidate of candidates) trainingCandidates.push({ ...candidate, ...raceContext });
    }
  }

  const model = trainPayoutModel(trainingCandidates);
  for (const record of records) {
    record.candidates = record.candidates
      .map((candidate) => model.score(candidate))
      .sort((a, b) => b.edgeScore - a.edgeScore || b.learnedRoi - a.learnedRoi);
  }

  const validation = records.filter((row) => row.split === "validation");
  const holdout = records.filter((row) => row.split === "holdout");
  const raceConfigs = [];
  const defaultPolicy = {
    profile: "all",
    stakeMode: "equal",
    minLearnedRoi: 0,
    minLearnedHit: 0,
    maxRank: 6,
    includesFirst: "any",
    ticketCount: 2,
    hedge: "hit"
  };
  for (const mode of ["edge", "roi", "hit", "confidence"]) {
    for (const count of [5, 6, 7, 8, 9, 10, 11, 12]) {
      const selected = selectRaces(validation, count, mode);
      raceConfigs.push({ mode, count, result: evaluate(selected, defaultPolicy, 100) });
    }
  }
  raceConfigs.sort((a, b) => b.result.objective - a.result.objective);
  const finalists = raceConfigs.slice(0, 5);
  const searched = [];

  for (const config of finalists) {
    console.log(`Searching payout-only policy for ${config.mode}/${config.count}R...`);
    const selected = selectRaces(validation, config.count, config.mode);
    const policies = {};
    for (const course of courses) {
      const winner = searchPolicy(selected, budget.COURSE_TARGET_STAKES[course], course);
      if (!winner) throw new Error(`NO_PAYOUT_ONLY_POLICY:${course}`);
      policies[course] = winner;
      console.log(`${course}: validation ROI ${round(winner.result.roi)}% / hit ${round(winner.result.hit)}% / minMonth ${round(winner.result.minMonth)}%`);
    }
    const minimumRoi = Math.min(...courses.map((course) => policies[course].result.roi));
    const minimumHit = Math.min(...courses.map((course) => policies[course].result.hit));
    const minimumMonth = Math.min(...courses.map((course) => policies[course].result.minMonth));
    searched.push({
      ...config,
      policies,
      aggregate: minimumRoi * 0.5 + minimumMonth * 0.3 + minimumHit * 0.2
    });
  }

  searched.sort((a, b) => b.aggregate - a.aggregate);
  const winner = searched[0];
  if (!winner) throw new Error("NO_PAYOUT_ONLY_WINNER");
  const holdoutRows = selectRaces(holdout, winner.count, winner.mode);
  const holdoutMetrics = Object.fromEntries(courses.map((course) => [
    course,
    evaluate(holdoutRows, winner.policies[course].policy, budget.COURSE_TARGET_STAKES[course])
  ]));

  const report = {
    generatedAt: new Date().toISOString(),
    targetRoiPct: 200,
    minimumRacesPerVenueDay: 5,
    method: "Use exact JRA payout_yen as return per 100 yen and zero for losing combinations. No inferred multi-bet odds, odds buckets or odds filters are used for training or selection.",
    training: {
      races: model.trainingRaces,
      tickets: model.trainingTickets,
      globalTicketRoi: round(model.globalReturn),
      globalTicketHitPct: round(model.globalHit * 100)
    },
    selectedRaceConfiguration: { mode: winner.mode, count: winner.count },
    validation: Object.fromEntries(courses.map((course) => [course, {
      policy: winner.policies[course].policy,
      roi: round(winner.policies[course].result.roi),
      hit: round(winner.policies[course].result.hit),
      minMonth: round(winner.policies[course].result.minMonth),
      profit: winner.policies[course].result.profit,
      hitRequirementMet: winner.policies[course].result.hit >= requiredHitRatePct
    }])),
    holdout: Object.fromEntries(courses.map((course) => [course, {
      roi: round(holdoutMetrics[course].roi),
      hit: round(holdoutMetrics[course].hit),
      profit: holdoutMetrics[course].profit,
      pass200: holdoutMetrics[course].roi >= 200,
      hitRequirementMet: holdoutMetrics[course].hit >= requiredHitRatePct
    }]))
  };

  await (await import("node:fs/promises")).writeFile(
    "payout-only-policy.json",
    JSON.stringify(report, null, 2) + "\n"
  );
  console.log(`Winner: ${winner.mode}/${winner.count}R`);
  console.log(`Training: ${report.training.races} races / ${report.training.tickets} candidate tickets`);
  for (const course of courses) {
    console.log(`${course}: validation ${report.validation[course].roi}% / holdout ${report.holdout[course].roi}% / holdout hit ${report.holdout[course].hit}% / 200% ${report.holdout[course].pass200 ? "PASS" : "FAIL"}`);
  }
  console.log("Payout-only result: payout-only-policy.json");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
