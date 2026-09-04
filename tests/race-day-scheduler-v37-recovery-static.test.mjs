import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const entry = fs.readFileSync('src/public-site-entry-v37.ts', 'utf8');
const wrangler = fs.readFileSync('wrangler.jsonc', 'utf8');

test('v37 keeps the public entry and restores the upstream race-day scheduler', () => {
  assert.match(entry, /import publicSite from "\.\/public-site-entry-v37-core\.js"/);
  assert.match(entry, /import upstreamSite from "\.\/public-site-entry-v34\.js"/);
  assert.match(entry, /upstreamSite\.scheduled\(controller, env, ctx\)/);
  assert.match(entry, /publicSite\.scheduled\(controller, env, ctx\)/);
  assert.match(wrangler, /"main": "src\/public-site-entry-v37\.ts"/);
});

test('the D1-quota emergency page no longer reloads every 30 seconds', () => {
  assert.match(entry, /120000/);
  assert.doesNotMatch(entry, /location\.reload\(\),30000/);
});
