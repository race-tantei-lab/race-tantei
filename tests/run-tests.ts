import { strict as assert } from "node:assert";
import {
  extractEntryLinks,
  extractResultUrl,
  pageLooksLikeEntry,
  pageLooksLikeResult,
  parseEntryPage,
  parseResultPage,
  toResultUrl
} from "../src/v1/jra.js";
import { buildBudgetCourseBets, COURSE_BUDGETS } from "../src/v1/budget-courses.js";
import { generatePrediction } from "../src/v1/model.js";
import type {
  BetType,
  BudgetCourse,
  RaceRecord,
  RunnerHistoryStats,
  RunnerPrediction,
  RunnerRecord
} from "../src/v1/types.js";

const entryUrl = "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0101202601030520260801%2F15";
const officialResultUrl = "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0101202601030520260801%2F88";
const fallbackResult = toResultUrl(entryUrl);
assert.ok(fallbackResult.includes("accessS.html"));
assert.ok(decodeURIComponent(fallbackResult).includes("pw01sde"));

const navigation = `
<a href="/JRADB/accessD.html?CNAME=pw01dde0101202601030120260801%2FAA">1R</a>
<a data-url='https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01dde0101202601030220260801%2FBB'>2R</a>
<a href="/JRADB/accessS.html?CNAME=pw01sde0101202601030520260801%2F88">レース結果</a>`;
assert.equal(extractEntryLinks(navigation, "https://www.jra.go.jp/").length, 2);
assert.equal(extractResultUrl(navigation, entryUrl), officialResultUrl);

const entryHtml = `<!doctype html><html><body>
<h1>出馬表</h1>
<div>2026年8月1日（土曜） 1回札幌3日 発走時刻：12時20分</div>
<div>5レース</div><h2>メイクデビュー札幌</h2>
<p>2歳 新馬 （混合）［指定］ 馬齢 コース：1,500メートル（芝・右）</p>
<a href="/JRADB/accessS.html?CNAME=pw01sde0101202601030520260801%2F88">レース結果</a>
<table><tr><th>枠</th><th>馬番</th><th>馬名 / 単勝オッズ(人気) 馬体重 調教師名 血統</th><th>性齢/毛色 負担重量 騎手名</th></tr>
<tr><td><img alt="枠1白"></td><td>1</td><td>イントゥーザブルー5.6(4番人気) 470kg(初出走) 清水 英克(美浦) 父：キタサンブラック</td><td>牡2/栗 55.0 kg 丹内 祐次</td></tr>
<tr><td><img alt="枠4青"></td><td>5</td><td>ティアラード3.3(2番人気) 460kg(初出走) 小栗 実(栗東) 父：モーリス</td><td>牝2/黒鹿 55.0 kg 横山 武史</td></tr>
<tr><td><img alt="枠5黄"></td><td>7</td><td>ブルージェイ2.5(1番人気) 460kg(初出走) 加藤 征弘(美浦) 父：ロードカナロア</td><td>牡2/黒鹿 55.0 kg 鮫島 克駿</td></tr>
</table></body></html>`;
assert.equal(pageLooksLikeEntry(entryHtml), true);
const entry = parseEntryPage(entryHtml, entryUrl);
assert.equal(entry.race.raceId, "2026-08-01-sapporo-05");
assert.equal(entry.race.startTimeUtc, "2026-08-01T03:20:00.000Z");
assert.equal(entry.race.resultUrl, officialResultUrl);
assert.equal(entry.race.distanceM, 1500);
assert.equal(entry.race.surface, "芝");
assert.equal(entry.runners.length, 3);
assert.equal(entry.runners[2]?.horseName, "ブルージェイ");
assert.equal(entry.runners[2]?.winOdds, 2.5);
assert.equal(entry.runners[2]?.jockey, "鮫島 克駿");
assert.equal(entry.runners[2]?.trainer, "加藤 征弘");

