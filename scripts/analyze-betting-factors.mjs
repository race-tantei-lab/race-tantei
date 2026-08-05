const token = process.env.CLOUDFLARE_API_TOKEN;
const account = process.env.CLOUDFLARE_ACCOUNT_ID || "3c6d1826b573b2e68cb13ec37e9e8ade";
const database = process.env.CLOUDFLARE_D1_DATABASE_ID || "949b5e8b-d1a4-4c4e-80d1-d031afdc03de";
const endpoint = `https://api.cloudflare.com/client/v4/accounts/${account}/d1/database/${database}/query`;
const courses = ["ライト", "スタンダード", "プレミアム"];

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

function quantile(sorted, probability) {
  if (!sorted.length) return 0;
  const position = (sorted.length - 1) * probability;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower] ?? 0;
  const weight = position - lower;
  return (sorted[lower] ?? 0) * (1 - weight) + (sorted[upper] ?? 0) * weight;
}

function summarize(rows) {
  const weightedStake = rows.reduce((sum, row) => sum + row.stakeYen, 0);
  const weightedReturn = rows.reduce(
    (sum, row) => sum + Math.round(row.stakeYen / 100 * row.returnPer100),
    0
  );
  const equalStake = rows.length * 100;
  const equalReturn = rows.reduce((sum, row) => sum + row.returnPer100, 0);
  const hitTickets = rows.filter((row) => row.returnPer100 > 0).length;
  return {
    tickets: rows.length,
    races: new Set(rows.map((row) => row.raceId)).size,
    weightedRoi: weightedStake > 0 ? round(weightedReturn / weightedStake * 100) : 0,
    equalStakeRoi: equalStake > 0 ? round(equalReturn / equalStake * 100) : 0,
    ticketHitPct: rows.length > 0 ? round(hitTickets / rows.length * 100) : 0,
    weightedProfitYen: weightedReturn - weightedStake
  };
}

