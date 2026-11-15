/**
 * Triple-method cash forecasts, RESEARCH-only. These are not three horse models.
 * Existing official frozen ticket combinations remain authoritative and unchanged.
 * Every cash forecast sees only preceding months' payout observations.
 */
import archive from "./three-model-archived-cash-priors.json" with {type:"json"};
import {restored716Tickets,RESTORED_RESEARCH_SLA,RESTORED_RESEARCH_TRAINING_TICKETS} from "./restored-716-money-policy.js";
export type MethodId="current"|"cash6"|"cash96";
export type Race={raceId:string;raceDate:string;venue:string;raceNo:number;
  raceName:string|null;surface:string|null;distanceM:number|null;
  startTimeUtc:string|null;startTimeJst:string|null};
export type Bet={raceId:string;betType:string;combination:string;stakeYen:number;
  assumedOdds:number|null;lockedAt:string|null;settlementStatus:string;returnYen:number|null};
export type PastBet=Bet&Race;
export type Ticket={betType:string;combination:string;stakeYen:number;assumedOdds:number;
  expectedCashIndex:number|null;settledReturnYen:number|null};
export type ModelPick={race:Race;status:"actual"|"simulation"|"awaiting"|"skipped";
  detail:string;expectedCashIndex:number|null;tickets:Ticket[]};
export type Panel={id:MethodId;title:string;description:string;hypothetical:boolean;
  selectedRaces:number;awaitingRaces:number;trainingTickets:number;
  venues:{venue:string;races:ModelPick[]}[]};
type Stats=[number,number,number,number];
type MonthStats={global:number[];keys:Record<string,number[]>};
const FROZEN=archive as unknown as {sourceLastDate:string;raceCount:number;ticketCount:number;
  monthly:Record<string,MonthStats>};
const TYPES=new Set(["単勝","ワイド","馬連","馬単","3連複","3連単"]);
const BOUNDS=[2,3,5,8,12,20,35,60,100,200,400];
const WEIGHTS=[.25,.22,.16,.07,.08,.05,.07,.05,.05];
const SHRINK=[10,20,30,30,35,55,45,65,30];

function monthIndex(s:string):number{
  if(!/^20\d\d-(0[1-9]|1[0-2])$/.test(s))throw Error("INVALID_FORECAST_MONTH");
  return Number(s.slice(0,4))*12+Number(s.slice(5,7));
}
export function cashFeatureKeys(r:Race,b:Pick<Bet,"betType"|"assumedOdds">):string[]{
  const k=b.betType,odd=Number(b.assumedOdds);
  if(!TYPES.has(k)||!Number.isFinite(odd)||odd<=0)throw Error("BAD_MARKET_PRICE");
  const bucket=BOUNDS.findIndex(cap=>odd<cap),ob=bucket<0?BOUNDS.length:bucket;
  const rn=Number(r.raceNo),month=Number(r.raceDate.slice(5,7)),dist=Number(r.distanceM||0);
  return [
    ["type",k],["typeOdds",k,ob],["typeVenue",k,r.venue],
    ["typeRace",k,rn<=4?0:rn<=8?1:2],["typeSurface",k,r.surface||"障害"],
    ["typeSeason",k,Math.floor((month-1)/3)],
    ["typeDistance",k,Math.min(6,Math.floor(dist/400))],
    ["typeOddsVenue",k,ob,r.venue],["odds",ob],
  ].map(v=>JSON.stringify(v));
}
export function preT15(lockedAt:string|null,startUTC:string|null,date:string,startJST:string|null):boolean{
  if(!lockedAt)return false;
  const locked=Date.parse(lockedAt),utc=Date.parse(String(startUTC||""));
  const m=String(startJST||"").match(/(\d{1,2}):(\d{2})/);
  const local=m?Date.parse(date+"T"+m[1]!.padStart(2,"0")+":"+m[2]+":00+09:00"):NaN;
  const start=Number.isFinite(utc)?utc:local;
  return Number.isFinite(start)&&Number.isFinite(locked)&&locked<=start-900000;
}
function completePriorPair(xs:PastBet[]):boolean{
  return xs.length===2&&new Set(xs.map(x=>x.betType)).size===2&&xs.every(x=>
    TYPES.has(x.betType)&&x.settlementStatus==="settled"&&
    x.returnYen!==null&&Number.isFinite(Number(x.returnYen))&&Number(x.returnYen)>=0&&
    Number.isInteger(Number(x.stakeYen))&&Number(x.stakeYen)>=100&&
    Number(x.stakeYen)%100===0&&Number.isFinite(Number(x.assumedOdds))&&Number(x.assumedOdds)>0&&
    preT15(x.lockedAt,x.startTimeUtc,x.raceDate,x.startTimeJst));
}
type Fit={seen:number;keyStats:Map<string,Stats>;cashPrior:number;hitPrior:number;
  objective:"cash80"|"hit_cash"};
