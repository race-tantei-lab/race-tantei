const token = process.env.CLOUDFLARE_API_TOKEN;
const account = process.env.CLOUDFLARE_ACCOUNT_ID || "3c6d1826b573b2e68cb13ec37e9e8ade";
const database = process.env.CLOUDFLARE_D1_DATABASE_ID || "949b5e8b-d1a4-4c4e-80d1-d031afdc03de";
const endpoint = `https://api.cloudflare.com/client/v4/accounts/${account}/d1/database/${database}/query`;
const courses = ["ライト", "スタンダード", "プレミアム"];
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
const round = (value) => Number(value.toFixed(4));

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
    values.push({
      start: `${prefix}-01`,
      end: `${nextYear}-${String(nextMonth).padStart(2, "0")}-01`
    });
    month = nextMonth;
    year = nextYear;
  }
  return values;
}

function canonical(type, combination) {
  const values = (String(combination).match(/\d{1,2}/g) ?? []).map(Number);
  if (["ワイド", "馬連", "3連複"].includes(type)) values.sort((a, b) => a - b);
  return values.join("-");
}

function emptyHistory() {
  return {
    starts: 0,
    wins: 0,
    places: 0,
    finishSum: 0,
    final3fSum: 0,
    final3fCount: 0,
    recent: [],
    lastDate: null
  };
}

function smoothedRate(successes, starts, priorRate, priorCount) {
  return (successes + priorRate * priorCount) / (starts + priorCount);
}

function historyFeatures(history, date) {
  const winRate = smoothedRate(history.wins, history.starts, 0.08, 12);
  const placeRate = smoothedRate(history.places, history.starts, 0.25, 12);
  const averageFinish = history.starts > 0 ? history.finishSum / history.starts : 7;
  const recent = history.recent.slice(-5);
  const recentAverage = recent.length ? recent.reduce((sum, value) => sum + value, 0) / recent.length : 7;
  const recentPlace = recent.length ? recent.filter((value) => value <= 3).length / recent.length : 0.25;
  const averageFinal3f = history.final3fCount > 0 ? history.final3fSum / history.final3fCount : 36;
  const daysSince = history.lastDate
    ? Math.max(0, (Date.parse(date) - Date.parse(history.lastDate)) / 86400000)
    : 90;
  return {
    winRate,
    placeRate,
    averageFinish,
    starts: history.starts,
    recentAverage,
    recentPlace,
    averageFinal3f,
    daysSince
  };
}

function parseAge(sexAge) {
  const match = String(sexAge ?? "").match(/(\d+)/);
  return match ? Number(match[1]) : 4;
}

function sexFlags(sexAge) {
  const value = String(sexAge ?? "");
  return {
    female: value.includes("牝") ? 1 : 0,
    gelding: value.includes("セ") ? 1 : 0
  };
}

function distanceBucket(distance) {
  if (distance < 1400) return "sprint";
  if (distance < 1800) return "mile";
  if (distance < 2200) return "middle";
  return "long";
}

