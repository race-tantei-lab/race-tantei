import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fetchJraArchivePage } from '../dist-test/src/v1/three-month-archive.js';

function arg(name, fallback = null) {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
const INPUT = path.resolve(arg('--input'));
const OUT = path.resolve(arg('--out'));
const META = path.resolve(arg('--meta'));
if (!INPUT || !OUT || !META) throw new Error('--input --out --meta required');

function parseJsonl(text) { return text.split(/\r?\n/).filter(Boolean).map(x => JSON.parse(x)); }
function cnameFromUrl(url) {
  try { return decodeURIComponent(new URL(url).searchParams.get('CNAME') || ''); }
  catch { return ''; }
}
function extractOddsCnames(html) {
  const text = String(html || '').replace(/&amp;/gi,'&').replace(/\\u0026/gi,'&').replace(/\\\//g,'/');
  const out=[];
  for (const m of text.matchAll(/(?:CNAME=|cname=)([^"'&<>\s)]+)/gi)) {
    const v=decodeURIComponent(m[1] || '').trim();
    if (/^(?:pw|sw)15[1-8]ou/i.test(v)) out.push(v.replace(/^sw/i,'pw'));
  }
  for (const m of text.matchAll(/((?:pw|sw)15[1-8]ou[^"'<>\s,)]+)/gi)) {
    const v=(m[1] || '').trim();
    if (v) out.push(v.replace(/^sw/i,'pw'));
  }
  return [...new Set(out)];
}
function checksum(cname) {
  const m=String(cname).match(/\/([0-9A-F]{2})$/i);
  return m ? parseInt(m[1],16) : null;
}
function raceIdentity(cname) {
  const m=String(cname).match(/(?:pw|sw)01sde(?:01|10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/i);
  return m ? {venue:Number(m[1]),year:Number(m[2]),meeting:Number(m[3]),day:Number(m[4]),raceNo:Number(m[5]),ymd:m[6]} : null;
}
function market(cname) {
  const m=String(cname).match(/^(?:pw|sw)(15[1-8])ou/i);
  return m ? m[1] : null;
}
async function mapConcurrent(values, concurrency, mapper) {
  const result=new Array(values.length); let cursor=0;
  async function worker(){ while(true){ const i=cursor++; if(i>=values.length)return; result[i]=await mapper(values[i],i); } }
  await Promise.all(Array.from({length:Math.min(concurrency,values.length)},worker));
  return result;
}

const rows=parseJsonl(await readFile(INPUT,'utf8')).filter(r => r.resultUrlResolutionMethod === 'jra_month_archive');
const failures=[];
const collected=await mapConcurrent(rows,3,async (row,index)=>{
  const resultCname=cnameFromUrl(row.resultUrl);
  try {
    const page=await fetchJraArchivePage(resultCname);
    const odds=extractOddsCnames(page.html);
    const grouped={};
    for(const c of odds){ const m=market(c); if(m && !(m in grouped)) grouped[m]=c; }
    const identity=raceIdentity(resultCname);
    const item={
      raceId:row.raceId,
      raceDate:row.raceDate,
      venue:row.venue,
      raceNo:row.raceNo,
      resultCname,
      resultChecksum:checksum(resultCname),
      identity,
      oddsCnames:grouped,
      oddsChecksums:Object.fromEntries(Object.entries(grouped).map(([k,v])=>[k,checksum(v)])),
      syntheticOddsUsed:false,
      productionDatabaseWritten:false,
    };
    if ((index+1)%10===0 || index+1===rows.length) console.log(JSON.stringify({processed:index+1,total:rows.length,failures:failures.length}));
    return item;
  } catch(error) {
    failures.push({raceId:row.raceId,resultCname,error:error instanceof Error?`${error.name}:${error.message}`:String(error)});
    return null;
  }
});
const ok=collected.filter(Boolean);
await mkdir(path.dirname(OUT),{recursive:true});
await writeFile(OUT,ok.map(x=>JSON.stringify(x)).join('\n')+(ok.length?'\n':''));
const coverage={};
for(const code of ['151','154','155','156','157','158']) coverage[code]=ok.filter(x=>x.oddsCnames[code]).length;
const meta={purpose:'research_only_official_jra_cname_checksum_pair_collection',inputRows:rows.length,completedRows:ok.length,failures,coverage,syntheticOddsUsed:false,productionDatabaseWritten:false,productionModelChanged:false};
await writeFile(META,JSON.stringify(meta,null,2)+'\n');
console.log(JSON.stringify(meta));
if(failures.length || ok.length!==rows.length) process.exitCode=2;
