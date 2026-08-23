from pathlib import Path

p=Path('src/v1/completed-worker-live-lock.ts')
t=p.read_text(encoding='utf-8')
t=t.replace('const DEADLINE_MS = 15 * 60 * 1000;\n', 'const DEADLINE_MS = 15 * 60 * 1000;\nconst FINAL_REFLECTION_DEADLINE_MS = 10 * 60 * 1000;\n', 1)
t=t.replace('  generatedAt: string;\n', '  generatedAt: string;\n  generationStartedAt?: string;\n', 1)
t=t.replace('  if (!Number.isFinite(Date.parse(snapshot.generatedAt)) || !Number.isFinite(Date.parse(snapshot.oddsFetchedAt))) return false;\n', '  if (!Number.isFinite(Date.parse(snapshot.generatedAt)) || !Number.isFinite(Date.parse(snapshot.oddsFetchedAt))) return false;\n  if (snapshot.generationStartedAt != null && !Number.isFinite(Date.parse(snapshot.generationStartedAt))) return false;\n', 1)
t=t.replace('    generatedAt: iso(),\n', '    generatedAt: iso(),\n    generationStartedAt: iso(now),\n', 1)
start=t.index('async function commitSnapshot(')
end=t.index('\nasync function saveAudit(', start)
new_commit=r'''async function commitSnapshot(db: D1Database, raceId: string, snapshot: PreviewSnapshot, now: Date, finalizedFrom: "fresh" | "last_good" | "deadline_watchdog"): Promise<void> {
  if (!validSnapshot(snapshot, raceId)) throw new Error(`WORKER_FINAL_SNAPSHOT_INVALID:${raceId}`);
  const { race } = await loadRace(db, raceId);
  if (!race.startTimeUtc) throw new Error(`WORKER_START_TIME_MISSING:${raceId}`);
  const startMs = Date.parse(race.startTimeUtc);
  if (!Number.isFinite(startMs) || startMs <= now.getTime()) throw new Error(`WORKER_REFUSES_POST_START_LOCK:${raceId}`);
  const remainingAtCommit = startMs - now.getTime();
  const generationStartedMs = Date.parse(String(snapshot.generationStartedAt || snapshot.generatedAt));
  if (finalizedFrom === "fresh") {
    if (!Number.isFinite(generationStartedMs) || startMs - generationStartedMs < DEADLINE_MS) throw new Error(`WORKER_FRESH_GENERATION_STARTED_AFTER_T15:${raceId}`);
    if (remainingAtCommit < FINAL_REFLECTION_DEADLINE_MS) throw new Error(`WORKER_FRESH_REFLECTION_CROSSED_T10:${raceId}`);
  } else if (remainingAtCommit < DEADLINE_MS) {
    throw new Error(`WORKER_NONFRESH_REFLECTION_CROSSED_T15:${raceId}`);
  }
  const existing = await publicBetRows(db, raceId);
  if (isStrictComplete(existing)) return;
  if (existing.length && existing.some((row) => Number(row.sourcePredictionId) !== -2 || row.settlementStatus !== "pending")) throw new Error(`WORKER_UNSAFE_PARTIAL_ROWS:${raceId}`);
  const lockedAt = iso(now);
  const hasBodyWeight = snapshotHasOfficialBodyWeight(snapshot);
  const bodyWeightSnapshot = hasBodyWeight ? snapshot.bodyWeightSnapshot as OfficialBodyWeightSnapshot : null;
  const statements: D1PreparedStatement[] = [];
  if (existing.length) statements.push(db.prepare("DELETE FROM rt_public_bets WHERE race_id=? AND source_prediction_id=-2 AND settlement_status='pending'").bind(raceId));
  statements.push(db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(`${FINAL_PREFIX}${raceId}`, JSON.stringify({
    status: "locked", raceId, lockedAt, finalizedFrom,
    generationStartedAt: snapshot.generationStartedAt ?? null,
    reflectionDeadlineMinutes: 10,
    sourceModel: COMPLETED_MODEL_VERSION, modelSha256: COMPLETED_MODEL_SHA256,
    previewGeneratedAt: snapshot.generatedAt,
    bodyWeightApplied: hasBodyWeight,
    bodyWeightFetchedAt: bodyWeightSnapshot?.fetchedAt ?? null,
    bodyWeightSource: bodyWeightSnapshot?.sourceUrl ?? null,
    bodyWeightSnapshotSha256: bodyWeightSnapshot?.snapshotSha256 ?? null,
    bodyWeights: bodyWeightSnapshot?.activeRunners ?? null,
    bodyWeightError: snapshot.bodyWeightError ?? null,
    oddsFetchedAt: snapshot.oddsFetchedAt, oddsSource: snapshot.oddsSource,
    oddsSnapshotSha256: snapshot.oddsSnapshotSha256,
    onlineLearning: snapshot.onlineLearning ?? null,
    runnerRecencyFactors: snapshot.runnerRecencyFactors ?? null,
    tickets: snapshot.tickets,
  })));
  for (const bet of snapshot.courseBets) {
    statements.push(db.prepare(`
      INSERT INTO rt_public_bets(race_id,course,bet_type,combination,stake_yen,assumed_odds,return_yen,settlement_status,locked_at,source_prediction_id)
      VALUES(?,?,?,?,?,?,NULL,'pending',?,-2)
    `).bind(raceId, bet.course, bet.betType, bet.combination, bet.stakeYen, Number(bet.assumedOdds.toFixed(6)), lockedAt));
  }
  await db.batch(statements);
  const saved = await publicBetRows(db, raceId);
  if (!isStrictComplete(saved)) throw new Error(`WORKER_POST_WRITE_GATE_FAILED:${raceId}`);
}
'''
t=t[:start]+new_commit+t[end:]
old=r'''      // T-15 is an assertion boundary, never a recovery window. New preview
      // generation or final creation is forbidden once the boundary is reached.
      if (remaining <= DEADLINE_MS) {
        errors.push({ raceId, error: `WORKER_HARD_T15_MISSED:${raceId}` });
        continue;
      }

      const existingPreview = await latestPreview(env.DB, raceId);
      if (remaining > FINAL_LOCK_ARM_MS && existingPreview && previewIsFreshEnough(existingPreview, remaining, raceNow)) {
        continue;
      }
      if (generatedThisTick >= 1 && remaining > FINAL_LOCK_ARM_MS) continue;

      let fresh: PreviewSnapshot | null = null;
      try {
        model ??= await loadWorkerModel(env.DB);
        fresh = await generatePreview(env.DB, model, raceId, new Date());
        generatedThisTick += 1;
        refreshedPreviewRaceIds.push(raceId);
        if (snapshotHasOfficialBodyWeight(fresh)) refreshedBodyWeightRaceIds.add(raceId);
        else bodyWeightPendingRaceIds.add(raceId);
      } catch (error) {
        errors.push({ raceId, error: errorText(error) });
      }

      // Normal finalization happens by T-25. If the newest fetch failed, use
      // the durable last-good official preview instead of waiting until T-15.
      const commitNow = new Date();
      const remainingAfterGeneration = startMs - commitNow.getTime();
      if (remainingAfterGeneration <= DEADLINE_MS) {
        errors.push({ raceId, error: `WORKER_GENERATION_CROSSED_T15:${raceId}` });
        continue;
      }
      if (remainingAfterGeneration <= FINAL_LOCK_ARM_MS) {
        const stored = fresh ?? await latestOfficialBodyWeightPreview(env.DB, raceId) ?? await latestPreview(env.DB, raceId);
        if (!stored) throw new Error(`WORKER_T25_PREVIEW_MISSING:${raceId}`);
        if (!snapshotHasOfficialBodyWeight(stored)) bodyWeightBreachRaceIds.add(raceId);
        await commitSnapshot(env.DB, raceId, stored, commitNow, fresh ? "fresh" : "last_good");
        lockedByWorker.push(raceId);
        if (fresh) finalizedFromFreshRaceIds.push(raceId);
        else finalizedFromFallbackRaceIds.push(raceId);
      }
'''
new=r'''      // T-15 is the generation-start boundary. No new calculation starts
      // after it. A fresh calculation that started on time may finish and be
      // reflected until the hard T-10 reflection boundary.
      if (remaining < DEADLINE_MS) {
        errors.push({ raceId, error: `WORKER_HARD_T15_START_MISSED:${raceId}` });
        continue;
      }
      const existingPreview = await latestPreview(env.DB, raceId);
      if (remaining > FINAL_LOCK_ARM_MS && existingPreview && previewIsFreshEnough(existingPreview, remaining, raceNow)) continue;
      if (generatedThisTick >= 1 && remaining > FINAL_LOCK_ARM_MS) continue;
      const generationStartedAt = new Date();
      let fresh: PreviewSnapshot | null = null;
      try {
        model ??= await loadWorkerModel(env.DB);
        fresh = await generatePreview(env.DB, model, raceId, generationStartedAt);
        generatedThisTick += 1;
        refreshedPreviewRaceIds.push(raceId);
        if (snapshotHasOfficialBodyWeight(fresh)) refreshedBodyWeightRaceIds.add(raceId); else bodyWeightPendingRaceIds.add(raceId);
      } catch (error) { errors.push({ raceId, error: errorText(error) }); }
      const commitNow = new Date();
      const remainingAfterGeneration = startMs - commitNow.getTime();
      if (remainingAfterGeneration < FINAL_REFLECTION_DEADLINE_MS) {
        errors.push({ raceId, error: `WORKER_GENERATION_CROSSED_T10:${raceId}` });
        continue;
      }
      if (!fresh && remainingAfterGeneration < DEADLINE_MS) {
        errors.push({ raceId, error: `WORKER_FALLBACK_CROSSED_T15:${raceId}` });
        continue;
      }
      if (remainingAfterGeneration <= FINAL_LOCK_ARM_MS) {
        const stored = fresh ?? await latestOfficialBodyWeightPreview(env.DB, raceId) ?? await latestPreview(env.DB, raceId);
        if (!stored) throw new Error(`WORKER_T17_PREVIEW_MISSING:${raceId}`);
        if (!snapshotHasOfficialBodyWeight(stored)) bodyWeightBreachRaceIds.add(raceId);
        await commitSnapshot(env.DB, raceId, stored, commitNow, fresh ? "fresh" : "last_good");
        lockedByWorker.push(raceId);
        if (fresh) finalizedFromFreshRaceIds.push(raceId); else finalizedFromFallbackRaceIds.push(raceId);
      }
'''
if old not in t: raise SystemExit('LIVE_FINALIZATION_BLOCK_NOT_FOUND')
t=t.replace(old,new,1)
t=t.replace('        if (remaining <= DEADLINE_MS) deadlineBreachRaceIds.add(raceId);', '        if (remaining < FINAL_REFLECTION_DEADLINE_MS) deadlineBreachRaceIds.add(raceId);', 1)
p.write_text(t,encoding='utf-8')

