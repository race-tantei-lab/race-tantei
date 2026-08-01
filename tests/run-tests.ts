import { strict as assert } from "node:assert";
import { extractEntryLinks, parseEntryPage, parseResultPage, toResultUrl } from "../src/v1/jra.js";
import { generatePrediction } from "../src/v1/model.js";
import type { RaceRecord, RunnerHistoryStats, RunnerRecord } from "../src/v1/types.js";

const entryUrl = "https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01dde0101202601030520260801%2F15";
const resultUrl = toResultUrl(entryUrl);
assert.ok(resultUrl.includes("accessS.html"));
assert.ok(decodeURIComponent(resultUrl).includes("sw01sde"));

const navigation = `<a href="/JRADB/accessD.html?CNAME=sw01dde0101202601030120260801%2FAA">1R</a>
<a href='https://sp.jra.jp/JRADB/accessD.html?CNAME=sw01dde0101202601030220260801%2FBB'>2R</a>`;
assert.equal(extractEntryLinks(navigation, "https://sp.jra.jp/").length, 2);

const entryHtml = `<!doctype html><html><body>
<h1>出馬表</h1>
<h2>2026年8月1日(土曜) 1回札幌3日</h2>
<h3>5R メイクデビュー札幌</h3>
<p>2歳 新馬 (混合)[指定] 馬齢</p>
<p>コース 1500m 芝・右 発走12:20</p>
<table><tr><th>枠</th><th>馬番</th><th>馬名 / 単勝オッズ(人気)</th></tr>
<tr><td>1</td><td>1</td><td>イントゥーザブルー 5.6 (4番人気) 牡2 / 栗 470kg(初出走) 丹内祐次 (55.0) 清水英克 (美浦)</td></tr>
<tr><td>4</td><td>5</td><td>ティアラード 3.3 (2番人気) 牝2 / 黒鹿 460kg(初出走) 横山武史 (55.0) 小栗実 (栗東)</td></tr>
<tr><td>5</td><td>7</td><td>ブルージェイ 2.5 (1番人気) 牡2 / 黒鹿 460kg(初出走) 鮫島克駿 (55.0) 加藤征弘 (美浦)</td></tr>
</table></body></html>`;
const entry = parseEntryPage(entryHtml, entryUrl);
assert.equal(entry.race.raceId, "2026-08-01-sapporo-05");
assert.equal(entry.race.startTimeUtc, "2026-08-01T03:20:00.000Z");
assert.equal(entry.runners.length, 3);
assert.equal(entry.runners[2]?.horseName, "ブルージェイ");
assert.equal(entry.runners[2]?.winOdds, 2.5);

const resultHtml = `<!doctype html><html><body>
<h1>レース結果</h1><h2>2026年8月1日(土曜) 1回札幌3日</h2><h3>5R メイクデビュー札幌</h3>
<p>2歳 新馬 (混合)[指定] 馬齢</p><p>コース 1500m 芝・右 発走12:20</p><p>天候:曇 芝:稍重</p>
<table><tr><th>着順</th><th>枠</th><th>馬番</th><th>馬名</th></tr>
<tr><td>1</td><td>5</td><td>7</td><td>ブルージェイ 1番人気 牡2 / 460kg(初出走) 鮫島克駿 (55.0) 加藤征弘 (美浦) 1:30.4 / 35.4</td></tr>
<tr><td>2</td><td>4</td><td>5</td><td>ティアラード 2番人気 牝2 / 460kg(初出走) 横山武史 (55.0) 小栗実 (栗東) 1:30.9 (２ 1/2) / 35.7</td></tr>
<tr><td>3</td><td>3</td><td>3</td><td>ギャルズマインド 3番人気 牝2 / 436kg(初出走) 浜中俊 (55.0) 武幸四郎 (栗東) 1:31.0 (１) / 35.8</td></tr>
</table>
<h2>払戻金</h2><table>
<tr><td>単勝</td><td>7</td><td>250円</td><td>1番人気</td></tr>
<tr><td>馬連</td><td>5-7</td><td>430円</td><td>1番人気</td></tr>
<tr><td>3連複</td><td>3-5-7</td><td>550円</td><td>1番人気</td></tr>
</table><p>返還馬番 4番</p></body></html>`;
const result = parseResultPage(resultHtml, resultUrl);
assert.equal(result.results.length, 3);
assert.equal(result.results[0]?.horseNo, 7);
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
const prediction = generatePrediction(race, runners, stats, "v1.0.0", 100, 2000);
assert.equal(prediction.runners.length, 3);
assert.equal(prediction.runners[0]?.horseNo, 7);
assert.ok(Math.abs(prediction.runners.reduce((sum, runner) => sum + runner.winProbability, 0) - 1) < 0.000001);
assert.ok(prediction.bets.reduce((sum, bet) => sum + bet.stakeYen, 0) <= 2000);
console.log("race-tantei v1 tests passed");
