#!/usr/bin/env python3
import argparse
import datetime as dt
import gzip
import importlib.util
import itertools
import json
import math
from pathlib import Path

import lightgbm as lgb
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
CORE_PATH=ROOT/'scripts'/'ten-year-production-core.py'
COLLECTOR_PATH=ROOT/'scripts'/'collect-jra-official-odds.py'
COURSE_STAKES={'ライト':[1000,1000],'スタンダード':[2500,2500],'プレミアム':[5000,5000]}
BET_ORDER=('単勝','ワイド','馬連','馬単','3連複','3連単')


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def combo_positions(kind,n):
    if kind=='単勝': return ((i,) for i in range(n))
    if kind in ('ワイド','馬連'): return itertools.combinations(range(n),2)
    if kind=='馬単': return itertools.permutations(range(n),2)
    if kind=='3連複': return itertools.combinations(range(n),3)
    if kind=='3連単': return itertools.permutations(range(n),3)
    raise RuntimeError(f'UNKNOWN_BET_TYPE:{kind}')


def combo_text(kind,pos,horse_nos):
    vals=[horse_nos[i] for i in pos]
    if kind in ('ワイド','馬連','3連複'): vals=sorted(vals)
    return '-'.join(str(x) for x in vals)


def load_odds(path,selected_ids):
    with gzip.open(path,'rt',encoding='utf-8') as fh: rows=json.load(fh)
    out={};coverage=set()
    for row in rows:
        rid=str(row.get('raceId') or '')
        if rid not in selected_ids: continue
        bt=str(row.get('betType') or '');combo=str(row.get('combination') or '')
        if not bt or not combo: continue
        try:
            lo=float(row.get('oddsMin'));hi=float(row.get('oddsMax'))
        except (TypeError,ValueError):
            continue
        odd=(lo+hi)/2.0
        if not math.isfinite(odd) or odd<=0: continue
        out[(rid,bt,combo)]=odd;coverage.add(rid)
    return out,coverage


