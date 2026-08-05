const token = process.env.CLOUDFLARE_API_TOKEN;
const account = process.env.CLOUDFLARE_ACCOUNT_ID || "3c6d1826b573b2e68cb13ec37e9e8ade";
const database = process.env.CLOUDFLARE_D1_DATABASE_ID || "949b5e8b-d1a4-4c4e-80d1-d031afdc03de";
const endpoint = `https://api.cloudflare.com/client/v4/accounts/${account}/d1/database/${database}/query`;
const courses = ["ライト", "スタンダード", "プレミアム"];
const baselineHitRequirement = 36.8;
const beamSize = 10;

const profiles = {
  single: new Set(["単勝"]),
  wide: new Set(["ワイド"]),
  quinella: new Set(["馬連"]),
  trio: new Set(["3連複"]),
  trifecta: new Set(["3連単"]),
  singleWide: new Set(["単勝", "ワイド"]),
  wideQuinella: new Set(["ワイド", "馬連"]),
  stable: new Set(["単勝", "ワイド", "馬連"]),
  middle: new Set(["ワイド", "馬連", "馬単", "3連複"]),
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

function candidateScore(row, mode) {
  const expected = Math.max(0.01, row.expectedValuePct / 100);
  const edge = Math.max(0.001, expected - 1);
  const hit = Math.max(0.000001, row.hitProbability);
  if (mode === "edge") return edge * Math.sqrt(hit) * row.reliability;
  if (mode === "hit") return hit * expected * row.reliability;
  if (mode === "balanced") return expected * Math.pow(hit, 0.7) * row.reliability;
  return expected * Math.sqrt(hit) * row.reliability / Math.sqrt(Math.max(1.1, row.assumedOdds));
}

function raceRank(row, mode) {
  const bestValue = row.candidates.reduce(
    (maximum, candidate) => Math.max(maximum, candidateScore(candidate, "value")),
    0
  );
  const bestEdge = row.candidates.reduce(
    (maximum, candidate) => Math.max(maximum, candidateScore(candidate, "edge")),
    0
  );
  const bestHit = row.candidates.reduce(
    (maximum, candidate) => Math.max(maximum, candidateScore(candidate, "hit")),
    0
  );
  if (mode === "model") return row.modelScore;
  if (mode === "value") return bestValue;
  if (mode === "edge") return bestEdge;
  if (mode === "confidence") return row.topWinProbability * 4 + row.probabilityGap * 6 + bestHit;
  return row.modelScore + bestEdge * 3 + bestHit;
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

function policyKey(policy) {
  return JSON.stringify(policy);
}

function filterCandidates(race, policy) {
  const allowed = profiles[policy.profile] ?? profiles.all;
  let rows = race.candidates.filter((row) =>
    allowed.has(row.betType)
    && row.expectedValuePct >= policy.minEv
    && row.hitProbability >= policy.minHit
    && row.assumedOdds <= policy.maxOdds
    && row.maximumRank <= policy.maxRank
    && (policy.includesFirst === "any"
      || (policy.includesFirst === "yes" && row.includesFirst)
      || (policy.includesFirst === "no" && !row.includesFirst))
  );

  if (!rows.length) {
    rows = race.candidates
      .filter((row) => allowed.has(row.betType))
      .sort((a, b) => b.hitProbability - a.hitProbability || b.expectedValuePct - a.expectedValuePct)
      .slice(0, 1);
  }
  if (!rows.length) {
    rows = [...race.candidates]
      .sort((a, b) => b.hitProbability - a.hitProbability || b.expectedValuePct - a.expectedValuePct)
      .slice(0, 1);
  }
  return rows
    .sort((a, b) => candidateScore(b, policy.scoreMode) - candidateScore(a, policy.scoreMode))
    .slice(0, policy.maxTickets);
}

function allocate(rows, target, policy) {
  if (!rows.length) return [];
  const units = Math.max(rows.length, Math.floor(target / 100));
  const stakes = rows.map(() => 1);
  let remaining = units - rows.length;
  const weights = rows.map((row) => {
    if (policy.stakeMode === "equal") return 1;
    if (policy.stakeMode === "hit") return Math.max(0.000001, row.hitProbability);
    return Math.max(0.000001, candidateScore(row, policy.scoreMode));
  });
  const weightTotal = weights.reduce((sum, value) => sum + value, 0);
  const exact = weights.map((value) => remaining * value / weightTotal);
  const additions = exact.map(Math.floor);
  remaining -= additions.reduce((sum, value) => sum + value, 0);
  for (const row of exact
    .map((value, index) => ({ index, fraction: value - Math.floor(value) }))
    .sort((a, b) => b.fraction - a.fraction)) {
    if (remaining <= 0) break;
    additions[row.index] += 1;
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
    const tickets = allocate(filterCandidates(race, policy), target, policy);
    let raceReturn = 0;
    for (const ticket of tickets) {
      const value = Math.round(ticket.stakeYen / 100 * ticket.returnPer100);
      stake += ticket.stakeYen;
      returned += value;
      raceReturn += value;
    }
    if (raceReturn > 0) hitRaces += 1;
    const month = race.raceDate.slice(0, 7);
    const monthly = months.get(month) ?? { stake: 0, returned: 0 };
    monthly.stake += tickets.reduce((sum, row) => sum + row.stakeYen, 0);
    monthly.returned += raceReturn;
    months.set(month, monthly);
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
    score: minMonth * 0.5 + roi * 0.35 + hit * 0.15
  };
}

function retain(rows) {
  const unique = new Map();
  for (const row of rows) {
    const key = policyKey(row.policy);
    const existing = unique.get(key);
    if (!existing || row.result.score > existing.result.score) unique.set(key, row);
  }
  const values = [...unique.values()];
  const eligible = values.filter((row) => row.result.hit >= baselineHitRequirement);
  return (eligible.length ? eligible : values)
    .sort((a, b) => b.result.score - a.result.score || b.result.roi - a.result.roi)
    .slice(0, beamSize);
}

function expandBeam(records, target) {
  let beam = [];
  for (const profile of Object.keys(profiles)) {
    for (const scoreMode of ["value", "edge", "hit", "balanced"]) {
      const policy = {
        profile,
        scoreMode,
        minEv: 0,
        minHit: 0,
        maxOdds: 2500,
        maxRank: 7,
        includesFirst: "any",
        maxTickets: 1,
        stakeMode: "equal"
      };
      beam.push({ policy, result: evaluate(records, policy, target) });
    }
  }
  beam = retain(beam);

  const dimensions = [
    ["minEv", [0, 90, 100, 105, 110, 120, 130, 150, 180, 220]],
    ["minHit", [0, 0.005, 0.01, 0.02, 0.04, 0.06, 0.1, 0.15, 0.25]],
    ["maxOdds", [5, 10, 20, 40, 80, 150, 500, 2500]],
    ["maxRank", [2, 3, 4, 5, 7]],
    ["includesFirst", ["any", "yes", "no"]],
    ["maxTickets", [1, 2, 3, 4, 6]],
    ["stakeMode", ["equal", "score", "hit"]]
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

function simpleRaceScreen(records) {
  const ticketPolicy = {
    profile: "all",
    scoreMode: "edge",
    minEv: 100,
    minHit: 0.01,
    maxOdds: 2500,
    maxRank: 7,
    includesFirst: "any",
    maxTickets: 1,
    stakeMode: "equal"
  };
  const result = evaluate(records, ticketPolicy, 100);
  return result.score;
}

async function main() {
  const [universe, budget, betting, state, scope] = await Promise.all([
    import("../dist-test/src/v1/betting-candidate-universe.js"),
    import("../dist-test/src/v1/budget-courses.js"),
    import("../dist-test/src/v1/learned-betting-policy.js"),
    import("../dist-test/src/v1/learned-calibration-state.js"),
    import("../dist-test/src/v1/walk-forward-scope.js")
  ]);

  const races = await sql(`
    SELECT r.race_id raceId,r.race_date raceDate,r.venue,r.race_no raceNo,
           r.refund_horse_nos_json refunds,p.id predictionId
    FROM rt_races r
    JOIN rt_predictions p ON p.race_id=r.race_id
    WHERE p.model_version=? AND p.status='locked'
      AND (r.race_date BETWEEN ? AND ? OR r.race_date BETWEEN ? AND ?)
    ORDER BY r.race_date,r.venue,r.race_no
  `, [
    state.WORKER_LEARNED_MODEL_VERSION,
    scope.WALK_FORWARD_VALIDATION_START_DATE,
    scope.WALK_FORWARD_VALIDATION_END_DATE,
    scope.WALK_FORWARD_HOLDOUT_START_DATE,
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
      const values = runnersByRace.get(row.raceId) ?? [];
      values.push({
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
      runnersByRace.set(row.raceId, values);
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
  for (const race of races) {
    const predictions = runnersByRace.get(race.raceId) ?? [];
    if (predictions.length < 3) continue;
    const modelScore = betting.learnedPredictionRaceScore(predictions);
    if (!Number.isFinite(modelScore)) continue;
    const ranked = [...predictions].sort((a, b) => a.predictedOrder - b.predictedOrder);
    const refunds = new Set(JSON.parse(race.refunds || "[]"));
    const payoutMap = new Map((payoutsByRace.get(race.raceId) ?? []).map((row) => [
      `${row.betType}:${canonical(row.betType, row.combination)}`,
      num(row.payoutYen)
    ]));
    const candidates = universe.buildBettingCandidateUniverse(predictions, 7).map((candidate) => {
      const horses = (candidate.combination.match(/\d{1,2}/g) ?? []).map(Number);
      const returnPer100 = horses.some((horse) => refunds.has(horse))
        ? 100
        : payoutMap.get(`${candidate.betType}:${canonical(candidate.betType, candidate.combination)}`) ?? 0;
      return { ...candidate, returnPer100 };
    });
    if (!candidates.length) continue;
    records.push({
      raceId: race.raceId,
      raceDate: race.raceDate,
      venue: race.venue,
      raceNo: num(race.raceNo),
      modelScore,
      topWinProbability: ranked[0]?.winProbability ?? 0,
      probabilityGap: (ranked[0]?.winProbability ?? 0) - (ranked[1]?.winProbability ?? 0),
      candidates
    });
  }

  const validation = records.filter((row) =>
    row.raceDate >= scope.WALK_FORWARD_VALIDATION_START_DATE
    && row.raceDate <= scope.WALK_FORWARD_VALIDATION_END_DATE
  );
  const holdout = records.filter((row) =>
    row.raceDate >= scope.WALK_FORWARD_HOLDOUT_START_DATE
    && row.raceDate <= scope.WALK_FORWARD_HOLDOUT_END_DATE
  );

  const raceConfigurations = [];
  for (const mode of ["model", "value", "edge", "confidence", "balanced"]) {
    for (const count of [5, 6, 7, 8, 9, 10, 11, 12]) {
      const selected = selectRaces(validation, count, mode);
      raceConfigurations.push({ mode, count, score: simpleRaceScreen(selected) });
    }
  }
  raceConfigurations.sort((a, b) => b.score - a.score);
  const finalists = raceConfigurations.slice(0, 2);
  const searched = [];

  for (const config of finalists) {
    console.log(`Searching policies for ${config.mode}/${config.count}R...`);
    const selected = selectRaces(validation, config.count, config.mode);
    const policies = {};
    for (const course of courses) {
      const winner = expandBeam(selected, budget.COURSE_TARGET_STAKES[course]);
      if (!winner) throw new Error(`NO_POLICY:${config.mode}:${config.count}:${course}`);
      policies[course] = winner;
      console.log(`${course}: validation ROI ${round(winner.result.roi)}% / hit ${round(winner.result.hit)}% / min month ${round(winner.result.minMonth)}%`);
    }
    const minRoi = Math.min(...courses.map((course) => policies[course].result.roi));
    const minHit = Math.min(...courses.map((course) => policies[course].result.hit));
    const minMonth = Math.min(...courses.map((course) => policies[course].result.minMonth));
    searched.push({
      ...config,
      policies,
      aggregateScore: minMonth * 0.5 + minRoi * 0.35 + minHit * 0.15
    });
  }

  searched.sort((a, b) => b.aggregateScore - a.aggregateScore);
  const winner = searched[0];
  if (!winner) throw new Error("NO_EXPANDED_POLICY_WINNER");
  const holdoutRows = selectRaces(holdout, winner.count, winner.mode);
  const holdoutMetrics = Object.fromEntries(courses.map((course) => [
    course,
    evaluate(holdoutRows, winner.policies[course].policy, budget.COURSE_TARGET_STAKES[course])
  ]));

  const report = {
    generatedAt: new Date().toISOString(),
    targetRoiPct: 200,
    minimumRacesPerVenueDay: 5,
    method: "Expanded candidate universe. Race and ticket policies selected on validation only; holdout evaluated after selection.",
    candidatePoolHorses: 7,
    raceConfigurationFinalists: finalists,
    selectedRaceConfiguration: { mode: winner.mode, count: winner.count },
    validation: Object.fromEntries(courses.map((course) => [course, {
      policy: winner.policies[course].policy,
      roi: round(winner.policies[course].result.roi),
      hit: round(winner.policies[course].result.hit),
      minMonth: round(winner.policies[course].result.minMonth),
      profit: winner.policies[course].result.profit
    }])),
    holdout: Object.fromEntries(courses.map((course) => [course, {
      roi: round(holdoutMetrics[course].roi),
      hit: round(holdoutMetrics[course].hit),
      profit: holdoutMetrics[course].profit,
      pass200: holdoutMetrics[course].roi >= 200
    }]))
  };

  await (await import("node:fs/promises")).writeFile(
    "expanded-policy-search.json",
    JSON.stringify(report, null, 2) + "\n"
  );
  console.log(`Winner: ${winner.mode}/${winner.count}R`);
  for (const course of courses) {
    console.log(`${course}: validation ${report.validation[course].roi}% / holdout ${report.holdout[course].roi}% / hit ${report.holdout[course].hit}%`);
  }
  console.log("Expanded result: expanded-policy-search.json");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
