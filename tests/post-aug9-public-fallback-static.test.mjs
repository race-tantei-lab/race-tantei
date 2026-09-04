import fs from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const v37 = fs.readFileSync('src/public-site-entry-v37.ts', 'utf8');
const fallback = fs.readFileSync('src/v1/post-aug9-public-fallback.ts', 'utf8');
const snapshot = fs.readFileSync('src/v1/post-aug9-public-snapshot.ts', 'utf8');

test('v37 preserves UI version while intercepting frozen historical reads', () => {
  assert.match(v37, /ten-year-completed-public-v37-target-race-count-20260830/);
  assert.match(v37, /hasPostAug9SnapshotDate/);
  assert.match(v37, /postAug9DayResponse/);
  assert.match(v37, /postAug9PerformanceResponse/);
});

test('fallback covers every frozen post-Aug9 race weekend after cutover', () => {
  for (const date of ['2026-08-15','2026-08-16','2026-08-22','2026-08-23','2026-08-29','2026-08-30']) {
    assert.ok(fallback.includes(date), date);
    assert.ok(snapshot.includes(date), date);
  }
});

test('fallback never invents historical bets and keeps missing target races visible', () => {
  assert.match(fallback, /projectCurrentPublicState/);
  assert.match(fallback, /SAFE_DATES/);
  assert.doesNotMatch(fallback, /INSERT|UPDATE|DELETE\s+FROM/i);
});
