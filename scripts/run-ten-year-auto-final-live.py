#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import pathlib
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE_PATH=ROOT/'scripts'/'run-auto-final-live.py'
SELECTION_PATH=ROOT/'scripts'/'generate-ten-year-preday-selection.py'
GENERATOR_PATH=ROOT/'scripts'/'generate-ten-year-live-bets.py'
EXPLANATION_PATH=ROOT/'scripts'/'write-ten-year-selection-explanations.py'
CONFIG_PATH=ROOT/'config'/'ten-year-completed-model.json'
MODEL_PATH=ROOT/'models'/'ten-year-completed-model.txt'
STATE_MANIFEST_PATH=ROOT/'models'/'ten-year-production-state-manifest.json'
COURSE_BUDGETS={'ライト':2000,'スタンダード':5000,'プレミアム':10000}
BODYWEIGHT_STATE_PREFIX='worker_bodyweight_snapshot:'


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m


def validate_selection(payload):
    selected=payload.get('selected')
    if not isinstance(selected,list) or not selected: raise RuntimeError('AUTO_SELECTION_EMPTY')
    if payload.get('sourceModel')!='ten-year-completed-model': raise RuntimeError(f"AUTO_SELECTION_MODEL_INVALID:{payload.get('sourceModel')}")
    if payload.get('resultDataUsedForTargetDay') is not False: raise RuntimeError('AUTO_SELECTION_USED_TARGET_RESULTS')
    counts={}
    for row in selected:
        venue=str(row.get('venue') or '');counts[venue]=counts.get(venue,0)+1
    if '' in counts or any(v!=5 for v in counts.values()): raise RuntimeError(f'AUTO_SELECTION_NOT_FIVE_PER_VENUE:{counts}')
    ids=[str(row.get('raceId') or '') for row in selected]
    if any(not x for x in ids) or len(ids)!=len(set(ids)): raise RuntimeError('AUTO_SELECTION_RACE_IDS_INVALID')
    return ids,list(counts)


def generate_selection(date,out_path):
    mod=load(SELECTION_PATH,'ten_year_auto_selection')
    old=sys.argv[:]
    try:
        sys.argv=[str(SELECTION_PATH),'--date',date,'--out',str(out_path)]
        mod.main()
    finally: sys.argv=old
    payload=json.loads(out_path.read_text(encoding='utf-8'));validate_selection(payload);return payload


def run_generator(date,selection_path,out_path):
    mod=load(GENERATOR_PATH,'ten_year_auto_generator')
    old=sys.argv[:]
    try:
        sys.argv=[str(GENERATOR_PATH),'--repo',str(ROOT),'--date',date,'--selection',str(selection_path),'--odds-file',str(ROOT/'current-selected-official-odds.json.gz'),'--out',str(out_path),'--insert']
        mod.main()
    finally: sys.argv=old


def verify_locked(collector,ids):
    for race_id in ids:
        rows=collector.d1_query('''SELECT course,COUNT(*) AS tickets,COUNT(DISTINCT bet_type) AS betTypes,SUM(stake_yen) AS stakeYen,MAX(CASE WHEN source_prediction_id=-2 THEN 1 ELSE 0 END) AS finalSource FROM rt_public_bets WHERE race_id=? GROUP BY course''',[race_id])
        by={str(r['course']):r for r in rows}
        if set(by)!=set(COURSE_BUDGETS): raise RuntimeError(f'AUTO_PUBLIC_COURSES_MISSING:{race_id}:{sorted(by)}')
        for course,budget in COURSE_BUDGETS.items():
            row=by[course]
            if int(row.get('tickets') or 0)!=2 or int(row.get('betTypes') or 0)!=2 or int(row.get('stakeYen') or 0)!=budget or int(row.get('finalSource') or 0)!=1:
                raise RuntimeError(f"AUTO_CANONICAL_BET_GATE_FAILED:{race_id}:{course}:tickets={row.get('tickets')}:types={row.get('betTypes')}:stake={row.get('stakeYen')}:source={row.get('finalSource')}")


def verify_official_bodyweights(collector,ids):
    verified=[]
    for race_id in ids:
        state_rows=collector.d1_query(
            'SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1',
            [f'{BODYWEIGHT_STATE_PREFIX}{race_id}'],
        )
        if not state_rows: raise RuntimeError(f'AUTO_BODYWEIGHT_SNAPSHOT_MISSING:{race_id}')
        try: snapshot=json.loads(str(state_rows[0].get('value') or '{}'))
        except json.JSONDecodeError as exc: raise RuntimeError(f'AUTO_BODYWEIGHT_SNAPSHOT_JSON_INVALID:{race_id}') from exc
        if snapshot.get('version')!=1 or snapshot.get('raceId')!=race_id: raise RuntimeError(f'AUTO_BODYWEIGHT_SNAPSHOT_IDENTITY_INVALID:{race_id}')
        if not isinstance(snapshot.get('snapshotSha256'),str) or len(snapshot['snapshotSha256'])!=64: raise RuntimeError(f'AUTO_BODYWEIGHT_SNAPSHOT_HASH_INVALID:{race_id}')
        body_rows=snapshot.get('activeRunners')
        if not isinstance(body_rows,list) or len(body_rows)<3: raise RuntimeError(f'AUTO_BODYWEIGHT_SNAPSHOT_RUNNERS_INVALID:{race_id}')
        official={int(row['horseNo']):(int(row['horseWeight']), None if row.get('weightChange') is None else int(row['weightChange'])) for row in body_rows}
        current=collector.d1_query(
            "SELECT horse_no AS horseNo,horse_weight AS horseWeight,weight_change AS weightChange FROM rt_runners WHERE race_id=? AND COALESCE(runner_status,'active')='active' ORDER BY horse_no",
            [race_id],
        )
        if len(current)<3: raise RuntimeError(f'AUTO_BODYWEIGHT_ACTIVE_RUNNERS_TOO_FEW:{race_id}:{len(current)}')
        for row in current:
            horse_no=int(row.get('horseNo') or 0)
            expected=official.get(horse_no)
            actual_weight=int(row['horseWeight']) if row.get('horseWeight') is not None else None
            actual_change=int(row['weightChange']) if row.get('weightChange') is not None else None
            if expected is None or actual_weight!=expected[0] or actual_change!=expected[1]:
                raise RuntimeError(f'AUTO_BODYWEIGHT_D1_MISMATCH:{race_id}:{horse_no}:{actual_weight}:{actual_change}:{expected}')
        verified.append(race_id)
    return verified


