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
    require('const PREVIEW_VERSION = 2;' in live,'BODYWEIGHT_PREVIEW_VERSION_NOT_BUMPED')
    require('bodyWeightSnapshot: OfficialBodyWeightSnapshot' in live,'BODYWEIGHT_PREVIEW_PROVENANCE_MISSING')
    require('bodyWeightFetchedAt' in live and 'bodyWeightSnapshotSha256' in live and 'bodyWeights:' in live,'BODYWEIGHT_FINAL_AUDIT_PROVENANCE_MISSING')
    refresh_pos=live.find('const bodyWeightSnapshot = await resolveOfficialBodyWeights')
    reread_pos=live.find('const refreshed = await loadRace',refresh_pos)
    feature_pos=live.find('loadCompletedFeatureStateForRace',reread_pos)
    vector_pos=live.find('completedFeatureVector',feature_pos)
    require(0 <= refresh_pos < reread_pos < feature_pos < vector_pos,'BODYWEIGHT_NOT_RESOLVED_BEFORE_FEATURE_VECTOR')
    require('bodyWeightSnapshotMatchesRunners(snapshot.bodyWeightSnapshot, runners)' in live,'BODYWEIGHT_FINAL_COMMIT_MATCH_GATE_MISSING')

    critical_pos=v20.find('await runCriticalPreRacePath(env);')
    generic_pos=v20.find('if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);',critical_pos)
    require(0 <= critical_pos < generic_pos,'CRITICAL_BODYWEIGHT_PATH_NOT_BEFORE_GENERIC_SYNC')

    require('horse_weight=COALESCE(excluded.horse_weight,rt_runners.horse_weight)' in direct,'DIRECT_SYNC_CAN_ERASE_CONFIRMED_BODYWEIGHT')
    require('refresh-selected-bodyweights-direct.mjs' in workflow,'GITHUB_BODYWEIGHT_ACQUISITION_NOT_WIRED')
    acquire_pos=workflow.find('node scripts/refresh-selected-bodyweights-direct.mjs')
    finalize_pos=workflow.find('python scripts/run-ten-year-auto-final-live.py',acquire_pos)
    require(0 <= acquire_pos < finalize_pos,'GITHUB_FINALIZER_RUNS_BEFORE_BODYWEIGHT_ACQUISITION')
    require('worker_bodyweight_snapshot:' in backup and 'parseEntryPage' in backup,'GITHUB_BODYWEIGHT_OFFICIAL_ACQUISITION_INVALID')
    require('verify_official_bodyweights' in wrapper,'GITHUB_FINALIZER_BODYWEIGHT_PROVENANCE_GATE_MISSING')
    verify_pos=wrapper.find('verified=verify_official_bodyweights')
    odds_pos=wrapper.find('return original_collect_official_odds',verify_pos)
    require(0 <= verify_pos < odds_pos,'GITHUB_ODDS_FINALIZATION_PRECEDES_BODYWEIGHT_GATE')

    cfg=json.loads(text('config/ten-year-completed-model.json'))
    require(str(cfg['runnerProbabilityModel']['modelWeightsSha256'])==EXPECTED_MODEL_SHA,'MODEL_CONFIG_SHA_CHANGED')
    require(sha256('models/ten-year-completed-model.txt')==EXPECTED_MODEL_SHA,'MODEL_WEIGHTS_CHANGED')
    require(len(cfg['runnerProbabilityModel']['features'])==56,'MODEL_FEATURE_COUNT_CHANGED')

    print(json.dumps({
        'status':'BODYWEIGHT_FINAL_LOCK_OK',
        'modelSha256':EXPECTED_MODEL_SHA,
        'featureCount':56,
        'refreshOpenMinutes':80,
        'previewVersion':2,
        'workerAcquisitionBeforeFeatures':True,
        'githubBackupAcquisitionBeforeFinalizer':True,
    },ensure_ascii=False))


if __name__=='__main__': main()
