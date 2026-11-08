/** Official-JRA pre-T15 ROI-first research shadow.
 * 20% is a minimum MODELED per-race two-ticket union hit probability.
 * The predicted EV is NOT historical profit, not validated ROI, not a user bet.
 * No database/network operations; canonical production tickets never changed.
 */
import { COMPLETED_BET_ORDER, completedCombinationProbability, type CompletedBetType, type OfficialOddsRow } from "./completed-ticket-runtime.js";

export type RoiFirstShadowTicket = {
  betType: CompletedBetType;
  combination: string;
  modelProbability: number;
  conservativeOfficialOdds: number;
  expectedReturnPerYen: number;
  stakeYen: number;
};
export type RoiFirstPreT15Shadow = {
  policy: "roi_first_jra_official_model_ev_v1";
  researchOnly: true;
  notActualJraRoi: true;
  minimumModeledHitPct: 20;
  modeledTwoTicketHitPct: number;
  modeledExpectedRoiPct: number;
  stakeYen: 2000;
  oddsFetchedAt: string;
  startTimeUtc: string;
  tickets: [RoiFirstShadowTicket, RoiFirstShadowTicket];
};
type Candidate = Omit<RoiFirstShadowTicket, "stakeYen"> & { horses: number[] };
const TYPES = new Set<CompletedBetType>(COMPLETED_BET_ORDER);
const UNORDERED = new Set<CompletedBetType>(["ワイド", "馬連", "3連複"]);
const JRA_T15_MS=15*60*1000;

// Highest-EV ticket per market can fail the union hit floor even when a
// lower-EV alternative permits a better legal two-market portfolio.
type Frontier={ ev?:Candidate; hit?:Candidate; balanced?:Candidate };
function betterBy(candidate:Candidate, existing:Candidate|undefined,
  score:(c:Candidate)=>number):boolean {
  if(!existing)return true;
  const a=score(candidate),b=score(existing);
  return a>b||(a===b&&candidate.combination<existing.combination);
}

