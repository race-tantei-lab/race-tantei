import process from 'node:process';
import { fetchJraPage } from '../dist-test/src/v1/jra.js';
import { fetchJraArchivePage } from '../dist-test/src/v1/three-month-archive.js';

const TARGETS = [
  {date:'2026-08-01',name:'chukyo-03-result-10',endpoint:'S',cname:'pw01sde1007202602030320260801/33'},
  {date:'2026-08-01',name:'chukyo-03-result-01-alt',endpoint:'S',cname:'pw01sde0107202602030320260801/54'},
  {date:'2026-08-01',name:'chukyo-03-entry-10',endpoint:'D',cname:'pw01dde1007202602030320260801/77'},
  {date:'2026-08-01',name:'chukyo-03-entry-01-alt',endpoint:'D',cname:'pw01dde0107202602030320260801/98'},
  {date:'2026-08-02',name:'chukyo-02-result-01',endpoint:'S',cname:'pw01sde0107202602040220260802/CF'},
  {date:'2026-08-02',name:'chukyo-02-result-10-alt',endpoint:'S',cname:'pw01sde1007202602040220260802/AE'},
  {date:'2026-08-02',name:'chukyo-02-entry-01',endpoint:'D',cname:'pw01dde0107202602040220260802/13'},
  {date:'2026-08-02',name:'chukyo-02-entry-10-alt',endpoint:'D',cname:'pw01dde1007202602040220260802/F2'},
  {date:'2026-08-09',name:'chukyo-01-result-01-control',endpoint:'S',cname:'pw01sde0107202602060120260809/9E'},
];

function uniq(values) { return [...new Set(values.filter(Boolean))]; }
function oddsCnames(html) {
  const text = String(html || '').replace(/&amp;/gi,'&').replace(/\\u0026/gi,'&').replace(/\\\//g,'/');
  const out = [];
  for (const m of text.matchAll(/(?:CNAME=|cname=)([^"'&<>\s)]+)/gi)) out.push(decodeURIComponent(m[1] || ''));
  for (const m of text.matchAll(/((?:pw|sw)15[1-8]ou[^"'<>\s,)]+)/gi)) out.push(m[1] || '');
  return uniq(out.map(v => v.trim()).filter(v => /^(?:pw|sw)15[1-8]ou/i.test(v)));
}
function snippets(html) {
  const text = String(html || '').replace(/\s+/g,' ');
  const out=[];
  for (const re of [/accessO/ig,/pw151/ig,/オッズ/g]) {
    let m; let n=0;
    while ((m=re.exec(text)) && n<4) { out.push(text.slice(Math.max(0,m.index-140),Math.min(text.length,m.index+260))); n++; }
  }
  return uniq(out).slice(0,8);
}
function url(endpoint,cname) {
  return `https://www.jra.go.jp/JRADB/access${endpoint}.html?CNAME=${encodeURIComponent(cname)}`;
}
async function one(t) {
  const row = {...t, direct:null, archivePost:null};
  try {
    const page = await fetchJraPage(url(t.endpoint,t.cname));
    row.direct = {count:oddsCnames(page.html).length,cnames:oddsCnames(page.html).slice(0,30),bytes:page.html.length,snippets:snippets(page.html)};
  } catch(e) { row.direct={error:`${e?.name||'Error'}:${e?.message||e}`}; }
  if (t.endpoint==='S') {
    try {
      const page = await fetchJraArchivePage(t.cname);
      row.archivePost={count:oddsCnames(page.html).length,cnames:oddsCnames(page.html).slice(0,30),bytes:page.html.length,snippets:snippets(page.html)};
    } catch(e) { row.archivePost={error:`${e?.name||'Error'}:${e?.message||e}`}; }
  }
  return row;
}

const rows=[];
for (const t of TARGETS) rows.push(await one(t));
console.log(JSON.stringify({purpose:'research_only_jra_alternate_layout_diagnostic',rows,syntheticOddsUsed:false,productionDatabaseWritten:false,productionModelChanged:false},null,2));
process.exit(0);
