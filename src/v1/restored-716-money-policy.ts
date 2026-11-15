/** Source-faithful port of the frozen 716.827267% CASH allocator.
 * Research ONLY: the ORIGINAL underlying horse/ticket generator trained across
 * the entire 2016–2026 historical period, so the retrospective performance is
 * NOT proof of real, out-of-fold or forward returns.
 * Recipe from research commit dcb1c55900dcc95d0ada22af7dbbd772d9b86fc2:
 * market × original odds bin × race number, cap 30000, prior 40,
 * cash exponent 4, top 3/5 by (a+b), 100-yen stakes.
 */
import priorJson from "./frozen-716-cash-prior-2026.json" with {type:"json"};
import type {Race,Bet,Ticket} from "./three-model-money-comparison.js";
const prior=priorJson as {
  schema:string; targetYear:number; latestTrainingYear:number; sourceCommit:string;
  recipe:{capYen:number;priorTickets:number;stakePower:number;
    racesPerVenueDay:number;raceRankMode:string;stakePerRaceYen:number;regime:string[]};
  markets:Record<string,number[]>;cells:Record<string,number[]>;
  historicalAudit:{races:number;stakeYen:number;paidYen:number;largestRacePaidYen:number};
  historicalResearchRoiPct:number;
};
const BINS=[0,1.5,2.5,4,6,10,16,25,40,65,100,200,400,800,1600,5000,1e18];
const MARKETS=new Set(["単勝","ワイド","馬連","馬単","3連複","3連単"]);
const cashRecipe=prior.recipe;
if(prior.schema!=="source-faithful-716-cash-2026-v1" ||
   prior.sourceCommit!=="dcb1c55900dcc95d0ada22af7dbbd772d9b86fc2" ||
   prior.targetYear!==2026||prior.latestTrainingYear!==2025||
   JSON.stringify(cashRecipe.regime)!=='["market","odds","raceNo"]'||
   cashRecipe.capYen!==30000||cashRecipe.priorTickets!==40||
   cashRecipe.stakePower!==4||cashRecipe.racesPerVenueDay!==3||
   cashRecipe.raceRankMode!=="both"||cashRecipe.stakePerRaceYen!==2000||
   prior.historicalAudit.races!==3132||prior.historicalAudit.paidYen!==44902060){
  throw Error("SOURCE_FAITHFUL_716_CASH_PRIOR_INVALID");
}
export const RESTORED_RESEARCH_ROI_PCT=prior.historicalResearchRoiPct;
export const RESTORED_RESEARCH_SLA=3;
export const RESTORED_RESEARCH_TRAINING_TICKETS=Object.values(prior.markets)
  .reduce((n,row)=>n+Number(row[0]),0);
function bin(odds:number):number{
  if(!Number.isFinite(odds)||odds<=0)throw Error("INVALID_ORIGINAL_OFFICIAL_ODDS");
  let index=0;
  while(index<BINS.length&&odds>=BINS[index]!)index++;
  return index-1;
}
/** Python round() ties to even, required for exact payout-replay parity. */
function pythonRound(x:number):number{
  const lo=Math.floor(x),frac=x-lo;
  if(Math.abs(frac-.5)<1e-12)return lo%2===0?lo:lo+1;
  return Math.round(x);
}
export function restored716Estimate(race:Race,bet:Bet):number{
  if(Number(race.raceDate.slice(0,4))!==prior.targetYear)
    throw Error("YEAR_SPECIFIC_CASH_PRIOR_NOT_TRAINED");
  if(!MARKETS.has(bet.betType)||!Number.isInteger(race.raceNo)||race.raceNo<1||race.raceNo>12)
    throw Error("INVALID_FROZEN_RACE_OR_TICKET");
  const n=prior.markets[bet.betType]?.[0]||0;
  const cash=prior.markets[bet.betType]?.[1]||0;
  const known=n?cash/(1000*n):.8;
  const key=JSON.stringify([bet.betType,bin(Number(bet.assumedOdds)),race.raceNo]);
  const count=prior.cells[key]?.[0]||0;
  const paid=prior.cells[key]?.[1]||0;
  return Math.max(.01,(paid/1000+40*known)/(count+40));
}
export function restored716Tickets(race:Race,pair:Bet[]):{tickets:Ticket[];priority:number}{
  if(pair.length!==2||pair[0]!.betType===pair[1]!.betType)
    throw Error("EXACT_TWO_DIFFERENT_MARKETS_REQUIRED");
  const a=restored716Estimate(race,pair[0]!);
  const b=restored716Estimate(race,pair[1]!);
  const pa=a**4,pb=b**4;
  const stakeA=100*Math.max(1,Math.min(19,pythonRound((pa/(pa+pb))*20)));
  const stakeB=2000-stakeA;
  const tickets=pair.map((t,i)=>({
    betType:t.betType,combination:t.combination,
    assumedOdds:Number(t.assumedOdds),
    stakeYen:i===0?stakeA:stakeB,
    expectedCashIndex:i===0?a:b,settledReturnYen:null
  }));
  return {tickets,priority:a+b};
}