Path('src/v1/completed-final-invariants.ts').write_text(r'''type TriggerRow = { name: string; sql: string | null };
export async function ensureCompletedFinalImmutability(db: D1Database): Promise<void> {
  const deadlineRows = await db.prepare(`SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name IN ('rt_guard_final_bet_insert_deadline','rt_guard_final_state_insert_deadline')`).all<TriggerRow>();
  const triggerSql = new Map((deadlineRows.results ?? []).map((row) => [row.name, String(row.sql || '')]));
  const betWindowCurrent = triggerSql.get('rt_guard_final_bet_insert_deadline')?.includes('FINAL_BET_REFLECTION_WINDOW_PASSED') === true;
  const stateWindowCurrent = triggerSql.get('rt_guard_final_state_insert_deadline')?.includes('FINAL_STATE_REFLECTION_WINDOW_PASSED') === true;
  if (!betWindowCurrent || !stateWindowCurrent) {
    await db.batch([
      db.prepare('DROP TRIGGER IF EXISTS rt_guard_final_bet_insert_deadline'), db.prepare('DROP TRIGGER IF EXISTS rt_guard_final_state_insert_deadline'),
      db.prepare(`CREATE TRIGGER rt_guard_final_state_insert_deadline BEFORE INSERT ON rt_system_state
        WHEN NEW.state_key LIKE 'worker_live_final:%' AND json_extract(NEW.state_value, '$.status')='locked' AND (
          COALESCE((SELECT unixepoch(start_time_utc) FROM rt_races WHERE race_id=json_extract(NEW.state_value,'$.raceId') LIMIT 1),0) < unixepoch('now')+600
          OR (COALESCE((SELECT unixepoch(start_time_utc) FROM rt_races WHERE race_id=json_extract(NEW.state_value,'$.raceId') LIMIT 1),0) < unixepoch('now')+900
            AND NOT (json_extract(NEW.state_value,'$.finalizedFrom')='fresh' AND unixepoch(json_extract(NEW.state_value,'$.generationStartedAt')) IS NOT NULL
              AND unixepoch(json_extract(NEW.state_value,'$.generationStartedAt')) <= COALESCE((SELECT unixepoch(start_time_utc)-900 FROM rt_races WHERE race_id=json_extract(NEW.state_value,'$.raceId') LIMIT 1),0))))
        BEGIN SELECT RAISE(ABORT,'FINAL_STATE_REFLECTION_WINDOW_PASSED'); END`),
      db.prepare(`CREATE TRIGGER rt_guard_final_bet_insert_deadline BEFORE INSERT ON rt_public_bets
        WHEN NEW.source_prediction_id=-2 AND (
          COALESCE((SELECT unixepoch(start_time_utc) FROM rt_races WHERE race_id=NEW.race_id LIMIT 1),0) < unixepoch('now')+600
          OR (COALESCE((SELECT unixepoch(start_time_utc) FROM rt_races WHERE race_id=NEW.race_id LIMIT 1),0) < unixepoch('now')+900
            AND NOT EXISTS (SELECT 1 FROM rt_system_state s WHERE s.state_key='worker_live_final:'||NEW.race_id
              AND json_extract(s.state_value,'$.status')='locked' AND json_extract(s.state_value,'$.finalizedFrom')='fresh'
              AND unixepoch(json_extract(s.state_value,'$.generationStartedAt')) IS NOT NULL
              AND unixepoch(json_extract(s.state_value,'$.generationStartedAt')) <= COALESCE((SELECT unixepoch(start_time_utc)-900 FROM rt_races WHERE race_id=NEW.race_id LIMIT 1),0))))
        BEGIN SELECT RAISE(ABORT,'FINAL_BET_REFLECTION_WINDOW_PASSED'); END`),
    ]);
  }
  await db.batch([
    db.prepare(`CREATE TRIGGER IF NOT EXISTS rt_guard_locked_public_bet_terms BEFORE UPDATE OF course,bet_type,combination,stake_yen,assumed_odds,locked_at,source_prediction_id ON rt_public_bets WHEN OLD.source_prediction_id=-2 BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FINAL_BET_TERMS'); END`),
    db.prepare(`CREATE TRIGGER IF NOT EXISTS rt_guard_locked_worker_final_state BEFORE UPDATE ON rt_system_state WHEN OLD.state_key LIKE 'worker_live_final:%' AND json_extract(OLD.state_value,'$.status')='locked' BEGIN SELECT RAISE(ABORT,'IMMUTABLE_WORKER_FINAL_STATE'); END`),
    db.prepare(`CREATE TRIGGER IF NOT EXISTS rt_guard_probability_fallback_final_insert BEFORE INSERT ON rt_system_state WHEN NEW.state_key LIKE 'worker_live_final:%' AND json_extract(NEW.state_value,'$.oddsMode')='probability_fallback' BEGIN SELECT RAISE(ABORT,'PROBABILITY_FALLBACK_FORBIDDEN'); END`),
    db.prepare(`CREATE TRIGGER IF NOT EXISTS rt_guard_probability_fallback_final_update BEFORE UPDATE ON rt_system_state WHEN NEW.state_key LIKE 'worker_live_final:%' AND json_extract(NEW.state_value,'$.oddsMode')='probability_fallback' BEGIN SELECT RAISE(ABORT,'PROBABILITY_FALLBACK_FORBIDDEN'); END`),
    db.prepare(`CREATE TRIGGER IF NOT EXISTS rt_guard_official_odds_final_insert BEFORE INSERT ON rt_system_state WHEN NEW.state_key LIKE 'worker_live_final:%' AND json_extract(NEW.state_value,'$.status')='locked' AND COALESCE(json_extract(NEW.state_value,'$.oddsSource'),'') NOT IN ('jra-fast-official','jra-crawl-official') BEGIN SELECT RAISE(ABORT,'OFFICIAL_JRA_ODDS_REQUIRED'); END`),
    db.prepare(`CREATE TRIGGER IF NOT EXISTS rt_guard_official_odds_final_update BEFORE UPDATE ON rt_system_state WHEN NEW.state_key LIKE 'worker_live_final:%' AND json_extract(NEW.state_value,'$.status')='locked' AND COALESCE(json_extract(NEW.state_value,'$.oddsSource'),'') NOT IN ('jra-fast-official','jra-crawl-official') BEGIN SELECT RAISE(ABORT,'OFFICIAL_JRA_ODDS_REQUIRED'); END`),
  ]);
}
''', encoding='utf-8')

