from pathlib import Path

path = Path("src/live-deadline-entry-v2.ts")
text = path.read_text()

old = 'import { runCompletedWorkerLiveLock } from "./v1/completed-worker-live-lock.js";\n'
new = old + 'import { runUpcomingEntryDerivedRepair } from "./v1/upcoming-entry-derived-repair.js";\n'
assert old in text and 'runUpcomingEntryDerivedRepair' not in text, "entry repair import changed unexpectedly"
text = text.replace(old, new, 1)

old = '''    const selectionNow = new Date();
    const selection = await freezeCompletedWorkerSelectionIfNeeded(env, selectionNow);
    const selectionReady = await hasSelection(env.DB, jstDate(selectionNow));
    if (!selectionReady) {
      const completed = new Date();
      const result = {
        ...base,
        status: "waiting_selection",
        phase: "complete",
        ok: true,
        selection,
        selectionCheckedAt: iso(selectionNow),
        completedAt: iso(completed),
        durationMs: completed.getTime() - started.getTime(),
      };
      await saveDriverState(env.DB, date, result);
      return result;
    }
'''
new = '''    const selectionNow = new Date();
    let selection = await freezeCompletedWorkerSelectionIfNeeded(env, selectionNow);
    let selectionReady = await hasSelection(env.DB, jstDate(selectionNow));
    let entryRepair: Record<string, unknown> | null = null;
    if (!selectionReady && String(selection.status || "") === "waiting_complete_program") {
      entryRepair = await runUpcomingEntryDerivedRepair(env, new Date()) as unknown as Record<string, unknown>;
      selection = await freezeCompletedWorkerSelectionIfNeeded(env, new Date());
      selectionReady = await hasSelection(env.DB, jstDate(new Date()));
    }
    if (!selectionReady) {
      const firstRace = await env.DB.prepare("SELECT MIN(start_time_utc) AS firstStart FROM rt_races WHERE race_date=? AND start_time_utc IS NOT NULL")
        .bind(date).first<{ firstStart: string | null }>();
      const firstStartMs = Date.parse(String(firstRace?.firstStart || ""));
      const remainingToFirstRaceMs = Number.isFinite(firstStartMs) ? firstStartMs - Date.now() : Number.NaN;
      const selectionCritical = Number.isFinite(remainingToFirstRaceMs) && remainingToFirstRaceMs <= 100 * 60_000;
      const completed = new Date();
      const result = {
        ...base,
        status: selectionCritical ? "selection_critical" : "waiting_selection",
        phase: "complete",
        ok: !selectionCritical,
        selection,
        entryRepair,
        selectionCheckedAt: iso(selectionNow),
        remainingToFirstRaceMs,
        completedAt: iso(completed),
        durationMs: completed.getTime() - started.getTime(),
      };
      await saveDriverState(env.DB, date, result);
      if (selectionCritical) throw new Error(`LIVE_DEADLINE_SELECTION_CRITICAL:${date}:${remainingToFirstRaceMs}`);
      return result;
    }
'''
assert old in text, "selection block changed unexpectedly"
text = text.replace(old, new, 1)

path.write_text(text)
print("round3 selection readiness hardening applied")
