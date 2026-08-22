from pathlib import Path
import re

path = Path("src/v1/completed-worker-live-lock.ts")
text = path.read_text()
original = text

old_constants = '''const BODY_WEIGHT_REFRESH_OPEN_MS = 80 * 60 * 1000;
const PREVIEW_OPEN_MS = 45 * 60 * 1000;
const DEADLINE_MS = 15 * 60 * 1000;
const PREVIEW_HISTORY = 3;
const PREVIEW_VERSION = 1;
const COURSES = Object.keys(COMPLETED_COURSE_STAKES) as Array<keyof typeof COMPLETED_COURSE_STAKES>;'''
new_constants = '''const BODY_WEIGHT_REFRESH_OPEN_MS = 100 * 60 * 1000;
const PREVIEW_OPEN_MS = 90 * 60 * 1000;
const PREVIEW_REQUIRED_MS = 30 * 60 * 1000;
const NORMAL_LOCK_MS = 25 * 60 * 1000;
const DEADLINE_MS = 15 * 60 * 1000;
const PREVIEW_HISTORY = 3;
const PREVIEW_VERSION = 1;
const OFFICIAL_ODDS_SOURCES = new Set(["jra-fast-official", "jra-crawl-official"]);
const COURSES = Object.keys(COMPLETED_COURSE_STAKES) as Array<keyof typeof COMPLETED_COURSE_STAKES>;'''
assert old_constants in text, "constants block changed unexpectedly"
text = text.replace(old_constants, new_constants, 1)

old_audit = '''  previewAvailableRaceIds: string[];
  finalizedFromFreshRaceIds: string[];'''
new_audit = '''  previewAvailableRaceIds: string[];
  previewMissingUrgentRaceIds: string[];
  finalizedFromFreshRaceIds: string[];'''
assert old_audit in text, "audit type block changed unexpectedly"
text = text.replace(old_audit, new_audit, 1)

old_model_decl = '''async function loadWorkerModel(db: D1Database): Promise<CompletedModelRuntime> {'''
new_model_decl = '''let cachedWorkerModel: { identity: string; runtime: CompletedModelRuntime } | null = null;

async function loadWorkerModel(db: D1Database): Promise<CompletedModelRuntime> {'''
assert old_model_decl in text, "model loader declaration changed unexpectedly"
text = text.replace(old_model_decl, new_model_decl, 1)

old_generation = '''  const generation = meta.get("generation") || "";
  const chunkCount = Number(meta.get("chunkCount") || 0);
  const byteLength = Number(meta.get("byteLength") || 0);
  if (!generation || !Number.isInteger(chunkCount) || chunkCount <= 0 || !Number.isInteger(byteLength) || byteLength <= 0) {
    throw new Error("WORKER_MODEL_META_INVALID");
  }
  const chunkResult = await db.prepare("SELECT seq,data_b64 AS dataB64 FROM rt_ml_model_chunk WHERE generation=? ORDER BY seq").bind(generation).all<ModelChunkRow>();'''
new_generation = '''  const generation = meta.get("generation") || "";
  const chunkCount = Number(meta.get("chunkCount") || 0);
  const byteLength = Number(meta.get("byteLength") || 0);
  if (!generation || !Number.isInteger(chunkCount) || chunkCount <= 0 || !Number.isInteger(byteLength) || byteLength <= 0) {
    throw new Error("WORKER_MODEL_META_INVALID");
  }
  const identity = `${generation}:${COMPLETED_MODEL_SHA256}:${byteLength}:${chunkCount}`;
  if (cachedWorkerModel?.identity === identity) return cachedWorkerModel.runtime;
  const chunkResult = await db.prepare("SELECT seq,data_b64 AS dataB64 FROM rt_ml_model_chunk WHERE generation=? ORDER BY seq").bind(generation).all<ModelChunkRow>();'''
assert old_generation in text, "model generation block changed unexpectedly"
text = text.replace(old_generation, new_generation, 1)

old_model_return = '''  return loadCompletedModelRuntime(merged.buffer);
}'''
new_model_return = '''  const runtime = loadCompletedModelRuntime(merged.buffer);
  cachedWorkerModel = { identity, runtime };
  return runtime;
}'''
assert old_model_return in text, "model return block changed unexpectedly"
text = text.replace(old_model_return, new_model_return, 1)

old_source_check = '''  if (!snapshot.oddsSource || !/^[0-9a-f]{64}$/.test(snapshot.oddsSnapshotSha256)) return false;'''
new_source_check = '''  if (!OFFICIAL_ODDS_SOURCES.has(snapshot.oddsSource) || !/^[0-9a-f]{64}$/.test(snapshot.oddsSnapshotSha256)) return false;'''
assert old_source_check in text, "preview source validation changed unexpectedly"
text = text.replace(old_source_check, new_source_check, 1)

old_empty = '''    refreshedPreviewRaceIds: [],
    previewAvailableRaceIds: [],
    finalizedFromFreshRaceIds: [],'''
new_empty = '''    refreshedPreviewRaceIds: [],
    previewAvailableRaceIds: [],
    previewMissingUrgentRaceIds: [],
    finalizedFromFreshRaceIds: [],'''
assert old_empty in text, "empty audit block changed unexpectedly"
text = text.replace(old_empty, new_empty, 1)