p=Path('src/v1/completed-worker-deadline-guard.ts'); t=p.read_text(encoding='utf-8')
t=t.replace('export const DEADLINE_GUARD_ARM_MS = 16 * 60 * 1000;\n', 'export const DEADLINE_GUARD_ARM_MS = 16 * 60 * 1000;\nexport const FINAL_REFLECTION_DEADLINE_MS = 10 * 60 * 1000;\n', 1)
t=t.replace('    && remainingMs < DEADLINE_GUARD_MS;', '    && remainingMs < FINAL_REFLECTION_DEADLINE_MS;', 1); p.write_text(t,encoding='utf-8')

p=Path('src/v1/live-preview-safety.ts'); t=p.read_text(encoding='utf-8')
t=t.replace('    if (remaining > 0 && remaining < 15 * 60_000 && !finalReady) audit.deadlineMissedRaceIds.push(raceId);', '    if (remaining > 0 && remaining < 10 * 60_000 && !finalReady) audit.deadlineMissedRaceIds.push(raceId);', 1); p.write_text(t,encoding='utf-8')

p=Path('src/live-deadline-entry-v2.ts'); t=p.read_text(encoding='utf-8')
t=t.replace('live-deadline-v5-t15-optimal-refresh-20260823', 'live-deadline-v6-t15-start-t10-reflect-20260823').replace('LIVE_DEADLINE_HARD_T15_BREACH','LIVE_DEADLINE_HARD_T10_REFLECTION_BREACH'); p.write_text(t,encoding='utf-8')

