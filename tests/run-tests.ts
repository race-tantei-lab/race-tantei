import { readFileSync } from "node:fs";
import { strict as assert } from "node:assert";
import { classifyHtml } from "../src/core/classify.js";
import { validateJraUrl } from "../src/core/security.js";
import { probeJraUrl } from "../src/core/probe.js";
import { parseEntryPage, parseResultPage } from "../src/phase1.js";

const fixture = (name: string): string => readFileSync(new URL(`../../tests/fixtures/${name}`, import.meta.url), "utf8");

const result = classifyHtml(fixture("result.html"));
assert.equal(result.pageKind, "race-result");
assert.ok(result.confidence >= 0.8);
assert.equal(result.blockedReason, null);

const entry = classifyHtml(fixture("entry.html"));
assert.equal(entry.pageKind, "race-entry");
assert.ok(entry.confidence >= 0.8);

const blocked = classifyHtml(fixture("blocked.html"));
assert.equal(blocked.pageKind, "blocked");
assert.equal(blocked.confidence, 1);

assert.equal(validateJraUrl("https://www.jra.go.jp/robots.txt").hostname, "www.jra.go.jp");
assert.throws(() => validateJraUrl("http://www.jra.go.jp/"), /HTTPS_REQUIRED/);
assert.throws(() => validateJraUrl("https://example.com/"), /HOST_NOT_ALLOWED/);

const mockFetch = async (): Promise<Response> => new Response(fixture("result.html"), {
  status: 200,
  headers: { "content-type": "text/html; charset=utf-8" }
});
const probed = await probeJraUrl("https://www.jra.go.jp/example", mockFetch);
assert.equal(probed.ok, true);
assert.equal(probed.evidence.pageKind, "race-result");
assert.equal(probed.httpStatus, 200);
assert.equal(probed.bodySha256.length, 64);

let redirectCalls = 0;
const redirectToUntrusted = async (): Promise<Response> => {
  redirectCalls += 1;
  return new Response(null, { status: 302, headers: { location: "https://example.com/steal" } });
};
const redirectResult = await probeJraUrl("https://www.jra.go.jp/example", redirectToUntrusted);
assert.equal(redirectResult.ok, false);
assert.equal(redirectResult.errorCode, "HOST_NOT_ALLOWED");
assert.equal(redirectCalls, 1);

const horseNames = [
  "イントゥーザブルー",
  "ハイランドウインド",
  "ギャルズマインド",
  "インワンズブラッド",
  "ティアラード"
];
const entryRows = horseNames.map((name, index) => {
  const horseNo = index + 1;
  const odds = horseNo === 4 ? "除外" : `${(horseNo + 1).toFixed(1)} (${horseNo}番人気)`;
  return `<tr><td>${horseNo}</td><td>${horseNo}</td><td>${name} ${odds}</td><td>${horseNo % 2 ? "牡2" : "牝2"} / 栗 ${460 + horseNo}kg(初出走)</td><td>丹内祐次 (55.0) 清水英克 (美浦)</td></tr>`;
}).join("");
const phase1EntryHtml = `<h2>2026年8月1日(土曜) 1回札幌3日</h2><h3>5R メイクデビュー札幌</h3><p>2歳 新馬 (混合)[指定] 馬齢</p><p>コース 1500m 芝・右 発走12:20</p><table>${entryRows}</table><p>オッズは最終オッズ</p>`;
const parsedEntry = parseEntryPage(phase1EntryHtml);
assert.equal(parsedEntry.race.raceId, "20260801-sapporo-05");
assert.equal(parsedEntry.race.distanceM, 1500);
assert.equal(parsedEntry.runners.length, 5);
assert.equal(parsedEntry.runners[3]?.runnerStatus, "excluded");

const resultRows = parsedEntry.runners.map((runner, index) => {
  const status = runner.horseNo === 4 ? "除外" : String(index + 1);
  const time = runner.horseNo === 4 ? "タイム" : `1:3${index}.${index} (${index === 0 ? "" : "１"}) / 35.${index}`;
  return `<tr><td>${status}</td><td>${runner.frameNo}</td><td>${runner.horseNo}</td><td>${runner.horseName} ${runner.popularity ?? ""}番人気</td><td>${runner.sexAge} / ${runner.horseWeight}kg</td><td>丹内祐次 (55.0) 清水英克 (美浦)</td><td>${time}</td></tr>`;
}).join("");
const phase1ResultHtml = `<h2>2026年8月1日(土曜) 1回札幌3日</h2><h3>5R メイクデビュー札幌</h3><p>2歳 新馬 (混合)[指定] 馬齢</p><p>コース 1500m 芝・右 発走12:20</p><h4>レース結果</h4><table>${resultRows}</table><h4>払戻金</h4><table><tr><td>単勝</td><td>1</td><td>250円</td><td>1番人気</td></tr><tr><td>複勝</td><td>1</td><td>110円</td><td>1番人気</td></tr><tr><td>馬連</td><td>1-5</td><td>430円</td><td>1番人気</td></tr><tr><td>3連複</td><td>1-3-5</td><td>550円</td><td>1番人気</td></tr></table><h4>勝馬の紹介</h4>`;
const parsedResult = parseResultPage(phase1ResultHtml, parsedEntry.runners);
assert.equal(parsedResult.results.filter((row) => row.finishPosition !== null).length, 4);
assert.equal(parsedResult.results.find((row) => row.horseNo === 4)?.resultStatus, "除外");
assert.equal(parsedResult.payouts.length, 4);
assert.equal(parsedResult.payouts.find((row) => row.betType === "馬連")?.payoutYen, 430);

console.log("Phase 0 and Phase 1 core tests passed.");
