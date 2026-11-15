#!/usr/bin/env node
/** Whole-history aggregation ONLY after archived 2017–2026 independent
 * FINAL-ODDS market + tickets and official payouts have been computed.
 * No partial estimate misrepresented as full history ROI.
 */
import {readdir,readFile,writeFile,mkdir} from "node:fs/promises";
import {join} from "node:path";
const dir="artifacts/combined";
const all=[];
for(const name of (await readdir(dir,{recursive:true})).filter(n=>n.startsWith("independent-year-roi-")&&n.endsWith(".json"))){
 const j=JSON.parse(await readFile(join(dir,name),"utf8"));all.push(j);
}
const expected=Array.from({length:10},(_,i)=>String(2017+i));
const byYear=new Map(all.map(x=>[x.year,x]));
const report={kind:"2017-2026-source-faithful-independent-cash6-cash96-final-odds-replay",
 oddsType:"JRA historical FINAL odds, not T-15", modelChanged:false,
 archivedHistoryEnd:"2026-08-09",expectedYears:expected,
 collectedYears:[...byYear.keys()].sort(),models:{},yearly:{},complete:false,
 caveat:"Historical compact horse archive lacks weather / track / direction; these are treated as UNKNOWN, so reproduction is approximate, not certified as exact pre-T15 probability features."};
for(const mode of ["cash6","cash96"]){
 let stakes=0,returned=0,hits=0,count=0,selected=0;
 const allTickets=[],allRaces=[];let missingYears=0,missingRaces=0;
 const annual={};
 for(const year of expected){
  const y=byYear.get(year);
  const v=y?.modeResults?.[mode];
  if(!v){missingYears++;annual[year]={roiPct:null,coveragePct:0};continue;}
  annual[year]={roiPct:v.roiPct,hitRacePct:v.hitRacePct,roiAfterLargestTicketPct:v.roiAfterLargestTicketPct,
    stakeYen:v.totalStakeYen,returnYen:v.totalPaidYen,selectedRaces:v.selectedRaces,settled:v.fullySettledRaces,coveragePct:v.coveragePct};
  stakes+=v.totalStakeYen;returned+=v.totalPaidYen;
  selected+=v.selectedRaces;count+=v.fullySettledRaces;missingRaces+=v.skipped;
  for(const r of v.bets){
    hits+=Number(r.hit);allRaces.push(r.paid);
    allTickets.push(...r.paidTickets);
  }
 }
 const maxTicket=Math.max(0,...allTickets),maxRace=Math.max(0,...allRaces);
 report.models[mode]={years:annual,yearsMissing:missingYears,selected,settled:count,missingRaces,
    coveragePct:selected?+(100*count/selected).toFixed(4):null,
    stakeYen:stakes,returnYen:returned,profitYen:returned-stakes,
    roiPct:stakes?+(100*returned/stakes).toFixed(4):null,
    roiWithoutLargestTicketPct:stakes?+(100*(returned-maxTicket)/stakes).toFixed(4):null,
    roiWithoutLargestRacePct:stakes?+(100*(returned-maxRace)/stakes).toFixed(4):null,
    hitRatePct:count?+(100*hits/count).toFixed(4):null,
    fullyVerified:!missingYears&&!missingRaces&&selected===count};
}
report.complete=Object.values(report.models).every(x=>x.fullyVerified);
await mkdir("artifacts",{recursive:true});
await writeFile("artifacts/independent-2017-2026-full-roi.json",JSON.stringify(report,null,2));
console.log("INDEPENDENT_FULL_HISTORY_ROI_SUMMARY",JSON.stringify({complete:report.complete,models:Object.fromEntries(Object.entries(report.models).map(([m,v])=>[m,{yearsMissing:v.yearsMissing,selected:v.selected,settled:v.settled,coverage:v.coveragePct,roi:v.roiPct,largestTicketExcluded:v.roiWithoutLargestTicketPct,largestRaceExcluded:v.roiWithoutLargestRacePct,hit:v.hitRatePct,annual:v.years}]))}));
if(!report.complete)console.log("PARTIAL_REPLAY_NOT_FULL_HISTORY: annual ROI is only for settled rows. Do NOT quote overall ROI as complete 2017–2026 results.");
