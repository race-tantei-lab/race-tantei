#!/usr/bin/env python3
import argparse,collections,json,math
from pathlib import Path
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

FEATURES=['fieldSize','raceNo','venueCode','monthSin','monthCos','abilityMargin12','abilityMargin13','abilityStd','abilityTop1Share','abilityTop3Share','abilityEntropy','abilitySkew']

def read_jsonl(p):
    with Path(p).open(encoding='utf-8') as f:
        for line in f:
            if line.strip():yield json.loads(line)

def rank_rows(rows):return sorted(rows,key=lambda r:(-float(r['abilityScore']),int(r['horseNo'])))
def softmax(vals):
    a=np.asarray(vals,dtype=float);a=a-a.max();e=np.exp(np.clip(a,-50,50));s=e.sum();return e/s if s>0 else np.ones_like(e)/len(e)
def race_row(rows):
    a=rank_rows(rows);field=len(a);date=str(a[0]['raceDate']);month=int(date[5:7]);vals=np.asarray([float(r['abilityScore']) for r in a],dtype=float);p=softmax(vals)
    winner=next((int(r['horseNo']) for r in rows if int(r.get('finishPosition') or 0)==1),None);ar={int(r['horseNo']):i for i,r in enumerate(a,1)};pop={int(r['horseNo']):max(1,int(r.get('marketPopularity') or field+1)) for r in rows};captured=winner is not None and ar.get(winner,999)<=3;winner_pop=pop.get(winner,1);target=math.log1p(min(18,winner_pop)) if captured else 0.0
    mean=float(vals.mean());std=float(vals.std());skew=float(np.mean(((vals-mean)/(std+1e-9))**3)) if field>2 else 0.0;entropy=float(-(p*np.log(np.maximum(p,1e-12))).sum())
    return {'raceId':str(a[0]['raceId']),'raceDate':date,'venueCode':int(a[0]['venueCode']),'raceNo':int(a[0]['raceNo']),'fieldSize':field,'monthSin':math.sin(2*math.pi*month/12),'monthCos':math.cos(2*math.pi*month/12),'abilityMargin12':vals[0]-vals[1] if field>1 else 0.0,'abilityMargin13':vals[0]-vals[2] if field>2 else 0.0,'abilityStd':std,'abilityTop1Share':float(p[0]),'abilityTop3Share':float(p[:3].sum()),'abilityEntropy':entropy,'abilitySkew':skew,'targetValueProxy':target,'abilityTop1Win':int(winner==int(a[0]['horseNo'])),'abilityTop3CapturedWinner':int(captured),'winnerPopularity':winner_pop if winner is not None else 0}
def model():return LGBMRegressor(objective='huber',n_estimators=260,learning_rate=.035,num_leaves=19,min_child_samples=100,subsample=.85,colsample_bytree=.9,reg_alpha=.8,reg_lambda=5.0,random_state=20260811,n_jobs=-1,verbosity=-1)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--predictions-dir',required=True);ap.add_argument('--out',required=True);ap.add_argument('--meta',required=True);a=ap.parse_args()
    races=collections.defaultdict(list)
    for p in sorted(Path(a.predictions_dir).glob('all-race-ranker-20*.jsonl')):
        for r in read_jsonl(p):races[str(r['raceId'])].append(r)
    rows=[race_row(v) for v in races.values()];rows.sort(key=lambda r:(r['raceDate'],r['venueCode'],r['raceNo']))
    if len(rows)!=34566:raise RuntimeError(f'ALL_RACE_COVERAGE_INVALID:{len(rows)}')
    years=sorted({r['raceDate'][:4] for r in rows});selected=[];struct=[];diag={};prior=[]
    for y in years:
        cur=[r for r in rows if r['raceDate'].startswith(y)]
        if len(prior)>=2000:
            tr=pd.DataFrame(prior);ev=pd.DataFrame(cur);mdl=model();mdl.fit(tr[FEATURES],tr['targetValueProxy']);scores=mdl.predict(ev[FEATURES]);method='past_years_value_proxy_no_current_market'
        else:
            scores=np.asarray([r['abilityMargin13']+.35*r['abilityTop3Share']-.05*r['abilityEntropy'] for r in cur]);method='fixed_premarket_warmup'
        for r,s in zip(cur,scores):r['selectionScore']=float(s)
        by=collections.defaultdict(list)
        for r in cur:by[(r['raceDate'],r['venueCode'])].append(r)
        chosen=[]
        for (date,venue),rr in sorted(by.items()):
            rr.sort(key=lambda r:(-r['selectionScore'],r['raceNo']))
            if len(rr)<5:
                struct.append({'date':date,'venueCode':venue,'eligible':len(rr)});continue
            chosen.extend(rr[:5])
        selected.extend(chosen)
        diag[y]={'method':method,'allRaces':len(cur),'selectedRaces':len(chosen),'top1WinnerAccuracy':round(sum(r['abilityTop1Win'] for r in chosen)/len(chosen),6) if chosen else None,'top3WinnerCoverage':round(sum(r['abilityTop3CapturedWinner'] for r in chosen)/len(chosen),6) if chosen else None,'avgWinnerPopularityWhenTop3Captured':round(sum(r['winnerPopularity'] for r in chosen if r['abilityTop3CapturedWinner'])/max(1,sum(r['abilityTop3CapturedWinner'] for r in chosen)),4) if chosen else None,'avgPastTargetProxyRealized':round(sum(r['targetValueProxy'] for r in chosen)/len(chosen),6) if chosen else None}
        prior.extend(cur)
    selected.sort(key=lambda r:(r['raceDate'],r['venueCode'],r['raceNo']))
    if len(selected)!=14410:raise RuntimeError(f'SELECTED_RACE_COUNT_INVALID:{len(selected)}')
    expected=[{'date':'2020-03-29','venueCode':6,'eligible':2}]
    if struct!=expected:raise RuntimeError(f'STRUCTURAL_EXCEPTION_INVALID:{struct}')
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w',encoding='utf-8') as f:
        for r in selected:f.write(json.dumps({'raceId':r['raceId'],'raceDate':r['raceDate'],'venueCode':r['venueCode'],'raceNo':r['raceNo'],'selectionScore':round(r['selectionScore'],8),'requiredMarkets':['win','umaren','wide','umatan','trio','trifecta'],'targetDayResultsUsedForSelection':False,'futureYearResultsUsedForSelection':False,'currentRaceMarketPopularityUsedForSelection':False,'currentRaceOfficialOddsUsedForSelection':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False},ensure_ascii=False,separators=(',',':'))+'\n')
    meta={'purpose':'research_only_premarket_meta_reselection_five_per_venue_day','allEvaluationRaces':len(rows),'selectedRaces':len(selected),'selectedByYear':{y:sum(1 for r in selected if r['raceDate'].startswith(y)) for y in years},'diagnosticsByYear':diag,'structuralCancellationExceptions':struct,'selectorFeatures':FEATURES,'targetDayResultsUsedForSelection':False,'futureYearResultsUsedForSelection':False,'currentRaceMarketPopularityUsedForSelection':False,'currentRaceOfficialOddsUsedForSelection':False,'pastYearsFinalPopularityUsedOnlyInTrainingTarget':True,'historicalFinalOddsTimingCaveatAppliesToPastTrainingTarget':True,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    Path(a.meta).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(meta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
