from pathlib import Path
import subprocess
import sys

source_path = Path('scripts/train-runner-ranking-v2.mjs')
out_path = Path('scripts/.generated-market-residual-ranking-v3.mjs')
source = source_path.read_text(encoding='utf-8')


def replace_between(start: str, end: str, replacement: str, label: str) -> None:
    global source
    i = source.find(start)
    if i < 0:
        raise RuntimeError(f'MARKET_RESIDUAL_PATCH_MISSING:{label}:start')
    j = source.find(end, i + len(start))
    if j < 0:
        raise RuntimeError(f'MARKET_RESIDUAL_PATCH_MISSING:{label}:end')
    source = source[:i] + replacement + source[j:]


def replace_required(old: str, new: str, label: str) -> None:
    global source
    if old not in source:
        raise RuntimeError(f'MARKET_RESIDUAL_PATCH_MISSING:{label}')
    source = source.replace(old, new, 1)

make_feature = r'''function makeFeatureVector(row, race, histories, marketProbability, fieldSize) {
  const horse = historyFeatures(histories.horse.get(row.horseName) ?? emptyHistory(), race.raceDate);
  const jockey = historyFeatures(histories.jockey.get(row.jockey) ?? emptyHistory(), race.raceDate);
  const trainer = historyFeatures(histories.trainer.get(row.trainer) ?? emptyHistory(), race.raceDate);
  const stable = historyFeatures(histories.stable.get(row.stable) ?? emptyHistory(), race.raceDate);
  const distance = distanceBucket(race.distanceM);
  const courseKey = `${row.horseName}|${race.venue}|${race.surface}|${distance}`;
  const jockeyCourseKey = `${row.jockey}|${race.surface}|${distance}`;
  const trainerCourseKey = `${row.trainer}|${race.surface}|${distance}`;
  const stableCourseKey = `${row.stable}|${race.surface}|${distance}`;
  const course = historyFeatures(histories.horseCourse.get(courseKey) ?? emptyHistory(), race.raceDate);
  const jockeyCourse = historyFeatures(histories.jockeyCourse.get(jockeyCourseKey) ?? emptyHistory(), race.raceDate);
  const trainerCourse = historyFeatures(histories.trainerCourse.get(trainerCourseKey) ?? emptyHistory(), race.raceDate);
  const stableCourse = historyFeatures(histories.stableCourse.get(stableCourseKey) ?? emptyHistory(), race.raceDate);
  const sex = sexFlags(row.sexAge);
  const popularity = row.popularity > 0 ? row.popularity / Math.max(1, fieldSize) : 0.5;
  const marketLog = Math.log(Math.max(0.000001, marketProbability));
  const venues = ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"];
  const venueFlags = venues.map((venue) => race.venue === venue ? 1 : 0);
  const surfaceFlags = [race.surface === "芝" ? 1 : 0, race.surface === "ダート" ? 1 : 0];
  const condition = String(race.trackCondition ?? "");
  const conditionFlags = [
    condition.includes("良") ? 1 : 0,
    condition.includes("稍") ? 1 : 0,
    condition.includes("重") && !condition.includes("不") ? 1 : 0,
    condition.includes("不") ? 1 : 0
  ];

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
    stable.winRate,
    stable.placeRate,
    course.winRate,
    course.placeRate,
    jockeyCourse.winRate,
    jockeyCourse.placeRate,
    trainerCourse.winRate,
    trainerCourse.placeRate,
    stableCourse.winRate,
    stableCourse.placeRate,
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
    marketProbability * stable.winRate * 10,
    marketProbability * horse.recentPlace * 4,
    course.winRate * horse.winRate * 10,
    fieldSize / 18,
    race.distanceM / 3200,
    race.raceNo / 12,
    ...surfaceFlags,
    ...conditionFlags,
    ...venueFlags
  ];
}

'''
replace_between('function makeFeatureVector(', 'function updateHistory(', make_feature, 'makeFeatureVector')

update_all = r'''function updateAllHistories(histories, race, row) {
  const result = {
    finishPosition: num(row.finishPosition),
    final3f: num(row.final3f),
    raceDate: race.raceDate
  };
  const distance = distanceBucket(race.distanceM);
  updateHistory(histories.horse, row.horseName, result);
  updateHistory(histories.jockey, row.jockey, result);
  updateHistory(histories.trainer, row.trainer, result);
  updateHistory(histories.stable, row.stable, result);
  updateHistory(histories.horseCourse, `${row.horseName}|${race.venue}|${race.surface}|${distance}`, result);
  updateHistory(histories.jockeyCourse, `${row.jockey}|${race.surface}|${distance}`, result);
  updateHistory(histories.trainerCourse, `${row.trainer}|${race.surface}|${distance}`, result);
  updateHistory(histories.stableCourse, `${row.stable}|${race.surface}|${distance}`, result);
}

'''
replace_between('function updateAllHistories(', 'function softmax(', update_all, 'updateAllHistories')

