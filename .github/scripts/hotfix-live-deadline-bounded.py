from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    s = p.read_text()
    if new in s:
        return
    if old not in s:
        raise SystemExit(f"pattern not found: {path}: {old[:120]!r}")
    p.write_text(s.replace(old, new, 1))


p = "src/v1/completed-worker-live-lock.ts"
replace_once(p, "const NEAR_PREVIEW_REFRESH_MS = 45 * 1000;", "const NEAR_PREVIEW_REFRESH_MS = 4 * 60 * 1000;")
replace_once(
    p,
    '''  const ids = await orderLiveRaceIdsByStart(env.DB, date, validateSelection(selection));
  const beforeStates = await Promise.all(ids.map(async (raceId) => isStrictComplete(await publicBetRows(env.DB, raceId))));
  const completeBefore = beforeStates.filter(Boolean).length;''',
    '''  const selectedIds = await orderLiveRaceIdsByStart(env.DB, date, validateSelection(selection));
  const activeResult = await env.DB.prepare(`
    SELECT race_id AS raceId FROM rt_races
    WHERE race_date=? AND start_time_utc>? AND start_time_utc<=?
  `).bind(date, iso(now), iso(new Date(now.getTime() + BODY_WEIGHT_REFRESH_OPEN_MS))).all<{ raceId: string }>();
  const activeSet = new Set((activeResult.results ?? []).map((row) => String(row.raceId)));
  const ids = selectedIds.filter((raceId) => activeSet.has(raceId));
  const beforeStates = await Promise.all(ids.map(async (raceId) => isStrictComplete(await publicBetRows(env.DB, raceId))));
  const completeBefore = beforeStates.filter(Boolean).length;''',
)
replace_once(
    p,
    '''  const errors: Array<{ raceId: string; error: string }> = [];
  let model: CompletedModelRuntime | null = null;

  for (const raceId of ids) {''',
    '''  const errors: Array<{ raceId: string; error: string }> = [];
  let model: CompletedModelRuntime | null = null;
  let generatedThisTick = 0;

  for (const raceId of ids) {''',
)
replace_once(
    p,
    '''      const existingPreview = await latestPreview(env.DB, raceId);
      if (remaining > NORMAL_LOCK_MS && existingPreview && previewIsFreshEnough(existingPreview, remaining, raceNow)) {
        continue;
      }

      let fresh: PreviewSnapshot | null = null;
      try {
        model ??= await loadWorkerModel(env.DB);
        fresh = await generatePreview(env.DB, model, raceId, new Date());
        refreshedPreviewRaceIds.push(raceId);''',
    '''      const existingPreview = await latestPreview(env.DB, raceId);
      if (remaining > NORMAL_LOCK_MS && existingPreview && previewIsFreshEnough(existingPreview, remaining, raceNow)) {
        continue;
      }
      if (remaining <= NORMAL_LOCK_MS && existingPreview) {
        const commitNow = new Date();
        if (startMs - commitNow.getTime() <= DEADLINE_MS) {
          errors.push({ raceId, error: `WORKER_STORED_PREVIEW_COMMIT_CROSSED_T15:${raceId}` });
          continue;
        }
        if (!snapshotHasOfficialBodyWeight(existingPreview)) bodyWeightBreachRaceIds.add(raceId);
        await commitSnapshot(env.DB, raceId, existingPreview, commitNow, "last_good");
        lockedByWorker.push(raceId);
        finalizedFromFallbackRaceIds.push(raceId);
        continue;
      }
      if (generatedThisTick >= 1 && remaining > NORMAL_LOCK_MS) continue;

      let fresh: PreviewSnapshot | null = null;
      try {
        model ??= await loadWorkerModel(env.DB);
        fresh = await generatePreview(env.DB, model, raceId, new Date());
        generatedThisTick += 1;
        refreshedPreviewRaceIds.push(raceId);''',
)
replace_once(p, "    selectedRaceCount: ids.length,", "    selectedRaceCount: selectedIds.length,")

p = "src/live-deadline-entry-v2.ts"
replace_once(p, 'const DRIVER_VERSION = "live-deadline-v3-priority-guard-20260823";', 'const DRIVER_VERSION = "live-deadline-v4-bounded-subrequests-20260823";')
replace_once(
    p,
    '''    const selectionNow = new Date();
    let selection = await freezeCompletedWorkerSelectionIfNeeded(env, selectionNow);
    let selectionReady = await hasSelection(env.DB, jstDate(selectionNow));
    let entryRepair: Record<string, unknown> | null = null;
    if (!selectionReady && String(selection.status || "") === "waiting_complete_program") {
      entryRepair = await runUpcomingEntryDerivedRepair(env, new Date()) as unknown as Record<string, unknown>;
      selection = await freezeCompletedWorkerSelectionIfNeeded(env, new Date());
      selectionReady = await hasSelection(env.DB, jstDate(new Date()));
    }''',
    '''    const selectionNow = new Date();
    let selectionReady = await hasSelection(env.DB, jstDate(selectionNow));
    let selection: Record<string, unknown> = { status: "already_frozen" };
    let entryRepair: Record<string, unknown> | null = null;
    if (!selectionReady) {
      selection = await freezeCompletedWorkerSelectionIfNeeded(env, selectionNow) as unknown as Record<string, unknown>;
      selectionReady = await hasSelection(env.DB, jstDate(selectionNow));
      if (!selectionReady && String(selection.status || "") === "waiting_complete_program") {
        entryRepair = await runUpcomingEntryDerivedRepair(env, new Date()) as unknown as Record<string, unknown>;
        selection = await freezeCompletedWorkerSelectionIfNeeded(env, new Date()) as unknown as Record<string, unknown>;
        selectionReady = await hasSelection(env.DB, jstDate(new Date()));
      }
    }''',
)
replace_once(
    p,
    '''    const restoredBefore = await restoreNewestOfficialPreviewArchives(env.DB, date);
    const slaBefore = await auditLiveDeadlineSla(env.DB, date, new Date());

    const guardBeforeNow = new Date();
    const guardBefore = await runCompletedWorkerDeadlineGuard(env, guardBeforeNow);''',
    '''    let restoredBefore: string[] = [];
    if (priorityGuard.errors.some((row) => row.error.includes("PREVIEW_MISSING"))) {
      restoredBefore = await restoreNewestOfficialPreviewArchives(env.DB, date);
    }
    const slaBefore = null;
    const guardBeforeNow = priorityGuardNow;
    const guardBefore = priorityGuard;''',
)
replace_once(
    p,
    '''    const restoredAfter = await restoreNewestOfficialPreviewArchives(env.DB, date);
    const guardAfterNow = new Date();
    const guardAfter = await runCompletedWorkerDeadlineGuard(env, guardAfterNow);
    const slaAfter = await auditLiveDeadlineSla(env.DB, date, new Date());''',
    '''    let restoredAfter: string[] = [];
    let guardAfterNow = new Date();
    let guardAfter = await runCompletedWorkerDeadlineGuard(env, guardAfterNow);
    if (guardAfter.errors.some((row) => row.error.includes("PREVIEW_MISSING"))) {
      restoredAfter = await restoreNewestOfficialPreviewArchives(env.DB, date);
      guardAfterNow = new Date();
      guardAfter = await runCompletedWorkerDeadlineGuard(env, guardAfterNow);
    }
    const slaAfter = await auditLiveDeadlineSla(env.DB, date, new Date());''',
)