function makeFeatureVector(row, race, histories, marketProbability, fieldSize) {
  const horse = historyFeatures(histories.horse.get(row.horseName) ?? emptyHistory(), race.raceDate);
  const jockey = historyFeatures(histories.jockey.get(row.jockey) ?? emptyHistory(), race.raceDate);
  const trainer = historyFeatures(histories.trainer.get(row.trainer) ?? emptyHistory(), race.raceDate);
  const courseKey = `${row.horseName}|${race.venue}|${race.surface}|${distanceBucket(race.distanceM)}`;
  const jockeyCourseKey = `${row.jockey}|${race.surface}|${distanceBucket(race.distanceM)}`;
  const trainerCourseKey = `${row.trainer}|${race.surface}|${distanceBucket(race.distanceM)}`;
  const course = historyFeatures(histories.horseCourse.get(courseKey) ?? emptyHistory(), race.raceDate);
  const jockeyCourse = historyFeatures(histories.jockeyCourse.get(jockeyCourseKey) ?? emptyHistory(), race.raceDate);
  const trainerCourse = historyFeatures(histories.trainerCourse.get(trainerCourseKey) ?? emptyHistory(), race.raceDate);
  const sex = sexFlags(row.sexAge);
  const popularity = row.popularity > 0 ? row.popularity / Math.max(1, fieldSize) : 0.5;
  const marketLog = Math.log(Math.max(0.000001, marketProbability));

  return [
    marketLog,
    marketProbability,
    -popularity,
    horse.winRate,
    horse.placeRate,
    -horse.averageFinish / 12,
    Math.log1p(horse.starts),
    -horse.recentAverage / 12,
    horse.recentPlace,
    (36 - horse.averageFinal3f) / 5,
    -clip(horse.daysSince, 0, 180) / 180,
    jockey.winRate,
    jockey.placeRate,
    trainer.winRate,
    trainer.placeRate,
    course.winRate,
    course.placeRate,
    jockeyCourse.winRate,
    trainerCourse.winRate,
    (num(row.assignedWeight) - 55) / 6,
    (num(row.horseWeight) - 480) / 100,
    clip(num(row.weightChange), -30, 30) / 30,
    (parseAge(row.sexAge) - 4) / 5,
    sex.female,
    sex.gelding,
    (num(row.frameNo) - 4.5) / 4.5,
    marketProbability * horse.winRate * 10,
    marketProbability * jockey.winRate * 10,
    marketProbability * trainer.winRate * 10,
    marketProbability * horse.recentPlace * 4,
    course.winRate * horse.winRate * 10,
    fieldSize / 18
  ];
}

function updateHistory(map, key, result) {
  if (!key) return;
  const history = map.get(key) ?? emptyHistory();
  history.starts += 1;
  history.wins += result.finishPosition === 1 ? 1 : 0;
  history.places += result.finishPosition > 0 && result.finishPosition <= 3 ? 1 : 0;
  history.finishSum += result.finishPosition > 0 ? result.finishPosition : 10;
  if (result.final3f > 0) {
    history.final3fSum += result.final3f;
    history.final3fCount += 1;
  }
  history.recent.push(result.finishPosition > 0 ? result.finishPosition : 10);
  if (history.recent.length > 8) history.recent.shift();
  history.lastDate = result.raceDate;
  map.set(key, history);
}

function updateAllHistories(histories, race, row) {
  const result = {
    finishPosition: num(row.finishPosition),
    final3f: num(row.final3f),
    raceDate: race.raceDate
  };
  updateHistory(histories.horse, row.horseName, result);
  updateHistory(histories.jockey, row.jockey, result);
  updateHistory(histories.trainer, row.trainer, result);
  updateHistory(histories.horseCourse, `${row.horseName}|${race.venue}|${race.surface}|${distanceBucket(race.distanceM)}`, result);
  updateHistory(histories.jockeyCourse, `${row.jockey}|${race.surface}|${distanceBucket(race.distanceM)}`, result);
  updateHistory(histories.trainerCourse, `${row.trainer}|${race.surface}|${distanceBucket(race.distanceM)}`, result);
}

function softmax(scores) {
  const maximum = Math.max(...scores);
  const values = scores.map((score) => Math.exp(clip(score - maximum, -40, 40)));
  const total = values.reduce((sum, value) => sum + value, 0);
  return values.map((value) => value / total);
}

function dot(weights, values) {
  let total = 0;
  for (let index = 0; index < weights.length; index += 1) total += (weights[index] ?? 0) * (values[index] ?? 0);
  return total;
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
  const means = sums.map((value) => count > 0 ? value / count : 0);
  const stds = squares.map((value, index) => {
    const variance = count > 0 ? value / count - means[index] * means[index] : 0;
    return Math.sqrt(Math.max(0.000001, variance));
  });
  return { means, stds };
}

function standardizeRaces(races, standardizer) {
  return races.map((race) => ({
    ...race,
    runners: race.runners.map((runner) => ({
      ...runner,
      x: runner.features.map((value, index) => clip(
        (value - standardizer.means[index]) / standardizer.stds[index],
        -6,
        6
      ))
    }))
  }));
}