ranking_block = r'''function marketProbabilities(race) {
  const raw = race.runners.map((runner) => runner.winOdds > 1 ? 1 / runner.winOdds : 0.000001);
  const total = raw.reduce((sum, value) => sum + value, 0);
  return raw.map((value) => value / Math.max(0.000001, total));
}

function residualFeatures(runner) {
  return runner.x.slice(2);
}

function residualProbabilities(weights, race, scale = 1) {
  const market = marketProbabilities(race);
  const scores = race.runners.map((runner, index) =>
    Math.log(Math.max(0.000000001, market[index] ?? 0))
    + scale * dot(weights, residualFeatures(runner))
  );
  return softmax(scores);
}

function evaluateRanking(weights, races, scale = 1) {
  let loss = 0;
  let top1 = 0;
  let top3 = 0;
  let top1Returned = 0;
  let longshotTop1 = 0;
  let longshotRaces = 0;
  let count = 0;
  for (const race of races) {
    const winnerIndex = race.runners.findIndex((runner) => runner.finishPosition === 1);
    if (winnerIndex < 0) continue;
    const probabilities = residualProbabilities(weights, race, scale);
    loss -= Math.log(Math.max(0.000000001, probabilities[winnerIndex] ?? 0));
    const order = probabilities
      .map((probability, index) => ({ probability, index }))
      .sort((a, b) => b.probability - a.probability);
    const winnerOdds = race.runners[winnerIndex]?.winOdds ?? 0;
    if (winnerOdds >= 5) longshotRaces += 1;
    if (order[0]?.index === winnerIndex) {
      top1 += 1;
      top1Returned += winnerOdds * 100;
      if (winnerOdds >= 5) longshotTop1 += 1;
    }
    if (order.slice(0, 3).some((row) => row.index === winnerIndex)) top3 += 1;
    count += 1;
  }
  return {
    races: count,
    logLoss: count > 0 ? loss / count : Number.POSITIVE_INFINITY,
    top1Pct: count > 0 ? top1 / count * 100 : 0,
    top3Pct: count > 0 ? top3 / count * 100 : 0,
    top1Roi: count > 0 ? top1Returned / (count * 100) * 100 : 0,
    longshotTop1Pct: longshotRaces > 0 ? longshotTop1 / longshotRaces * 100 : 0
  };
}

function rankingSelectionScore(metrics) {
  return metrics.logLoss
    - Math.min(220, metrics.top1Roi) * 0.00045
    - metrics.top1Pct * 0.001
    - metrics.longshotTop1Pct * 0.00035;
}

function trainModel(train, validation, config) {
  const dimension = Math.max(0, (train[0]?.runners[0]?.x.length ?? 2) - 2);
  let weights = Array(dimension).fill(0);
  let bestWeights = [...weights];
  let bestScale = 0;
  let bestMetrics = evaluateRanking(weights, validation, 0);

  for (let epoch = 1; epoch <= config.epochs; epoch += 1) {
    const gradient = Array(dimension).fill(0);
    let weightedRunnerCount = 0;
    for (const race of train) {
      const winnerIndex = race.runners.findIndex((runner) => runner.finishPosition === 1);
      if (winnerIndex < 0) continue;
      const probabilities = residualProbabilities(weights, race, 1);
      const winnerOdds = Math.max(1, race.runners[winnerIndex]?.winOdds ?? 1);
      const raceWeight = Math.min(8, Math.pow(winnerOdds, config.longshotPower));
      race.runners.forEach((runner, runnerIndex) => {
        const error = ((probabilities[runnerIndex] ?? 0) - (runnerIndex === winnerIndex ? 1 : 0)) * raceWeight;
        residualFeatures(runner).forEach((value, featureIndex) => {
          gradient[featureIndex] += error * value;
        });
        weightedRunnerCount += raceWeight;
      });
    }
    const scale = config.learningRate / Math.max(1, weightedRunnerCount);
    weights = weights.map((weight, index) =>
      weight - scale * gradient[index] - config.learningRate * config.l2 * weight
    );

    if (epoch % 5 === 0 || epoch === config.epochs) {
      for (const residualScale of [0, 0.2, 0.4, 0.6, 0.8, 1, 1.25]) {
        const metrics = evaluateRanking(weights, validation, residualScale);
        if (rankingSelectionScore(metrics) < rankingSelectionScore(bestMetrics) - 0.000001) {
          bestMetrics = metrics;
          bestWeights = [...weights];
          bestScale = residualScale;
        }
      }
    }
  }
  return { weights: bestWeights, scale: bestScale, validation: bestMetrics, config };
}

function marketBaseline(races) {
  return evaluateRanking([], races, 0);
}

function buildPredictions(race, weights, scale = 1) {
  const probabilities = residualProbabilities(weights, race, scale);
  return race.runners.map((runner, index) => ({
    horseNo: runner.horseNo,
    horseName: runner.horseName,
    winProbability: probabilities[index] ?? 0,
    placeProbability: clip(1 - Math.pow(1 - (probabilities[index] ?? 0), 3), probabilities[index] ?? 0, 0.96),
    fairOdds: probabilities[index] > 0 ? 1 / probabilities[index] : 999,
    currentOdds: runner.winOdds,
    expectedValuePct: runner.winOdds > 1 ? (probabilities[index] ?? 0) * runner.winOdds * 100 : null,
    predictedOrder: 0,
    explanation: "market residual runner ranking v3",
    popularity: runner.popularity
  })).sort((a, b) => b.winProbability - a.winProbability).map((row, index) => ({ ...row, predictedOrder: index + 1 }));
}

'''
replace_between('function evaluateRanking(', 'function candidateScore(', ranking_block, 'ranking-functions')

