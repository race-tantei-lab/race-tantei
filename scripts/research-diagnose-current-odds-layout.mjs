import process from 'node:process';
import { fetchJraPage } from '../dist-test/src/v1/jra.js';
import { fetchJraArchivePage } from '../dist-test/src/v1/three-month-archive.js';

const TARGETS = [
  ['2026-07-19','hakodate-06','pw01sde1002202601120620260719/86'],
  ['2026-08-01','chukyo-03','pw01sde1007202602030320260801/33'],
  ['2026-08-02','chukyo-02','pw01sde0107202602040220260802/CF'],
  ['2026-08-09','chukyo-01','pw01sde0107202602060120260809/9E'],
];

function uniq(values) { return [...new Set(values.filter(Boolean))]; }
function oddsCnames(html) {
  const text = String(html || '').replace(/&amp;/gi,'&').replace(/\\u0026/gi,'&').replace(/\\\//g,'/');
  const out = [];
  for (const m of text.matchAll(/(?:CNAME=|cname=)([^"'&<>\s)]+)/gi)) out.push(decodeURIComponent(m[1] || ''));
  for (const m of text.matchAll(/((?:pw|sw)15[1-8]ou[^"'<>\s,)]+)/gi)) out.push(m[1] || '');
  return uniq(out.map(v => v.trim()).filter(v => /^(?:pw|sw)15[1-8]ou/i.test(v)));
}
function resultUrl(cname) {
  return `https://www.jra.go.jp/JRADB/accessS.html?CNAME=${encodeURIComponent(cname)}`;
}
async function one(date, name, cname) {
  const row = { date, name, cname, direct: null, archivePost: null };
  try {
    const page = await fetchJraPage(resultUrl(cname));
    row.direct = { count: oddsCnames(page.html).length, cnames: oddsCnames(page.html).slice(0,30), bytes: page.html.length };
  } catch (e) { row.direct = { error: `${e?.name || 'Error'}:${e?.message || e}` }; }
  try {
    const page = await fetchJraArchivePage(cname);
    row.archivePost = { count: oddsCnames(page.html).length, cnames: oddsCnames(page.html).slice(0,30), bytes: page.html.length };
  } catch (e) { row.archivePost = { error: `${e?.name || 'Error'}:${e?.message || e}` }; }
  return row;
}

const rows = [];
for (const t of TARGETS) rows.push(await one(...t));
console.log(JSON.stringify({ purpose:'research_only_jra_odds_layout_diagnostic', rows, syntheticOddsUsed:false, productionDatabaseWritten:false, productionModelChanged:false }, null, 2));
process.exit(0);
