import {fitPreviousCash,scoreCash,type Race,type PastBet} from "./three-model-money-comparison.js";
import {completedCombinationProbability,COMPLETED_BET_ORDER,type CompletedBetType,type CompletedTicket,type OfficialOddsRow,type CompletedCourseBet} from "./completed-ticket-runtime.js";

export type IndependentMode="cash6"|"cash96";
export type IndependentRace=Race&{entryUrl?:string|null;status?:string|null};
export type IndependentSelection={
 date:string;mode:IndependentMode;createdAt:string;sourceModel:string;trainingThrough:string;
 selected:Array<{raceId:string;venue:string;raceNo:number;raceScore:number}>;
};
export type IndependentFinal={
 date:string;mode:IndependentMode;raceId:string;lockedAt:string;oddsFetchedAt:string;
 startTimeUtc:string;sourceModel:string;oddsSource:string;
 tickets:CompletedTicket[];courseBets:CompletedCourseBet[];
};
export const INDEPENDENT_SOURCE_VERSION="rolling-independent-cash-v1";
export const MODE_CONFIG={
 cash6:{horizon:6,objective:"hit_cash" as const,targetRaces:5},
 cash96:{horizon:96,objective:"cash80" as const,targetRaces:3}
};
const PROXIES:Array<{betType:CompletedBetType;assumedOdds:number}>=[
 {betType:"単勝",assumedOdds:4},{betType:"ワイド",assumedOdds:6},
 {betType:"馬連",assumedOdds:14},{betType:"馬単",assumedOdds:24},
 {betType:"3連複",assumedOdds:40},{betType:"3連単",assumedOdds:90}
];
export function fitIndependent(date:string,mode:IndependentMode,history:PastBet[]){
 const cfg=MODE_CONFIG[mode];
 return fitPreviousCash(date.slice(0,7),cfg.horizon,cfg.objective,history);
}
type CashFit=ReturnType<typeof fitIndependent>;
export function independentlyRankRaces(
 date:string,mode:IndependentMode,races:IndependentRace[],fit:CashFit
):IndependentSelection["selected"]{
 const byVenue=new Map<string,Array<{raceId:string;venue:string;raceNo:number;raceScore:number}>>();
 for(const r of races){
   if(r.raceDate!==date||!r.raceId||!r.startTimeUtc)continue;
   const preds=PROXIES.map(proxy=>{
     const p=scoreCash(r,proxy,fit);
     // No race-day result, current-model selection or settled current-month ticket.
     return mode==="cash6" ? .55*p.cash+.45*p.hit*Math.max(1,fit.cashPrior/Math.max(.1,fit.hitPrior))
       :p.cash;
   }).sort((a,b)=>b-a);
   const score=(preds[0]||0)*.6+(preds[1]||0)*.4;
   const rows=byVenue.get(r.venue)||[];
   rows.push({raceId:r.raceId,venue:r.venue,raceNo:r.raceNo,raceScore:score});
   byVenue.set(r.venue,rows);
 }
 if(!byVenue.size)throw Error("INDEPENDENT_PROGRAM_MISSING");
 const result:IndependentSelection["selected"]=[];
 for(const [venue,rows] of byVenue){
   if(rows.length!==12)throw Error("INDEPENDENT_PROGRAM_NOT_12:"+venue+":"+rows.length);
   rows.sort((a,b)=>b.raceScore-a.raceScore||a.raceNo-b.raceNo);
   result.push(...rows.slice(0,MODE_CONFIG[mode].targetRaces));
 }
 return result.sort((a,b)=>a.venue.localeCompare(b.venue,"ja")||a.raceNo-b.raceNo);
}
export function canFreezeIndependent(startUtc:string,oddsFetchedAt:string,lockedAt:string):boolean{
 const start=Date.parse(startUtc),fetched=Date.parse(oddsFetchedAt),locked=Date.parse(lockedAt);
 return [start,fetched,locked].every(Number.isFinite)&&
   fetched<=locked&&locked<=start-15*60*1000&&fetched<=start-15*60*1000;
}
function comboPositions(type:CompletedBetType,combo:string,horseNos:readonly number[]):number[]|null{
 const values=combo.split("-").map(Number);
 const size=type==="単勝"?1:(type==="ワイド"||type==="馬連"||type==="馬単")?2:3;
 if(values.length!==size||new Set(values).size!==size)return null;
 const positions=values.map(n=>horseNos.indexOf(n));
 if(positions.some(n=>n<0))return null;
 if(type==="ワイド"||type==="馬連"||type==="3連複"){
   if(values.some((v,i)=>i>0&&v<values[i-1]))return null;
 }
 return positions;
}
export function chooseIndependentTickets(
 race:Race,mode:IndependentMode,fit:CashFit,
 horseNos:readonly number[],weights:readonly number[],quotes:readonly OfficialOddsRow[]
):CompletedTicket[]{
 if(horseNos.length!==weights.length||horseNos.length<3||new Set(horseNos).size!==horseNos.length)throw Error("BAD_INDEPENDENT_RUNNERS");
 const total=weights.reduce((a,b)=>a+b,0);
 if(!Number.isFinite(total)||Math.abs(total-1)>1e-7||weights.some(w=>!Number.isFinite(w)||w<=0))throw Error("BAD_INDEPENDENT_HORSE_PROBABILITIES");
 const byType=new Map<CompletedBetType,CompletedTicket>();
 const contextForecastCache=new Map<string,ReturnType<typeof scoreCash>>();
 for(const q of quotes){
   if(!COMPLETED_BET_ORDER.includes(q.betType))continue;
   const odds=Number(q.oddsMin);
   if(!Number.isFinite(odds)||odds<1||!Number.isFinite(q.oddsMax)||q.oddsMax<odds)continue;
   const pos=comboPositions(q.betType,q.combination,horseNos);
   if(!pos)continue;
   const p=completedCombinationProbability(q.betType,pos,weights);
   if(!Number.isFinite(p)||p<=0)continue;
   const priceBand=odds<2?0:odds<3?1:odds<5?2:odds<8?3:odds<12?4:odds<20?5:odds<35?6:odds<60?7:odds<100?8:odds<200?9:odds<400?10:11;
   const key=q.betType+":"+priceBand;
   let forecast=contextForecastCache.get(key);
   if(!forecast){forecast=scoreCash(race,{betType:q.betType,assumedOdds:odds},fit);contextForecastCache.set(key,forecast);}
   const cashRatio=Math.max(.15,Math.min(4,forecast.cash/Math.max(.1,fit.cashPrior)));
   const hitRatio=Math.max(.15,Math.min(4,forecast.hit/Math.max(.02,fit.hitPrior)));
   const factor=mode==="cash6"?.70*cashRatio+.30*hitRatio:cashRatio;
   const expected=p*odds*factor;
   if(!Number.isFinite(expected)||expected<=0)continue;
   const ticket:CompletedTicket={
     betType:q.betType,combination:q.combination,horses:pos.map(i=>horseNos[i]),
     predictedProbability:p,officialOdds:odds,valueProduct:expected,score:expected
   };
   const old=byType.get(q.betType);
   if(!old||ticket.score>old.score||
      (ticket.score===old.score&&ticket.combination<old.combination))byType.set(q.betType,ticket);
 }
 if(byType.size<2)throw Error("INDEPENDENT_OFFICIAL_MARKETS_INCOMPLETE");
 const best=[...byType.values()].sort((a,b)=>b.score-a.score||
   COMPLETED_BET_ORDER.indexOf(a.betType)-COMPLETED_BET_ORDER.indexOf(b.betType)||
   a.combination.localeCompare(b.combination));
 return best.slice(0,2);
}
export function independentCourseBets(tickets:readonly CompletedTicket[]):CompletedCourseBet[]{
 if(tickets.length!==2||tickets[0].betType===tickets[1].betType)throw Error("INDEPENDENT_NEEDS_TWO_TYPES");
 const budgets:[string,number][]=[["ライト",2000],["スタンダード",5000],["プレミアム",10000]];
 return budgets.flatMap(([course,budget])=>tickets.map((t,i)=>({
   course:course as CompletedCourseBet["course"],betType:t.betType,
   combination:t.combination,stakeYen:(i===0?9:1)*budget/10,assumedOdds:t.officialOdds
 })));
}
export function settleIndependent(
 final:IndependentFinal,payouts:readonly {betType:string;combination:string;payoutYen:number}[],
 settled:boolean,course="ライト"
):{stake:number;paid:number;hit:boolean}|null{
 if(!settled)return null;
 const rows=final.courseBets.filter(b=>b.course===course);
 if(rows.length!==2)return null;
 const stake=rows.reduce((a,b)=>a+b.stakeYen,0);
 const paid=rows.reduce((sum,b)=>{
   const q=payouts.find(p=>p.betType===b.betType&&p.combination===b.combination);
   return sum+(q?Math.round(q.payoutYen*b.stakeYen/100):0);
 },0);
 return {stake,paid,hit:paid>0};
}
