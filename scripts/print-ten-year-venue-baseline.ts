import { tenYearRaces } from "../src/v1/ten-year-history.js";

const rows = await tenYearRaces();
const byVenue = new Map<string,{races:number;stakeYen:number;returnYen:number}>();
let races=0,stakeYen=0,returnYen=0;
for (const race of rows) {
  if (!race.tickets?.length) continue;
  const ret=race.tickets.reduce((sum,t)=>sum+Number(t.returnLightYen||0),0);
  races+=1; stakeYen+=2000; returnYen+=ret;
  const v=byVenue.get(race.venue) ?? {races:0,stakeYen:0,returnYen:0};
  v.races+=1; v.stakeYen+=2000; v.returnYen+=ret; byVenue.set(race.venue,v);
}
const venues=[...byVenue.entries()].sort((a,b)=>a[0].localeCompare(b[0],"ja")).map(([venue,v])=>({
  venue,...v,roiPct:v.returnYen/v.stakeYen*100
}));
console.log("TEN_YEAR_VENUE_BASELINE",JSON.stringify({
  total:{races,stakeYen,returnYen,roiPct:returnYen/stakeYen*100},
  venues
}));
