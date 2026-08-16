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
    v20=text('src/public-site-entry-v20.ts')
    direct=text('scripts/sync-upcoming-entries-direct.mjs')
    backup=text('scripts/refresh-selected-bodyweights-direct.mjs')
    wrapper=text('scripts/run-ten-year-auto-final-live.py')
    workflow=text('.github/workflows/auto-final-live-bets.yml')

    require('fetchJraPage' in body and 'parseEntryPage' in body and 'pageLooksLikeEntry' in body,'BODYWEIGHT_DIRECT_JRA_PARSER_MISSING')
    require('sp.jra.jp' in body and 'www.jra.go.jp' in body,'BODYWEIGHT_ALTERNATE_JRA_HOST_MISSING')
    require('BODYWEIGHT_NOT_PUBLISHED' in body,'BODYWEIGHT_PUBLISH_RETRY_SIGNAL_MISSING')
    require('worker_bodyweight_snapshot:' in body,'BODYWEIGHT_PROVENANCE_STATE_MISSING')
    require('BODYWEIGHT_D1_VERIFY_FAILED' in body,'BODYWEIGHT_D1_REREAD_VERIFY_MISSING')

    require('const BODY_WEIGHT_REFRESH_OPEN_MS = 80 * 60 * 1000;' in live,'BODYWEIGHT_T80_REFRESH_WINDOW_MISSING')
    require('const PREVIEW_OPEN_MS = 45 * 60 * 1000;' in live,'BODYWEIGHT_PREVIEW_WINDOW_MISSING')
    require('const FINALIZE_OPEN_MS = DEADLINE_MS;' in live,'BODYWEIGHT_T15_FINALIZE_WINDOW_MISSING')
    require('const DEADLINE_MS = 15 * 60 * 1000;' in live,'BODYWEIGHT_T15_DEADLINE_MISSING')
    require('bodyWeightApplied?: boolean' in live and 'bodyWeightSnapshot?: OfficialBodyWeightSnapshot | null' in live,'BODYWEIGHT_PREVIEW_MUST_ALLOW_PROVISIONAL_FALLBACK')
    require('bodyWeightError = errorText(error)' in live,'BODYWEIGHT_FETCH_FAILURE_NOT_CAPTURED')
    require('latestOfficialBodyWeightPreview' in live,'BODYWEIGHT_LAST_GOOD_WEIGHTED_PREVIEW_MISSING')
    require('official ?? fresh ?? await latestPreview(env.DB, raceId)' in live,'BODYWEIGHT_FINAL_FALLBACK_ORDER_INVALID')
    require('await latestOfficialBodyWeightPreview(env.DB, raceId) ?? await latestPreview(env.DB, raceId)' in live,'BODYWEIGHT_DEADLINE_LOCAL_FALLBACK_MISSING')
    require('bodyWeightBreachRaceIds' in live,'BODYWEIGHT_BREACH_AUDIT_MISSING')
    require('bodyWeightFetchedAt' in live and 'bodyWeightSnapshotSha256' in live and 'bodyWeights:' in live,'BODYWEIGHT_FINAL_AUDIT_PROVENANCE_MISSING')
    require('WORKER_FINAL_BODYWEIGHT_MISMATCH' not in live,'BODYWEIGHT_MISSING_STILL_BLOCKS_FINAL_BETS')

    body_try=live.find('bodyWeightSnapshot = await resolveOfficialBodyWeights')
    body_catch=live.find('bodyWeightError = errorText(error)',body_try)
    reread=live.find('const refreshed = await loadRace',body_catch)
    feature=live.find('loadCompletedFeatureStateForRace',reread)
    vector=live.find('completedFeatureVector',feature)
    require(0 <= body_try < body_catch < reread < feature < vector,'BODYWEIGHT_REFRESH_NOT_ATTEMPTED_BEFORE_FEATURE_VECTOR')

    critical_pos=v20.find('await runCriticalPreRacePath(env);')
    generic_pos=v20.find('if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);',critical_pos)
    require(0 <= critical_pos < generic_pos,'CRITICAL_BODYWEIGHT_PATH_NOT_BEFORE_GENERIC_SYNC')

    require('horse_weight=COALESCE(excluded.horse_weight,rt_runners.horse_weight)' in direct,'DIRECT_SYNC_CAN_ERASE_CONFIRMED_BODYWEIGHT')
    require('refresh-selected-bodyweights-direct.mjs' in workflow,'GITHUB_BODYWEIGHT_ACQUISITION_NOT_WIRED')
    acquire_pos=workflow.find('node scripts/refresh-selected-bodyweights-direct.mjs')
    finalize_pos=workflow.find('python scripts/run-ten-year-auto-final-live.py',acquire_pos)
    require(0 <= acquire_pos < finalize_pos,'GITHUB_FINALIZER_RUNS_BEFORE_BODYWEIGHT_ACQUISITION')
    require('worker_bodyweight_snapshot:' in backup and 'parseEntryPage' in backup,'GITHUB_BODYWEIGHT_OFFICIAL_ACQUISITION_INVALID')
    require('const FINALIZE_OPEN_MS = 16 * 60 * 1000;' in backup,'GITHUB_BODYWEIGHT_T16_ACQUISITION_WINDOW_MISSING')
    require('verify_official_bodyweights' in wrapper,'GITHUB_BODYWEIGHT_PROVENANCE_AUDIT_MISSING')
    require('fallback_without_verified_snapshot' in wrapper,'GITHUB_BODYWEIGHT_FAILURE_STILL_BLOCKS_FINALIZER')
    require('base.MIN_LOCK_SECONDS=0' in wrapper and 'base.MAX_LOCK_SECONDS=15*60' in wrapper,'GITHUB_FINALIZER_NOT_PERSISTENT_T15_TO_START_FALLBACK')
    require('base.MIN_LOCK_SECONDS=14*60' not in wrapper,'GITHUB_FINALIZER_OLD_ONE_MINUTE_WINDOW_REINTRODUCED')
    verify_pos=wrapper.find('verified=verify_official_bodyweights')
    except_pos=wrapper.find('except Exception as exc:',verify_pos)
    odds_pos=wrapper.find('return original_collect_official_odds',except_pos)
    require(0 <= verify_pos < except_pos < odds_pos,'GITHUB_BODYWEIGHT_AUDIT_NOT_NONBLOCKING')

    cfg=json.loads(text('config/ten-year-completed-model.json'))
    require(str(cfg['runnerProbabilityModel']['modelWeightsSha256'])==EXPECTED_MODEL_SHA,'MODEL_CONFIG_SHA_CHANGED')
    require(sha256('models/ten-year-completed-model.txt')==EXPECTED_MODEL_SHA,'MODEL_WEIGHTS_CHANGED')
    require(len(cfg['runnerProbabilityModel']['features'])==56,'MODEL_FEATURE_COUNT_CHANGED')

    print(json.dumps({
        'status':'BODYWEIGHT_NONBLOCKING_FINAL_LOCK_OK',
        'modelSha256':EXPECTED_MODEL_SHA,
        'featureCount':56,
        'refreshOpenMinutes':80,
        'previewOpenMinutes':45,
        'finalizeOpenMinutes':15,
        'deadlineMinutes':15,
        'githubFallbackWindowMinutes':'15_until_start',
        'githubBodyweightAcquisitionOpenMinutes':16,
        'bodyweightAppliedWhenAvailable':True,
        'bodyweightFailureDoesNotSuppressPrediction':True,
        'workerAndGithubAcquisition':True,
    },ensure_ascii=False))


if __name__=='__main__': main()
