const token = process.env.CLOUDFLARE_API_TOKEN;
const account = process.env.CLOUDFLARE_ACCOUNT_ID || "3c6d1826b573b2e68cb13ec37e9e8ade";
const database = process.env.CLOUDFLARE_D1_DATABASE_ID || "949b5e8b-d1a4-4c4e-80d1-d031afdc03de";
const endpoint = `https://api.cloudflare.com/client/v4/accounts/${account}/d1/database/${database}/query`;
const courses = ["ライト", "スタンダード", "プレミアム"];
const venues = ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"];
const requiredHitRatePct = 36.8;
const beamSize = 10;

if (!token) throw new Error("CLOUDFLARE_API_TOKEN is not set");

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

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const num = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const clip = (value, minimum, maximum) => Math.max(minimum, Math.min(maximum, value));
const round = (value) => Number(value.toFixed(2));

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

function monthRanges(start, end) {
  const values = [];
  let year = Number(start.slice(0, 4));
  let month = Number(start.slice(5, 7));
  const endYear = Number(end.slice(0, 4));
  const endMonth = Number(end.slice(5, 7));
  while (year < endYear || (year === endYear && month <= endMonth)) {
    const prefix = `${year}-${String(month).padStart(2, "0")}`;
    const nextYear = month === 12 ? year + 1 : year;
    const nextMonth = month === 12 ? 1 : month + 1;
    values.push({ start: `${prefix}-01`, end: `${nextYear}-${String(nextMonth).padStart(2, "0")}-01` });
    year = nextYear;
    month = nextMonth;
  }
  return values;
}

function canonical(type, combination) {
  const values = (String(combination).match(/\d{1,2}/g) ?? []).map(Number);
  if (["ワイド", "馬連", "3連複"].includes(type)) values.sort((a, b) => a - b);
  return values.join("-");
}

function parseAge(sexAge) {
  const match = String(sexAge ?? "").match(/(\d+)/);
  return match ? Number(match[1]) : 4;
}

function buildFeatures(row, race, marketProbability, fieldSize) {
  const baseProbability = clip(num(row.baseProbability), 0.000001, 0.999999);
  const market = clip(marketProbability, 0.000001, 0.999999);
  const edgeLog = Math.log(baseProbability / market);
  const sex = String(row.sexAge ?? "");
  const surfaceDirt = String(race.surface).includes("ダ") ? 1 : 0;
  const badTrack = ["重", "不良", "稍重"].some((value) => String(race.trackCondition).includes(value)) ? 1 : 0;
  const base = [
    Math.log(market),
    Math.log(baseProbability),
    edgeLog,
    baseProbability,
    market,
    num(row.predictedOrder) / Math.max(1, fieldSize),
    num(row.popularity) / Math.max(1, fieldSize),
    Math.log(Math.max(1.01, num(row.currentOdds))),
    (num(row.assignedWeight) - 55) / 6,
    (num(row.horseWeight) - 480) / 100,
    clip(num(row.weightChange), -30, 30) / 30,
    (parseAge(row.sexAge) - 4) / 5,
    sex.includes("牝") ? 1 : 0,
    sex.includes("セ") ? 1 : 0,
    (num(row.frameNo) - 4.5) / 4.5,
    fieldSize / 18,
    surfaceDirt,
    num(race.distanceM) / 3000,
    badTrack,
    baseProbability * Math.log(Math.max(1.01, num(row.currentOdds))),
    edgeLog * Math.log(Math.max(1.01, num(row.currentOdds))),
    baseProbability * (1 - num(row.popularity) / Math.max(1, fieldSize))
  ];
  return [...base, ...venues.map((venue) => race.venue === venue ? 1 : 0)];
}

function computeStandardizer(races) {
  const dimension = races[0]?.runners[0]?.features.length ?? 0;
  const sums = Array(dimension).fill(0);
  const squares = Array(dimension).fill(0);
  let count = 0;
  for (const race of races) {
    for (const runner of race.runners) {
      count += 1;
      runner.features.forEach((value, index) => {
        sums[index] += value;
        squares[index] += value * value;
      });
    }
  }
  const means = sums.map((value) => value / Math.max(1, count));
  const stds = squares.map((value, index) => Math.sqrt(Math.max(0.000001, value / Math.max(1, count) - means[index] * means[index])));
  return { means, stds };
}

