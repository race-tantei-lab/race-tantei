#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPECTED_MODEL_SHA='63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5'


def require(condition,message):
    if not condition: raise RuntimeError(message)


def text(rel):
    return (ROOT/rel).read_text(encoding='utf-8')


def sha256(rel):
    h=hashlib.sha256()
    with (ROOT/rel).open('rb') as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def main():
    body=text('src/v1/bodyweight-refresh.ts')
    live=text('src/v1/completed-worker-live-lock.ts')
    guard=text('src/v1/completed-worker-deadline-guard.ts')
    v20=text('src/public-site-entry-v20.ts')
    direct=text('scripts/sync-upcoming-entries-direct.mjs')
    workflow=text('.github/workflows/auto-final-live-bets.yml')
    stored_backup=text('scripts/run-stored-preview-deadline-backup.py')

    require('fetchJraPage' in body and 'parseEntryPage' in body and 'pageLooksLikeEntry' in body,'BODYWEIGHT_DIRECT_JRA_PARSER_MISSING')
    require('sp.jra.jp' in body and 'www.jra.go.jp' in body,'BODYWEIGHT_ALTERNATE_JRA_HOST_MISSING')
    require('BODYWEIGHT_NOT_PUBLISHED' in body,'BODYWEIGHT_PUBLISH_RETRY_SIGNAL_MISSING')
    require('worker_bodyweight_snapshot:' in body,'BODYWEIGHT_PROVENANCE_STATE_MISSING')
    require('BODYWEIGHT_D1_VERIFY_FAILED' in body,'BODYWEIGHT_D1_REREAD_VERIFY_MISSING')

    require('const BODY_WEIGHT_REFRESH_OPEN_MS = 80 * 60 * 1000;' in live,'BODYWEIGHT_T80_REFRESH_WINDOW_MISSING')
    require('const PREVIEW_OPEN_MS = 45 * 60 * 1000;' in live,'BODYWEIGHT_PREVIEW_WINDOW_MISSING')
    require('const DEADLINE_MS = 15 * 60 * 1000;' in live,'BODYWEIGHT_T15_DEADLINE_MISSING')
    require('const FINALIZE_OPEN_MS' not in live,'BODYWEIGHT_OLD_POST_DEADLINE_FINALIZE_WINDOW_REINTRODUCED')
    require('bodyWeightApplied?: boolean' in live and 'bodyWeightSnapshot?: OfficialBodyWeightSnapshot | null' in live,'BODYWEIGHT_PREVIEW_MUST_ALLOW_PROVISIONAL_FALLBACK')
    require('bodyWeightError = errorText(error)' in live,'BODYWEIGHT_FETCH_FAILURE_NOT_CAPTURED')
    require('latestOfficialBodyWeightPreview' in live,'BODYWEIGHT_LAST_GOOD_WEIGHTED_PREVIEW_MISSING')
    require('const stored = await latestOfficialBodyWeightPreview(env.DB, raceId) ?? await latestPreview(env.DB, raceId);' in live,'BODYWEIGHT_T15_STORED_PREVIEW_ORDER_INVALID')
    require('await commitSnapshot(env.DB, raceId, stored, now, "deadline_watchdog")' in live,'BODYWEIGHT_T15_STORED_PREVIEW_NOT_LOCKED')
    require('bodyWeightBreachRaceIds' in live,'BODYWEIGHT_BREACH_AUDIT_MISSING')
    require('bodyWeightFetchedAt' in live and 'bodyWeightSnapshotSha256' in live and 'bodyWeights:' in live,'BODYWEIGHT_FINAL_AUDIT_PROVENANCE_MISSING')
    require('WORKER_FINAL_BODYWEIGHT_MISMATCH' not in live,'BODYWEIGHT_MISSING_STILL_BLOCKS_FINAL_BETS')

    t15_start=live.index('if (remaining <= DEADLINE_MS)')
    t15_end=live.index('let fresh: PreviewSnapshot | null = null;',t15_start)
    t15=live[t15_start:t15_end]
    for forbidden in ('resolveOfficialBodyWeights(', 'refreshOfficialBodyWeights(', 'generatePreview(', 'fetchFastJraOfficialOddsForRace(', 'loadCompletedFeatureStateForRace(', 'loadCompletedRecencyLearning('):
        require(forbidden not in t15,f'BODYWEIGHT_T15_NETWORK_OR_RECOMPUTE_REINTRODUCED:{forbidden}')

    body_try=live.find('bodyWeightSnapshot = await resolveOfficialBodyWeights')
    body_catch=live.find('bodyWeightError = errorText(error)',body_try)
    reread=live.find('const refreshed = await loadRace',body_catch)
    feature=live.find('loadCompletedFeatureStateForRace',reread)
    vector=live.find('completedFeatureVector',feature)
    require(0 <= body_try < body_catch < reread < feature < vector,'BODYWEIGHT_REFRESH_NOT_ATTEMPTED_BEFORE_FEATURE_VECTOR')

    require('snapshot.bodyWeightApplied===true' in guard,'DEADLINE_GUARD_BODYWEIGHT_PROVENANCE_MISSING')
    require('bodyWeightFetchedAt:body?.fetchedAt??null' in guard,'DEADLINE_GUARD_BODYWEIGHT_FETCH_TIME_MISSING')
    require('bodyWeightSnapshotSha256:body?.snapshotSha256??null' in guard,'DEADLINE_GUARD_BODYWEIGHT_SHA_MISSING')
    for forbidden in ('resolveOfficialBodyWeights(', 'refreshOfficialBodyWeights(', 'fetchFastJraOfficialOddsForRace('):
        require(forbidden not in guard,f'DEADLINE_GUARD_BODYWEIGHT_NETWORK_REINTRODUCED:{forbidden}')

    critical_pos=v20.find('await runCriticalPreRacePath(env);')
    generic_pos=v20.find('if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);',critical_pos)
    require(0 <= critical_pos < generic_pos,'CRITICAL_BODYWEIGHT_PATH_NOT_BEFORE_GENERIC_SYNC')
    require('horse_weight=COALESCE(excluded.horse_weight,rt_runners.horse_weight)' in direct,'DIRECT_SYNC_CAN_ERASE_CONFIRMED_BODYWEIGHT')

    require('scripts/run-stored-preview-deadline-backup.py' in workflow,'GITHUB_STORED_PREVIEW_BACKUP_NOT_WIRED')
    require('stored_preview_only' in workflow,'GITHUB_BACKUP_NOT_STORED_PREVIEW_ONLY')
    require('refresh-selected-bodyweights-direct.mjs' not in workflow,'GITHUB_BACKUP_STILL_FETCHES_BODYWEIGHT_AFTER_T15')
    require('run-critical-auto-bet-generation.py' not in workflow,'GITHUB_BACKUP_STILL_GENERATES_AFTER_T15')
    require('"mode": "stored_preview_only"' in stored_backup,'GITHUB_BACKUP_MODE_INVALID')
    require('"generatedRaceIds": []' in stored_backup,'GITHUB_BACKUP_CAN_GENERATE_NEW_PREDICTIONS')

    cfg=json.loads(text('config/ten-year-completed-model.json'))
    require(str(cfg['runnerProbabilityModel']['modelWeightsSha256'])==EXPECTED_MODEL_SHA,'MODEL_CONFIG_SHA_CHANGED')
    require(sha256('models/ten-year-completed-model.txt')==EXPECTED_MODEL_SHA,'MODEL_WEIGHTS_CHANGED')
    require(len(cfg['runnerProbabilityModel']['features'])==56,'MODEL_FEATURE_COUNT_CHANGED')

    print(json.dumps({
        'status':'BODYWEIGHT_PREDEADLINE_PREVIEW_ATOMIC_LOCK_OK',
        'modelSha256':EXPECTED_MODEL_SHA,
        'featureCount':56,
        'refreshOpenMinutes':80,
        'previewOpenMinutes':45,
        'deadlineMinutes':15,
        'postDeadlineBodyweightFetch':False,
        'postDeadlinePredictionRecompute':False,
        'githubBackupMode':'stored_preview_only',
        'bodyweightAppliedWhenAvailable':True,
        'bodyweightFailureDoesNotSuppressPredeadlinePreview':True,
    },ensure_ascii=False))


if __name__=='__main__': main()
