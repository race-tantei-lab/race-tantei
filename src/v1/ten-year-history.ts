import encoded from "./ten-year-history-data/index.js";

export const TEN_YEAR_HISTORY_START="2016-08-10";
export const TEN_YEAR_HISTORY_END="2026-08-09";

type RawTicket=[betType:string,combination:string,officialOdds:number,returnLightYen:number];
type RawRace=[raceId:string,raceDate:string,venue:string,raceNo:number,raceName:string|null,startTimeJst:string|null,surface:string|null,distanceM:number|null,tickets:RawTicket[]|null];

type ArchivePayload={start:string;end:string;races:RawRace[]};

export type TenYearTicket={betType:string;combination:string;officialOdds:number;returnLightYen:number};
export type TenYearRace={
  raceId:string;
  raceDate:string;
  venue:string;
  raceNo:number;
  raceName:string;
  startTimeJst:string|null;
  surface:string|null;
  distanceM:number|null;
  tickets:TenYearTicket[]|null;
};
export type TenYearCalendarRow={raceDate:string;venue:string;raceCount:number};

let archivePromise:Promise<TenYearRace[]>|null=null;
let raceMapPromise:Promise<Map<string,TenYearRace>>|null=null;

async function inflateArchive():Promise<TenYearRace[]>{
  const binary=atob(encoded);
  const bytes=new Uint8Array(binary.length);
  for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
  const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  const payload=JSON.parse(await new Response(stream).text()) as ArchivePayload;
  if(payload.start!==TEN_YEAR_HISTORY_START||payload.end!==TEN_YEAR_HISTORY_END)throw new Error("TEN_YEAR_HISTORY_RANGE_MISMATCH");
  if(payload.races.length!==34566)throw new Error(`TEN_YEAR_HISTORY_COUNT:${payload.races.length}`);
  return payload.races.map((r)=>({
    raceId:String(r[0]),raceDate:String(r[1]),venue:String(r[2]),raceNo:Number(r[3]),raceName:String(r[4]??`${r[3]}R`),
    startTimeJst:r[5]===null?null:String(r[5]),surface:r[6]===null?null:String(r[6]),distanceM:r[7]===null?null:Number(r[7]),
    tickets:r[8]===null?null:r[8].map((t)=>({betType:String(t[0]),combination:String(t[1]),officialOdds:Number(t[2]),returnLightYen:Number(t[3])}))
  }));
}

export function tenYearRaces():Promise<TenYearRace[]>{
  if(!archivePromise)archivePromise=inflateArchive();
  return archivePromise;
}

export async function tenYearRaceMap():Promise<Map<string,TenYearRace>>{
  if(!raceMapPromise)raceMapPromise=tenYearRaces().then((rows)=>new Map(rows.map((r)=>[r.raceId,r])));
  return raceMapPromise;
}

export async function tenYearCalendar():Promise<TenYearCalendarRow[]>{
  const map=new Map<string,number>();
  for(const r of await tenYearRaces()){
    const key=`${r.raceDate}|${r.venue}`;
    map.set(key,(map.get(key)??0)+1);
  }
  return [...map.entries()].map(([key,raceCount])=>{
    const [raceDate,venue]=key.split("|");
    return {raceDate,venue,raceCount};
  }).sort((a,b)=>a.raceDate.localeCompare(b.raceDate)||a.venue.localeCompare(b.venue));
}

export async function tenYearRacesOnDate(date:string):Promise<TenYearRace[]>{
  return (await tenYearRaces()).filter((r)=>r.raceDate===date);
}