const resultHtml = `<!doctype html><html><body>
<h1>レース結果</h1>
<div>2026年8月1日（土曜） 1回札幌3日 発走時刻：12時20分</div>
<div>天候曇 芝稍重 5レース</div><h2>メイクデビュー札幌</h2>
<p>2歳 新馬 （混合）［指定］ 馬齢 コース：1,500メートル（芝・右）</p>
<a href="/JRADB/accessD.html?CNAME=pw01dde0101202601030520260801%2F15">出馬表</a>
<table><tr><th>着順</th><th>枠</th><th>馬番</th><th>馬名</th><th>性齢</th><th>負担重量</th><th>騎手名</th><th>タイム</th><th>着差</th><th>推定上り</th></tr>
<tr><td>1</td><td><img alt="枠5黄"></td><td>7</td><td>ブルージェイ</td><td>牡2</td><td>55.0</td><td>鮫島 克駿</td><td>1:30.4</td><td></td><td>35.4</td></tr>
<tr><td>2</td><td><img alt="枠4青"></td><td>5</td><td>ティアラード</td><td>牝2</td><td>55.0</td><td>横山 武史</td><td>1:30.9</td><td>２ 1/2</td><td>35.7</td></tr>
<tr><td>3</td><td><img alt="枠3赤"></td><td>3</td><td>ギャルズマインド</td><td>牝2</td><td>55.0</td><td>浜中 俊</td><td>1:31.0</td><td>１</td><td>35.8</td></tr>
</table>
<h2>払戻金</h2><table>
<tr><td>単勝</td><td>7</td><td>250円</td><td>1番人気</td></tr>
<tr><td>馬連</td><td>5-7</td><td>430円</td><td>1番人気</td></tr>
<tr><td>3連複</td><td>3-5-7</td><td>550円</td><td>1番人気</td></tr>
</table><p>返還馬番：4</p></body></html>`;
assert.equal(pageLooksLikeResult(resultHtml), true);
const result = parseResultPage(resultHtml, officialResultUrl);
assert.equal(result.results.length, 3);
assert.equal(result.results[0]?.horseNo, 7);
assert.equal(result.results[0]?.final3f, 35.4);
assert.equal(result.payouts.find((p) => p.betType === "単勝")?.payoutYen, 250);
assert.deepEqual(result.refundHorseNos, [4]);

const race: RaceRecord = entry.race;
const runners: RunnerRecord[] = entry.runners;
const stats: RunnerHistoryStats[] = runners.map((runner) => ({
  horseNo: runner.horseNo,
  horseStarts: runner.horseNo === 7 ? 3 : 0,
  horseWins: runner.horseNo === 7 ? 1 : 0,
  horsePlaces: runner.horseNo === 7 ? 2 : 0,
  jockeyStarts: 20,
  jockeyWins: runner.horseNo === 7 ? 4 : 2,
  trainerStarts: 20,
  trainerWins: runner.horseNo === 7 ? 3 : 2,
  courseStarts: 0,
  courseWins: 0
}));
const prediction = generatePrediction(race, runners, stats, "v3.0.0-value-engine", 108, 2000);
assert.equal(prediction.runners.length, 3);
assert.equal(prediction.runners[0]?.horseNo, 7);
assert.ok(Math.abs(prediction.runners.reduce((sum, runner) => sum + runner.winProbability, 0) - 1) < 0.000001);
assert.ok(prediction.bets.reduce((sum, bet) => sum + bet.stakeYen, 0) <= 2000);
assert.ok(prediction.bets.every((bet) => bet.course === "ライト"));
assert.ok(prediction.bets.every((bet) => bet.stakeYen % 100 === 0));

function runnerPrediction(
  horseNo: number,
  probability: number,
  odds: number,
  predictedOrder: number
): RunnerPrediction {
  return {
    horseNo,
    horseName: `テスト${horseNo}`,
    winProbability: probability,
    placeProbability: Math.min(0.96, 1 - Math.pow(1 - probability, 3)),
    fairOdds: 1 / probability,
    currentOdds: odds,
    expectedValuePct: probability * odds * 100,
    predictedOrder,
    explanation: "テスト"
  };
}

const marketAligned: RunnerPrediction[] = [
  runnerPrediction(1, 0.5, 2, 1),
  runnerPrediction(2, 0.25, 4, 2),
  runnerPrediction(3, 0.125, 8, 3),
  runnerPrediction(4, 0.0625, 16, 4),
  runnerPrediction(5, 0.0625, 16, 5)
];
assert.deepEqual(buildBudgetCourseBets(marketAligned, 108), []);

const strongEdge: RunnerPrediction[] = [
  runnerPrediction(1, 0.58, 5, 1),
  runnerPrediction(2, 0.16, 2.2, 2),
  runnerPrediction(3, 0.11, 4, 3),
  runnerPrediction(4, 0.08, 8, 4),
  runnerPrediction(5, 0.07, 14, 5)
];
const valueBets = buildBudgetCourseBets(strongEdge, 108);
assert.ok(valueBets.length > 0);
assert.ok(valueBets.every((bet) => bet.expectedValuePct >= 108));
assert.ok(valueBets.every((bet) => bet.stakeYen >= 100 && bet.stakeYen % 100 === 0));

const allowed: Record<BudgetCourse, Set<BetType>> = {
  ライト: new Set<BetType>(["単勝", "ワイド", "馬連"]),
  スタンダード: new Set<BetType>(["単勝", "ワイド", "馬連", "馬単", "3連複"]),
  プレミアム: new Set<BetType>(["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"])
};
for (const course of Object.keys(COURSE_BUDGETS) as BudgetCourse[]) {
  const courseBets = valueBets.filter((bet) => bet.course === course);
  const stake = courseBets.reduce((sum, bet) => sum + bet.stakeYen, 0);
  assert.ok(stake <= COURSE_BUDGETS[course]);
  assert.ok(stake < COURSE_BUDGETS[course]);
  assert.ok(courseBets.every((bet) => allowed[course].has(bet.betType)));
}
assert.deepEqual(buildBudgetCourseBets(strongEdge, 10000), []);

console.log("race-tantei Phase B value-engine tests passed");
