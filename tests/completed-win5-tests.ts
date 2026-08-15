import { strict as assert } from "node:assert";
import { optimizeWin5Profile, parseWin5TargetsFromHtml, win5LockDeadlineMs, type Win5RacePrediction } from "../src/v1/completed-win5.js";

const html = `<!doctype html><html><body>
<section><h2>8月16日（日曜）</h2><table>
<tr><td>中京 6R</td><td>15時00分 発走</td></tr>
<tr><td>札幌 10R</td><td>15時10分 発走</td></tr>
<tr><td>新潟 7R</td><td>15時25分 発走</td></tr>
<tr><td>中京 7R</td><td>15時35分 発走</td></tr>
<tr><td>札幌 11R</td><td>15時45分 発走</td></tr>
</table></section>
<section><h2>8月23日（日曜）</h2><table><tr><td>札幌 9R</td><td>14時15分 発走</td></tr></table></section>
</body></html>`;

const targets = parseWin5TargetsFromHtml(html, "2026-08-16");
assert.equal(targets.length, 5);
assert.deepEqual(targets.map((row) => [row.leg, row.venue, row.raceNo, row.startTimeJst]), [
  [1, "中京", 6, "15:00"], [2, "札幌", 10, "15:10"], [3, "新潟", 7, "15:25"], [4, "中京", 7, "15:35"], [5, "札幌", 11, "15:45"],
]);
assert.equal(targets[0].startTimeUtc, "2026-08-16T06:00:00.000Z");
assert.equal(new Date(win5LockDeadlineMs(targets)).toISOString(), "2026-08-16T05:45:00.000Z");
assert.equal(parseWin5TargetsFromHtml(html, "2026-08-17").length, 0);

const audit = {
  status: "applied" as const,
  version: "canonical-recency-v1",
  cutoffUtc: "2026-08-16T05:40:00.000Z",
  historyDays: 30,
  halfLifeDays: 7,
  dateMultipliers: { sameDay: 6, previousDay: 4, days2To7: 2, days8To30: 1 },
  futureResultsAllowed: false as const,
  sameDayFinishedResultsAllowed: true as const,
  runnerHistoryRaces: 20,
  sameDayFinishedRaces: 4,
  previousDayFinishedRaces: 12,
  last7DaysFinishedRaces: 60,
  betHistoryRaces: 10,
  sameDaySettledBetRaces: 3,
  previousDaySettledBetRaces: 8,
  last7DaysSettledBetRaces: 30,
  runnerFactorRange: [0.5, 2] as [number, number],
  betFactorRange: [0.7, 1.35] as [number, number],
};

function race(leg: 1 | 2 | 3 | 4 | 5, probabilities: number[]): Win5RacePrediction {
  return {
    leg,
    raceId: `2026-08-16-test-${leg}`,
    raceDate: "2026-08-16",
    venue: leg % 2 ? "中京" : "新潟",
    raceNo: leg + 5,
    raceName: `test-${leg}`,
    startTimeJst: `15:${String(leg * 5).padStart(2, "0")}`,
    startTimeUtc: `2026-08-16T06:${String(leg * 5).padStart(2, "0")}:00.000Z`,
    bodyWeightApplied: true,
    bodyWeightError: null,
    onlineLearning: audit,
    runners: probabilities.map((probability, index) => ({ horseNo: index + 1, horseName: `horse-${leg}-${index + 1}`, probability, winOdds: 2 + index })),
  };
}

const races = [
  race(1, [0.55, 0.25, 0.12, 0.05, 0.03]),
  race(2, [0.42, 0.28, 0.16, 0.09, 0.05]),
  race(3, [0.60, 0.18, 0.10, 0.07, 0.05]),
  race(4, [0.38, 0.30, 0.17, 0.10, 0.05]),
  race(5, [0.50, 0.24, 0.14, 0.08, 0.04]),
];

const steady = optimizeWin5Profile(races, "堅実", 200);
const standard = optimizeWin5Profile(races, "標準", 100);
const shot = optimizeWin5Profile(races, "一撃", 50);
for (const profile of [steady, standard, shot]) {
  assert.equal(profile.purchaseYen, profile.points * 100);
  assert.ok(profile.points <= profile.maxPoints);
  assert.equal(profile.legs.length, 5);
  const recomputed = profile.legs.reduce((product, leg) => product * leg.selected.length, 1);
  assert.equal(profile.points, recomputed);
  assert.ok(profile.estimatedFiveLegHitProbability > 0 && profile.estimatedFiveLegHitProbability <= 1);
}
assert.ok(steady.estimatedFiveLegHitProbability >= standard.estimatedFiveLegHitProbability);
assert.ok(standard.estimatedFiveLegHitProbability >= shot.estimatedFiveLegHitProbability);
assert.ok(steady.points <= 200 && standard.points <= 100 && shot.points <= 50);

console.log("completed WIN5 tests passed");