function evaluateRanking(weights, races) {
  let loss = 0;
  let top1 = 0;
  let top3 = 0;
  let count = 0;
  for (const race of races) {
    const winnerIndex = race.runners.findIndex((runner) => runner.finishPosition === 1);
    if (winnerIndex < 0) continue;
    const probabilities = softmax(race.runners.map((runner) => dot(weights, runner.x)));
    loss -= Math.log(Math.max(0.000000001, probabilities[winnerIndex] ?? 0));
    const order = probabilities
      .map((probability, index) => ({ probability, index }))
      .sort((a, b) => b.probability - a.probability);
    if (order[0]?.index === winnerIndex) top1 += 1;
    if (order.slice(0, 3).some((row) => row.index === winnerIndex)) top3 += 1;
    count += 1;
  }
  return {
    races: count,
    logLoss: count > 0 ? loss / count : Number.POSITIVE_INFINITY,
    top1Pct: count > 0 ? top1 / count * 100 : 0,
    top3Pct: count > 0 ? top3 / count * 100 : 0
  };
}

function trainModel(train, validation, config) {
  const dimension = train[0]?.runners[0]?.x.length ?? 0;
  let weights = Array(dimension).fill(0);
  let bestWeights = [...weights];
  let bestMetrics = evaluateRanking(weights, validation);

  for (let epoch = 1; epoch <= config.epochs; epoch += 1) {
    const gradient = Array(dimension).fill(0);
    let runnerCount = 0;
    for (const race of train) {
      const winnerIndex = race.runners.findIndex((runner) => runner.finishPosition === 1);
      if (winnerIndex < 0) continue;
      const probabilities = softmax(race.runners.map((runner) => dot(weights, runner.x)));
      race.runners.forEach((runner, runnerIndex) => {
        const error = (probabilities[runnerIndex] ?? 0) - (runnerIndex === winnerIndex ? 1 : 0);
        runner.x.forEach((value, featureIndex) => {
          gradient[featureIndex] += error * value;
        });
        runnerCount += 1;
      });
    }
    const scale = config.learningRate / Math.max(1, runnerCount);
    weights = weights.map((weight, index) =>
      weight - scale * gradient[index] - config.learningRate * config.l2 * weight
    );

    if (epoch % 5 === 0 || epoch === config.epochs) {
      const metrics = evaluateRanking(weights, validation);
      if (
        metrics.logLoss < bestMetrics.logLoss - 0.000001
        || (Math.abs(metrics.logLoss - bestMetrics.logLoss) < 0.000001 && metrics.top1Pct > bestMetrics.top1Pct)
      ) {
        bestMetrics = metrics;
        bestWeights = [...weights];
      }
    }
  }
  return { weights: bestWeights, validation: bestMetrics, config };
}

function marketBaseline(races) {
  let loss = 0;
  let top1 = 0;
  let top3 = 0;
  let count = 0;
  for (const race of races) {
    const winnerIndex = race.runners.findIndex((runner) => runner.finishPosition === 1);
    if (winnerIndex < 0) continue;
    const raw = race.runners.map((runner) => runner.winOdds > 1 ? 1 / runner.winOdds : 0.0001);
    const total = raw.reduce((sum, value) => sum + value, 0);
    const probabilities = raw.map((value) => value / total);
    loss -= Math.log(Math.max(0.000000001, probabilities[winnerIndex] ?? 0));
    const order = probabilities.map((probability, index) => ({ probability, index })).sort((a, b) => b.probability - a.probability);
    if (order[0]?.index === winnerIndex) top1 += 1;
    if (order.slice(0, 3).some((row) => row.index === winnerIndex)) top3 += 1;
    count += 1;
  }
  return {
    races: count,
    logLoss: count > 0 ? loss / count : 0,
    top1Pct: count > 0 ? top1 / count * 100 : 0,
    top3Pct: count > 0 ? top3 / count * 100 : 0
  };
}

function buildPredictions(race, weights) {
  const probabilities = softmax(race.runners.map((runner) => dot(weights, runner.x)));
  return race.runners.map((runner, index) => ({
    horseNo: runner.horseNo,
    horseName: runner.horseName,
    winProbability: probabilities[index] ?? 0,
    placeProbability: clip(1 - Math.pow(1 - (probabilities[index] ?? 0), 3), probabilities[index] ?? 0, 0.96),
    fairOdds: probabilities[index] > 0 ? 1 / probabilities[index] : 999,
    currentOdds: runner.winOdds,
    expectedValuePct: runner.winOdds > 1 ? (probabilities[index] ?? 0) * runner.winOdds * 100 : null,
    predictedOrder: 0,
    explanation: "chronological runner ranking v2",
    popularity: runner.popularity
  })).sort((a, b) => b.winProbability - a.winProbability).map((row, index) => ({ ...row, predictedOrder: index + 1 }));
}