function standardize(races, standardizer) {
  return races.map((race) => ({
    ...race,
    runners: race.runners.map((runner) => ({
      ...runner,
      x: runner.features.map((value, index) => clip((value - standardizer.means[index]) / standardizer.stds[index], -6, 6))
    }))
  }));
}

function dot(weights, values) {
  let total = 0;
  for (let index = 0; index < weights.length; index += 1) total += (weights[index] ?? 0) * (values[index] ?? 0);
  return total;
}

function softmax(scores) {
  const maximum = Math.max(...scores);
  const values = scores.map((score) => Math.exp(clip(score - maximum, -40, 40)));
  const total = values.reduce((sum, value) => sum + value, 0);
  return values.map((value) => value / total);
}

function rankingMetrics(weights, races) {
  let loss = 0;
  let top1 = 0;
  let top3 = 0;
  let count = 0;
  for (const race of races) {
    const winnerIndex = race.runners.findIndex((runner) => runner.finishPosition === 1);
    if (winnerIndex < 0) continue;
    const probabilities = softmax(race.runners.map((runner) => dot(weights, runner.x)));
    loss -= Math.log(Math.max(0.000000001, probabilities[winnerIndex] ?? 0));
    const order = probabilities.map((probability, index) => ({ probability, index })).sort((a, b) => b.probability - a.probability);
    if (order[0]?.index === winnerIndex) top1 += 1;
    if (order.slice(0, 3).some((row) => row.index === winnerIndex)) top3 += 1;
    count += 1;
  }
  return {
    races: count,
    logLoss: loss / Math.max(1, count),
    top1Pct: top1 / Math.max(1, count) * 100,
    top3Pct: top3 / Math.max(1, count) * 100
  };
}

function trainWeightedModel(train, validation, config) {
  const dimension = train[0]?.runners[0]?.x.length ?? 0;
  let weights = Array(dimension).fill(0);
  let best = { weights: [...weights], metrics: rankingMetrics(weights, validation) };
  for (let epoch = 1; epoch <= config.epochs; epoch += 1) {
    const gradient = Array(dimension).fill(0);
    let normalization = 0;
    for (const race of train) {
      const winnerIndex = race.runners.findIndex((runner) => runner.finishPosition === 1);
      if (winnerIndex < 0) continue;
      const winnerOdds = race.runners[winnerIndex]?.currentOdds ?? 1;
      const raceWeight = Math.pow(Math.min(30, Math.max(1, winnerOdds)), config.longshotPower);
      const probabilities = softmax(race.runners.map((runner) => dot(weights, runner.x)));
      race.runners.forEach((runner, runnerIndex) => {
        const error = ((probabilities[runnerIndex] ?? 0) - (runnerIndex === winnerIndex ? 1 : 0)) * raceWeight;
        runner.x.forEach((value, featureIndex) => {
          gradient[featureIndex] += error * value;
        });
      });
      normalization += raceWeight * race.runners.length;
    }
    const scale = config.learningRate / Math.max(1, normalization);
    weights = weights.map((weight, index) => weight - scale * gradient[index] - config.learningRate * config.l2 * weight);
    if (epoch % 5 === 0 || epoch === config.epochs) {
      const metrics = rankingMetrics(weights, validation);
      if (metrics.logLoss < best.metrics.logLoss) best = { weights: [...weights], metrics };
    }
  }
  return { ...best, config };
}

function predictionsForRace(race, model) {
  const probabilities = softmax(race.runners.map((runner) => dot(model.weights, runner.x)));
  return race.runners.map((runner, index) => ({
    horseNo: runner.horseNo,
    horseName: runner.horseName,
    winProbability: probabilities[index] ?? 0,
    placeProbability: clip(1 - Math.pow(1 - (probabilities[index] ?? 0), 3), probabilities[index] ?? 0, 0.96),
    fairOdds: probabilities[index] > 0 ? 1 / probabilities[index] : 999,
    currentOdds: runner.currentOdds,
    expectedValuePct: runner.currentOdds > 1 ? (probabilities[index] ?? 0) * runner.currentOdds * 100 : null,
    predictedOrder: 0,
    explanation: `longshot-value-power-${model.config.longshotPower}`,
    popularity: runner.popularity
  })).sort((a, b) => b.winProbability - a.winProbability).map((row, index) => ({ ...row, predictedOrder: index + 1 }));
}