export function fitPreviousCash(target:string,horizon:number,objective:"cash80"|"hit_cash",older:PastBet[]):Fit{
  if(FROZEN.sourceLastDate!=="2026-08-09"||FROZEN.raceCount!==14410||
     FROZEN.ticketCount!==28820)throw Error("FROZEN_CASH_DATA_SOURCE_NOT_VERIFIED");
  const end=monthIndex(target),first=end-horizon;
  let count=0,paid40=0,paid80=0,hits=0;
  const keys=new Map<string,Stats>();
  for(const [m,data] of Object.entries(FROZEN.monthly)){
    const id=monthIndex(m);
    if(id<first||id>=end)continue;
    const g=data.global;
    count+=Number(g[0]||0);paid40+=Number(g[1]||0);
    paid80+=Number(g[2]||0);hits+=Number(g[3]||0);
    for(const [key,value] of Object.entries(data.keys)){
      const a=keys.get(key)||[0,0,0,0];
      for(let j=0;j<4;j++)a[j]+=Number(value[j]||0);
      keys.set(key,a);
    }
  }
  const grouped=new Map<string,PastBet[]>();
  for(const row of older){
    if(row.raceDate<=FROZEN.sourceLastDate)continue;
    const mon=monthIndex(row.raceDate.slice(0,7));
    if(mon<first||mon>=end)continue;
    const a=grouped.get(row.raceId)||[];
    a.push(row);grouped.set(row.raceId,a);
  }
  for(const rows of grouped.values()){
    if(!completePriorPair(rows))continue;
    for(const row of rows){
      const pay=Number(row.returnYen)/Number(row.stakeYen),hit=Number(Number(row.returnYen)>0);
      count++;paid40+=Math.min(pay,40);paid80+=Math.min(pay,80);hits+=hit;
      for(const key of cashFeatureKeys(row,row)){
        const a=keys.get(key)||[0,0,0,0];
        a[0]++;a[1]+=Math.min(pay,40);a[2]+=Math.min(pay,80);a[3]+=hit;
        keys.set(key,a);
      }
    }
  }
  return {seen:count,keyStats:keys,
    cashPrior:Math.max(.25,(objective==="cash80"?paid80:paid40)/Math.max(1,count)),
    hitPrior:Math.max(.05,hits/Math.max(1,count)),objective};
}
export function scoreCash(r:Race,bet:Bet,fit:Fit):{cash:number;hit:number}{
  let cash=0,hit=0;
  cashFeatureKeys(r,bet).forEach((key,i)=>{
    const a=fit.keyStats.get(key)||[0,0,0,0];
    const n=a[0],prior=SHRINK[i]!;
    cash+=WEIGHTS[i]!*(((fit.objective==="cash80"?a[2]:a[1])+prior*fit.cashPrior)/(n+prior));
    hit+=WEIGHTS[i]!*((a[3]+prior*fit.hitPrior)/(n+prior));
  });
  if(fit.objective==="hit_cash")cash=.66*cash+.34*(hit*Math.min(25,fit.cashPrior/Math.max(.1,fit.hitPrior)));
  return {cash:Math.max(.01,cash),hit:Math.min(.99,Math.max(.01,hit))};
}
function validCurrent(xs:Bet[],preserveSourceOrder=false):Bet[]|null{
  if(xs.length!==2||new Set(xs.map(x=>x.betType)).size!==2||
    xs.some(x=>!TYPES.has(x.betType)||!Number.isFinite(Number(x.assumedOdds))||
      Number(x.assumedOdds)<=0||!Number.isInteger(Number(x.stakeYen))||
      Number(x.stakeYen)<100||Number(x.stakeYen)%100!==0))return null;
  if(preserveSourceOrder)return [...xs];
  return [...xs].sort((a,b)=>a.betType.localeCompare(b.betType,"ja")||
    a.combination.localeCompare(b.combination,"ja"));
}
function originals(xs:Bet[]):Ticket[]{
  return xs.map(x=>({betType:x.betType,combination:x.combination,
    stakeYen:Number(x.stakeYen),assumedOdds:Number(x.assumedOdds),
    expectedCashIndex:null,
    settledReturnYen:x.settlementStatus==="settled"?x.returnYen:null}));
}
function speculative(xs:Bet[],a:number,b:number):Ticket[]{
  const sizes=a>=b?[1800,200]:[200,1800];
  return xs.map((x,i)=>({betType:x.betType,combination:x.combination,
    assumedOdds:Number(x.assumedOdds),stakeYen:sizes[i]!,expectedCashIndex:i===0?a:b,
    settledReturnYen:null}));
}
export function compareThree(date:string,selectedIds:string[],races:Race[],
  bets:Bet[],older:PastBet[]):Panel[]{
  const available=new Map(races.map(x=>[x.raceId,x]));
  const byVenue=new Map<string,Race[]>(),selected=new Set(selectedIds);
  for(const id of selected){
    const race=available.get(id);if(!race)continue;
    const arr=byVenue.get(race.venue)||[];arr.push(race);byVenue.set(race.venue,arr);
  }
  for(const arr of byVenue.values())arr.sort((a,b)=>a.raceNo-b.raceNo);
  const byBet=new Map<string,Bet[]>();
  for(const bet of bets){
    if(!selected.has(bet.raceId))continue;
    const arr=byBet.get(bet.raceId)||[];arr.push(bet);byBet.set(bet.raceId,arr);
  }
  // The prior six-month method is retired: the second public model is now
  // the precisely frozen 716% research cash allocator, not a relabel.
  const definitions=[
    {id:"current" as const,title:"現行モデル",description:"従来どおりの実際に固定した買い目・購入金額",hypothetical:false},
    {id:"cash6" as const,title:"716.83%研究モデル",description:"2023〜2026/8の過去検証値。元の方式で5候補から3R選び100円単位配分",hypothetical:true}
  ];
  return definitions.map(def=>{
    let selectedRaces=0,awaitingRaces=0;
    const venues=[...byVenue].map(([venue,rows])=>{
      const candidates=rows.map(r=>{
        const original=validCurrent(byBet.get(r.raceId)||[],def.id==="cash6");
        const onTime=original!==null&&original.every(b=>preT15(b.lockedAt,r.startTimeUtc,r.raceDate,r.startTimeJst));
        if(!original)return {race:r,original:null,ready:false,tickets:[] as Ticket[],expected:0};
        if(def.id==="current")return {race:r,original,ready:onTime,tickets:originals(original),expected:0};
        if(!onTime)return {race:r,original,ready:false,tickets:[] as Ticket[],expected:0};
        const result=restored716Tickets(r,original);
        return {race:r,original,ready:true,tickets:result.tickets,expected:result.priority};
      });
      // Original 716% formula chooses 3/5 by descending (cash A + cash B).
      // With incomplete original tickets, no hindsight-based partial slate.
      const complete=rows.length===5&&candidates.every(c=>c.ready);
      const ranks=new Set(def.id==="cash6"&&complete?
        [...candidates].sort((a,b)=>b.expected-a.expected||
          (a.race.raceId<b.race.raceId?-1:a.race.raceId>b.race.raceId?1:0))
          .slice(0,RESTORED_RESEARCH_SLA).map(x=>x.race.raceId):[]);
      const selections:ModelPick[]=candidates.map(c=>{
        let status:ModelPick["status"]="awaiting",detail="本番買い目の確定待ち",tickets:Ticket[]=[];
        if(def.id==="current"&&c.original){
          status="actual";tickets=c.tickets;detail=c.ready?"本番確定買い目":"本番の保存済み買い目（T−15固定は未確認）";
        }else if(def.id==="cash6"&&complete){
          if(ranks.has(c.race.raceId)){
            status="simulation";tickets=c.tickets;
            detail="元の716.83%研究方式による仮想配分・実購入ではありません";
          }else{status="skipped";detail="元の研究方式で会場5候補中の上位3レース外";}
        }else if(def.id==="cash6"){
          detail="会場5レースの発走15分前固定馬券がすべて揃うまで判定待ち";
        }
        if(status==="actual"||status==="simulation")selectedRaces++;
        if(status==="awaiting")awaitingRaces++;
        return {race:c.race,status,detail,tickets,expectedCashIndex:status==="simulation"?c.expected:null};
      });
      return {venue,races:selections};
    });
    return {...def,selectedRaces,awaitingRaces,
      trainingTickets:def.id==="cash6"?RESTORED_RESEARCH_TRAINING_TICKETS:0,venues};
  });
}
