from pathlib import Path

path = Path("src/live-deadline-entry-v2.ts")
text = path.read_text()

old = 'const DRIVER_STATE_PREFIX = "live_deadline_driver:";\nconst SELECTION_PREFIX = "final_daily_selection:";'
new = 'const DRIVER_STATE_PREFIX = "live_deadline_driver:";\nconst LEASE_SKIP_PREFIX = "live_deadline_lease_skip:";\nconst SELECTION_PREFIX = "final_daily_selection:";'
assert old in text, "driver constants changed unexpectedly"
text = text.replace(old, new, 1)

old = '''async function saveDriverState(db: D1Database, date: string, payload: Record<string, unknown>): Promise<void> {
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at)
    VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(`${DRIVER_STATE_PREFIX}${date}`, JSON.stringify(payload)).run();
}
'''
new = old + '''
async function saveLeaseSkipState(db: D1Database, date: string, payload: Record<string, unknown>): Promise<void> {
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at)
    VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(`${LEASE_SKIP_PREFIX}${date}`, JSON.stringify(payload)).run();
}
'''
assert old in text and 'saveLeaseSkipState' not in text, "driver state helper changed unexpectedly"
text = text.replace(old, new, 1)

old = '''    await saveDriverState(env.DB, date, skipped);
    return skipped;'''
new = '''    await saveLeaseSkipState(env.DB, date, skipped);
    return skipped;'''
assert old in text, "lease busy write changed unexpectedly"
text = text.replace(old, new, 1)

old = '''  } catch (error) {
    const completed = new Date();
    const failure = {
      ...base,
      status: "error",
      phase: "failed",
      ok: false,
      error: errorText(error),
      completedAt: iso(completed),
      durationMs: completed.getTime() - started.getTime(),
    };
    try { await saveDriverState(env.DB, date, failure); }
    catch (auditError) { console.error("LIVE_DEADLINE_AUDIT_WRITE_FAILED", auditError); }
    throw error;
  } finally {'''
new = '''  } catch (error) {
    const completed = new Date();
    let previousState: unknown = null;
    try {
      const row = await env.DB.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
        .bind(`${DRIVER_STATE_PREFIX}${date}`).first<{ value: string }>();
      previousState = row?.value ? JSON.parse(row.value) : null;
    } catch { /* preserve the primary failure even if audit recovery fails */ }
    const failure = {
      ...base,
      status: "error",
      phase: "failed",
      ok: false,
      error: errorText(error),
      previousState,
      completedAt: iso(completed),
      durationMs: completed.getTime() - started.getTime(),
    };
    try { await saveDriverState(env.DB, date, failure); }
    catch (auditError) { console.error("LIVE_DEADLINE_AUDIT_WRITE_FAILED", auditError); }
    throw error;
  } finally {'''
assert old in text, "driver catch block changed unexpectedly"
text = text.replace(old, new, 1)

path.write_text(text)
print("round3 driver audit hardening applied")