function candidateScore(row) {
  const expected = Math.max(0.01, row.expectedValuePct / 100);
  return expected * Math.pow(Math.max(0.000001, row.hitProbability), 0.5) * row.reliability;
}

function selectByVenueDay(records, count, scoreFn) {
  const groups = new Map();
  for (const race of records) {
    const key = `${race.raceDate}:${race.venue}`;
    groups.set(key, [...(groups.get(key) ?? []), race]);
  }
  return [...groups.values()].flatMap((rows) => [...rows]
    .sort((a, b) => scoreFn(b) - scoreFn(a) || a.raceNo - b.raceNo)
    .slice(0, Math.max(5, count)));
}

function evaluateSingleValue(records, count) {
  const selected = selectByVenueDay(records, count, (race) => {
    const best = race.predictions.reduce((current, row) => {
      const value = row.currentOdds > 1 ? row.winProbability * row.currentOdds : 0;
      return value > current ? value : current;
    }, 0);
    return best;
  });
  let stake = 0;
  let returned = 0;
  let hits = 0;
  const months = new Map();
  for (const race of selected) {
    const best = [...race.predictions].sort((a, b) =>
      (b.winProbability * (b.currentOdds ?? 0)) - (a.winProbability * (a.currentOdds ?? 0))
    )[0];
    if (!best) continue;
    const value = race.payouts.get(`単勝:${best.horseNo}`) ?? 0;
    stake += 100;
    returned += value;
    if (value > 0) hits += 1;
    const month = race.raceDate.slice(0, 7);
    const row = months.get(month) ?? { stake: 0, returned: 0 };
    row.stake += 100;
    row.returned += value;
    months.set(month, row);
  }
  const roi = returned / Math.max(1, stake) * 100;
  const hit = hits / Math.max(1, selected.length) * 100;
  const monthRois = [...months.values()].map((row) => row.returned / Math.max(1, row.stake) * 100);
  const minMonth = monthRois.length ? Math.min(...monthRois) : 0;
  return { count, races: selected.length, roi, hit, minMonth, score: roi * 0.5 + minMonth * 0.3 + hit * 0.2 };
}

function raceScore(race, mode) {
  const top = race.predictions[0]?.winProbability ?? 0;
  const gap = top - (race.predictions[1]?.winProbability ?? 0);
  const best = race.candidates[0];
  if (mode === "confidence") return top * 5 + gap * 8;
  if (mode === "edge") return candidateScore(best ?? { expectedValuePct: 0, hitProbability: 0, reliability: 0 });
  return top * 3 + gap * 5 + candidateScore(best ?? { expectedValuePct: 0, hitProbability: 0, reliability: 0 });
}

function selectRaces(records, count, mode) {
  return selectByVenueDay(records, count, (race) => raceScore(race, mode));
}

function portfolio(race, policy) {
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
  if (!rows.length) rows = race.candidates.filter((row) => allowed.has(row.betType));
  if (!rows.length) rows = race.candidates;
  rows = [...rows].sort((a, b) => candidateScore(b) - candidateScore(a));
  const chosen = [];
  const add = (row) => {
    if (!row) return;
    const key = `${row.betType}:${row.combination}`;
    if (!chosen.some((item) => `${item.betType}:${item.combination}` === key)) chosen.push(row);
  };
  if (policy.hedge === "hit") add([...race.candidates].sort((a, b) => b.hitProbability - a.hitProbability)[0]);
  if (policy.hedge === "single") add([...race.candidates].filter((row) => row.betType === "単勝").sort((a, b) => b.hitProbability - a.hitProbability)[0]);
  if (policy.hedge === "wide") add([...race.candidates].filter((row) => row.betType === "ワイド").sort((a, b) => b.hitProbability - a.hitProbability)[0]);
  for (const row of rows) {
    if (chosen.length >= policy.ticketCount) break;
    add(row);
  }
  return chosen.slice(0, policy.ticketCount);
}

