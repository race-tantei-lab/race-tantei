/** Literal frozen 2026 out-of-year research model runtime. No production mutation.
 * Port of 2024+2025 pooled LambdaRank/top3/ticket-hurdle joblib.
 * Training cut: 2025-12-28. Independent-year historical evaluation: 2026-08-09.
 * It is NOT a validated 2026-11 profitable model; do not silently promote.
 */
import {
  COMPLETED_BET_ORDER, completedCombinationProbability,
  type CompletedBetType, type OfficialOddsRow
} from "./completed-ticket-runtime.js";

type TreeNode=readonly number[]; // leaf [1,value], branch [0,feature,threshold,left,right,missingLeft]
type HistTrees={baseline:number;trees:TreeNode[][]};
export type PayoutHurdleAsset={
  name:string;trainThrough:string;evalPeriod:string;
  notProductionValidated:boolean;
  horseFeatureCount:number;ticketFeatureCount:number;
  ranker:TreeNode[][];top3:HistTrees;hit:HistTrees;paid:HistTrees;
  priors:Record<string,{hitPrior:number;wonReturnPrior:number}>;
};
export type Nov2026ResearchTicket={
  betType:CompletedBetType;combination:string;
  officialOdds:number;plProbability:number;learnedHitProbability:number;
  expectedReturnPerYen:number;stakeYen:number;
};
export type Nov2026HurdleOutput={
  model:string;researchOnly:true;trainThrough:string;
  evaluatedThrough:string;notValidatedForwardInNovember2026:true;
  modeledHitFloorPct:20;modeledExpectedRoiPct:number;
  oddsSource:"JRA official snapshot";tickets:[Nov2026ResearchTicket,Nov2026ResearchTicket];
};

const UNORDERED=new Set<CompletedBetType>(["ワイド","馬連","3連複"]);
function predictTreeForest(x:readonly number[],trees:readonly TreeNode[][]):number{
  let sum=0;
  for(const tree of trees){
    let n=0;
    for(let steps=0;steps<128;steps++){
      const row=tree[n];
      if(!row)throw Error("NOV2026_TREE_NODE_MISSING");
      if(row[0]===1){sum+=row[1]!;break;}
      if(row[0]!==0)throw Error("NOV2026_UNKNOWN_NODE");
      const feature=x[row[1]!];
      n=(!Number.isFinite(feature)?Boolean(row[5]):feature!<=row[2]!)?row[3]!:row[4]!;
      if(steps===127)throw Error("NOV2026_TREE_DEPTH_EXCEEDED");
    }
  }
  return sum;
}
function histRaw(x:readonly number[],m:HistTrees):number{
  return m.baseline+predictTreeForest(x,m.trees);
}
function sigmoid(x:number):number{
  return x>=0?1/(1+Math.exp(-x)):Math.exp(x)/(1+Math.exp(x));
}
function rankSoftmax(score:readonly number[]):number[]{
  const best=Math.max(...score);
  const exps=score.map(x=>Math.exp(Math.max(-60,(x-best)/1.4)));
  const sum=exps.reduce((a,b)=>a+b,0);
  return exps.map(x=>x/sum);
}
function combinations(ids:readonly number[],k:number):number[][]{
  const out:number[][]=[];
  function recur(start:number,pick:number[]):void{
    if(pick.length===k){out.push([...pick]);return;}
    for(let i=start;i<=ids.length-(k-pick.length);i++)recur(i+1,[...pick,ids[i]!]);
  }
  recur(0,[]);
  return out;
}
function permutations(ids:readonly number[],k:number):number[][]{
  const out:number[][]=[];
  function recur(pick:number[],used:Set<number>):void{
    if(pick.length===k){out.push([...pick]);return;}
    for(const i of ids)if(!used.has(i)){const next=new Set(used);next.add(i);recur([...pick,i],next);}
  }
  recur([],new Set());
  return out;
}
function ticketPositions(kind:CompletedBetType,order:readonly number[]):number[][]{
  if(kind==="単勝")return order.map(i=>[i]);
  if(kind==="馬単")return permutations(order.slice(0,4),2);
  if(kind==="3連単")return permutations(order.slice(0,4),3);
  return combinations(order,kind==="3連複"?3:2);
}
type Candidate={kind:CompletedBetType;combo:string;indices:number[];
  pl:number;officialOdd:number;features:number[];expected:number;hit:number};
