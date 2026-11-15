/** Entire historical year cash6/cash96 TRUE source ticket and payout replay.
 * Same deployed model fitIndependent, independentlyRankRaces, and
 * chooseIndependentTickets source; original tickets NEVER used as predictions.
 * Official JRA final odds (not pre-T15) + official result payouts.
 */
import {readFile,writeFile} from "node:fs/promises";
import {gunzipSync} from "node:zlib";
import {dirname,join} from "node:path";
import {fileURLToPath} from "node:url";
import {fitIndependent,chooseIndependentTickets,independentCourseBets,settleIndependent,type IndependentMode} from "../src/v1/independent-rolling-core.js";
import history from "../src/v1/ten-year-history-data/index.js";
import type {OfficialOddsRow} from "../src/v1/completed-ticket-runtime.js";
const ROOT=join(dirname(fileURLToPath(import.meta.url)),"..");
const OUT=join(ROOT,"artifacts");
const YEAR=String(process.env.AUDIT_YEAR||"2017");
const LATE=process.env.AUDIT_LATE==="1";
const LIMITED=Number(process.env.AUDIT_LIMIT||"0");
const ARCHIVE=new Map<string,any>(JSON.parse(gunzipSync(Buffer.from(history,"base64")).toString("utf8")).races.map((x:any)=>[x[0],x]));
const modes=["cash6","cash96"] as const;
const selection=JSON.parse(await readFile(join(OUT,LATE?"independent-late-2026-selections.json":"independent-full-period-selections.json"),"utf8"));
const lateDb=LATE?JSON.parse(gunzipSync(await readFile(join(OUT,"independent-late-2026-d1.json.gz"))).toString("utf8")):null;
if(lateDb){for(const b of lateDb.races){const r=b.race;ARCHIVE.set(r.raceId,[r.raceId,r.raceDate,r.venue,r.raceNo,r.raceName,r.startTimeJst,r.surface,r.distanceM,null]);}}
const result=JSON.parse(await readFile(join(OUT,"independent-year-result-"+YEAR+".json"),"utf8"));
const oddsPath=join(OUT,"independent-year-final-odds-"+YEAR+".jsonl.gz");
const weightPath=join(OUT,LATE?"independent-late-2026-horse-weights.jsonl.gz":"independent-full-period-horse-weights.jsonl.gz");
const oddsText=gunzipSync(await readFile(oddsPath)).toString("utf8");
const weightText=gunzipSync(await readFile(weightPath)).toString("utf8");
const odds=new Map<string,any>(),weights=new Map<string,any>(),payouts=new Map<string,any>();
for(const s of oddsText.split("\n"))if(s.trim()){const r=JSON.parse(s);odds.set(r.raceId,r);}
for(const s of weightText.split("\n"))if(s.trim()){const r=JSON.parse(s);if(r.date.slice(0,4)===YEAR)weights.set(r.raceId,r);}
for(const r of result.races)payouts.set(r.raceId,r);
function makeQuotes(record:Record<string,any>):OfficialOddsRow[]{
 const horses=(record.horses||[]).map(Number).sort((a:number,b:number)=>a-b);
 const pairs:number[][]=[],orderedPairs:number[][]=[],triples:number[][]=[],orderedTriples:number[][]=[];
 for(const a of horses)for(const b of horses)if(a<b)pairs.push([a,b]);
 for(const a of horses)for(const b of horses)if(a!==b)orderedPairs.push([a,b]);
 for(const a of horses)for(const b of horses)for(const c of horses)if(a<b&&b<c)triples.push([a,b,c]);
 for(const a of horses)for(const b of horses)for(const c of horses)if(a!==b&&a!==c&&b!==c)orderedTriples.push([a,b,c]);
 const markets:[string,number[][],string][]=[
  ["単勝",horses.map((n:number)=>[n]),"win"],
  ["ワイド",pairs,"wide"],["馬連",pairs,"umaren"],["馬単",orderedPairs,"umatan"],["3連複",triples,"trio"],["3連単",orderedTriples,"trifecta"],
 ];
 const rows:OfficialOddsRow[]=[];
 for(const [type,combos,key] of markets){
  const values=record[key]||[];
  if(values.length!==combos.length)throw Error("OFFICIAL_ODDS_COMBINATION_SHAPE:"+type+":"+record.raceId+":"+values.length+":"+combos.length);
  for(let i=0;i<combos.length;i++){
    const value=values[i],min=Number(Array.isArray(value)?value[0]:value),max=Number(Array.isArray(value)?value[1]:value);
    if(Number.isFinite(min)&&Number.isFinite(max)&&min>=1&&max>=min)
     rows.push({betType:type as OfficialOddsRow["betType"],combination:combos[i].join("-"),oddsMin:min,oddsMax:max});
  }
 }
 return rows;
}
function resultPair(k:string):string{return k.replace(/[→－–—]/g,"-").replace(/\s+/g,"");}
const fits=new Map<string,ReturnType<typeof fitIndependent>>();
const year:any={year:LATE?"2026-08-10..2026-11-15":YEAR,modelNames:[],modeResults:{},analysisDefinition:{
 availableMonths:selection.start+".."+selection.end,
 odds:"official JRA POSTRACE FINAL odds, not pre-T15",
 horseProbabilities:LATE?"frozen shared 500-tree LightGBM, full pre-2026-Aug history plus D1 Nov 2026 historical features":"frozen shared 500-tree LightGBM, per-date chronological features reconstructed from compact 2016-2026 archive",
 missingHorseFeatureMetadata:LATE?"source D1 has pre-known weather track and direction; odds are still retrospective final":"weather/track/direction default unknown when no official historical result metadata; not a certified pre-T15 replication",
 sameDeployedSourceFunctions:true,
 revenue:"actual JRA 100-yen payouts, not official odds treated as refunds",
 originalTicketReweighting:false
},resultUrlStats:{expected:result.expected,payoutRaces:result.payoutRaces},oddsCoverage:odds.size,featureRaces:weights.size};
for(const mode of modes){
 const days=selection.modeResults.filter((x:any)=>x.mode===mode&&x.date.slice(0,4)===YEAR);
 const all=days.flatMap((x:any)=>x.selected.map((r:any)=>({...r,date:x.date})));
 const chosen=LIMITED>0?all.slice(0,LIMITED):all;
 const settled:any[]=[],issues:any[]=[];
 for(const sel of chosen){
  const p=weights.get(sel.raceId),q=odds.get(sel.raceId),r=payouts.get(sel.raceId);
  if(!p||!q||!r){issues.push({raceId:sel.raceId,reason:!p?"NO_HISTORIC_HORSE_FEATURES":!q?"JRA_FINAL_ODDS_MISSING":"JRA_OFFICIAL_PAYOUT_MISSING"});continue;}
  try{
   const inOdds=(q.horses as unknown[]).map(Number).sort((a,b)=>a-b);
   const predictionHorses=p.horseNos.slice().sort((a:number,b:number)=>a-b);
   if(inOdds.join(",")!==predictionHorses.join(","))throw Error("ODDS_HORSE_SET_MISMATCH:"+inOdds.length+":"+predictionHorses.length);
   const quotes=makeQuotes(q);
   if(quotes.length<10)throw Error("TOO_FEW_JRA_FINAL_ODDS");
   const k=mode+":"+sel.date.slice(0,7);
   let fit=fits.get(k);
   if(!fit){fit=fitIndependent(sel.date,mode,LATE?lateDb.pastOriginalSettled:[]);fits.set(k,fit);}
   const fakeRace:any={raceId:sel.raceId,raceDate:sel.date,venue:sel.venue,raceNo:sel.raceNo,raceName:null,surface:null,distanceM:null,startTimeUtc:null,startTimeJst:null};
   // Correct market priors: use actual archived surface, distance, race name
   // rather than winner-dependent result fields.
   const archive=ARCHIVE.get(sel.raceId);
   if(!archive)throw Error("ARCHIVED_RACE_CONTEXT_NOT_FOUND");
   fakeRace.raceName=archive[4];fakeRace.surface=archive[6];fakeRace.distanceM=archive[7];
   fakeRace.startTimeJst=archive[5];
   fakeRace.startTimeUtc=new Date(Date.parse(sel.date+"T"+archive[5]+":00+09:00")).toISOString();
   const tickets=chooseIndependentTickets(fakeRace as any,mode,fit,p.horseNos,p.weights,quotes);
   const bets=independentCourseBets(tickets);
   const payoff=r.payouts.map((x:any)=>({...x,combination:resultPair(String(x.combination)),betType:String(x.betType)}));
   const fake={date:sel.date,mode,raceId:sel.raceId,sourceModel:"rolling-independent-cash-v1",startTimeUtc:fakeRace.startTimeUtc,
     lockedAt:new Date(Date.parse(fakeRace.startTimeUtc)-20*60000).toISOString(),
     oddsFetchedAt:"RETROSPECTIVE_FINAL_ODDS",oddsSource:"JRA_OFFICIAL_FINAL",tickets,courseBets:bets};
   const settlement=settleIndependent(fake as any,payoff,true);
   if(!settlement)throw Error("PAYOUTS_UNAVAILABLE");
   const light=bets.filter(x=>x.course==="ライト");
   const ticketPaid=tickets.map(t=>{
     const stake=light.find(b=>b.betType===t.betType&&b.combination===t.combination)?.stakeYen;
     if(!stake)throw Error("NO_TICKET_STAKE");
     const pay=payoff.find((x:any)=>x.betType===t.betType&&x.combination===t.combination)?.payoutYen||0;
     return Math.round(Number(pay)*stake/100);
   });
   const paid=ticketPaid.reduce((a,b)=>a+b,0);
   if(paid!==settlement.paid)throw Error("RETURNS_NOT_EQUAL_TO_DEPLOYED_SETTLE:"+paid+":"+settlement.paid);
   settled.push({raceId:sel.raceId,date:sel.date,venue:sel.venue,stake:2000,paid,hit:paid>0,paidTickets:ticketPaid,tickets:tickets.map(t=>({type:t.betType,combination:t.combination,odds:t.officialOdds}))});
  }catch(e){issues.push({raceId:sel.raceId,reason:String(e)});}
 }
 const stake=settled.length*2000,pay=settled.reduce((a,r)=>a+r.paid,0);
 const maxTicket=Math.max(0,...settled.flatMap(r=>r.paidTickets)),maxRace=Math.max(0,...settled.map(r=>r.paid));
 year.modeResults[mode]={selectedRaces:chosen.length,fullySettledRaces:settled.length,skipped:issues.length,
   coveragePct:chosen.length?Number((100*settled.length/chosen.length).toFixed(3)):0,
   totalStakeYen:stake,totalPaidYen:pay,totalProfitYen:pay-stake,
   roiPct:stake?Number((100*pay/stake).toFixed(3)):null,
   roiAfterLargestTicketPct:stake?Number((100*(pay-maxTicket)/stake).toFixed(3)):null,
   roiAfterLargestRacePct:stake?Number((100*(pay-maxRace)/stake).toFixed(3)):null,
   hitRacePct:settled.length?Number((100*settled.filter(r=>r.hit).length/settled.length).toFixed(3)):null,
   largestTicketYen:maxTicket,largestRaceYen:maxRace,
   issues:issues.slice(0,500),bets:settled
 };
 console.log("INDEPENDENT_FULL_YEAR_ROI",JSON.stringify({year:YEAR,mode,selected:chosen.length,settled:settled.length,skipped:issues.length,stake,paid:pay,roi:year.modeResults[mode].roiPct,largestExcluded:year.modeResults[mode].roiAfterLargestTicketPct,hit:year.modeResults[mode].hitRacePct,sampleMissing:issues.slice(0,5)}));
}
await writeFile(join(OUT,LATE?"independent-year-roi-late-2026.json":"independent-year-roi-"+YEAR+".json"),JSON.stringify(year));
