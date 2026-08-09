import b0 from "./canonical-history-data/bin-00.js";
import b1 from "./canonical-history-data/bin-01.js";
import b2 from "./canonical-history-data/bin-02.js";
import b3 from "./canonical-history-data/bin-03.js";
import { SELECTED_2024 } from "./frozen-selected-2024.js";
import { SELECTED_2025 } from "./frozen-selected-2025.js";
import { SELECTED_2026 } from "./frozen-selected-2026.js";
import type { PublicBetRow } from "./public-history-db.js";

const CUTOFF="2026-08-02";
const BET_TYPES=["単勝","馬連","ワイド","馬単","3連複","3連単"] as const;
const ODDS_MID=[1.4,2.45,3.9,5.9,8.4,12.2,17.3,24.5,38.7,61.2,86.6,122.5,212.1,387.3,632.5,979.8,1549.2,2500.0] as const;
const COURSES=[["ライト",20],["スタンダード",50],["プレミアム",100]] as const;
const VENUE_SLUG:Record<string,string>={札幌:"sapporo",函館:"hakodate",福島:"fukushima",新潟:"niigata",東京:"tokyo",中山:"nakayama",中京:"chukyo",京都:"kyoto",阪神:"hanshin",小倉:"kokura"};

type CompactTicket={bet:number;combo:number;bin:number;payout:number};
type CompactRace=CompactTicket[];
export type CanonicalCoursePayouts={ライト:number;スタンダード:number;プレミアム:number};
let cache:Promise<Map<string,CompactRace>>|null=null;

function raceIds(record:Record<string,string>):string[]{
  const out:string[]=[];
  for(const [key,value] of Object.entries(record)){
    const [date,venue]=key.split("|");
    if(!date||!venue||date>CUTOFF)continue;
    const slug=VENUE_SLUG[venue];if(!slug)throw new Error(`UNKNOWN_VENUE:${venue}`);
    for(const raceNo of value.split("."))out.push(`${date}-${slug}-${String(Number(raceNo)).padStart(2,"0")}`);
  }
  return out;
}

function readVarint(bytes:Uint8Array,cursor:{i:number}):number{
  let value=0,shift=0;
  while(cursor.i<bytes.length){const b=bytes[cursor.i++];value|=(b&127)<<shift;if(b<128)return value;shift+=7;if(shift>28)throw new Error("VARINT_TOO_LARGE");}
  throw new Error("TRUNCATED_CANONICAL_HISTORY");
}

async function inflate():Promise<Uint8Array>{
  const encoded=b0+b1+b2+b3;
  const binary=atob(encoded);const compressed=new Uint8Array(binary.length);
  for(let i=0;i<binary.length;i++)compressed[i]=binary.charCodeAt(i);
  const stream=new Blob([compressed]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
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

async function load():Promise<Map<string,CompactRace>>{
  const ids=[...raceIds(SELECTED_2024),...raceIds(SELECTED_2025),...raceIds(SELECTED_2026)];
  if(ids.length!==3210)throw new Error(`CANONICAL_RACE_INDEX_MISMATCH:${ids.length}`);
  const bytes=await inflate();const cursor={i:0};const count=readVarint(bytes,cursor);
  if(count!==ids.length)throw new Error(`CANONICAL_ARCHIVE_COUNT_MISMATCH:${count}`);
  const map=new Map<string,CompactRace>();let ticketCount=0;
  const audit=new Map<number,[number,number]>([[20,[0,0]],[50,[0,0]],[100,[0,0]]]);
  for(let r=0;r<count;r++){
    const n=readVarint(bytes,cursor);const tickets:CompactRace=[];
    for(let i=0;i<n;i++)tickets.push({bet:readVarint(bytes,cursor),combo:readVarint(bytes,cursor),bin:readVarint(bytes,cursor),payout:0});
    const winners=readVarint(bytes,cursor);
    for(let i=0;i<winners;i++){const ticketIndex=readVarint(bytes,cursor),payout=readVarint(bytes,cursor);const t=tickets[ticketIndex];if(!t)throw new Error("INVALID_WINNER_INDEX");t.payout=payout;}
    ticketCount+=n;map.set(ids[r],tickets);
    const bins=tickets.map(t=>t.bin);
    for(const [,unitsTotal] of COURSES){const units=allocation(bins,unitsTotal),a=audit.get(unitsTotal)!;a[0]+=units.reduce((s,u)=>s+u*100,0);a[1]+=units.reduce((s,u,i)=>s+u*tickets[i].payout,0);}
  }
  if(cursor.i!==bytes.length||ticketCount!==17735)throw new Error(`CANONICAL_ARCHIVE_INTEGRITY:${cursor.i}/${bytes.length}/${ticketCount}`);
  const expected=new Map<number,[number,number]>([[20,[6420000,19141940]],[50,[16050000,47986180]],[100,[32100000,95798280]]]);
  for(const [unitsTotal,value] of expected){const actual=audit.get(unitsTotal)!;if(actual[0]!==value[0]||actual[1]!==value[1])throw new Error(`CANONICAL_TOTAL_MISMATCH:${unitsTotal}:${actual.join("/")}`);}
  return map;
}

function archive():Promise<Map<string,CompactRace>>{cache??=load().catch(error=>{cache=null;throw error;});return cache;}

export async function getStaticCanonicalState(raceId:string):Promise<{hasBets:boolean;hit:boolean}|null>{
  if(raceId.slice(0,10)>CUTOFF)return null;const tickets=(await archive()).get(raceId);if(!tickets)return null;
  return {hasBets:true,hit:tickets.some(t=>t.payout>0)};
}

export async function getStaticCanonicalCoursePayouts(raceId:string):Promise<CanonicalCoursePayouts|null>{
  if(raceId.slice(0,10)>CUTOFF)return null;
  const tickets=(await archive()).get(raceId);if(!tickets)return null;
  const bins=tickets.map(t=>t.bin);
  const out:CanonicalCoursePayouts={ライト:0,スタンダード:0,プレミアム:0};
  for(const [course,unitsTotal] of COURSES){
    const units=allocation(bins,unitsTotal);
    out[course]=units.reduce((sum,u,i)=>sum+u*tickets[i].payout,0);
  }
  return out;
}

export async function getStaticCanonicalBets(raceId:string):Promise<PublicBetRow[]>{
  if(raceId.slice(0,10)>CUTOFF)return [];const tickets=(await archive()).get(raceId);if(!tickets)return [];
  const bins=tickets.map(t=>t.bin);const out:PublicBetRow[]=[];
  for(const [course,unitsTotal] of COURSES){const units=allocation(bins,unitsTotal);
    tickets.forEach((ticket,i)=>out.push({course,betType:BET_TYPES[ticket.bet]??"不明",combination:comboText(ticket.bet,ticket.combo),stakeYen:units[i]*100,assumedOdds:null,returnYen:units[i]*ticket.payout,settlementStatus:"settled"}));
  }
  return out;
}
