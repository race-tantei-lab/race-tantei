import { DIRECT_CANONICAL_HISTORY } from "./canonical-history-direct.js";
import type { PublicBetRow } from "./public-history-db.js";

const CUTOFF="2026-08-02";
const BET_TYPES=["単勝","馬連","ワイド","馬単","3連複","3連単"] as const;
const ODDS_MID=[1.4,2.45,3.9,5.9,8.4,12.2,17.3,24.5,38.7,61.2,86.6,122.5,212.1,387.3,632.5,979.8,1549.2,2500.0] as const;
const COURSES=[["ライト",20],["スタンダード",50],["プレミアム",100]] as const;

export type CanonicalCoursePayouts={ライト:number;スタンダード:number;プレミアム:number};

type CompactTuple=[number,number,number,number];

function race(raceId:string):CompactTuple[]|null{
  if(raceId.slice(0,10)>CUTOFF)return null;
  const rows=DIRECT_CANONICAL_HISTORY[raceId];
  if(!rows)return null;
  return rows as CompactTuple[];
}

function allocation(binCodes:number[],unitsTotal:number):number[]{
  const n=binCodes.length,cap=Math.max(1,Math.floor(unitsTotal*0.35+1e-12));
  if(n<3||n>10||n*cap<unitsTotal)throw new Error("INVALID_CANONICAL_TICKET_COUNT");
  const units=Array(n).fill(1) as number[];let remaining=unitsTotal-n;
  const weights=binCodes.map(code=>{const odds=ODDS_MID[code];if(odds===undefined)throw new Error("INVALID_ODDS_BIN");return Math.min(1,Math.pow(100/odds,1.5));});
  const totalWeight=weights.reduce((a,b)=>a+b,0);const targets=weights.map(w=>unitsTotal*w/totalWeight);
  while(remaining>0){
    const eligible=units.map((_,i)=>i).filter(i=>units[i]<cap);
    eligible.sort((a,b)=>{
      const deficiency=(targets[b]-units[b])-(targets[a]-units[a]);if(Math.abs(deficiency)>1e-12)return deficiency;
      const weight=weights[b]-weights[a];if(Math.abs(weight)>1e-12)return weight;
      const oddsA=ODDS_MID[binCodes[a]]??0,oddsB=ODDS_MID[binCodes[b]]??0;if(oddsA!==oddsB)return oddsA-oddsB;
      return a-b;
    });
    const next=eligible[0];if(next===undefined)throw new Error("CANONICAL_ALLOCATION_FAILED");units[next]+=1;remaining-=1;
  }
  return units;
}

function comboText(bet:number,packed:number):string{
  if(bet===0)return String(packed);
  if(bet===4||bet===5){const a=packed>>10,b=(packed>>5)&31,c=packed&31;return `${a}-${b}-${c}`;}
  const a=packed>>5,b=packed&31;return `${a}-${b}`;
}

export async function getStaticCanonicalState(raceId:string):Promise<{hasBets:boolean;hit:boolean}|null>{
  const rows=race(raceId);if(!rows)return null;
  return {hasBets:true,hit:rows.some(t=>Number(t[3])>0)};
}

export async function getStaticCanonicalCoursePayouts(raceId:string):Promise<CanonicalCoursePayouts|null>{
  const rows=race(raceId);if(!rows)return null;
  const bins=rows.map(t=>Number(t[2]));
  const out:CanonicalCoursePayouts={ライト:0,スタンダード:0,プレミアム:0};
  for(const [course,unitsTotal] of COURSES){
    const units=allocation(bins,unitsTotal);
    out[course]=units.reduce((sum,u,i)=>sum+u*Number(rows[i][3]),0);
  }
  return out;
}

export async function getStaticCanonicalBets(raceId:string):Promise<PublicBetRow[]>{
  const rows=race(raceId);if(!rows)return [];
  const bins=rows.map(t=>Number(t[2]));const out:PublicBetRow[]=[];
  for(const [course,unitsTotal] of COURSES){
    const units=allocation(bins,unitsTotal);
    rows.forEach((ticket,i)=>out.push({
      course,
      betType:BET_TYPES[Number(ticket[0])]??"不明",
      combination:comboText(Number(ticket[0]),Number(ticket[1])),
      stakeYen:units[i]*100,
      assumedOdds:null,
      returnYen:units[i]*Number(ticket[3]),
      settlementStatus:"settled"
    }));
  }
  return out;
}
