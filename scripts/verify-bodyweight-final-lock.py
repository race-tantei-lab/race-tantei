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
    wrapper=text('src/live-deadline-entry-v3.ts')

    require('fetchJraPage' in body and 'parseEntryPage' in body and 'pageLooksLikeEntry' in body,'BODYWEIGHT_DIRECT_JRA_PARSER_MISSING')
    require('sp.jra.jp' in body and 'www.jra.go.jp' in body,'BODYWEIGHT_ALTERNATE_JRA_HOST_MISSING')
    require('BODYWEIGHT_NOT_PUBLISHED' in body,'BODYWEIGHT_PUBLISH_RETRY_SIGNAL_MISSING')
    require('worker_bodyweight_snapshot:' in body,'BODYWEIGHT_PROVENANCE_STATE_MISSING')
    require('BODYWEIGHT_D1_VERIFY_FAILED' in body,'BODYWEIGHT_D1_REREAD_VERIFY_MISSING')

    require('const BODY_WEIGHT_REFRESH_OPEN_MS = 100 * 60 * 1000;' in live,'BODYWEIGHT_T100_REFRESH_WINDOW_MISSING')
    require('const PREVIEW_OPEN_MS = 90 * 60 * 1000;' in live,'BODYWEIGHT_T90_PREVIEW_WINDOW_MISSING')
    require('const FINAL_LOCK_ARM_MS = 30 * 60 * 1000;' in live,'BODYWEIGHT_T30_FINAL_ARM_MISSING')
    require('const DEADLINE_MS = 15 * 60 * 1000;' in live,'BODYWEIGHT_T15_DEADLINE_MISSING')
    require('const FINAL_REFLECTION_DEADLINE_MS = 10 * 60 * 1000;' in live,'BODYWEIGHT_T10_REFLECTION_MISSING')
    require('const FINALIZE_OPEN_MS' not in live,'BODYWEIGHT_OLD_POST_DEADLINE_FINALIZE_WINDOW_REINTRODUCED')
    require('bodyWeightApplied?: boolean' in live and 'bodyWeightSnapshot?: OfficialBodyWeightSnapshot | null' in live,'BODYWEIGHT_PREVIEW_PROVENANCE_MISSING')
    require('bodyWeightError = errorText(error)' in live,'BODYWEIGHT_FETCH_FAILURE_NOT_CAPTURED')
    require('latestOfficialBodyWeightPreview' in live,'BODYWEIGHT_LAST_GOOD_WEIGHTED_PREVIEW_MISSING')
    require('const stored = fresh ?? await latestOfficialBodyWeightPreview(env.DB, raceId) ?? await latestPreview(env.DB, raceId);' in live,'BODYWEIGHT_STORED_PREVIEW_ORDER_INVALID')
    require('bodyWeightBreachRaceIds' in live,'BODYWEIGHT_BREACH_AUDIT_MISSING')
    require('bodyWeightFetchedAt:' in live and 'bodyWeightSnapshotSha256:' in live and 'bodyWeights:' in live,'BODYWEIGHT_FINAL_AUDIT_PROVENANCE_MISSING')

    # At T-15 exactly, as well as after T-15, the worker must not start any
    # new network/model calculation. This intentionally verifies <=, not <.
    t15_start=live.index('if (remaining <= DEADLINE_MS)')
    t15_end=live.index('const existingPreview = await latestPreview',t15_start)
    t15=live[t15_start:t15_end]
    for forbidden in ('resolveOfficialBodyWeights(', 'refreshOfficialBodyWeights(', 'generatePreview(', 'fetchFastJraOfficialOddsForRace(', 'loadCompletedFeatureStateForRace(', 'loadCompletedRecencyLearning('):
        require(forbidden not in t15,f'BODYWEIGHT_T15_NETWORK_OR_RECOMPUTE_REINTRODUCED:{forbidden}')
    require('WORKER_HARD_T15_START_MISSED' in t15,'BODYWEIGHT_T15_HARD_BLOCK_MISSING')

    # Re-check the boundary at the actual generation start, after intervening
    # D1/preview work, so a tick cannot cross T-15 by a few milliseconds and
    # then begin a new calculation.
    require('const remainingAtGenerationStart = startMs - generationStartedAt.getTime();' in live,'BODYWEIGHT_ACTUAL_GENERATION_START_RECHECK_MISSING')
    require('remainingAtGenerationStart <= DEADLINE_MS' in live,'BODYWEIGHT_ACTUAL_GENERATION_START_T15_GUARD_MISSING')
    require('WORKER_FRESH_GENERATION_STARTED_AFTER_T15' in live,'BODYWEIGHT_ACTUAL_GENERATION_START_T15_ERROR_MISSING')

    body_try=live.find('bodyWeightSnapshot = await resolveOfficialBodyWeights')
    body_catch=live.find('bodyWeightError = errorText(error)',body_try)
    reread=live.find('const refreshed = await loadRace',body_catch)
    feature=live.find('loadCompletedFeatureStateForRace',reread)
    vector=live.find('completedFeatureVector',feature)
    require(0 <= body_try < body_catch < reread < feature < vector,'BODYWEIGHT_REFRESH_NOT_ATTEMPTED_BEFORE_FEATURE_VECTOR')

    require('remainingAfterGeneration < FINAL_REFLECTION_DEADLINE_MS' in live,'BODYWEIGHT_FRESH_T10_REFLECTION_GUARD_MISSING')
    require('remainingAfterGeneration < DEADLINE_MS' in live,'BODYWEIGHT_NONFRESH_T15_REFLECTION_GUARD_MISSING')
    require('WORKER_GENERATION_CROSSED_T10' in live,'BODYWEIGHT_FRESH_T10_GUARD_MISSING')
    require('WORKER_FALLBACK_CROSSED_T15' in live,'BODYWEIGHT_NONFRESH_T15_GUARD_MISSING')

    require('bodyWeightApplied: snapshot.bodyWeightApplied === true' in guard,'DEADLINE_GUARD_BODYWEIGHT_PROVENANCE_MISSING')
    require('bodyWeightFetchedAt: body?.fetchedAt ?? null' in guard,'DEADLINE_GUARD_BODYWEIGHT_FETCH_TIME_MISSING')
    require('bodyWeightSnapshotSha256: body?.snapshotSha256 ?? null' in guard,'DEADLINE_GUARD_BODYWEIGHT_SHA_MISSING')
    for forbidden in ('resolveOfficialBodyWeights(', 'refreshOfficialBodyWeights(', 'fetchFastJraOfficialOddsForRace('):
        require(forbidden not in guard,f'DEADLINE_GUARD_BODYWEIGHT_NETWORK_REINTRODUCED:{forbidden}')

    require('LIVE_DEADLINE_ROLE' in wrapper and 'role === "backup"' in wrapper,'LIVE_BACKUP_ROLE_MISSING')
    require('if (await primaryIsAlive(env.DB)) return;' in wrapper,'LIVE_BACKUP_TRUE_STANDBY_GUARD_MISSING')
    require('await liveDeadlineV2.scheduled(controller, env);' in wrapper,'LIVE_PRIMARY_OR_BACKUP_WORKER_PATH_MISSING')

    cfg=json.loads(text('config/ten-year-completed-model.json'))
    require(str(cfg['runnerProbabilityModel']['modelWeightsSha256'])==EXPECTED_MODEL_SHA,'MODEL_CONFIG_SHA_CHANGED')
    require(sha256('models/ten-year-completed-model.txt')==EXPECTED_MODEL_SHA,'MODEL_WEIGHTS_CHANGED')
    require(len(cfg['runnerProbabilityModel']['features'])==56,'MODEL_FEATURE_COUNT_CHANGED')

    print(json.dumps({
        'status':'BODYWEIGHT_WORKER_NATIVE_PREDEADLINE_LOCK_OK',
        'modelSha256':EXPECTED_MODEL_SHA,
        'featureCount':56,
        'refreshOpenMinutes':100,
        'previewOpenMinutes':90,
        'finalArmMinutes':30,
        'generationStartDeadlineMinutes':15,
        'generationStartBoundaryInclusive':True,
        'actualGenerationStartRecheck':True,
        'freshReflectionDeadlineMinutes':10,
        'postT15GenerationStart':False,
        'backupMode':'same_worker_true_standby',
        'officialBodyweightAppliedWhenAvailable':True,
    },ensure_ascii=False))


if __name__=='__main__': main()
