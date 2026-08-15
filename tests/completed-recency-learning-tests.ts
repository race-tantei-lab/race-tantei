import {
  buildCompletedBetRecency,
  buildCompletedRunnerRecency,
  completedRecencyBetFactor,
  completedRecencyWeight,
} from "../src/v1/completed-recency-learning";

function expect(condition: unknown, message: string): void {
  if (!condition) throw new Error(message);
}

const cutoff = "2026-08-15T11:00:00Z";
const same = completedRecencyWeight("2026-08-15T08:00:00Z", "2026-08-15", cutoff, "2026-08-15");
const previous = completedRecencyWeight("2026-08-14T08:00:00Z", "2026-08-14", cutoff, "2026-08-15");
const week = completedRecencyWeight("2026-08-09T08:00:00Z", "2026-08-09", cutoff, "2026-08-15");
const old = completedRecencyWeight("2026-07-18T08:00:00Z", "2026-07-18", cutoff, "2026-08-15");
expect(same > previous && previous > week && week > old, `recency order invalid: ${same},${previous},${week},${old}`);
expect(completedRecencyWeight("2026-08-15T12:00:00Z", "2026-08-15", cutoff, "2026-08-15") === 0, "future result must have zero weight");

const race = { raceId:"target", raceDate:"2026-08-15", venue:"新潟", surface:"芝" } as any;
const runners = [
  { horseNo:1, horseName:"NEW1", jockey:"JGOOD", trainer:"TN" },
  { horseNo:2, horseName:"NEW2", jockey:"JBAD", trainer:"TN" },
  { horseNo:3, horseName:"NEW3", jockey:"JX", trainer:"TN" },
] as any[];
const history = [
  { raceId:"r1",raceDate:"2026-08-15",startTimeUtc:"2026-08-15T08:00:00Z",venue:"新潟",surface:"芝",horseNo:1,horseName:"H1",jockey:"JGOOD",trainer:"T1",finishPosition:1,marketProbability:0.1,fieldSize:4 },
  { raceId:"r1",raceDate:"2026-08-15",startTimeUtc:"2026-08-15T08:00:00Z",venue:"新潟",surface:"芝",horseNo:2,horseName:"H2",jockey:"JBAD",trainer:"T2",finishPosition:2,marketProbability:0.5,fieldSize:4 },
  { raceId:"r1",raceDate:"2026-08-15",startTimeUtc:"2026-08-15T08:00:00Z",venue:"新潟",surface:"芝",horseNo:3,horseName:"H3",jockey:"JX",trainer:"T3",finishPosition:3,marketProbability:0.2,fieldSize:4 },
  { raceId:"r1",raceDate:"2026-08-15",startTimeUtc:"2026-08-15T08:00:00Z",venue:"新潟",surface:"芝",horseNo:4,horseName:"H4",jockey:"JY",trainer:"T4",finishPosition:4,marketProbability:0.2,fieldSize:4 },
] as any[];
const learned = buildCompletedRunnerRecency(history,race,runners as any,cutoff);
expect(learned.factors[0] > learned.factors[1], `same-day winning jockey should outrank losing favorite jockey: ${learned.factors}`);
expect(learned.audit.sameDayFinishedRaces === 1, "same-day race was not counted");

const betRows = [
  {raceId:"r1",raceDate:"2026-08-15",startTimeUtc:"2026-08-15T08:00:00Z",venue:"新潟",betType:"単勝",stakeYen:1000,returnYen:5000,assumedOdds:5},
  {raceId:"r1",raceDate:"2026-08-15",startTimeUtc:"2026-08-15T08:00:00Z",venue:"新潟",betType:"ワイド",stakeYen:1000,returnYen:0,assumedOdds:5},
] as any[];
const bet = buildCompletedBetRecency(betRows,race,cutoff);
const winFactor = completedRecencyBetFactor({betBuckets:bet.buckets} as any,"単勝","新潟",5);
const wideFactor = completedRecencyBetFactor({betBuckets:bet.buckets} as any,"ワイド","新潟",5);
expect(winFactor > wideFactor, `settled same-day return must influence bet-type factor: ${winFactor} <= ${wideFactor}`);

console.log(JSON.stringify({status:"COMPLETED_RECENCY_LEARNING_TEST_OK",weights:{same,previous,week,old},runnerFactors:learned.factors,betFactors:{winFactor,wideFactor}}));