replace_required(
'''  const histories = {
    horse: new Map(), jockey: new Map(), trainer: new Map(),
    horseCourse: new Map(), jockeyCourse: new Map(), trainerCourse: new Map()
  };''',
'''  const histories = {
    horse: new Map(), jockey: new Map(), trainer: new Map(), stable: new Map(),
    horseCourse: new Map(), jockeyCourse: new Map(), trainerCourse: new Map(), stableCourse: new Map()
  };''',
'histories'
)

model_selection = r'''  const configurations = [
    { learningRate: 0.06, l2: 0.002, epochs: 70, longshotPower: 0 },
    { learningRate: 0.035, l2: 0.006, epochs: 90, longshotPower: 0 },
    { learningRate: 0.025, l2: 0.012, epochs: 110, longshotPower: 0 },
    { learningRate: 0.04, l2: 0.006, epochs: 90, longshotPower: 0.12 },
    { learningRate: 0.03, l2: 0.01, epochs: 110, longshotPower: 0.22 },
    { learningRate: 0.02, l2: 0.015, epochs: 130, longshotPower: 0.35 }
  ];
  const marketValidation = marketBaseline(validation);
  const models = configurations.map((config) => trainModel(train, validation, config));
  models.sort((a, b) => {
    const aPenalty = Math.max(0, a.validation.logLoss - marketValidation.logLoss) * 2.5;
    const bPenalty = Math.max(0, b.validation.logLoss - marketValidation.logLoss) * 2.5;
    return rankingSelectionScore(a.validation) + aPenalty - rankingSelectionScore(b.validation) - bPenalty;
  });
  const winner = models[0];
  if (!winner) throw new Error("MARKET_RESIDUAL_NO_MODEL");
  const marketHoldout = marketBaseline(holdout);
  const modelHoldout = evaluateRanking(winner.weights, holdout, winner.scale);

'''
replace_between('  const configurations = [', '  function buildBettingRecords(', model_selection + '  function buildBettingRecords(', 'model-selection')

replace_required('const predictions = buildPredictions(race, winner.weights);', 'const predictions = buildPredictions(race, winner.weights, winner.scale);', 'prediction-scale')
replace_required('    selectedTrainingConfig: winner.config,', '    selectedTrainingConfig: { ...winner.config, residualScale: winner.scale },', 'report-scale')

source = source.replaceAll('runner-ranking-v2.json', 'market-residual-ranking-v3.json')
source = source.replaceAll('Runner ranking result:', 'Market residual ranking result:')
source = source.replaceAll('RANKING_V2_', 'MARKET_RESIDUAL_')
source = source.replaceAll('ranking-v2 policy', 'market-residual policy')

out_path.write_text(source, encoding='utf-8')
try:
    check = subprocess.run(['node', '--check', str(out_path)], text=True, capture_output=True)
    if check.returncode != 0:
        print(check.stdout)
        print(check.stderr, file=sys.stderr)
        raise SystemExit(check.returncode)
    result = subprocess.run(['node', str(out_path)])
    raise SystemExit(result.returncode)
finally:
    out_path.unlink(missing_ok=True)