function winning(kind:CompletedBetType, selected:readonly number[], top3:readonly number[]):boolean {
  if(kind==="単勝")return selected[0]===top3[0];
  if(kind==="馬単")return selected[0]===top3[0]&&selected[1]===top3[1];
  if(kind==="馬連")return selected.includes(top3[0]!)&&selected.includes(top3[1]!);
  if(kind==="ワイド")return selected.every(x=>top3.includes(x));
  if(kind==="3連単")return selected.every((x,i)=>x===top3[i]);
  if(kind==="3連複")return selected.every(x=>top3.includes(x));
  throw new Error("ROI_SHADOW_UNKNOWN_JRA_BET_TYPE");
}
function expectedCount(kind:CompletedBetType):number {
  return kind==="単勝"?1:kind==="3連複"||kind==="3連単"?3:2;
}
function normalizedKey(kind:CompletedBetType, horses:readonly number[]):string {
  const copy=[...horses];
  if(UNORDERED.has(kind))copy.sort((a,b)=>a-b);
  return copy.join("-");
}
function outcomeProbability(weights:readonly number[],a:number,b:number,c:number):number {
  return weights[a]!*weights[b]!/Math.max(1e-12,1-weights[a]!)
    *weights[c]!/Math.max(1e-12,1-weights[a]!-weights[b]!);
}
export function roiFirstOfficialShadow(
  horseNos:readonly number[], weights:readonly number[], oddsRows:readonly OfficialOddsRow[],
  oddsFetchedAt:string, startTimeUtc:string
):RoiFirstPreT15Shadow|null {
  const fetched=Date.parse(oddsFetchedAt), start=Date.parse(startTimeUtc);
  if(!Number.isFinite(fetched)||!Number.isFinite(start)||!/(?:Z|[+-]\d{2}:\d{2})$/.test(oddsFetchedAt)
    ||!/(?:Z|[+-]\d{2}:\d{2})$/.test(startTimeUtc)||fetched>start-JRA_T15_MS)
    return null; // no fabricated T-15 timestamp or post-deadline lock
  if(horseNos.length<3||horseNos.length>18||horseNos.length!==weights.length
      ||new Set(horseNos).size!==horseNos.length
      ||horseNos.some(x=>!Number.isInteger(x)||x<1||x>18)
      ||weights.some(p=>!Number.isFinite(p)||p<=0)
      ||Math.abs(weights.reduce((a,b)=>a+b,0)-1)>1e-9
      ||oddsRows.length>12000)return null;
  const indexes=new Map(horseNos.map((x,i)=>[x,i]));
  const best=new Map<CompletedBetType,Frontier>();
  const seen=new Set<string>();
  for(const row of oddsRows) {
    if(!TYPES.has(row.betType))continue;
    const horses=row.combination.split("-").map(Number);
    if(horses.length!==expectedCount(row.betType)||new Set(horses).size!==horses.length
        ||horses.some(x=>!indexes.has(x))
        ||normalizedKey(row.betType,horses)!==row.combination)continue;
    const key=row.betType+"|"+row.combination;
    if(seen.has(key))return null; // conflicting odds snapshots rejected
    seen.add(key);
    // For wide ranged payouts the bottom quoted odds is conservative.
    const low=Number(row.oddsMin),high=Number(row.oddsMax);
    if(!Number.isFinite(low)||!Number.isFinite(high)||low<1||high<low)continue;
    const p=completedCombinationProbability(row.betType,horses.map(x=>indexes.get(x)!),weights);
    if(!Number.isFinite(p)||p<=0||p>1)continue;
    const proposed:Candidate={betType:row.betType,combination:row.combination,
      modelProbability:p,conservativeOfficialOdds:low,expectedReturnPerYen:p*low,horses};
    const frontier:Frontier=best.get(row.betType)??{};
    if(betterBy(proposed,frontier.ev,c=>c.expectedReturnPerYen))frontier.ev=proposed;
    if(betterBy(proposed,frontier.hit,c=>c.modelProbability))frontier.hit=proposed;
    if(betterBy(proposed,frontier.balanced,
       c=>c.expectedReturnPerYen*Math.sqrt(c.modelProbability)))frontier.balanced=proposed;
    best.set(row.betType,frontier);
  }
  // Only true 6-market snapshots can qualify; never invent missing official odds.
  if(best.size!==COMPLETED_BET_ORDER.length)return null;
  const chosen=COMPLETED_BET_ORDER.flatMap(t=>{
    const f=best.get(t)!;
    const three=[f.ev!,f.hit!,f.balanced!];
    return three.filter((c,i)=>three.findIndex(x=>x.combination===c.combination)===i);
  });
  const totalOutcomes:number[][]=[];
  const probabilities:number[]=[];
  for(let a=0;a<weights.length;a++)for(let b=0;b<weights.length;b++){
    if(a===b)continue;
    for(let c=0;c<weights.length;c++){
      if(c===a||c===b)continue;
      totalOutcomes.push([horseNos[a]!,horseNos[b]!,horseNos[c]!]);
      probabilities.push(outcomeProbability(weights,a,b,c));
    }
  }
  const total=probabilities.reduce((sum,p)=>sum+p,0);
  if(!Number.isFinite(total)||Math.abs(total-1)>1e-7)return null;
  let output:RoiFirstPreT15Shadow|null=null;
  let bestEv=-Infinity;
  for(let i=0;i<chosen.length;i++)for(let j=i+1;j<chosen.length;j++){
    const a=chosen[i]!,b=chosen[j]!;
    if(a.betType===b.betType)continue;
    let pairHit=0;
    for(let k=0;k<totalOutcomes.length;k++){
      const finish=totalOutcomes[k]!;
      if(winning(a.betType,a.horses,finish)||winning(b.betType,b.horses,finish))
        pairHit+=probabilities[k]!;
    }
    // A floor on the event "at least one of two bets wins", NOT ticket hit.
    if(pairHit*100+1e-9<20)continue;
    // Linear expected-payout optimization under two different mandatory types
    // and 100-yen betting increments: allocate 1900 to higher EV, 100 to other.
    const stakeA=a.expectedReturnPerYen>=b.expectedReturnPerYen?1900:100;
    const stakeB=2000-stakeA;
    const ev=stakeA*a.expectedReturnPerYen+stakeB*b.expectedReturnPerYen;
    if(ev<=bestEv)continue;
    bestEv=ev;
    const toTicket=(t:Candidate,stakeYen:number):RoiFirstShadowTicket=>({
      betType:t.betType,combination:t.combination,modelProbability:t.modelProbability,
      conservativeOfficialOdds:t.conservativeOfficialOdds,expectedReturnPerYen:t.expectedReturnPerYen,stakeYen
    });
    output={policy:"roi_first_jra_official_model_ev_v1",researchOnly:true,
      notActualJraRoi:true,minimumModeledHitPct:20,
      modeledTwoTicketHitPct:Math.round(pairHit*10000)/100,
      modeledExpectedRoiPct:Math.round(ev/2000*10000)/100,
      stakeYen:2000,oddsFetchedAt,startTimeUtc,
      tickets:[toTicket(a,stakeA),toTicket(b,stakeB)]};
  }
  return output;
}
