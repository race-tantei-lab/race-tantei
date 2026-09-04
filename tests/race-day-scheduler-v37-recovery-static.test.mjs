import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const entry = fs.readFileSync('src/public-site-entry-v37.ts', 'utf8');
const wrangler = fs.readFileSync('wrangler.jsonc', 'utf8');

test('v37 stays the public display-only entry', () => {
  assert.match(entry, /import publicSite from "\.\/public-site-entry-v34\.js"/);
  assert.doesNotMatch(entry, /publicSite\.scheduled\(controller/);
  assert.doesNotMatch(entry, /runCompletedWorkerLiveLock/);
  assert.match(wrangler, /"main": "src\/public-site-entry-v37\.ts"/);
});

test('public maintenance repairs bounded-read indexes without generating bets', () => {
  assert.match(entry, /CREATE INDEX IF NOT EXISTS rt_idx_races_date ON rt_races\(race_date DESC, venue, race_no\)/);
  assert.match(entry, /CREATE INDEX IF NOT EXISTS rt_idx_public_bets_race ON rt_public_bets\(race_id, id\)/);
  assert.match(entry, /await ensureRaceDayIndexes\(env\.DB\)/);
  assert.match(entry, /await runPublicMaintenance\(env/);
});

test('the D1-quota emergency page backs off to a two-minute retry', () => {
  assert.match(entry, /location\.reload\(\),120000/);
  assert.doesNotMatch(entry, /location\.reload\(\),30000/);
});