def choose_two(core,rid,runners,w,odds):
    horse_nos=[int(r['horseNo']) for r in runners];n=len(runners);by_type=[]
    for bt in BET_ORDER:
        candidates=[]
        for pos in combo_positions(bt,n):
            combo=combo_text(bt,pos,horse_nos);odd=odds.get((rid,bt,combo))
            if odd is None: continue
            p=float(core.combination_probability(bt,pos,w))
            if not math.isfinite(p) or p<=0: continue
            candidates.append({'betType':bt,'combination':combo,'horses':[horse_nos[i] for i in pos],'predictedProbability':p,'officialOdds':odd,'valueProduct':p*odd})
        if not candidates: raise RuntimeError(f'OFFICIAL_ODDS_MISSING_BET_TYPE:{rid}:{bt}')
        candidates.sort(key=lambda x:(-x['valueProduct'],x['officialOdds'],x['combination']))
        retained=candidates[:5]
        for x in retained:x['score']=math.log(x['predictedProbability'])+0.4*math.log(x['officialOdds'])
        retained.sort(key=lambda x:(-x['score'],-x['predictedProbability'],x['combination']))
        by_type.append(retained[0])
    by_type.sort(key=lambda x:(-x['score'],BET_ORDER.index(x['betType']),x['combination']))
    chosen=[]
    for x in by_type:
        if all(y['betType']!=x['betType'] for y in chosen): chosen.append(x)
        if len(chosen)==2: break
    if len(chosen)!=2 or len({x['betType'] for x in chosen})!=2: raise RuntimeError(f'CANONICAL_TWO_DISTINCT_TYPES_FAILED:{rid}')
    return chosen


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--repo',default='.');ap.add_argument('--date',required=True);ap.add_argument('--selection',required=True);ap.add_argument('--out',required=True);ap.add_argument('--odds-file',required=True);ap.add_argument('--insert',action='store_true');a=ap.parse_args()
    core=load(CORE_PATH,'ten_year_production_core_bets');collector=load(COLLECTOR_PATH,'ten_year_bets_collector');cfg=core.load_config()
    sel=json.loads(Path(a.selection).read_text(encoding='utf-8'))
    if sel.get('sourceModel')!='ten-year-completed-model' or sel.get('resultDataUsedForTargetDay') is not False: raise RuntimeError('CANONICAL_SELECTION_INVALID')
    ids=[str(r['raceId']) for r in sel.get('selected',[])];selected_ids=set(ids)
    odds,coverage=load_odds(Path(a.odds_file),selected_ids)
    target_ids=[rid for rid in ids if rid in coverage]
    if not target_ids: raise RuntimeError('NO_WINDOW_RACES_IN_OFFICIAL_ODDS')

    state=core.load_feature_state();delta=core.delta_bundles(collector,state['throughDate'],a.date);core.advance_feature_state(state,delta)
    target_map={str(b['race']['raceId']):b for b in core.target_bundles(collector,a.date)}
    booster=lgb.Booster(model_file=str(core.MODEL_PATH));features=list(cfg['runnerProbabilityModel']['features'])
    if booster.num_feature()!=len(features):raise RuntimeError(f'MODEL_FEATURE_COUNT_INVALID:{booster.num_feature()}/{len(features)}')
    generated_at=dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z');out=[]
    for rid in target_ids:
        b=target_map.get(rid)
        if b is None: raise RuntimeError(f'TARGET_RACE_NOT_IN_D1:{rid}')
        runners=[r for r in b.get('runners',[]) if (r.get('runnerStatus') or 'active')=='active'];runners.sort(key=lambda r:int(r.get('horseNo') or 0))
        if len(runners)<3:raise RuntimeError(f'TOO_FEW_ACTIVE_RUNNERS:{rid}:{len(runners)}')
        rows=[core.ml_feature_row(state,b['race'],r,len(runners)) for r in runners]
        x=np.asarray([[float(row[f]) for f in features] for row in rows],dtype=np.float64)
        raw=np.asarray(booster.predict(x),dtype=np.float64)
        if raw.shape!=(len(runners),) or not np.all(np.isfinite(raw)) or np.any(raw<=0):raise RuntimeError(f'MODEL_PREDICTION_INVALID:{rid}')
        w=raw/raw.sum();chosen=choose_two(core,rid,runners,w,odds)
        course_bets=[]
        for course,stakes in COURSE_STAKES.items():
            for i,t in enumerate(chosen):
                course_bets.append({'course':course,'betType':t['betType'],'combination':t['combination'],'stakeYen':stakes[i],'assumedOdds':t['officialOdds']})
        out.append({'raceId':rid,'raceDate':a.date,'venue':b['race'].get('venue'),'raceNo':b['race'].get('raceNo'),'sourceModel':'ten-year-completed-model','runnerProbabilities':[{'horseNo':int(runners[i]['horseNo']),'probability':float(w[i])} for i in range(len(runners))],'tickets':chosen,'courseBets':course_bets})

    artifact={'generatedAt':generated_at,'date':a.date,'sourceModel':'ten-year-completed-model','ticketsPerRace':2,'resultDataUsedForTargetDay':False,'officialOddsOnly':True,'races':out}
    op=Path(a.out);op.parent.mkdir(parents=True,exist_ok=True);op.write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if a.insert:
        collector.d1_query('''CREATE TABLE IF NOT EXISTS rt_public_bets (id INTEGER PRIMARY KEY AUTOINCREMENT,race_id TEXT NOT NULL,course TEXT NOT NULL,bet_type TEXT NOT NULL,combination TEXT NOT NULL,stake_yen INTEGER NOT NULL,assumed_odds REAL,return_yen INTEGER,settlement_status TEXT NOT NULL,locked_at TEXT,source_prediction_id INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(race_id,course,bet_type,combination))''')
        for race in out:
            rid=race['raceId']
            existing=collector.d1_query('SELECT COUNT(*) AS n FROM rt_public_bets WHERE race_id=?',[rid])
            if int(existing[0].get('n') or 0)!=0:raise RuntimeError(f'RACE_ALREADY_LOCKED:{rid}')
            for cb in race['courseBets']:
                collector.d1_query("INSERT INTO rt_public_bets(race_id,course,bet_type,combination,stake_yen,assumed_odds,return_yen,settlement_status,locked_at,source_prediction_id) VALUES(?,?,?,?,?,?,NULL,'pending',?,-2)",[rid,cb['course'],cb['betType'],cb['combination'],int(cb['stakeYen']),round(float(cb['assumedOdds']),6),generated_at])
            saved=collector.d1_query('SELECT course,bet_type,combination,stake_yen,assumed_odds FROM rt_public_bets WHERE race_id=? ORDER BY course,bet_type,combination',[rid])
            exp={(cb['course'],cb['betType'],cb['combination'],int(cb['stakeYen']),round(float(cb['assumedOdds']),6)) for cb in race['courseBets']}
            got={(str(x['course']),str(x['bet_type']),str(x['combination']),int(x['stake_yen']),round(float(x['assumed_odds']),6)) for x in saved}
            if got!=exp:raise RuntimeError(f'PUBLIC_BET_LOCK_VERIFY_FAILED:{rid}:{len(got)}/{len(exp)}')
    print(json.dumps({'sourceModel':'ten-year-completed-model','races':len(out),'raceIds':[r['raceId'] for r in out],'inserted':bool(a.insert)},ensure_ascii=False))


if __name__=='__main__':main()