function groupRows(rows, keyFn) {
  const groups = new Map();
  for (const row of rows) {
    const key = keyFn(row);
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  return groups;
}

function factorReport(validationRows, holdoutRows, keyFn) {
  const validationGroups = groupRows(validationRows, keyFn);
  const holdoutGroups = groupRows(holdoutRows, keyFn);
  const all = [...validationGroups.entries()].map(([key, rows]) => ({
    key,
    validation: summarize(rows),
    holdout: summarize(holdoutGroups.get(key) ?? [])
  }));
  const eligible = all.filter((row) => row.validation.tickets >= 25 && row.validation.races >= 12);
  const positive = [...eligible]
    .filter((row) => row.validation.equalStakeRoi >= 100)
    .sort((a, b) =>
      b.validation.equalStakeRoi - a.validation.equalStakeRoi
      || b.validation.tickets - a.validation.tickets
    )
    .slice(0, 20);
  const losses = [...eligible]
    .sort((a, b) =>
      a.validation.equalStakeRoi - b.validation.equalStakeRoi
      || b.validation.tickets - a.validation.tickets
    )
    .slice(0, 15);
  return {
    all: all.sort((a, b) => a.key.localeCompare(b.key, "ja")),
    validationPositiveSignals: positive,
    validationLossSources: losses
  };
}

async function main() {
  const [betting, state, scope] = await Promise.all([
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

  const raceRecords = [];
  const ticketRows = [];

  for (const race of races) {
    const predictions = runnersByRace.get(race.raceId) ?? [];
    if (predictions.length < 2) continue;
    const ranked = [...predictions].sort((a, b) => a.predictedOrder - b.predictedOrder);
    const first = ranked[0];
    const second = ranked[1];
    const topWinProbability = first?.winProbability ?? 0;
    const probabilityGap = topWinProbability - (second?.winProbability ?? 0);
    const raceScore = betting.learnedPredictionRaceScore(predictions);
    if (!Number.isFinite(raceScore)) continue;

    const split = race.raceDate >= scope.WALK_FORWARD_HOLDOUT_START_DATE ? "holdout" : "validation";
    raceRecords.push({ raceId: race.raceId, split, score: raceScore });

    const refunds = new Set(JSON.parse(race.refunds || "[]"));
    const payoutMap = new Map((payoutsByRace.get(race.raceId) ?? []).map((row) => [
      `${row.betType}:${canonical(row.betType, row.combination)}`,
      num(row.payoutYen)
    ]));
    const orderByHorse = new Map(ranked.map((row) => [row.horseNo, row.predictedOrder]));

    for (const bet of betting.buildLearnedVenueBets(predictions)) {
      const horses = (String(bet.combination).match(/\d{1,2}/g) ?? []).map(Number);
      const returnPer100 = horses.some((horse) => refunds.has(horse))
        ? 100
        : payoutMap.get(`${bet.betType}:${canonical(bet.betType, bet.combination)}`) ?? 0;
      const ranks = horses.map((horse) => orderByHorse.get(horse) ?? 99);
      ticketRows.push({
        split,
        raceId: race.raceId,
        raceDate: race.raceDate,
        venue: race.venue,
        raceNo: num(race.raceNo),
        course: bet.course,
        betType: bet.betType,
        combination: bet.combination,
        stakeYen: num(bet.stakeYen),
        assumedOdds: num(bet.assumedOdds),
        hitProbability: num(bet.hitProbability),
        expectedValuePct: num(bet.expectedValuePct),
        returnPer100,
        includesFirst: ranks.includes(1),
        rankSum: ranks.reduce((sum, value) => sum + value, 0),
        maximumRank: Math.max(...ranks),
        fieldSize: predictions.length,
        topWinProbability,
        probabilityGap,
        raceScore
      });
    }
  }

  const validationScores = raceRecords
    .filter((row) => row.split === "validation")
    .map((row) => row.score)
    .sort((a, b) => a - b);
  const scoreCuts = [0.2, 0.4, 0.6, 0.8].map((value) => quantile(validationScores, value));

  for (const row of ticketRows) {
    row.oddsBucket = bucket(row.assumedOdds, [3, 5, 10, 20, 50, 100], ["<3", "3-5", "5-10", "10-20", "20-50", "50-100", "100+"]);
    row.evBucket = bucket(row.expectedValuePct, [100, 110, 125, 150, 200, 300], ["<100", "100-110", "110-125", "125-150", "150-200", "200-300", "300+"]);
    row.hitBucket = bucket(row.hitProbability, [0.01, 0.03, 0.06, 0.1, 0.18, 0.3], ["<1%", "1-3%", "3-6%", "6-10%", "10-18%", "18-30%", "30%+"]);
    row.rankBucket = bucket(row.rankSum, [3, 5, 8, 12], ["rankSum<3", "rankSum3-4", "rankSum5-7", "rankSum8-11", "rankSum12+"]);
    row.fieldBucket = bucket(row.fieldSize, [10, 14, 17], ["<=9", "10-13", "14-16", "17+"]);
    row.topProbabilityBucket = bucket(row.topWinProbability, [0.2, 0.3, 0.4, 0.5], ["<20%", "20-30%", "30-40%", "40-50%", "50%+"]);
    row.gapBucket = bucket(row.probabilityGap, [0.03, 0.07, 0.12, 0.2], ["<3pt", "3-7pt", "7-12pt", "12-20pt", "20pt+"]);
    row.scoreBucket = bucket(row.raceScore, scoreCuts, ["Q1", "Q2", "Q3", "Q4", "Q5"]);
  }

  const validationRows = ticketRows.filter((row) => row.split === "validation");
  const holdoutRows = ticketRows.filter((row) => row.split === "holdout");
  const factors = {
    course: factorReport(validationRows, holdoutRows, (row) => row.course),
    courseBetType: factorReport(validationRows, holdoutRows, (row) => `${row.course}|${row.betType}`),
    courseOdds: factorReport(validationRows, holdoutRows, (row) => `${row.course}|${row.oddsBucket}`),
    courseExpectedValue: factorReport(validationRows, holdoutRows, (row) => `${row.course}|${row.evBucket}`),
    courseHitProbability: factorReport(validationRows, holdoutRows, (row) => `${row.course}|${row.hitBucket}`),
    courseIncludesFirst: factorReport(validationRows, holdoutRows, (row) => `${row.course}|first=${row.includesFirst}`),
    courseRankSum: factorReport(validationRows, holdoutRows, (row) => `${row.course}|${row.rankBucket}`),
    courseScoreQuintile: factorReport(validationRows, holdoutRows, (row) => `${row.course}|score=${row.scoreBucket}`),
    courseFieldSize: factorReport(validationRows, holdoutRows, (row) => `${row.course}|field=${row.fieldBucket}`),
    courseTopProbability: factorReport(validationRows, holdoutRows, (row) => `${row.course}|top=${row.topProbabilityBucket}`),
    courseProbabilityGap: factorReport(validationRows, holdoutRows, (row) => `${row.course}|gap=${row.gapBucket}`),
    betTypeOdds: factorReport(validationRows, holdoutRows, (row) => `${row.betType}|${row.oddsBucket}`),
    betTypeExpectedValue: factorReport(validationRows, holdoutRows, (row) => `${row.betType}|${row.evBucket}`),
    betTypeHitProbability: factorReport(validationRows, holdoutRows, (row) => `${row.betType}|${row.hitBucket}`),
    courseBetTypeOdds: factorReport(validationRows, holdoutRows, (row) => `${row.course}|${row.betType}|${row.oddsBucket}`),
    courseBetTypeScore: factorReport(validationRows, holdoutRows, (row) => `${row.course}|${row.betType}|score=${row.scoreBucket}`)
  };

  const report = {
    generatedAt: new Date().toISOString(),
    method: "Validation factors are ranked without using holdout results. Holdout is attached only as a blind stability check.",
    validationRange: [scope.WALK_FORWARD_VALIDATION_START_DATE, scope.WALK_FORWARD_VALIDATION_END_DATE],
    holdoutRange: [scope.WALK_FORWARD_HOLDOUT_START_DATE, scope.WALK_FORWARD_HOLDOUT_END_DATE],
    races: {
      validation: new Set(validationRows.map((row) => row.raceId)).size,
      holdout: new Set(holdoutRows.map((row) => row.raceId)).size
    },
    tickets: {
      validation: validationRows.length,
      holdout: holdoutRows.length
    },
    overall: {
      validation: Object.fromEntries(courses.map((course) => [course, summarize(validationRows.filter((row) => row.course === course))])),
      holdout: Object.fromEntries(courses.map((course) => [course, summarize(holdoutRows.filter((row) => row.course === course))]))
    },
    scoreQuintileBoundaries: scoreCuts.map(round),
    factors
  };

  await (await import("node:fs/promises")).writeFile(
    "betting-factor-analysis.json",
    JSON.stringify(report, null, 2) + "\n"
  );

  console.log(`Validation: ${report.races.validation} races / ${report.tickets.validation} tickets`);
  console.log(`Holdout: ${report.races.holdout} races / ${report.tickets.holdout} tickets`);
  for (const course of courses) {
    const validation = report.overall.validation[course];
    const holdout = report.overall.holdout[course];
    console.log(`${course}: validation weighted ROI ${validation.weightedRoi}% / holdout ${holdout.weightedRoi}%`);
  }
  console.log("Factor result: betting-factor-analysis.json");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