def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def check_only(collector):
    import lightgbm as lgb
    cfg=json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    if cfg.get('status')!='completed' or cfg.get('name')!='ten-year-completed-model': raise RuntimeError('CANONICAL_CONFIG_INVALID')
    expected=str(cfg['runnerProbabilityModel']['modelWeightsSha256']);actual=sha256(MODEL_PATH)
    if actual!=expected: raise RuntimeError(f'CANONICAL_MODEL_SHA_MISMATCH:{actual}:{expected}')
    booster=lgb.Booster(model_file=str(MODEL_PATH))
    features=cfg['runnerProbabilityModel']['features']
    if booster.num_feature()!=len(features) or len(features)!=56: raise RuntimeError(f'CANONICAL_MODEL_FEATURE_COUNT_INVALID:{booster.num_feature()}:{len(features)}')
    manifest=json.loads(STATE_MANIFEST_PATH.read_text(encoding='utf-8'))
    if manifest.get('throughDate')!='2026-08-09': raise RuntimeError(f"CANONICAL_STATE_DATE_INVALID:{manifest.get('throughDate')}")
    for rel,meta in manifest.get('files',{}).items():
        p=ROOT/rel
        if not p.exists() or sha256(p)!=str(meta.get('sha256')): raise RuntimeError(f'CANONICAL_STATE_SHA_INVALID:{rel}')
    tables=collector.d1_query("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('rt_races','rt_runners','rt_results','rt_payouts','rt_public_bets','rt_system_state')")
    names={str(r.get('name')) for r in tables};required={'rt_races','rt_runners','rt_results','rt_payouts','rt_public_bets','rt_system_state'}
    if names!=required: raise RuntimeError(f'AUTO_D1_TABLES_MISSING:{sorted(required-names)}')
    if not EXPLANATION_PATH.exists(): raise RuntimeError('SELECTION_EXPLANATION_SCRIPT_MISSING')
    print(json.dumps({'status':'check_ok','sourceModel':'ten-year-completed-model','modelSha256':actual,'features':len(features),'stateThroughDate':manifest['throughDate'],'tables':sorted(names),'selectionExplanationScript':str(EXPLANATION_PATH.relative_to(ROOT))},ensure_ascii=False))


def main():
    base=load(BASE_PATH,'legacy_auto_final_live_runtime')
    explanation=load(EXPLANATION_PATH,'ten_year_auto_selection_explanation')
    base.validate_selection=validate_selection
    base.generate_dynamic_selection=generate_selection
    base.run_learned_generator=run_generator
    base.verify_locked=verify_locked
    base.check_only=check_only
    base.COURSE_BUDGETS=COURSE_BUDGETS

    original_freeze_or_load_selection=base.freeze_or_load_selection
    def freeze_or_load_with_explanation(collector,date,out_path):
        payload,status=original_freeze_or_load_selection(collector,date,out_path)
        if payload is not None and status=='frozen':
            try:
                rows=explanation.ensure_selection_explanations(collector,date,payload)
                print(json.dumps({'selectionExplanation':'ok','date':date,'rows':len(rows),'selectionStatus':status},ensure_ascii=False))
            except Exception as exc:
                print(json.dumps({'selectionExplanation':'error','date':date,'error':str(exc),'selectionStatus':status},ensure_ascii=False),file=sys.stderr)
        return payload,status
    base.freeze_or_load_selection=freeze_or_load_with_explanation

    # Bodyweight is acquisition evidence, not a kill switch. Verify it when the
    # independent refresher has a snapshot, but never turn a transient JRA
    # bodyweight failure into "no prediction". The canonical fallback still
    # generates from the latest available D1 inputs and official odds.
    original_collect_official_odds=base.collect_official_odds
    def collect_after_bodyweight_audit(window_ids):
        collector=base.collector_module()
        try:
            verified=verify_official_bodyweights(collector,window_ids)
            print(json.dumps({'officialBodyweightStatus':'verified','officialBodyweightVerifiedRaceIds':verified},ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({'officialBodyweightStatus':'fallback_without_verified_snapshot','raceIds':window_ids,'warning':f'{type(exc).__name__}:{exc}'},ensure_ascii=False),file=sys.stderr)
        return original_collect_official_odds(window_ids)
    base.collect_official_odds=collect_after_bodyweight_audit

    # Cloudflare Worker is the one-minute primary path. GitHub Actions remains a
    # narrow independent fallback and must not pre-empt the Worker's fresher odds.
    # Never pre-empt T-15. Worker is primary at the boundary; this minute-loop
    # fallback may recover only after the boundary, during T-15..T-14.
    base.MIN_LOCK_SECONDS=14*60
    base.MAX_LOCK_SECONDS=15*60
    base.main()


if __name__=='__main__':main()
