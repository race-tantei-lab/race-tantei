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

test('race-day scheduler repairs the production bounded-read indexes first', () => {
  assert.match(entry, /CREATE INDEX IF NOT EXISTS rt_idx_races_date ON rt_races\(race_date DESC, venue, race_no\)/);
  assert.match(entry, /CREATE INDEX IF NOT EXISTS rt_idx_public_bets_race ON rt_public_bets\(race_id, id\)/);
  assert.match(entry, /await ensureRaceDayIndexes\(env\.DB\)/);
});

test('the D1-quota emergency page retry is rewritten from 30s to 120s', () => {
  assert.match(entry, /\.replace\("setTimeout\(\(\)=>location\.reload\(\),30000\)", "setTimeout\(\(\)=>location\.reload\(\),120000\)"\)/);
});
