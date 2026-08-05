const token = process.env.CLOUDFLARE_API_TOKEN;
const account = process.env.CLOUDFLARE_ACCOUNT_ID || "3c6d1826b573b2e68cb13ec37e9e8ade";
const database = process.env.CLOUDFLARE_D1_DATABASE_ID || "949b5e8b-d1a4-4c4e-80d1-d031afdc03de";
const endpoint = `https://api.cloudflare.com/client/v4/accounts/${account}/d1/database/${database}/query`;
const courses = ["ライト", "スタンダード", "プレミアム"];
const profiles = {
  all: new Set(["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"]),
  no3tan: new Set(["単勝", "ワイド", "馬連", "馬単", "3連複"]),
  hit: new Set(["単勝", "ワイド", "馬連", "3連複"]),
  stable: new Set(["単勝", "ワイド", "馬連"]),
  singleWide: new Set(["単勝", "ワイド"]),
  wideOnly: new Set(["ワイド"])
};
if (!token) throw new Error("CLOUDFLARE_API_TOKEN is not set");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const num = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const split = (values, size) => Array.from({ length: Math.ceil(values.length / size) }, (_, index) => values.slice(index * size, (index + 1) * size));

async function sql(query, params = []) {
  let last;
  for (let attempt = 1; attempt <= 6; attempt += 1) {
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ sql: query, params })
      });
      const payload = await response.json();
      if (!response.ok || payload.success !== true) {
        const error = new Error(`D1_${response.status}:${JSON.stringify(payload.errors ?? [])}`);
        if (response.status === 429 || response.status >= 500) throw error;
        throw error;
      }
      await sleep(60);
      return payload.result?.[0]?.results ?? [];
    } catch (error) {
      last = error;
      if (attempt === 6) throw error;
      await sleep(attempt * 1500);
    }
  }
  throw last;
}

function canonical(type, combination) {
  const values = (String(combination).match(/\d{1,2}/g) ?? []).map(Number);
  if (["ワイド", "馬連", "3連複"].includes(type)) values.sort((a, b) => a - b);
  return values.join("-");
}

function ticketScore(ticket) {
  return Math.max(0.01, ticket.expectedValuePct / 100) * Math.sqrt(Math.max(0.000001, ticket.hitProbability));
}

function allocate(tickets, target, limit) {
  const rows = [...tickets].sort((a, b) => ticketScore(b) - ticketScore(a)).slice(0, limit);
  if (!rows.length) return [];
  const units = Math.floor(target / 100);
  const base = rows.map(() => 1);
  const extra = Math.max(0, units - rows.length);
  const weights = rows.map(ticketScore);
  const total = weights.reduce((sum, value) => sum + value, 0);
  const exact = weights.map((value) => extra * value / total);
  const add = exact.map(Math.floor);
  let left = extra - add.reduce((sum, value) => sum + value, 0);
  for (const row of exact.map((value, index) => ({ index, rest: value - Math.floor(value) })).sort((a, b) => b.rest - a.rest)) {
    if (!left) break;
    add[row.index] += 1;
    left -= 1;
  }
  return rows.map((row, index) => ({ ...row, stakeYen: (base[index] + add[index]) * 100 }));
}

function portfolio(race, course, policy, target) {
  const original = race.tickets[course] ?? [];
  let rows = original.filter((ticket) =>
    profiles[policy.profile].has(ticket.betType)
    && ticket.expectedValuePct >= policy.minEv
    && ticket.hitProbability >= policy.minHit
    && ticket.assumedOdds <= policy.maxOdds
  );
  if (!rows.length && original.length) rows = [[...original].sort((a, b) => ticketScore(b) - ticketScore(a))[0]];
  return allocate(rows, target, policy.maxTickets);
}

function selected(records, count) {
  const groups = new Map();
  for (const race of records) {
    const key = `${race.raceDate}:${race.venue}`;
    groups.set(key, [...(groups.get(key) ?? []), race]);
  }
  return [...groups.values()].flatMap((rows) => rows.sort((a, b) => b.score - a.score || a.raceNo - b.raceNo).slice(0, Math.max(5, count)));
}

