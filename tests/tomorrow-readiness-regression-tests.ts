import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseRaceName } from "../src/v1/jra.js";

const chromeBeforeRace = `
<html><body>
<h2>緊急情報</h2>
<h2>関連メニュー</h2>
<div>2026年9月12日（土曜） 4回中山3日 発走時刻：15時30分</div>
<div>11レース</div>
<h2>ラジオ日本賞</h2>
<div>3歳以上 オープン （国際）（特指） 別定 コース：1,200メートル（ダート・右）</div>
</body></html>`;
assert.equal(parseRaceName(chromeBeforeRace, 11), "ラジオ日本賞");

const gradeRace = `
<html><body>
<h2>開催お知らせ</h2>
<div>2026年9月12日（土曜） 4回阪神3日 発走時刻：15時45分</div>
<div>11レース</div>
<h2>第77回チャレンジカップ</h2>
<div>3歳以上 オープン （国際）（特指） ハンデ コース：2,000メートル（芝・右）</div>
</body></html>`;
assert.equal(parseRaceName(gradeRace, 11), "第77回チャレンジカップ");

const genericRace = `
<html><body>
<h2>検索ウィンドウ</h2>
<div>2026年9月12日（土曜） 4回中山3日 発走時刻：10時50分</div>
<div>3レース</div>
<h2>3歳未勝利</h2>
<div>3歳 未勝利 [指定] 馬齢 コース：1,200メートル（ダート・右）</div>
</body></html>`;
assert.equal(parseRaceName(genericRace, 3), "3歳未勝利");

const workerSource = readFileSync("src/v1/completed-worker-live-lock.ts", "utf8");
assert.equal(workerSource.includes("ids.length !== 15"), false, "live worker must not hard-code 15 races");
assert.equal(workerSource.includes("counts.size !== 3"), false, "live worker must not hard-code three venues");
assert.equal(workerSource.includes("expectedVenues.size * 5"), true, "live worker must require five races per active venue");
assert.equal(workerSource.includes("Number(count) !== 12"), true, "live worker must validate the authoritative 12-race venue program");

console.log("tomorrow-readiness-regression-tests: ok");
