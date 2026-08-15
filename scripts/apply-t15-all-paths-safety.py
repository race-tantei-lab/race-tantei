from pathlib import Path


def replace_once(path, old, new):
    p=Path(path); text=p.read_text(encoding='utf-8')
    count=text.count(old)
    if count!=1:
        raise RuntimeError(f'{path}: expected one match, got {count}: {old!r}')
    p.write_text(text.replace(old,new,1),encoding='utf-8')
    print('patched',path)

replace_once('scripts/run-ten-year-auto-final-live.py',
"    base.MIN_LOCK_SECONDS=15*60\n    base.MAX_LOCK_SECONDS=16*60",
"    # Never pre-empt T-15. Worker is primary at the boundary; this minute-loop\n    # fallback may recover only after the boundary, during T-15..T-14.\n    base.MIN_LOCK_SECONDS=14*60\n    base.MAX_LOCK_SECONDS=15*60")

replace_once('scripts/run-emergency-earliest-missing-bet.py',
'RECOVERY_OPEN_SECONDS = 16 * 60',
'RECOVERY_OPEN_SECONDS = 15 * 60')

replace_once('scripts/run-critical-auto-bet-generation.py',
'RECOVERY_OPEN_SECONDS = 16 * 60',
'RECOVERY_OPEN_SECONDS = 15 * 60')

p=Path('scripts/verify-live-lock-safety.py')
text=p.read_text(encoding='utf-8')
text=text.replace("        'const FINALIZE_OPEN_MS = 16 * 60 * 1000;',\n", "        'const FINALIZE_OPEN_MS = DEADLINE_MS;',\n")
text=text.replace('    require(canonical, "base.MIN_LOCK_SECONDS=15*60", "canonical GitHub fallback")\n    require(canonical, "base.MAX_LOCK_SECONDS=16*60", "canonical GitHub fallback")',
                  '    require(canonical, "base.MIN_LOCK_SECONDS=14*60", "canonical GitHub fallback")\n    require(canonical, "base.MAX_LOCK_SECONDS=15*60", "canonical GitHub fallback")')
text=text.replace('    require(emergency, "RECOVERY_OPEN_SECONDS = 16 * 60", "emergency fallback")',
                  '    require(emergency, "RECOVERY_OPEN_SECONDS = 15 * 60", "emergency fallback")')
text=text.replace('    require(critical_script, "RECOVERY_OPEN_SECONDS = 16 * 60", "manual critical recovery")',
                  '    require(critical_script, "RECOVERY_OPEN_SECONDS = 15 * 60", "manual critical recovery")')
text=text.replace('        "finalize_open=16m",\n        "deadline=15m",\n        "github_fallback=16m",\n        "emergency_fallback=16m",',
                  '        "finalize_open=15m",\n        "deadline=15m",\n        "github_fallback=15m_to_14m_post_boundary",\n        "emergency_fallback=15m",')
# The old early-lock marker is now explicitly forbidden so future regressions fail closed.
anchor='    forbid(worker, \'WORKER_FINAL_BODYWEIGHT_MISMATCH\', "Worker live-lock")\n'
if anchor not in text:
    raise RuntimeError('verify-live-lock-safety.py forbid anchor missing')
text=text.replace(anchor, anchor+'    forbid(worker, "const FINALIZE_OPEN_MS = 16 * 60 * 1000;", "Worker live-lock")\n')
p.write_text(text,encoding='utf-8')
print('patched scripts/verify-live-lock-safety.py')