function metrics(records, course, policy, target) {
  let stake = 0, returned = 0, hits = 0, tickets = 0, ticketHits = 0;
  const months = new Map();
  for (const race of records) {
    const bets = portfolio(race, course, policy, target);
    let raceReturn = 0;
    for (const bet of bets) {
      const value = Math.round(bet.stakeYen / 100 * bet.returnPer100);
      stake += bet.stakeYen;
      returned += value;
      raceReturn += value;
      tickets += 1;
      ticketHits += value > 0 ? 1 : 0;
    }
    hits += raceReturn > 0 ? 1 : 0;
    const month = race.raceDate.slice(0, 7);
    const row = months.get(month) ?? { stake: 0, returned: 0 };
    row.stake += bets.reduce((sum, bet) => sum + bet.stakeYen, 0);
    row.returned += raceReturn;
    months.set(month, row);
  }
  const roi = stake ? returned / stake * 100 : 0;
  const hit = records.length ? hits / records.length * 100 : 0;
  const minMonth = months.size ? Math.min(...[...months.values()].map((row) => row.stake ? row.returned / row.stake * 100 : 0)) : 0;
  return { races: records.length, roi, hit, ticketHit: tickets ? ticketHits / tickets * 100 : 0, minMonth, profit: returned - stake };
}

function grid() {
  const rows = [];
  for (const profile of Object.keys(profiles))
    for (const minEv of [0, 110, 120, 130, 150, 180])
      for (const minHit of [0, 0.04, 0.08, 0.12, 0.18])
        for (const maxOdds of [12, 30, 80, 2500])
          for (const maxTickets of [1, 2, 3, 5, 8]) rows.push({ profile, minEv, minHit, maxOdds, maxTickets });
  return rows;
}

function bestPolicy(records, course, target, baseline) {
  const candidates = grid().map((policy) => {
    const result = metrics(records, course, policy, target);
    const score = result.roi * 0.6 + result.minMonth * 0.3 + result.hit * 0.1;
    return { policy, result, score };
  });
  const improved = candidates.filter((row) => row.result.hit >= baseline.hit + 1);
  return (improved.length ? improved : candidates.filter((row) => row.result.hit >= baseline.hit))
    .sort((a, b) => b.score - a.score || b.result.roi - a.result.roi)[0];
}

const round = (value) => Number(value.toFixed(1));

