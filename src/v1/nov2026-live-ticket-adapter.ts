/**
 * User-requested November 2026 payout-focused production challenger adapter.
 * Exact frozen 2024+2025 two-head research weights + actual JRA official quotes.
 * Historical 2026 Jan-Aug metrics ARE NOT a claim of November prospective ROI.
 *
 * Never write D1 here, never change a locked/settled ticket, and keep one total
 * stake per configured course. If genuine six-market odds are unavailable,
 * refuse and let the already-computed ten-year model provide safe fallback.
 */
import modelJson from "./nov2026-payout-hurdle-model.json" with {type:"json"};
import {
  inferNov2026PayoutHurdleResearch, type PayoutHurdleAsset
} from "./nov2026-payout-hurdle-runtime.js";
import {
  COMPLETED_COURSE_STAKES,
  type CompletedTicket, type CompletedCourseBet, type CompletedBetType,
  type OfficialOddsRow
} from "./completed-ticket-runtime.js";

export const NOV2026_TICKET_MODEL_VERSION="nov2026-payout-hurdle-experimental-live-v1" as const;
const MODEL=modelJson as unknown as PayoutHurdleAsset;
type Selection={tickets:CompletedTicket[];courseBets:CompletedCourseBet[];
  ticketSelectionModel:typeof NOV2026_TICKET_MODEL_VERSION;
  historicalValidationOnly:true;};

export function chooseNov2026PayoutHurdleLiveTickets(
  horseNos:readonly number[],featureVectors:readonly (readonly number[])[],
  raceNo:number,oddsRows:readonly OfficialOddsRow[],
  oddsFetchedAt:string,startTimeUtc:string
):Selection|null{
  const fetched=Date.parse(oddsFetchedAt);
  const start=Date.parse(startTimeUtc);
  if(!Number.isFinite(fetched)||!Number.isFinite(start)||
    fetched>start-15*60*1000||!oddsFetchedAt.endsWith("Z"))return null;
  if(MODEL.name!=="nov2026-frozen-pooled-twohead-research"
    ||MODEL.trainThrough!=="2025-12-28"||
    MODEL.notProductionValidated!==true)return null;
  const chosen=inferNov2026PayoutHurdleResearch(
    MODEL,horseNos,featureVectors,raceNo,oddsRows
  );
  if(!chosen||chosen.tickets.length!==2
    ||chosen.tickets[0].betType===chosen.tickets[1].betType||
    chosen.tickets.reduce((sum,t)=>sum+t.stakeYen,0)!==2000||
    chosen.tickets.some(t=>t.stakeYen<100||t.stakeYen%100!==0||
      !Number.isFinite(t.learnedHitProbability)||t.learnedHitProbability<=0||
      t.learnedHitProbability>1||!Number.isFinite(t.expectedReturnPerYen)||
      t.expectedReturnPerYen<=0))return null;
  const valid=new Map<string,number>();
  for(const quote of oddsRows){
    const k=quote.betType+"|"+quote.combination;
    if(valid.has(k))return null;
    const low=Number(quote.oddsMin),high=Number(quote.oddsMax);
    if(Number.isFinite(low)&&Number.isFinite(high)&&low>=1&&low<=high)
      valid.set(k,low);
  }
  const tickets=chosen.tickets.map((t):CompletedTicket=>{
    const official=valid.get(t.betType+"|"+t.combination);
    if(official===undefined||official!==t.officialOdds)
      throw new Error("NOV2026_UNVERIFIED_JRA_QUOTE");
    return {
      betType:t.betType,combination:t.combination,
      horses:t.combination.split("-").map(Number),
      predictedProbability:t.learnedHitProbability,
      officialOdds:official,
      valueProduct:t.learnedHitProbability*official,
      score:Math.log(t.expectedReturnPerYen),
    };
  });
  const courseBets:CompletedCourseBet[]=[];
  const splits={
    "ライト":[1900,100],
    "スタンダード":[4700,300],
    "プレミアム":[9500,500],
  } as const;
  for(const course of ["ライト","スタンダード","プレミアム"] as const){
    const winner=chosen.tickets[0].stakeYen===1900?0:1;
    const other=1-winner;
    const amounts=[0,0];
    amounts[winner]=splits[course][0];
    amounts[other]=splits[course][1];
    if(amounts.reduce((a,b)=>a+b,0)!==
      COMPLETED_COURSE_STAKES[course][0]+COMPLETED_COURSE_STAKES[course][1])
      throw new Error("NOV2026_COURSE_BUDGET_MISMATCH");
    for(let i=0;i<2;i++){
      const ticket=tickets[i];
      if(!ticket)throw new Error("NOV2026_TICKET_MISSING");
      courseBets.push({course,betType:ticket.betType as CompletedBetType,
        combination:ticket.combination,assumedOdds:ticket.officialOdds,
        stakeYen:amounts[i]});
    }
  }
  return {tickets,courseBets,ticketSelectionModel:NOV2026_TICKET_MODEL_VERSION,
    historicalValidationOnly:true};
}