function candidateScore(row) {
  const edge = Math.max(0.01, row.expectedValuePct / 100);
  return edge * Math.pow(Math.max(0.000001, row.hitProbability), 0.55) * row.reliability;
}

function raceScore(race, mode) {
  const ranked = race.predictions;
  const top = ranked[0]?.winProbability ?? 0;
  const gap = top - (ranked[1]?.winProbability ?? 0);
  const bestCandidate = race.candidates[0];
  if (mode === "confidence") return top * 5 + gap * 8;
  if (mode === "edge") return candidateScore(bestCandidate ?? { expectedValuePct: 0, hitProbability: 0, reliability: 0 });
  return top * 3 + gap * 5 + candidateScore(bestCandidate ?? { expectedValuePct: 0, hitProbability: 0, reliability: 0 });
}

function selectRaces(records, count, mode) {
  const groups = new Map();
  for (const row of records) {
    const key = `${row.raceDate}:${row.venue}`;
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  return [...groups.values()].flatMap((rows) => [...rows]
    .sort((a, b) => raceScore(b, mode) - raceScore(a, mode) || a.raceNo - b.raceNo)
    .slice(0, Math.max(5, count)));
}

function portfolio(race, policy) {
  const allowed = profiles[policy.profile] ?? profiles.all;
  let candidates = race.candidates.filter((row) =>
    allowed.has(row.betType)
    && row.expectedValuePct >= policy.minEv
    && row.hitProbability >= policy.minHit
    && row.assumedOdds <= policy.maxOdds
    && row.maximumRank <= policy.maxRank
    && (policy.includesFirst === "any"
      || (policy.includesFirst === "yes" && row.includesFirst)
      || (policy.includesFirst === "no" && !row.includesFirst))
  );
  if (!candidates.length) candidates = race.candidates.filter((row) => allowed.has(row.betType));
  if (!candidates.length) candidates = race.candidates;
  candidates = [...candidates].sort((a, b) => candidateScore(b) - candidateScore(a));
  const chosen = [];
  const add = (row) => {
    if (!row) return;
    const key = `${row.betType}:${row.combination}`;
    if (!chosen.some((item) => `${item.betType}:${item.combination}` === key)) chosen.push(row);
  };
  if (policy.hedge === "hit") add([...race.candidates].sort((a, b) => b.hitProbability - a.hitProbability)[0]);
  if (policy.hedge === "single") add([...race.candidates].filter((row) => row.betType === "単勝").sort((a, b) => b.hitProbability - a.hitProbability)[0]);
  if (policy.hedge === "wide") add([...race.candidates].filter((row) => row.betType === "ワイド").sort((a, b) => b.hitProbability - a.hitProbability)[0]);
  for (const row of candidates) {
    if (chosen.length >= policy.ticketCount) break;
    add(row);
  }
  return chosen.slice(0, policy.ticketCount);
}

function allocate(rows, target, policy) {
  if (!rows.length) return [];
  const units = Math.max(rows.length, Math.floor(target / 100));
  const stakes = rows.map(() => 1);
  let remaining = units - rows.length;
  const weights = rows.map((row) => {
    if (policy.stakeMode === "equal") return 1;
    if (policy.stakeMode === "hit") return Math.max(0.0001, row.hitProbability);
    return Math.max(0.0001, candidateScore(row));
  });
  const total = weights.reduce((sum, value) => sum + value, 0);
  const exact = weights.map((value) => remaining * value / total);
  const additions = exact.map(Math.floor);
  remaining -= additions.reduce((sum, value) => sum + value, 0);
  for (const item of exact.map((value, index) => ({ index, fraction: value - Math.floor(value) })).sort((a, b) => b.fraction - a.fraction)) {
    if (remaining <= 0) break;
    additions[item.index] += 1;
    remaining -= 1;
  }
  return rows.map((row, index) => ({ ...row, stakeYen: ((stakes[index] ?? 1) + (additions[index] ?? 0)) * 100 }));
}

function evaluatePortfolio(records, policy, target) {
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
  return { races: records.length, roi, hit, minMonth, profit: returned - stake, objective: roi * 0.45 + minMonth * 0.35 + hit * 0.2 };
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
      beam.push({ policy, result: evaluatePortfolio(records, policy, target) });
    }
  }
  beam = retain(beam);
  const dimensions = [
    ["minEv", [0, 80, 90, 100, 105, 110, 120, 140, 170]],
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
        expanded.push({ policy, result: evaluatePortfolio(records, policy, target) });
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

  const runnerRows = [];
  const payoutMapByRace = new Map();
  for (const range of monthRanges(scope.WALK_FORWARD_CONTEXT_START_DATE, scope.WALK_FORWARD_HOLDOUT_END_DATE)) {
    const rows = await sql(`
      SELECT r.race_id raceId,r.race_date raceDate,r.venue,r.race_no raceNo,
        r.surface,r.distance_m distanceM,r.weather,r.track_condition trackCondition,
        r.refund_horse_nos_json refunds,
        rr.horse_no horseNo,rr.frame_no frameNo,rr.horse_name horseName,rr.sex_age sexAge,
        rr.horse_weight horseWeight,rr.weight_change weightChange,rr.jockey,
        rr.assigned_weight assignedWeight,rr.trainer,rr.stable,rr.win_odds winOdds,
        rr.popularity,rr.runner_status runnerStatus,
        rs.finish_position finishPosition,rs.final3f
      FROM rt_races r
      JOIN rt_runners rr ON rr.race_id=r.race_id
      LEFT JOIN rt_results rs ON rs.race_id=r.race_id AND rs.horse_no=rr.horse_no
      WHERE r.race_date>=? AND r.race_date<? AND r.status='finished'
      ORDER BY r.race_date,r.venue,r.race_no,rr.horse_no
    `, [range.start, range.end]);
    runnerRows.push(...rows);
    const payouts = await sql(`
      SELECT p.race_id raceId,p.bet_type betType,p.combination,p.payout_yen payoutYen
      FROM rt_payouts p JOIN rt_races r ON r.race_id=p.race_id
      WHERE r.race_date>=? AND r.race_date<?
    `, [range.start, range.end]);
    for (const row of payouts) {
      const key = `${row.betType}:${canonical(row.betType, row.combination)}`;
      const map = payoutMapByRace.get(row.raceId) ?? new Map();
      map.set(key, num(row.payoutYen));
      payoutMapByRace.set(row.raceId, map);
    }
  }

  const grouped = new Map();
  for (const row of runnerRows) {
    const race = grouped.get(row.raceId) ?? {
      raceId: row.raceId,
      raceDate: row.raceDate,
      venue: row.venue,
      raceNo: num(row.raceNo),
      surface: row.surface ?? "",
      distanceM: num(row.distanceM),
      weather: row.weather ?? "",
      trackCondition: row.trackCondition ?? "",
      refunds: row.refunds ?? "[]",
      rows: []
    };
    race.rows.push({
      horseNo: num(row.horseNo),
      frameNo: num(row.frameNo),
      horseName: row.horseName,
      sexAge: row.sexAge,
      horseWeight: num(row.horseWeight),
      weightChange: num(row.weightChange),
      jockey: row.jockey ?? "",
      assignedWeight: num(row.assignedWeight),
      trainer: row.trainer ?? "",
      stable: row.stable ?? "",
      winOdds: num(row.winOdds),
      popularity: num(row.popularity),
      runnerStatus: row.runnerStatus,
      finishPosition: num(row.finishPosition),
      final3f: num(row.final3f)
    });
    grouped.set(row.raceId, race);
  }

  const rawRaces = [...grouped.values()].sort((a, b) =>
    a.raceDate.localeCompare(b.raceDate)
    || a.venue.localeCompare(b.venue, "ja")
    || a.raceNo - b.raceNo
  );
  const histories = {
    horse: new Map(), jockey: new Map(), trainer: new Map(),
    horseCourse: new Map(), jockeyCourse: new Map(), trainerCourse: new Map()
  };
  const featureRaces = [];
  for (const race of rawRaces) {
    const active = race.rows.filter((row) => row.runnerStatus === "active" && row.winOdds > 1 && row.finishPosition > 0);
    if (active.length < 3 || !active.some((row) => row.finishPosition === 1)) {
      for (const row of race.rows.filter((item) => item.finishPosition > 0)) updateAllHistories(histories, race, row);
      continue;
    }
    const inverse = active.map((row) => 1 / row.winOdds);
    const total = inverse.reduce((sum, value) => sum + value, 0);
    const runners = active.map((row, index) => ({
      ...row,
      features: makeFeatureVector(row, race, histories, inverse[index] / total, active.length)
    }));
    featureRaces.push({ ...race, runners });
    for (const row of race.rows.filter((item) => item.finishPosition > 0)) updateAllHistories(histories, race, row);
  }

  const split = (race) => race.raceDate <= scope.WALK_FORWARD_TRAIN_END_DATE
    ? "train"
    : race.raceDate <= scope.WALK_FORWARD_VALIDATION_END_DATE
      ? "validation"
      : "holdout";
  const trainRaw = featureRaces.filter((race) => race.raceDate >= scope.WALK_FORWARD_TRAIN_START_DATE && split(race) === "train");
  const validationRaw = featureRaces.filter((race) => split(race) === "validation");
  const holdoutRaw = featureRaces.filter((race) => split(race) === "holdout");
  const standardizer = computeStandardizer(trainRaw);
  const train = standardizeRaces(trainRaw, standardizer);
  const validation = standardizeRaces(validationRaw, standardizer);
  const holdout = standardizeRaces(holdoutRaw, standardizer);

  const configurations = [
    { learningRate: 0.08, l2: 0.001, epochs: 50 },
    { learningRate: 0.04, l2: 0.004, epochs: 70 },
    { learningRate: 0.02, l2: 0.012, epochs: 90 }
  ];
  const models = configurations.map((config) => trainModel(train, validation, config));
  models.sort((a, b) => a.validation.logLoss - b.validation.logLoss || b.validation.top1Pct - a.validation.top1Pct);
  const winner = models[0];
  if (!winner) throw new Error("RUNNER_RANKING_NO_MODEL");
  const marketValidation = marketBaseline(validation);
  const marketHoldout = marketBaseline(holdout);
  const modelHoldout = evaluateRanking(winner.weights, holdout);

  function buildBettingRecords(races) {
    const records = [];
    for (const race of races) {
      const predictions = buildPredictions(race, winner.weights);
      const refunds = new Set(JSON.parse(race.refunds || "[]"));
      const payouts = payoutMapByRace.get(race.raceId) ?? new Map();
      const candidates = universe.buildBettingCandidateUniverse(predictions, 7).map((candidate) => {
        const horses = (candidate.combination.match(/\d{1,2}/g) ?? []).map(Number);
        const returnPer100 = horses.some((horse) => refunds.has(horse))
          ? 100
          : payouts.get(`${candidate.betType}:${canonical(candidate.betType, candidate.combination)}`) ?? 0;
        return { ...candidate, returnPer100 };
      }).sort((a, b) => candidateScore(b) - candidateScore(a));
      if (!candidates.length) continue;
      records.push({
        raceId: race.raceId,
        raceDate: race.raceDate,
        venue: race.venue,
        raceNo: race.raceNo,
        predictions,
        candidates
      });
    }
    return records;
  }

  const validationBetting = buildBettingRecords(validation);
  const holdoutBetting = buildBettingRecords(holdout);
  const raceConfigs = [];
  const defaultPolicy = { profile: "all", stakeMode: "equal", minEv: 0, minHit: 0, maxOdds: 2500, maxRank: 7, includesFirst: "any", ticketCount: 2, hedge: "hit" };
  for (const mode of ["confidence", "edge", "combined"]) {
    for (const count of [5, 6, 7, 8, 9, 10, 11, 12]) {
      const selected = selectRaces(validationBetting, count, mode);
      raceConfigs.push({ mode, count, result: evaluatePortfolio(selected, defaultPolicy, 100) });
    }
  }
  raceConfigs.sort((a, b) => b.result.objective - a.result.objective);
  const finalists = raceConfigs.slice(0, 4);
  const policyRuns = [];
  for (const config of finalists) {
    console.log(`Searching ranking-v2 policy for ${config.mode}/${config.count}R...`);
    const selected = selectRaces(validationBetting, config.count, config.mode);
    const policies = {};
    for (const course of courses) {
      const policy = searchPolicy(selected, budget.COURSE_TARGET_STAKES[course], course);
      if (!policy) throw new Error(`RANKING_V2_NO_POLICY:${course}`);
      policies[course] = policy;
      console.log(`${course}: validation ROI ${round(policy.result.roi)}% / hit ${round(policy.result.hit)}% / minMonth ${round(policy.result.minMonth)}%`);
    }
    const minimumRoi = Math.min(...courses.map((course) => policies[course].result.roi));
    const minimumHit = Math.min(...courses.map((course) => policies[course].result.hit));
    const minimumMonth = Math.min(...courses.map((course) => policies[course].result.minMonth));
    policyRuns.push({ ...config, policies, aggregate: minimumRoi * 0.45 + minimumMonth * 0.35 + minimumHit * 0.2 });
  }
  policyRuns.sort((a, b) => b.aggregate - a.aggregate);
  const policyWinner = policyRuns[0];
  if (!policyWinner) throw new Error("RANKING_V2_NO_POLICY_WINNER");
  const holdoutSelected = selectRaces(holdoutBetting, policyWinner.count, policyWinner.mode);
  const holdoutMetrics = Object.fromEntries(courses.map((course) => [
    course,
    evaluatePortfolio(holdoutSelected, policyWinner.policies[course].policy, budget.COURSE_TARGET_STAKES[course])
  ]));

  const report = {
    generatedAt: new Date().toISOString(),
    targetRoiPct: 200,
    minimumRacesPerVenueDay: 5,
    featureCount: winner.weights.length,
    samples: { train: train.length, validation: validation.length, holdout: holdout.length },
    selectedTrainingConfig: winner.config,
    ranking: {
      marketValidation: Object.fromEntries(Object.entries(marketValidation).map(([key, value]) => [key, typeof value === "number" ? round(value) : value])),
      modelValidation: Object.fromEntries(Object.entries(winner.validation).map(([key, value]) => [key, typeof value === "number" ? round(value) : value])),
      marketHoldout: Object.fromEntries(Object.entries(marketHoldout).map(([key, value]) => [key, typeof value === "number" ? round(value) : value])),
      modelHoldout: Object.fromEntries(Object.entries(modelHoldout).map(([key, value]) => [key, typeof value === "number" ? round(value) : value]))
    },
    selectedRaceConfiguration: { mode: policyWinner.mode, count: policyWinner.count },
    validation: Object.fromEntries(courses.map((course) => [course, {
      policy: policyWinner.policies[course].policy,
      roi: round(policyWinner.policies[course].result.roi),
      hit: round(policyWinner.policies[course].result.hit),
      minMonth: round(policyWinner.policies[course].result.minMonth),
      hitRequirementMet: policyWinner.policies[course].result.hit >= requiredHitRatePct
    }])),
    holdout: Object.fromEntries(courses.map((course) => [course, {
      roi: round(holdoutMetrics[course].roi),
      hit: round(holdoutMetrics[course].hit),
      profit: holdoutMetrics[course].profit,
      pass200: holdoutMetrics[course].roi >= 200,
      hitRequirementMet: holdoutMetrics[course].hit >= requiredHitRatePct
    }]))
  };

  await (await import("node:fs/promises")).writeFile("runner-ranking-v2.json", JSON.stringify(report, null, 2) + "\n");
  console.log(`Ranking validation: market logloss ${round(marketValidation.logLoss)} / model ${round(winner.validation.logLoss)}, top1 market ${round(marketValidation.top1Pct)}% / model ${round(winner.validation.top1Pct)}%`);
  console.log(`Ranking holdout: market logloss ${round(marketHoldout.logLoss)} / model ${round(modelHoldout.logLoss)}, top1 market ${round(marketHoldout.top1Pct)}% / model ${round(modelHoldout.top1Pct)}%`);
  console.log(`Winner: ${policyWinner.mode}/${policyWinner.count}R`);
  for (const course of courses) {
    console.log(`${course}: validation ${report.validation[course].roi}% / holdout ${report.holdout[course].roi}% / hit ${report.holdout[course].hit}% / 200% ${report.holdout[course].pass200 ? "PASS" : "FAIL"}`);
  }
  console.log("Runner ranking result: runner-ranking-v2.json");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
