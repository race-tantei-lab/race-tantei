import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const entry = fs.readFileSync('src/public-site-entry-v41.ts', 'utf8');
const wrangler = fs.readFileSync('wrangler.jsonc', 'utf8');

test('v41 restores upstream race-day scheduler while preserving v37 UI', () => {
  assert.match(entry, /import publicSite from "\.\/public-site-entry-v37\.js"/);
  assert.match(entry, /import upstreamSite from "\.\/public-site-entry-v34\.js"/);
  assert.match(entry, /upstreamSite\.scheduled\(controller, env, ctx\)/);
  assert.match(entry, /publicSite\.scheduled\(controller, env, ctx\)/);
  assert.match(wrangler, /"main": "src\/public-site-entry-v41\.ts"/);
});

test('emergency page retry is throttled while D1 quota is unavailable', () => {
  assert.match(entry, /120000/);
  assert.doesNotMatch(entry, /location\.reload\(\),30000/);
});