loop_pattern = re.compile(r'''  for \(const raceId of ids\) \{\n    const existing = await publicBetRows\(env\.DB, raceId\);\n    if \(isStrictComplete\(existing\)\) continue;\n    try \{.*?\n  \}\n\n  const previewAvailableRaceIds: string\[\] = \[\];''', re.S)
loop_match = loop_pattern.search(text)
assert loop_match, "live race loop not found"
new_loop = '''  for (const raceId of ids) {
    const existing = await publicBetRows(env.DB, raceId);
    if (isStrictComplete(existing)) continue;
    try {
      const { race } = await loadRace(env.DB, raceId);
      if (!race.startTimeUtc) throw new Error(`WORKER_START_TIME_MISSING:${raceId}`);
      const startMs = Date.parse(race.startTimeUtc);
      const raceNow = new Date();
      const remaining = startMs - raceNow.getTime();
      if (remaining <= 0) { alreadyStartedIncompleteRaceIds.push(raceId); continue; }
      if (remaining > BODY_WEIGHT_REFRESH_OPEN_MS) { notYetInWindowRaceIds.push(raceId); continue; }

      // From T-100 to T-90 we only refresh official body weight data. From
      // T-90 onward we repeatedly generate official-JRA-odds previews, so one
      // transient JRA/cron failure cannot leave us with no last-good snapshot.
      if (remaining > PREVIEW_OPEN_MS) {
        try {
          await refreshOfficialBodyWeights(env.DB, race, raceNow);
          refreshedBodyWeightRaceIds.add(raceId);
        } catch {
          bodyWeightPendingRaceIds.add(raceId);
        }
        continue;
      }

      // T-15 is an assertion boundary, never a recovery window. New preview
      // generation or final creation is forbidden once the boundary is reached.
      if (remaining <= DEADLINE_MS) {
        errors.push({ raceId, error: `WORKER_HARD_T15_MISSED:${raceId}` });
        continue;
      }

      let fresh: PreviewSnapshot | null = null;
      try {
        model ??= await loadWorkerModel(env.DB);
        fresh = await generatePreview(env.DB, model, raceId, new Date());
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
      if (remainingAfterGeneration <= NORMAL_LOCK_MS) {
        const stored = fresh ?? await latestOfficialBodyWeightPreview(env.DB, raceId) ?? await latestPreview(env.DB, raceId);
        if (!stored) throw new Error(`WORKER_T25_PREVIEW_MISSING:${raceId}`);
        if (!snapshotHasOfficialBodyWeight(stored)) bodyWeightBreachRaceIds.add(raceId);
        await commitSnapshot(env.DB, raceId, stored, commitNow, fresh ? "fresh" : "last_good");
        lockedByWorker.push(raceId);
        if (fresh) finalizedFromFreshRaceIds.push(raceId);
        else finalizedFromFallbackRaceIds.push(raceId);
      }
    } catch (error) {
      errors.push({ raceId, error: errorText(error) });
    }
  }

  const previewAvailableRaceIds: string[] = [];'''
text = text[:loop_match.start()] + new_loop + text[loop_match.end():]

old_second_decl = '''  const previewAvailableRaceIds: string[] = [];
  const protectedRaceIds: string[] = [];'''
new_second_decl = '''  const previewAvailableRaceIds: string[] = [];
  const previewMissingUrgentRaceIds: string[] = [];
  const protectedRaceIds: string[] = [];'''
assert old_second_decl in text, "post-loop audit declarations changed unexpectedly"
text = text.replace(old_second_decl, new_second_decl, 1)

old_preview_audit = '''    const preview = await latestPreview(env.DB, raceId);
    if (preview) {
      previewAvailableRaceIds.push(raceId);
      protectedRaceIds.push(raceId);
    }
    try {
      const { race } = await loadRace(env.DB, raceId);
      if (race.startTimeUtc) {
        const remaining = Date.parse(race.startTimeUtc) - now.getTime();
        if (remaining <= DEADLINE_MS) deadlineBreachRaceIds.add(raceId);
      }
    } catch {
      deadlineBreachRaceIds.add(raceId);
    }'''
new_preview_audit = '''    const preview = await latestPreview(env.DB, raceId);
    if (preview) {
      previewAvailableRaceIds.push(raceId);
      protectedRaceIds.push(raceId);
    }
    try {
      const { race } = await loadRace(env.DB, raceId);
      if (race.startTimeUtc) {
        const remaining = Date.parse(race.startTimeUtc) - Date.now();
        if (!preview && remaining > DEADLINE_MS && remaining <= PREVIEW_REQUIRED_MS) previewMissingUrgentRaceIds.push(raceId);
        if (remaining <= DEADLINE_MS) deadlineBreachRaceIds.add(raceId);
      }
    } catch {
      deadlineBreachRaceIds.add(raceId);
    }'''
assert old_preview_audit in text, "post-loop preview audit block changed unexpectedly"
text = text.replace(old_preview_audit, new_preview_audit, 1)

old_status = '''    status: breaches.length ? "deadline_breach" : bodyWeightBreaches.length ? "body_weight_breach" : errors.length ? "retrying" : "ok",'''
new_status = '''    status: breaches.length ? "deadline_breach" : previewMissingUrgentRaceIds.length ? "preview_critical" : bodyWeightBreaches.length ? "body_weight_breach" : errors.length ? "retrying" : "ok",'''
assert old_status in text, "audit status line changed unexpectedly"
text = text.replace(old_status, new_status, 1)

old_payload = '''    refreshedPreviewRaceIds,
    previewAvailableRaceIds,
    finalizedFromFreshRaceIds,'''
new_payload = '''    refreshedPreviewRaceIds,
    previewAvailableRaceIds,
    previewMissingUrgentRaceIds,
    finalizedFromFreshRaceIds,'''
assert old_payload in text, "audit payload block changed unexpectedly"
text = text.replace(old_payload, new_payload, 1)

assert text != original, "no live-lock hardening changes produced"
path.write_text(text)
print("round3 live-lock hardening applied")
