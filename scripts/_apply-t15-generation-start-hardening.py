from pathlib import Path

path = Path("src/v1/completed-worker-live-lock.ts")
text = path.read_text(encoding="utf-8")
old = '''      const generationStartedAt = new Date();
      let fresh: PreviewSnapshot | null = null;
'''
new = '''      const generationStartedAt = new Date();
      const remainingAtGenerationStart = startMs - generationStartedAt.getTime();
      if (remainingAtGenerationStart <= DEADLINE_MS) {
        errors.push({ raceId, error: `WORKER_FRESH_GENERATION_STARTED_AFTER_T15:${raceId}` });
        continue;
      }
      let fresh: PreviewSnapshot | null = null;
'''
if text.count(old) != 1:
    raise SystemExit(f"unexpected target count: {text.count(old)}")
path.write_text(text.replace(old, new), encoding="utf-8")
