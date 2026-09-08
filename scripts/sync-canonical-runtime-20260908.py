#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_required(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"MISSING_REPLACEMENT:{path}:{old[:100]}")
    file.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    manifest_path = ROOT / "config/canonical-production-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["asOfJst"] = "2026-09-08T10:17:00+09:00"
    manifest["verifiedProductionBaselineCommit"] = "19f85d50d3eb01d8f533e8387c51142313434cda"
    manifest["handoffVerification"]["verifies"] = [
        "canonical model identity and productionChanged status",
        "model weights SHA256 plus production state artifact hashes",
        "completion audit gates and canonical 34,566 / 14,410 race counts",
        "wrangler.jsonc actual public entry, deploy revision, model version and D1 identity",
        "actual primary/backup wrangler entries, roles and cron schedules",
        "race-day gate before D1 and no runtime sqlite_master/PRAGMA/DDL in live cron",
        "official JRA odds only, T-15 fresh-generation start boundary and T-10 fresh-reflection boundary",
        "persistent D1 guard migration source and control-plane live-index verification",
        "README and HANDOFF current-runtime markers",
    ]
    prod = manifest["production"]
    prod["deadlineGuardArmMinutes"] = 25
    prod["liveDeadlineEntry"] = "src/live-deadline-entry-v3.ts"
    prod["liveDeadlineDriverEntry"] = "src/live-deadline-entry-v2.ts"
    prod["normalLockMinutes"] = 30
    prod["hardDeadlineMinutes"] = 15
    prod["finalReflectionDeadlineMinutes"] = 10
    site = manifest["site"]
    site["entry"] = "src/public-site-entry-recovery-20260906.ts"
    site["revision"] = "ten-year-completed-public-v37-original-home-restored-20260905"

    old_req = "Official JRA-odds previews begin from 90 minutes before post time, a preview is required by 30 minutes, normal immutable finalization is targeted by 25 minutes, the DB-only rescue guard operates from 20 to 15 minutes, and T-15 is a hard no-new-final boundary."
    new_req = "Official JRA-odds previews begin from 90 minutes before post time and are required by 30 minutes. The fresh finalization window begins around T-30; stored official-preview rescue is armed from T-25 through the exact T-15 boundary. No fresh calculation may start at T-15 or later, while a fresh calculation that started before T-15 may be reflected only through the T-10 boundary."
    manifest["currentUiRequirements"] = [new_req if row == old_req else row for row in manifest.get("currentUiRequirements", [])]
    old_rule = "Treat src/live-deadline-entry-v2.ts plus wrangler.live-deadline.jsonc and wrangler.live-deadline-backup.jsonc as the canonical race-bet live scheduler; public-site requests must not mutate live race bets."
    new_rule = "Treat src/live-deadline-entry-v3.ts as the canonical live scheduler wrapper and src/live-deadline-entry-v2.ts as its isolated live driver; both wrangler.live-deadline*.jsonc files must point to v3, and public-site requests must not mutate live race bets."
    boundary_old = "T-15 is a hard creation boundary: never create or backfill a new final race bet after fewer than 15 minutes remain before post time."
    boundary_new = "T-15 is the hard fresh-generation start boundary: never start a new model/odds calculation at T-15 or later; only a fresh calculation started before T-15 may reflect until T-10, while stored/nonfresh finalization may not cross below T-15."
    manifest["authoritativeRules"] = [new_rule if row == old_rule else boundary_new if row == boundary_old else row for row in manifest.get("authoritativeRules", [])]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    replace_required(
        "README.md",
        "  - 2026-08-22確認値: `src/public-site-entry-v34.ts`\n- deploy revision: `ten-year-completed-public-v34-live-deadline-detached-20260822`",
        "  - 2026-09-08確認値: `src/public-site-entry-recovery-20260906.ts`\n- deploy revision: `ten-year-completed-public-v37-original-home-restored-20260905`",
    )
    replace_required("README.md", "- scheduler entry: `src/live-deadline-entry-v2.ts`", "- scheduler wrapper: `src/live-deadline-entry-v3.ts`\n- isolated live driver: `src/live-deadline-entry-v2.ts`")
    replace_required(
        "README.md",
        "- **T-90**: JRA公式オッズでpreview作成開始\n- **T-40**: 早期SLA監査\n- **T-30**: official preview必須\n- **T-25**: 通常のimmutable final\n- **T-20**: 保存済みofficial previewだけを使う救済guard\n- **T-15**: hard creation boundary。新規推論・オッズ取得・買い目生成・backfillは禁止\n- T-15後の新規finalはD1 invariantでも拒否",
        "- **T-90**: JRA公式オッズでpreview作成開始\n- **T-40**: 早期SLA監査\n- **T-30**: official preview必須。fresh finalization window開始\n- **T-25**: 保存済みofficial previewによるrescue guard開始\n- **T-15**: fresh generation開始禁止。stored/nonfresh finalizationもここを下回って新規作成しない\n- **T-10**: T-15より前に開始したfresh計算の最終反映限界\n- T-15以降に新しい計算を開始せず、T-10以降にfresh結果を反映しない",
    )
    replace_required("README.md", "2. `src/live-deadline-entry-v2.ts` と2つの `wrangler.live-deadline*.jsonc` を確認", "2. `src/live-deadline-entry-v3.ts` → `src/live-deadline-entry-v2.ts` の実wrapper/driverと、2つの `wrangler.live-deadline*.jsonc` を確認")

    replace_required("HANDOFF.md", "- manifest as-of: `2026-08-22T19:20:00+09:00`", "- manifest as-of: `2026-09-08T10:17:00+09:00`")
    replace_required("HANDOFF.md", "- verified live-architecture baseline commit: `5265321ad2186271aee96f45f98cbeec79c7df83`", "- verified live-architecture baseline commit: `19f85d50d3eb01d8f533e8387c51142313434cda`")
    replace_required("HANDOFF.md", "  - 2026-08-22確認値: `src/public-site-entry-v34.ts`", "  - 2026-09-08確認値: `src/public-site-entry-recovery-20260906.ts`")
    replace_required("HANDOFF.md", "  - 2026-08-22確認値: `ten-year-completed-public-v34-live-deadline-detached-20260822`", "  - 2026-09-08確認値: `ten-year-completed-public-v37-original-home-restored-20260905`")
    replace_required("HANDOFF.md", "- scheduler entry: `src/live-deadline-entry-v2.ts`", "- scheduler wrapper: `src/live-deadline-entry-v3.ts`\n- isolated live driver: `src/live-deadline-entry-v2.ts`")
    replace_required("HANDOFF.md", "6. `src/live-deadline-entry-v2.ts`\n7. `src/v1/completed-worker-live-lock.ts`", "6. `src/live-deadline-entry-v3.ts`\n7. `src/live-deadline-entry-v2.ts`\n8. `src/v1/completed-worker-live-lock.ts`")
    replace_required(
        "HANDOFF.md",
        "8. `src/v1/completed-worker-deadline-guard.ts`\n9. `src/v1/completed-final-invariants.ts`\n10. `src/v1/live-preview-safety.ts`\n11. `.github/workflows/deploy-live-deadline.yml`\n12. `.github/workflows/verify-live-deadline-production.yml`\n13. `config/ten-year-completed-model.json`\n14. `analysis-results/ten-year-model-completion-20260812.json`\n15. `analysis-results/completed-model-methodology-audit-20260813.md`\n16. 最新mainのproduction checks / readiness / deploymentを直接確認\n17. 必要なら本番D1で対象レースのpreview / final state / `locked_at` / `oddsSource` を確認\n18. 依頼された具体作業へ進む。**モデル探索からやり直さない。**",
        "9. `src/v1/completed-worker-deadline-guard.ts`\n10. `src/v1/completed-final-invariants.ts`\n11. `src/v1/live-preview-safety.ts`\n12. `.github/workflows/deploy-live-deadline.yml`\n13. `.github/workflows/verify-live-deadline-production.yml`\n14. `config/ten-year-completed-model.json`\n15. `analysis-results/ten-year-model-completion-20260812.json`\n16. `analysis-results/completed-model-methodology-audit-20260813.md`\n17. 最新mainのproduction checks / readiness / deploymentを直接確認\n18. 必要なら本番D1で対象レースのpreview / final state / `locked_at` / `oddsSource` を確認\n19. 依頼された具体作業へ進む。**モデル探索からやり直さない。**",
    )
    replace_required(
        "HANDOFF.md",
        "- **T-90**: JRA公式オッズでpreview作成を開始\n- **T-40**: 早期SLA監査\n- **T-30**: official previewが無ければ異常検知\n- **T-17**: 最新情報でfresh previewを再生成してimmutable finalを確定\n- **T-16**: fresh経路失敗時だけ、保存済みofficial previewを使うDB中心の最終救済guard\n- **T-15**: hard creation boundary。新規作成を一切しない。既に正しくfinal済みか確認するだけ\n- **T-15経過後**: D1 trigger自体が新規final / 後付けfinalを拒否",
        "- **T-90**: JRA公式オッズでpreview作成を開始\n- **T-40**: 早期SLA監査\n- **T-30**: official preview必須。fresh finalization windowを開始\n- **T-25**: 保存済みofficial previewだけを使えるrescue guardを開始\n- **T-15**: fresh generation開始のhard boundary。ここから新しいモデル推論・オッズ取得・買い目計算を開始しない。stored/nonfresh finalizationもT-15未満へ持ち越さない\n- **T-10**: T-15より前に開始したfresh計算の最終反映限界。これを下回ったfresh結果は確定に使わない",
    )
    replace_required("HANDOFF.md", "現在は隔離Worker + lease + archive + T-90/T-17/T-16/T-15構成を正本とする。旧GitHub backup方式や公開サイト経由のlive-tickを現行経路として復活させない。", "現在はv3 race-day gate / heartbeat wrapper + v2 isolated driver + lease + archive + T-90/T-30/T-25/T-15/T-10構成を正本とする。旧GitHub backup方式や公開サイト経由のlive-tickを現行経路として復活させない。")

    verifier = '''#!/usr/bin/env python3
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
    for m in ("shouldRunOnJraRaceDay","if (!raceDay.shouldRun)","PRIMARY_STALE_SECONDS = 150","if (role === \"backup\")","primaryIsAlive(env.DB)","await liveDeadlineV2.scheduled(controller, env)"): require(wrapper,m,"live v3 wrapper")
    driver=read(prod["liveDeadlineDriverEntry"])
    for m in ("acquireLiveDeadlineLease","runCompletedWorkerDeadlineGuard","runCompletedWorkerLiveLock","LIVE_DEADLINE_HARD_T15_BREACH"): require(driver,m,"live v2 driver")
    live=read("src/v1/completed-worker-live-lock.ts")
    for m in ("PREVIEW_OPEN_MS = 90 * 60 * 1000","PREVIEW_REQUIRED_MS = 30 * 60 * 1000","FINAL_LOCK_ARM_MS = 30 * 60 * 1000","DEADLINE_MS = 15 * 60 * 1000","FINAL_REFLECTION_DEADLINE_MS = 10 * 60 * 1000","WORKER_FRESH_GENERATION_STARTED_AFTER_T15","WORKER_GENERATION_CROSSED_T10","new Set([\"jra-fast-official\", \"jra-crawl-official\"])"): require(live,m,"live lock")
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
'''
    (ROOT / "scripts/verify-canonical-handoff.py").write_text(verifier, encoding="utf-8")

    workflow = '''name: Verify canonical handoff
on:
  workflow_dispatch:
  push:
    branches: [main]
    paths:
      - 'HANDOFF.md'
      - 'README.md'
      - 'config/canonical-production-manifest.json'
      - 'config/ten-year-completed-model.json'
      - 'analysis-results/ten-year-model-completion-20260812.json'
      - 'models/**'
      - 'scripts/verify-canonical-handoff.py'
      - 'scripts/verify-race-day-gate.py'
      - 'scripts/verify-live-lock-safety.py'
      - 'scripts/verify-live-preview-priority.py'
      - 'scripts/verify-public-language.py'
      - 'scripts/install-race-day-runtime-guards.sql'
      - 'wrangler.jsonc'
      - 'wrangler.live-deadline.jsonc'
      - 'wrangler.live-deadline-backup.jsonc'
      - 'src/public-site-entry-*.ts'
      - 'src/live-deadline-entry-v3.ts'
      - 'src/live-deadline-entry-v2.ts'
      - 'src/v1/completed-worker-live-lock.ts'
      - 'src/v1/completed-worker-deadline-guard.ts'
      - 'src/v1/live-preview-safety.ts'
      - '.github/workflows/deploy-live-deadline.yml'
      - '.github/workflows/verify-live-deadline-production.yml'
      - '.github/workflows/verify-live-query-indexes.yml'
      - '.github/workflows/verify-canonical-handoff.yml'
permissions:
  contents: read
  statuses: write
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - name: Publish canonical handoff pending
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh api --method POST -H 'Accept: application/vnd.github+json' "/repos/${GITHUB_REPOSITORY}/statuses/${GITHUB_SHA}" -f state=pending -f context='production/canonical-handoff' -f description='Verifying canonical Race Tantei handoff v5' -f target_url="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - name: Verify canonical handoff
        run: python scripts/verify-canonical-handoff.py
      - name: Publish canonical handoff success
        if: success()
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh api --method POST -H 'Accept: application/vnd.github+json' "/repos/${GITHUB_REPOSITORY}/statuses/${GITHUB_SHA}" -f state=success -f context='production/canonical-handoff' -f description='Canonical Race Tantei handoff v5 verified' -f target_url="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
      - name: Publish canonical handoff failure
        if: failure()
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh api --method POST -H 'Accept: application/vnd.github+json' "/repos/${GITHUB_REPOSITORY}/statuses/${GITHUB_SHA}" -f state=failure -f context='production/canonical-handoff' -f description='Canonical Race Tantei handoff v5 verification failed' -f target_url="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
'''
    (ROOT / ".github/workflows/verify-canonical-handoff.yml").write_text(workflow, encoding="utf-8")
    print("CANONICAL_RUNTIME_SYNC_OK")


if __name__ == "__main__":
    main()