function allocate(rows, target, policy) {
  if (!rows.length) return [];
  const units = Math.max(rows.length, Math.floor(target / 100));
  const base = rows.map(() => 1);
  let remaining = units - rows.length;
  const weights = rows.map((row) => policy.stakeMode === "equal"
    ? 1
    : policy.stakeMode === "hit"
      ? Math.max(0.0001, row.hitProbability)
      : Math.max(0.0001, candidateScore(row)));
  const total = weights.reduce((sum, value) => sum + value, 0);
  const exact = weights.map((value) => remaining * value / total);
  const additions = exact.map(Math.floor);
  remaining -= additions.reduce((sum, value) => sum + value, 0);
  for (const item of exact.map((value, index) => ({ index, fraction: value - Math.floor(value) })).sort((a, b) => b.fraction - a.fraction)) {
    if (remaining <= 0) break;
    additions[item.index] += 1;
    remaining -= 1;
  }
  return rows.map((row, index) => ({ ...row, stakeYen: ((base[index] ?? 1) + (additions[index] ?? 0)) * 100 }));
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
  const roi = returned / Math.max(1, stake) * 100;
  const hit = hitRaces / Math.max(1, records.length) * 100;
  const monthRois = [...months.values()].map((row) => row.returned / Math.max(1, row.stake) * 100);
  const minMonth = monthRois.length ? Math.min(...monthRois) : 0;
  return { roi, hit, minMonth, profit: returned - stake, objective: roi * 0.45 + minMonth * 0.35 + hit * 0.2 };
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
    for (const stakeMode of ["equal", "score", "hit"]) {
      const policy = { profile, stakeMode, minEv: 0, minHit: 0, maxOdds: 2500, maxRank: 7, includesFirst: "any", ticketCount: 2, hedge: "none" };
      beam.push({ policy, result: evaluate(records, policy, target) });
    }
  }
  beam = retain(beam);
  const dimensions = [
    ["minEv", [0, 80, 90, 100, 105, 110, 120, 140, 170, 220]],
    ["minHit", [0, 0.005, 0.01, 0.02, 0.04, 0.07, 0.1, 0.15, 0.25]],
    ["maxOdds", [5, 10, 20, 40, 80, 150, 500, 2500]],
    ["maxRank", [2, 3, 4, 5, 7]],
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
  const [universe, budget, scope] = await Promise.all([
    import("../dist-test/src/v1/betting-candidate-universe.js"),
    import("../dist-test/src/v1/budget-courses.js"),
    import("../dist-test/src/v1/walk-forward-scope.js")
  ]);

  const grouped = new Map();
  const payoutsByRace = new Map();
  for (const range of monthRanges(scope.WALK_FORWARD_TRAIN_START_DATE, scope.WALK_FORWARD_HOLDOUT_END_DATE)) {
    const rows = await sql(`
      SELECT r.race_id raceId,r.race_date raceDate,r.venue,r.race_no raceNo,
        r.surface,r.distance_m distanceM,r.track_condition trackCondition,r.refund_horse_nos_json refunds,
        pr.horse_no horseNo,pr.horse_name horseName,pr.win_probability baseProbability,
        pr.predicted_order predictedOrder,pr.current_odds currentOdds,
        rr.frame_no frameNo,rr.sex_age sexAge,rr.horse_weight horseWeight,
        rr.weight_change weightChange,rr.assigned_weight assignedWeight,rr.popularity,
        rs.finish_position finishPosition
      FROM rt_races r
      JOIN rt_predictions p ON p.race_id=r.race_id AND p.model_version=? AND p.status='locked'
      JOIN rt_prediction_runners pr ON pr.prediction_id=p.id
      LEFT JOIN rt_runners rr ON rr.race_id=r.race_id AND rr.horse_no=pr.horse_no
      LEFT JOIN rt_results rs ON rs.race_id=r.race_id AND rs.horse_no=pr.horse_no
      WHERE r.race_date>=? AND r.race_date<?
      ORDER BY r.race_date,r.venue,r.race_no,pr.predicted_order
    `, [scope.WALK_FORWARD_BASE_MODEL_VERSION, range.start, range.end]);
    for (const row of rows) {
      const race = grouped.get(row.raceId) ?? {
        raceId: row.raceId,
        raceDate: row.raceDate,
        venue: row.venue,
        raceNo: num(row.raceNo),
        surface: row.surface ?? "",
        distanceM: num(row.distanceM),
        trackCondition: row.trackCondition ?? "",
        refunds: row.refunds ?? "[]",
        rows: []
      };
      race.rows.push({
        horseNo: num(row.horseNo),
        horseName: row.horseName,
        baseProbability: num(row.baseProbability),
        predictedOrder: num(row.predictedOrder),
        currentOdds: num(row.currentOdds),
        frameNo: num(row.frameNo),
        sexAge: row.sexAge,
        horseWeight: num(row.horseWeight),
        weightChange: num(row.weightChange),
        assignedWeight: num(row.assignedWeight),
        popularity: num(row.popularity),
        finishPosition: num(row.finishPosition)
      });
      grouped.set(row.raceId, race);
    }
    const payouts = await sql(`
      SELECT p.race_id raceId,p.bet_type betType,p.combination,p.payout_yen payoutYen
      FROM rt_payouts p JOIN rt_races r ON r.race_id=p.race_id
      WHERE r.race_date>=? AND r.race_date<?
    `, [range.start, range.end]);
    for (const row of payouts) {
      const map = payoutsByRace.get(row.raceId) ?? new Map();
      map.set(`${row.betType}:${canonical(row.betType, row.combination)}`, num(row.payoutYen));
      payoutsByRace.set(row.raceId, map);
    }
  }

  const rawRaces = [...grouped.values()].filter((race) => race.rows.length >= 3 && race.rows.some((row) => row.finishPosition === 1));
  for (const race of rawRaces) {
    const inverse = race.rows.map((row) => row.currentOdds > 1 ? 1 / row.currentOdds : 0.0001);
    const total = inverse.reduce((sum, value) => sum + value, 0);
    race.runners = race.rows.map((row, index) => ({
      ...row,
      features: buildFeatures(row, race, inverse[index] / total, race.rows.length)
    }));
    race.payouts = payoutsByRace.get(race.raceId) ?? new Map();
  }
  const split = (race) => race.raceDate <= scope.WALK_FORWARD_TRAIN_END_DATE
    ? "train"
    : race.raceDate <= scope.WALK_FORWARD_VALIDATION_END_DATE
      ? "validation"
      : "holdout";
  const trainRaw = rawRaces.filter((race) => split(race) === "train");
  const validationRaw = rawRaces.filter((race) => split(race) === "validation");
  const holdoutRaw = rawRaces.filter((race) => split(race) === "holdout");
  const standardizer = computeStandardizer(trainRaw);
  const train = standardize(trainRaw, standardizer);
  const validation = standardize(validationRaw, standardizer);
  const holdout = standardize(holdoutRaw, standardizer);

  const configs = [
    { longshotPower: 0, learningRate: 0.05, l2: 0.004, epochs: 50 },
    { longshotPower: 0.25, learningRate: 0.04, l2: 0.005, epochs: 60 },
    { longshotPower: 0.5, learningRate: 0.03, l2: 0.008, epochs: 70 },
    { longshotPower: 0.75, learningRate: 0.02, l2: 0.012, epochs: 80 }
  ];
  const models = configs.map((config) => trainWeightedModel(train, validation, config));

  function makeBettingRecords(races, model) {
    return races.map((race) => {
      const predictions = predictionsForRace(race, model);
      const refunds = new Set(JSON.parse(race.refunds || "[]"));
      const candidates = universe.buildBettingCandidateUniverse(predictions, 7).map((candidate) => {
        const horses = (candidate.combination.match(/\d{1,2}/g) ?? []).map(Number);
        const returnPer100 = horses.some((horse) => refunds.has(horse))
          ? 100
          : race.payouts.get(`${candidate.betType}:${canonical(candidate.betType, candidate.combination)}`) ?? 0;
        return { ...candidate, returnPer100 };
      }).sort((a, b) => candidateScore(b) - candidateScore(a));
      return { ...race, predictions, candidates };
    }).filter((race) => race.candidates.length > 0);
  }

  const modelScreens = [];
  for (const model of models) {
    const records = makeBettingRecords(validation, model);
    const screens = [5, 6, 7, 8, 9, 10, 11, 12].map((count) => evaluateSingleValue(records, count));
    screens.sort((a, b) => b.score - a.score);
    modelScreens.push({ model, records, screen: screens[0], allScreens: screens });
    console.log(`Power ${model.config.longshotPower}: best single-value ${screens[0].count}R ROI ${round(screens[0].roi)}% / hit ${round(screens[0].hit)}% / minMonth ${round(screens[0].minMonth)}%`);
  }
  modelScreens.sort((a, b) => b.screen.score - a.screen.score);
  const finalists = modelScreens.slice(0, 2);
  const policyRuns = [];
  for (const finalist of finalists) {
    for (const mode of ["edge", "confidence", "combined"]) {
      for (const count of [5, 6, 7, 8, 9, 10, 12]) {
        const selected = selectRaces(finalist.records, count, mode);
        const policies = {};
        for (const course of courses) {
          const winner = searchPolicy(selected, budget.COURSE_TARGET_STAKES[course], course);
          if (!winner) throw new Error(`LONGSHOT_NO_POLICY:${course}`);
          policies[course] = winner;
        }
        const minimumRoi = Math.min(...courses.map((course) => policies[course].result.roi));
        const minimumHit = Math.min(...courses.map((course) => policies[course].result.hit));
        const minimumMonth = Math.min(...courses.map((course) => policies[course].result.minMonth));
        policyRuns.push({ finalist, mode, count, policies, aggregate: minimumRoi * 0.45 + minimumMonth * 0.35 + minimumHit * 0.2 });
      }
    }
  }
  policyRuns.sort((a, b) => b.aggregate - a.aggregate);
  const winner = policyRuns[0];
  if (!winner) throw new Error("LONGSHOT_NO_WINNER");
  const holdoutRecords = makeBettingRecords(holdout, winner.finalist.model);
  const holdoutSelected = selectRaces(holdoutRecords, winner.count, winner.mode);
  const holdoutMetrics = Object.fromEntries(courses.map((course) => [
    course,
    evaluate(holdoutSelected, winner.policies[course].policy, budget.COURSE_TARGET_STAKES[course])
  ]));

  const report = {
    generatedAt: new Date().toISOString(),
    targetRoiPct: 200,
    minimumRacesPerVenueDay: 5,
    samples: { train: train.length, validation: validation.length, holdout: holdout.length },
    selectedModel: {
      config: winner.finalist.model.config,
      rankingValidation: Object.fromEntries(Object.entries(winner.finalist.model.metrics).map(([key, value]) => [key, typeof value === "number" ? round(value) : value])),
      singleValueScreen: Object.fromEntries(Object.entries(winner.finalist.screen).map(([key, value]) => [key, typeof value === "number" ? round(value) : value]))
    },
    selectedRaceConfiguration: { mode: winner.mode, count: winner.count },
    validation: Object.fromEntries(courses.map((course) => [course, {
      policy: winner.policies[course].policy,
      roi: round(winner.policies[course].result.roi),
      hit: round(winner.policies[course].result.hit),
      minMonth: round(winner.policies[course].result.minMonth),
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
  await (await import("node:fs/promises")).writeFile("longshot-value-model.json", JSON.stringify(report, null, 2) + "\n");
  console.log(`Winner power ${report.selectedModel.config.longshotPower}, ${winner.mode}/${winner.count}R`);
  for (const course of courses) {
    console.log(`${course}: validation ${report.validation[course].roi}% / holdout ${report.holdout[course].roi}% / hit ${report.holdout[course].hit}% / 200% ${report.holdout[course].pass200 ? "PASS" : "FAIL"}`);
  }
  console.log("Longshot result: longshot-value-model.json");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
