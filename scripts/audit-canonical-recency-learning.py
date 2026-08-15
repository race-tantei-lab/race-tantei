#!/usr/bin/env python3
import datetime as dt
import importlib.util
import json
import pathlib
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module

collector=load(ROOT/'scripts'/'collect-jra-official-odds.py','canonical_recency_audit_collector')
learning=load(ROOT/'scripts'/'live-recency-learning.py','canonical_recency_audit_learning')
now=dt.datetime.now(dt.timezone.utc);cutoff=now.isoformat().replace('+00:00','Z');today=(now+dt.timedelta(hours=9)).date().isoformat()
races=collector.d1_query("SELECT race_id AS raceId,race_date AS raceDate,venue,surface,race_no AS raceNo,start_time_utc AS startTimeUtc,status FROM rt_races WHERE race_date=? AND start_time_utc IS NOT NULL AND datetime(start_time_utc)<datetime(?) AND EXISTS (SELECT 1 FROM rt_results rr WHERE rr.race_id=rt_races.race_id AND rr.finish_position IS NOT NULL) ORDER BY start_time_utc",[today,cutoff])
if not races:
    print(json.dumps({'status':'NO_FINISHED_RACES_TODAY','date':today,'policy':learning.learning_policy()},ensure_ascii=False));raise SystemExit(0)
target=races[-1]
runners=collector.d1_query("SELECT horse_no AS horseNo,horse_name AS horseName,jockey,trainer,runner_status AS runnerStatus FROM rt_runners WHERE race_id=? AND COALESCE(runner_status,'active')='active' ORDER BY horse_no",[target['raceId']])
runner_rows,bet_rows=learning.load_recent_learning_rows(collector,today,cutoff)
factors,details,runner_audit=learning.build_runner_learning(runner_rows,target,runners,cutoff,today)
bet=learning.build_bet_learning(bet_rows,cutoff,today)
if len(races)>1 and int(runner_audit.get('sameDayFinishedRaces') or 0)<=0:
    raise RuntimeError('SAME_DAY_FINISHED_RESULTS_NOT_USED')
future_weight=learning.recency_weight((now+dt.timedelta(minutes=1)).isoformat().replace('+00:00','Z'),today,cutoff,today)
if future_weight!=0: raise RuntimeError(f'FUTURE_RESULT_WEIGHT_NONZERO:{future_weight}')
report={'status':'CANONICAL_RECENCY_PRODUCTION_OK','date':today,'cutoffUtc':cutoff,'finishedRacesAvailable':len(races),'targetAuditRaceId':target['raceId'],'runnerAudit':runner_audit,'betAudit':bet['audit'],'runnerFactorMin':min(factors) if factors else None,'runnerFactorMax':max(factors) if factors else None,'nonNeutralRunnerFactors':sum(1 for x in factors if abs(float(x)-1.0)>1e-9),'futureWeight':future_weight,'policy':learning.learning_policy(),'sampleRunnerDetails':details[:3]}
print(json.dumps(report,ensure_ascii=False))