function ticketFeatures(kind:CompletedBetType,indices:readonly number[],p:readonly number[],
  p3:readonly number[],order:readonly number[],placeOrder:readonly number[],
  raceNo:number,nCandidates:number):number[]{
  const pr=completedCombinationProbability(kind,indices,p);
  const picks=indices.map(i=>p[i]!);
  const vals=[...picks];while(vals.length<3)vals.push(0);
  const positions=indices.map(i=>order.indexOf(i)+1);
  const pds=[...positions];while(pds.length<3)pds.push(0);
  const sorted=[...p].sort((a,b)=>b-a);
  const entropy=-p.reduce((a,b)=>a+b*Math.log(Math.max(b,1e-12)),0)/Math.log(p.length);
  const top3s=order.slice(0,3).map(i=>p3[i]!);
  const allTop3=[...p3].sort((a,b)=>b-a);
  const chosenPlace=indices.map(i=>p3[i]!);
  const placeRanks=indices.map(i=>placeOrder.indexOf(i)+1);
  const base=[
    ...COMPLETED_BET_ORDER.map(t=>Number(t===kind)),
    p.length/18,raceNo/12,
    sorted[0]!,sorted[1]!,sorted[2]!,sorted[0]!+sorted[1]!+sorted[2]!,entropy,
    pr,Math.log(Math.max(pr,1e-9)),picks.reduce((a,b)=>a*b,1),
    vals[0]!+vals[1]!+vals[2]!,Math.max(...vals),Math.min(...picks),
    pds[0]!/6,pds[1]!/6,pds[2]!/6,
    positions.reduce((a,b)=>a+b,0)/16,Math.max(...positions)/6,
    vals[0]!,vals[1]!,vals[2]!,
    Number(kind==="馬単"||kind==="3連単"),
    Number(positions.includes(1)),Number(Math.max(...positions)<=3)
  ];
  const extra=[
    top3s[0]!,top3s[1]!,top3s[2]!,
    (allTop3[0]!+allTop3[1]!+allTop3[2]!)/3,
    chosenPlace.reduce((a,b)=>a+b,0)/chosenPlace.length,
    Math.min(...chosenPlace),
    chosenPlace.reduce((a,b)=>a*b,1),
    placeRanks.reduce((a,b)=>a+b,0)/36,
    Math.max(...placeRanks)/18,nCandidates/200
  ];
  return [...base,...extra].map(x=>Math.fround(x));
}
export function inferNov2026PayoutHurdleResearch(
  model:PayoutHurdleAsset,
  horseNos:readonly number[],features56:readonly (readonly number[])[],
  raceNo:number,officialRows:readonly OfficialOddsRow[]
):Nov2026HurdleOutput|null{
  if(model.horseFeatureCount!==56||model.ticketFeatureCount!==40
    ||model.notProductionValidated!==true
    ||!Number.isInteger(raceNo)||raceNo<1||raceNo>12
    ||horseNos.length<3||horseNos.length>18||horseNos.length!==features56.length
    ||new Set(horseNos).size!==horseNos.length
    ||horseNos.some(n=>!Number.isInteger(n)||n<1||n>18)
    ||features56.some(row=>row.length!==56||row.some(n=>!Number.isFinite(n))))return null;
  const scores=features56.map(row=>predictTreeForest(row,model.ranker));
  const p=rankSoftmax(scores);
  const p3=features56.map(row=>sigmoid(histRaw(row,model.top3)));
  const order=[...horseNos.keys()].sort((a,b)=>(p[b]!-p[a]!)||a-b).slice(0,5);
  const placeOrder=[...horseNos.keys()].sort((a,b)=>(p3[b]!-p3[a]!)||a-b);
  const valid=new Map<string,number>();
  for(const row of officialRows){
    const low=Number(row.oddsMin),high=Number(row.oddsMax);
    if(!Number.isFinite(low)||!Number.isFinite(high)||low<1||high<low)continue;
    const key=row.betType+"|"+row.combination;
    if(valid.has(key))return null;
    valid.set(key,low); // conservative genuine JRA quote only
  }
  const raw:Array<{kind:CompletedBetType;combo:string;indices:number[];pl:number;officialOdd:number}>=[];
  for(const kind of COMPLETED_BET_ORDER){
    for(const indices of ticketPositions(kind,order)){
      const nums=indices.map(i=>horseNos[i]!);
      if(UNORDERED.has(kind))nums.sort((a,b)=>a-b);
      const combo=nums.join("-");
      const odd=valid.get(kind+"|"+combo);
      if(!odd)continue;
      const pl=completedCombinationProbability(kind,indices,p);
      if(!(pl>0))continue;
      raw.push({kind,combo,indices,pl,officialOdd:odd});
    }
  }
  const best=new Map<CompletedBetType,Candidate>();
  for(const row of raw){
    const features=ticketFeatures(row.kind,row.indices,p,p3,order,placeOrder,raceNo,raw.length);
    if(features.length!==40||features.some(x=>!Number.isFinite(x)))return null;
    const prior=model.priors[row.kind];
    if(!prior)return null;
    const hit=0.87*sigmoid(histRaw(features,model.hit))+0.13*prior.hitPrior;
    const paid=0.87*Math.exp(histRaw(features,model.paid))+0.13*prior.wonReturnPrior;
    const expected=hit*paid;
    const candidate:Candidate={...row,features,expected,hit};
    const earlier=best.get(row.kind);
    if(!earlier||expected>earlier.expected)best.set(row.kind,candidate);
  }
  if(best.size!==COMPLETED_BET_ORDER.length)return null;
  const ranked=[...best.values()].sort((a,b)=>b.expected-a.expected);
  let optimal:{a:Candidate;b:Candidate;stakeA:number;score:number}|null=null;
  for(let i=0;i<ranked.length;i++)for(let j=i+1;j<ranked.length;j++){
    const a=ranked[i]!,b=ranked[j]!;
    if(a.kind===b.kind||Math.max(a.hit,b.hit)<0.2)continue;
    const stakeA=a.expected>=b.expected?1900:100;
    const score=stakeA*a.expected+(2000-stakeA)*b.expected;
    if(!optimal||score>optimal.score)optimal={a,b,stakeA,score};
  }
  if(!optimal)return null;
  const t=(x:Candidate,stakeYen:number):Nov2026ResearchTicket=>({
    betType:x.kind,combination:x.combo,officialOdds:x.officialOdd,
    plProbability:x.pl,learnedHitProbability:x.hit,
    expectedReturnPerYen:x.expected,stakeYen
  });
  return {model:model.name,researchOnly:true,trainThrough:model.trainThrough,
    evaluatedThrough:model.evalPeriod,notValidatedForwardInNovember2026:true,
    modeledHitFloorPct:20,modeledExpectedRoiPct:100*optimal.score/2000,
    oddsSource:"JRA official snapshot",
    tickets:[t(optimal.a,optimal.stakeA),t(optimal.b,2000-optimal.stakeA)]};
}