async function main() {
  const [betting, budget, state, scope] = await Promise.all([
    import("../dist-test/src/v1/learned-betting-policy.js"),
    import("../dist-test/src/v1/budget-courses.js"),
    import("../dist-test/src/v1/learned-calibration-state.js"),
    import("../dist-test/src/v1/walk-forward-scope.js")
  ]);
  const races = await sql(`
    SELECT r.race_id raceId,r.race_date raceDate,r.venue,r.race_no raceNo,r.refund_horse_nos_json refunds,p.id predictionId
    FROM rt_races r JOIN rt_predictions p ON p.race_id=r.race_id
    WHERE p.model_version=? AND p.status='locked'
      AND (r.race_date BETWEEN ? AND ? OR r.race_date BETWEEN ? AND ?)
    ORDER BY r.race_date,r.venue,r.race_no
  `, [state.WORKER_LEARNED_MODEL_VERSION, scope.WALK_FORWARD_VALIDATION_START_DATE, scope.WALK_FORWARD_VALIDATION_END_DATE, scope.WALK_FORWARD_HOLDOUT_START_DATE, scope.WALK_FORWARD_HOLDOUT_END_DATE]);

  const runners = new Map(), payouts = new Map();
  for (const ids of split(races.map((row) => num(row.predictionId)), 80)) {
    for (const row of await sql(`
      SELECT p.race_id raceId,pr.horse_no horseNo,pr.horse_name horseName,pr.win_probability winProbability,
        pr.place_probability placeProbability,pr.fair_odds fairOdds,pr.current_odds currentOdds,
        pr.expected_value_pct expectedValuePct,pr.predicted_order predictedOrder,pr.explanation,rr.popularity
      FROM rt_prediction_runners pr JOIN rt_predictions p ON p.id=pr.prediction_id
      LEFT JOIN rt_runners rr ON rr.race_id=p.race_id AND rr.horse_no=pr.horse_no
      WHERE pr.prediction_id IN (SELECT value FROM json_each(?)) ORDER BY p.race_id,pr.predicted_order
    `, [JSON.stringify(ids)])) {
      const values = runners.get(row.raceId) ?? [];
      values.push({ horseNo:num(row.horseNo), horseName:row.horseName, winProbability:num(row.winProbability), placeProbability:num(row.placeProbability), fairOdds:num(row.fairOdds), currentOdds:row.currentOdds===null?null:num(row.currentOdds), expectedValuePct:row.expectedValuePct===null?null:num(row.expectedValuePct), predictedOrder:num(row.predictedOrder), explanation:row.explanation??"", popularity:row.popularity===null?null:num(row.popularity) });
      runners.set(row.raceId, values);
    }
  }
  for (const ids of split(races.map((row) => row.raceId), 100)) {
    for (const row of await sql(`SELECT race_id raceId,bet_type betType,combination,payout_yen payoutYen FROM rt_payouts WHERE race_id IN (SELECT value FROM json_each(?))`, [JSON.stringify(ids)])) {
      payouts.set(row.raceId, [...(payouts.get(row.raceId) ?? []), row]);
    }
  }

  const records = races.flatMap((race) => {
    const predictions = runners.get(race.raceId) ?? [];
    if (predictions.length < 2) return [];
    const refunds = new Set(JSON.parse(race.refunds || "[]"));
    const payoutMap = new Map((payouts.get(race.raceId) ?? []).map((row) => [`${row.betType}:${canonical(row.betType,row.combination)}`, num(row.payoutYen)]));
    const tickets = Object.fromEntries(courses.map((course) => [course, []]));
    for (const bet of betting.buildLearnedVenueBets(predictions)) {
      const horses = (bet.combination.match(/\d{1,2}/g) ?? []).map(Number);
      const returnPer100 = horses.some((horse) => refunds.has(horse)) ? 100 : payoutMap.get(`${bet.betType}:${canonical(bet.betType,bet.combination)}`) ?? 0;
      tickets[bet.course].push({ ...bet, returnPer100 });
    }
    return [{ raceId:race.raceId, raceDate:race.raceDate, venue:race.venue, raceNo:num(race.raceNo), score:betting.learnedPredictionRaceScore(predictions), tickets }];
  });

  const validation = records.filter((row) => row.raceDate >= scope.WALK_FORWARD_VALIDATION_START_DATE && row.raceDate <= scope.WALK_FORWARD_VALIDATION_END_DATE);
  const holdout = records.filter((row) => row.raceDate >= scope.WALK_FORWARD_HOLDOUT_START_DATE && row.raceDate <= scope.WALK_FORWARD_HOLDOUT_END_DATE);
  const baselineRows = selected(validation, 5);
  const current = { profile:"all", minEv:0, minHit:0, maxOdds:2500, maxTickets:8 };
  const baseline = Object.fromEntries(courses.map((course) => [course, metrics(baselineRows, course, current, budget.COURSE_TARGET_STAKES[course])]));

  const candidates = [];
  for (const count of [5,6,7,8,9,10,12]) {
    console.log(`Analyzing ${count} races per venue/day...`);
    const rows = selected(validation, count);
    const policies = Object.fromEntries(courses.map((course) => [course, bestPolicy(rows, course, budget.COURSE_TARGET_STAKES[course], baseline[course])]));
    const minRoi = Math.min(...courses.map((course) => policies[course].result.roi));
    const minHit = Math.min(...courses.map((course) => policies[course].result.hit));
    const minMonth = Math.min(...courses.map((course) => policies[course].result.minMonth));
    candidates.push({ count, policies, score:minRoi*.6+minMonth*.3+minHit*.1, minRoi, minHit, minMonth });
  }
  candidates.sort((a,b) => b.score-a.score);
  const winner = candidates[0];
  const holdoutRows = selected(holdout, winner.count);
  const final = Object.fromEntries(courses.map((course) => [course, metrics(holdoutRows, course, winner.policies[course].policy, budget.COURSE_TARGET_STAKES[course])]));
  const report = {
    targetRoiPct:200,
    minimumRacesPerVenueDay:5,
    selectedRacesPerVenueDay:winner.count,
    baseline:Object.fromEntries(courses.map((course)=>[course,{roi:round(baseline[course].roi),hit:round(baseline[course].hit)}])),
    validation:Object.fromEntries(courses.map((course)=>[course,{policy:winner.policies[course].policy,roi:round(winner.policies[course].result.roi),hit:round(winner.policies[course].result.hit),minMonth:round(winner.policies[course].result.minMonth)}])),
    holdout:Object.fromEntries(courses.map((course)=>[course,{roi:round(final[course].roi),hit:round(final[course].hit),profit:final[course].profit,pass200:final[course].roi>=200}]))
  };
  await (await import("node:fs/promises")).writeFile("policy-analysis.json", JSON.stringify(report,null,2)+"\n");
  console.log("\n=== Baseline validation ===");
  for (const course of courses) console.log(`${course}: ROI ${report.baseline[course].roi}% / hit ${report.baseline[course].hit}%`);
  console.log(`\n=== Validation winner: ${winner.count}R per venue/day (minimum 5 preserved) ===`);
  for (const course of courses) console.log(`${course}: ROI ${report.validation[course].roi}% / hit ${report.validation[course].hit}% / ${JSON.stringify(report.validation[course].policy)}`);
  console.log("\n=== Untouched holdout ===");
  for (const course of courses) console.log(`${course}: ROI ${report.holdout[course].roi}% / hit ${report.holdout[course].hit}% / 200% ${report.holdout[course].pass200?"PASS":"FAIL"}`);
  console.log("\nFull result: policy-analysis.json");
}
main().catch((error)=>{ console.error(error); process.exitCode=1; });
