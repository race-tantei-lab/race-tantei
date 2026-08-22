#!/usr/bin/env python3
import json
from pathlib import Path

p = Path('config/canonical-production-manifest.json')
data = json.loads(p.read_text(encoding='utf-8'))

data['handoffVersion'] = max(int(data.get('handoffVersion', 0)), 5)
data['asOfJst'] = '2026-08-22T19:20:00+09:00'
data['verifiedProductionBaselineCommit'] = '5265321ad2186271aee96f45f98cbeec79c7df83'

verification = data.setdefault('handoffVerification', {})
verifies = list(verification.get('verifies') or [])
verifies = [v for v in verifies if 'canonical live workflow' not in v and 'Worker live-lock/SLA wiring' not in v]
for v in [
    'isolated primary and staggered backup live-deadline Workers, with no public live mutation route',
    'T-90 official preview acquisition, T-25 normal finalization, T-20 rescue guard, and hard T-15 database boundary',
    'append-only preview archive, last-good restore, lease exclusion, and T-40/T-30/T-25/T-20/T-15 SLA audit wiring',
]:
    if v not in verifies:
        verifies.append(v)
verification['verifies'] = verifies

prod = data.setdefault('production', {})
prod.pop('autoWorkflow', None)
prod.pop('independentLiveTick', None)
prod.pop('independentLiveTickWorkflow', None)
prod.update({
    'runner': 'scripts/run-ten-year-auto-final-live.py',
    'core': 'scripts/ten-year-production-core.py',
    'selection': 'scripts/generate-ten-year-preday-selection.py',
    'bets': 'scripts/generate-ten-year-live-bets.py',
    'deployWorkflow': '.github/workflows/deploy.yml',
    'workerModelAssetBuilder': 'scripts/build-worker-completed-model-assets.py',
    'workerModelParity': 'scripts/verify-worker-model-parity.ts',
    'workerSelectionParityWorkflow': '.github/workflows/verify-worker-selection-parity.yml',
    'workerLiveLock': 'src/v1/completed-worker-live-lock.ts',
    'liveDeadlineEntry': 'src/live-deadline-entry-v2.ts',
    'liveDeadlinePrimaryConfig': 'wrangler.live-deadline.jsonc',
    'liveDeadlineBackupConfig': 'wrangler.live-deadline-backup.jsonc',
    'liveDeadlineDeployWorkflow': '.github/workflows/deploy-live-deadline.yml',
    'liveDeadlineReadinessWorkflow': '.github/workflows/verify-live-deadline-production.yml',
    'publicLiveMutationEnabled': False,
    'previewOpenMinutes': 90,
    'previewRequiredMinutes': 30,
    'normalLockMinutes': 25,
    'deadlineGuardArmMinutes': 20,
    'hardDeadlineMinutes': 15,
    'officialOddsOnly': True,
    'syntheticOddsForbidden': True,
})

site = data.setdefault('site', {})
site['entry'] = 'src/public-site-entry-v34.ts'
site['revision'] = 'ten-year-completed-public-v34-live-deadline-detached-20260822'

reqs = list(data.get('currentUiRequirements') or [])
reqs = [r for r in reqs if '45分前' not in r and 'independent five-minute live-tick backup' not in r and 'Worker live-lock must reject a 15-minute SLA breach' not in r]
for r in [
    'Live race-bet generation is owned only by the isolated live-deadline Workers; the public-site Worker and public requests cannot create or finalize race bets.',
    'Official JRA-odds previews begin from 90 minutes before post time, a preview is required by 30 minutes, normal immutable finalization is targeted by 25 minutes, the DB-only rescue guard operates from 20 to 15 minutes, and T-15 is a hard no-new-final boundary.',
    'Primary live-deadline scheduling runs every minute and a separate staggered backup Worker runs every five minutes; a D1 lease prevents overlapping mutation while append-only preview archives preserve the newest last-good official preview.',
    'JRA official odds are the only allowed market odds; synthetic, estimated, and probability-derived substitute odds are forbidden by both application validation and D1 final-state guards.',
]:
    if r not in reqs:
        reqs.append(r)
data['currentUiRequirements'] = reqs

auth = list(data.get('authoritativeRules') or [])
for r in [
    'Treat src/live-deadline-entry-v2.ts plus wrangler.live-deadline.jsonc and wrangler.live-deadline-backup.jsonc as the canonical race-bet live scheduler; public-site requests must not mutate live race bets.',
    'T-15 is a hard creation boundary: never create or backfill a new final race bet after fewer than 15 minutes remain before post time.',
]:
    if r not in auth:
        auth.append(r)
data['authoritativeRules'] = auth

p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('PATCHED_CANONICAL_LIVE_ARCHITECTURE')
