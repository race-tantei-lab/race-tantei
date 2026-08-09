import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

const ROOT=process.cwd();
const V1=path.join(ROOT,'src','v1');
const OUT=path.join(V1,'canonical-history-direct.ts');
const VENUE_SLUG={札幌:'sapporo',函館:'hakodate',福島:'fukushima',新潟:'niigata',東京:'tokyo',中山:'nakayama',中京:'chukyo',京都:'kyoto',阪神:'hanshin',小倉:'kokura'};

function defaultString(i){
  const src=fs.readFileSync(path.join(V1,'canonical-history-data',`bin-${String(i).padStart(2,'0')}.ts`),'utf8').trim();
  const literal=src.replace(/^export\s+default\s+/,'').replace(/;\s*$/,'');
  const value=JSON.parse(literal);
  if(typeof value!=='string')throw new Error(`BAD_BIN_${i}`);
  return value;
}
function selected(year){
  const src=fs.readFileSync(path.join(V1,`frozen-selected-${year}.ts`),'utf8');
  const m=src.match(/=\s*(\{[\s\S]*\})\s*;\s*$/);
  if(!m)throw new Error(`BAD_SELECTED_${year}`);
  return JSON.parse(m[1]);
}
function readVarint(buf,state){
  let value=0,shift=0;
  while(state.i<buf.length){const b=buf[state.i++];value|=(b&127)<<shift;if(b<128)return value;shift+=7;if(shift>28)throw new Error('VARINT_TOO_LARGE');}
  throw new Error('TRUNCATED');
}

const ids=[];
for(const year of [2024,2025,2026]){
  for(const [key,value] of Object.entries(selected(year))){
    const [date,venue]=key.split('|');if(date>'2026-08-02')continue;
    const slug=VENUE_SLUG[venue];if(!slug)throw new Error(`UNKNOWN_VENUE:${venue}`);
    for(const raceNo of String(value).split('.'))ids.push(`${date}-${slug}-${String(Number(raceNo)).padStart(2,'0')}`);
  }
}
if(ids.length!==3210)throw new Error(`RACE_COUNT:${ids.length}`);

const chunks=[0,1,2,3].map(defaultString);
const encoded=chunks.join('');
const compressed=Buffer.from(encoded,'base64');
const data=zlib.gunzipSync(compressed);
const state={i:0};
const count=readVarint(data,state);if(count!==ids.length)throw new Error(`ARCHIVE_COUNT:${count}/${ids.length}`);
const out={};let ticketCount=0;
for(const raceId of ids){
  const n=readVarint(data,state),rows=[];
  for(let i=0;i<n;i++)rows.push([readVarint(data,state),readVarint(data,state),readVarint(data,state),0]);
  const winners=readVarint(data,state);
  for(let i=0;i<winners;i++){const idx=readVarint(data,state),payout=readVarint(data,state);if(!rows[idx])throw new Error('BAD_WINNER_INDEX');rows[idx][3]=payout;}
  ticketCount+=n;out[raceId]=rows;
}
if(state.i!==data.length||ticketCount!==17735)throw new Error(`INTEGRITY:${state.i}/${data.length}/${ticketCount}`);
fs.writeFileSync(OUT,`export const DIRECT_CANONICAL_HISTORY:Record<string,number[][]>=${JSON.stringify(out)};\n`);
console.log(JSON.stringify({chunks:chunks.map(x=>x.length),encoded:encoded.length,compressed:compressed.length,uncompressed:data.length,races:Object.keys(out).length,tickets:ticketCount,bytes:fs.statSync(OUT).size}));
