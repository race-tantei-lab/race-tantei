from pathlib import Path

path = Path("src/v1/completed-worker-live-lock.ts")
text = path.read_text()

old = '''const PREVIEW_REQUIRED_MS = 30 * 60 * 1000;
const NORMAL_LOCK_MS = 25 * 60 * 1000;
const DEADLINE_MS = 15 * 60 * 1000;'''
new = '''const PREVIEW_REQUIRED_MS = 30 * 60 * 1000;
const NORMAL_LOCK_MS = 25 * 60 * 1000;
const DEADLINE_MS = 15 * 60 * 1000;
const EARLY_PREVIEW_REFRESH_MS = 10 * 60 * 1000;
const MID_PREVIEW_REFRESH_MS = 5 * 60 * 1000;
const NEAR_PREVIEW_REFRESH_MS = 45 * 1000;'''
assert old in text, "preview timing constants changed unexpectedly"
text = text.replace(old, new, 1)

marker = '''async function latestOfficialBodyWeightPreview(db: D1Database, raceId: string): Promise<PreviewSnapshot | null> {
  return (await loadPreviewEnvelope(db, raceId))?.snapshots.find(snapshotHasOfficialBodyWeight) ?? null;
}
'''
insert = marker + '''
function previewRefreshIntervalMs(remainingMs: number): number {
  if (remainingMs > 45 * 60_000) return EARLY_PREVIEW_REFRESH_MS;
  if (remainingMs > 30 * 60_000) return MID_PREVIEW_REFRESH_MS;
  return NEAR_PREVIEW_REFRESH_MS;
}

function previewIsFreshEnough(snapshot: PreviewSnapshot, remainingMs: number, now: Date): boolean {
  const generatedMs = Date.parse(snapshot.generatedAt);
  if (!Number.isFinite(generatedMs)) return false;
  return now.getTime() - generatedMs < previewRefreshIntervalMs(remainingMs);
}
'''
assert marker in text and 'previewRefreshIntervalMs' not in text, "preview helper insertion point changed unexpectedly"
text = text.replace(marker, insert, 1)

old = '''      let fresh: PreviewSnapshot | null = null;
      try {
        model ??= await loadWorkerModel(env.DB);'''
new = '''      const existingPreview = await latestPreview(env.DB, raceId);
      if (remaining > NORMAL_LOCK_MS && existingPreview && previewIsFreshEnough(existingPreview, remaining, raceNow)) {
        continue;
      }

      let fresh: PreviewSnapshot | null = null;
      try {
        model ??= await loadWorkerModel(env.DB);'''
assert old in text, "preview generation block changed unexpectedly"
text = text.replace(old, new, 1)

path.write_text(text)
print("round3 preview refresh cadence hardening applied")