p=Path('tests/completed-worker-deadline-guard-tests.ts'); t=p.read_text(encoding='utf-8')
t=t.replace('  DEADLINE_GUARD_MS,\n', '  DEADLINE_GUARD_MS,\n  FINAL_REFLECTION_DEADLINE_MS,\n', 1)
t=t.replace('assert.equal(DEADLINE_GUARD_ARM_MS, 16 * 60 * 1000, "rescue guard arms one minute before the hard T-15 boundary");', 'assert.equal(DEADLINE_GUARD_ARM_MS, 16 * 60 * 1000, "rescue guard arms before T-15");\nassert.equal(FINAL_REFLECTION_DEADLINE_MS, 10 * 60 * 1000);')
t=t.replace('assert.equal(isDeadlineGuardMissed(15 * 60 * 1000), false, "exactly T-15 is still on time");\nassert.equal(isDeadlineGuardMissed(15 * 60 * 1000 - 1), true, "one millisecond past T-15 is a hard miss");\nassert.equal(isDeadlineGuardMissed(14 * 60 * 1000), true);', 'assert.equal(isDeadlineGuardMissed(15 * 60 * 1000), false);\nassert.equal(isDeadlineGuardMissed(14 * 60 * 1000), false);\nassert.equal(isDeadlineGuardMissed(10 * 60 * 1000), false);\nassert.equal(isDeadlineGuardMissed(10 * 60 * 1000 - 1), true);'); p.write_text(t,encoding='utf-8')

