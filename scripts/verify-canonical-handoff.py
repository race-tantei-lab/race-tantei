#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
MODEL_SHA = "63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5"
def fail(message: str) -> None: raise AssertionError(message)
def read(path: str) -> str: return (ROOT / path).read_text(encoding="utf-8")
def load_json(path: str): return json.loads(read(path))
def sha256_file(path: str) -> str:
    h=hashlib.sha256()
    with (ROOT/path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()
def require(source: str, marker: str, label: str) -> None:
    if marker not in source: fail(f"{label} missing marker: {marker}")
def run_static(script: str) -> None: subprocess.run([sys.executable, str(ROOT/script)], cwd=ROOT, check=True)
def main() -> None:
    required=["HANDOFF.md","README.md","config/canonical-production-manifest.json","config/ten-year-completed-model.json","analysis-results/ten-year-model-completion-20260812.json","models/ten-year-completed-model.txt","models/ten-year-production-state-manifest.json","data/ten-year-runners/manifest.json","wrangler.jsonc","wrangler.live-deadline.jsonc","wrangler.live-deadline-backup.jsonc","src/live-deadline-entry-v3.ts","src/live-deadline-entry-v2.ts","src/v1/completed-worker-live-lock.ts","src/v1/completed-worker-deadline-guard.ts","src/v1/live-preview-safety.ts","scripts/install-race-day-runtime-guards.sql",".github/workflows/deploy-live-deadline.yml",".github/workflows/verify-live-deadline-production.yml",".github/workflows/verify-live-query-indexes.yml"]
    missing=[p for p in required if not (ROOT/p).exists()]
    if missing: fail(f"missing required files: {missing}")
    manifest=load_json("config/canonical-production-manifest.json"); model=load_json("config/ten-year-completed-model.json"); audit=load_json("analysis-results/ten-year-model-completion-20260812.json"); state=load_json("models/ten-year-production-state-manifest.json"); runners=load_json("data/ten-year-runners/manifest.json"); public=load_json("wrangler.jsonc"); primary=load_json("wrangler.live-deadline.jsonc"); backup=load_json("wrangler.live-deadline-backup.jsonc")
    if manifest.get("status")!="production" or int(manifest.get("handoffVersion",0))<5 or manifest.get("sourceOfTruth")!="HANDOFF.md": fail("canonical manifest identity mismatch")
    if model.get("status")!="completed" or model.get("name")!="ten-year-completed-model" or model.get("productionChanged") is not True: fail("completed model identity mismatch")
    actual=sha256_file(manifest["model"]["weights"])
    if actual!=MODEL_SHA or manifest["model"]["weightsSha256"]!=MODEL_SHA: fail("canonical model SHA changed")
    if audit.get("completed") is not True or audit.get("allCompletionGatesPassed") is not True: fail("completion audit gates not passed")
    if int(audit.get("archive",{}).get("universeRaces",-1))!=34566 or int(audit.get("archive",{}).get("selectedRaces",-1))!=14410: fail("canonical archive counts changed")
    ra=audit.get("raceSelectionAudit",{})
    if ra.get("targetDayResultsUsedForSelection") is not False or ra.get("historicalFinalOddsUsedForSelection") is not False or ra.get("syntheticOddsUsed") is not False: fail("selection leakage audit changed")
    if state.get("throughDate")!=manifest["model"]["stateThroughDate"]: fail("production state throughDate mismatch")
    for p in (manifest["model"]["runnerFeatureState"], manifest["model"]["raceSelectionState"]):
        info=state.get("files",{}).get(p)
        if not isinstance(info,dict) or sha256_file(p)!=str(info.get("sha256","")): fail(f"state hash mismatch:{p}")
    if int(runners.get("races",-1))!=34566 or int(runners.get("runners",-1))!=480441: fail("runner archive identity mismatch")
    site=manifest["site"]
    if public.get("main")!=site.get("entry"): fail(f"wrangler main mismatch:{public.get('main')}!={site.get('entry')}")
    if public.get("vars",{}).get("DEPLOY_REVISION")!=site.get("revision"): fail("public deploy revision mismatch")
    d1=public.get("d1_databases",[])
    if len(d1)!=1 or d1[0].get("database_id")!=site["d1DatabaseId"]: fail("public D1 mismatch")
    prod=manifest["production"]
    expected={"liveDeadlineEntry":"src/live-deadline-entry-v3.ts","liveDeadlineDriverEntry":"src/live-deadline-entry-v2.ts","publicLiveMutationEnabled":False,"previewOpenMinutes":90,"previewRequiredMinutes":30,"normalLockMinutes":30,"deadlineGuardArmMinutes":25,"hardDeadlineMinutes":15,"finalReflectionDeadlineMinutes":10,"officialOddsOnly":True,"syntheticOddsForbidden":True}
    for k,v in expected.items():
        if prod.get(k)!=v: fail(f"production architecture mismatch {k}:{prod.get(k)!r}!={v!r}")
    if primary.get("main")!=prod["liveDeadlineEntry"] or backup.get("main")!=prod["liveDeadlineEntry"]: fail("live wrangler main mismatch")
    if primary.get("triggers",{}).get("crons")!=["* * * * *"] or backup.get("triggers",{}).get("crons")!=["2-59/5 * * * *"]: fail("live cron mismatch")
    if primary.get("vars",{}).get("LIVE_DEADLINE_ROLE")!="primary" or backup.get("vars",{}).get("LIVE_DEADLINE_ROLE")!="backup": fail("live role mismatch")
    wrapper=read(prod["liveDeadlineEntry"])
    for m in ("shouldRunOnJraRaceDay","if (!raceDay.shouldRun)","PRIMARY_STALE_SECONDS = 150","if (role === "backup")","primaryIsAlive(env.DB)","await liveDeadlineV2.scheduled(controller, env)"): require(wrapper,m,"live v3 wrapper")
    driver=read(prod["liveDeadlineDriverEntry"])
    for m in ("acquireLiveDeadlineLease","runCompletedWorkerDeadlineGuard","runCompletedWorkerLiveLock","LIVE_DEADLINE_HARD_T15_BREACH"): require(driver,m,"live v2 driver")
    live=read("src/v1/completed-worker-live-lock.ts")
    for m in ("PREVIEW_OPEN_MS = 90 * 60 * 1000","PREVIEW_REQUIRED_MS = 30 * 60 * 1000","FINAL_LOCK_ARM_MS = 30 * 60 * 1000","DEADLINE_MS = 15 * 60 * 1000","FINAL_REFLECTION_DEADLINE_MS = 10 * 60 * 1000","WORKER_FRESH_GENERATION_STARTED_AFTER_T15","WORKER_GENERATION_CROSSED_T10","new Set(["jra-fast-official", "jra-crawl-official"])"): require(live,m,"live lock")
    guard=read("src/v1/completed-worker-deadline-guard.ts")
    for m in ("DEADLINE_GUARD_MS = 15 * 60 * 1000","DEADLINE_GUARD_ARM_MS = 25 * 60 * 1000","FINAL_REFLECTION_DEADLINE_MS = 10 * 60 * 1000","remainingMs >= DEADLINE_GUARD_MS"): require(guard,m,"deadline guard")
    migration=read("scripts/install-race-day-runtime-guards.sql")
    for m in ("rt_live_preview_archive","rt_live_deadline_lease","rt_guard_final_bet_insert_deadline","rt_guard_final_state_insert_deadline","rt_guard_official_odds_final_insert","OFFICIAL_JRA_ODDS_REQUIRED","PROBABILITY_FALLBACK_FORBIDDEN"): require(migration,m,"D1 guards")
    for script in ("scripts/verify-race-day-gate.py","scripts/verify-live-lock-safety.py","scripts/verify-live-preview-priority.py","scripts/verify-public-language.py"): run_static(script)
    handoff=read("HANDOFF.md"); readme=read("README.md")
    for m in ("handoff version: **5**","src/public-site-entry-recovery-20260906.ts","src/live-deadline-entry-v3.ts","src/live-deadline-entry-v2.ts","public live mutation: **disabled**","**T-90**","**T-30**","**T-25**","**T-15**","**T-10**"): require(handoff,m,"HANDOFF")
    for m in ("src/public-site-entry-recovery-20260906.ts","src/live-deadline-entry-v3.ts","src/live-deadline-entry-v2.ts","**T-90**","**T-30**","**T-25**","**T-15**","**T-10**","CANONICAL_HANDOFF_OK"): require(readme,m,"README")
    print("CANONICAL_HANDOFF_OK",f"model_sha={actual}",f"site_entry={public['main']}","handoff_version=5","selected_races=14410","live_wrapper=v3","live_driver=v2","live_primary=1m","live_backup=5m_staggered","preview_open=90m","normal_lock=30m","rescue_guard=25m","fresh_start_deadline=15m","fresh_reflection_deadline=10m","runtime_schema_probe=false","official_jra_odds_only=true")
if __name__=="__main__":
    try: main()
    except Exception as exc:
        print(f"CANONICAL_HANDOFF_FAIL: {exc}",file=sys.stderr); raise
