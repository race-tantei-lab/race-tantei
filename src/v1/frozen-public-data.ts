import { TEN_YEAR_MONTHLY, TEN_YEAR_PUBLIC_LIGHT_RETURN_YEN, TEN_YEAR_PUBLIC_RACES } from "./ten-year-public-summary.js";
import { SELECTED_2024 } from "./frozen-selected-2024.js";
import { SELECTED_2025 } from "./frozen-selected-2025.js";
import { SELECTED_2026 } from "./frozen-selected-2026.js";

export type FrozenMetric={course:"ライト"|"スタンダード"|"プレミアム";budget:number;settledRaces:number;stakeYen:number;returnYen:number;roiPct:number};
export type FrozenMonthlyMetric={month:string;course:FrozenMetric["course"];settledRaces:number;stakeYen:number;returnYen:number;roiPct:number};

const COURSES=[
  {course:"ライト" as const,budget:2000,scale:1},
  {course:"スタンダード" as const,budget:5000,scale:2.5},
  {course:"プレミアム" as const,budget:10000,scale:5}
];

export const FROZEN_PUBLIC_METRICS:FrozenMetric[]=COURSES.map(({course,budget,scale})=>{
  const stakeYen=TEN_YEAR_PUBLIC_RACES*budget;
  const returnYen=Math.round(TEN_YEAR_PUBLIC_LIGHT_RETURN_YEN*scale);
  return {course,budget,settledRaces:TEN_YEAR_PUBLIC_RACES,stakeYen,returnYen,roiPct:returnYen/stakeYen*100};
});

export const FROZEN_PUBLIC_MONTHLY:FrozenMonthlyMetric[]=TEN_YEAR_MONTHLY.flatMap(row=>COURSES.map(({course,budget,scale})=>{
  const stakeYen=row.races*budget;
  const returnYen=Math.round(row.returnLightYen*scale);
  return {month:row.month,course,settledRaces:row.races,stakeYen,returnYen,roiPct:returnYen/stakeYen*100};
}));

const SELECTED:Record<string,string>={...SELECTED_2024,...SELECTED_2025,...SELECTED_2026};
export function isFrozenSelectedRace(raceDate:string,venue:string,raceNo:number):boolean{
  const selected=SELECTED[`${raceDate}|${venue}`];
  return !!selected&&selected.split(".").includes(String(raceNo));
}