p=Path('scripts/verify-live-lock-safety.py'); t=p.read_text(encoding='utf-8')
t=t.replace("        'const DEADLINE_MS = 15 * 60 * 1000;',\n", "        'const DEADLINE_MS = 15 * 60 * 1000;',\n        'const FINAL_REFLECTION_DEADLINE_MS = 10 * 60 * 1000;',\n", 1)
t=t.replace("        'WORKER_HARD_T15_MISSED',\n        'WORKER_GENERATION_CROSSED_T15',", "        'WORKER_HARD_T15_START_MISSED',\n        'WORKER_GENERATION_CROSSED_T10',")
t=t.replace('        "FINAL_BET_DEADLINE_PASSED",\n        "FINAL_STATE_DEADLINE_PASSED",', '        "FINAL_BET_REFLECTION_WINDOW_PASSED",\n        "FINAL_STATE_REFLECTION_WINDOW_PASSED",')
t=t.replace('        "LIVE_DEADLINE_HARD_T15_BREACH",', '        "LIVE_DEADLINE_HARD_T10_REFLECTION_BREACH",')
t=t.replace('        "deadline=15m_hard",', '        "generation_start_deadline=15m_hard",\n        "fresh_reflection_deadline=10m_hard",')
p.write_text(t,encoding='utf-8')
