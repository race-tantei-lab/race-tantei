#!/usr/bin/env python3
import argparse,collections,json,math
from pathlib import Path
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

FEATURES=['fieldSize','raceNo','venueCode','monthSin','monthCos','abilityMargin12','abilityMargin13','abilityStd','marketMargin12','marketStd','top1Agreement','top3Overlap','abilityTop1Popularity','abilityTop2Popularity','abilityTop3Popularity','abilityTop1MarketRank','marketTop1AbilityRank','scoreCorrelation']
EXPECTED_STRUCT=[{'date':'2020-03-29','venueCode':5,'eligible':2}]

def rank_rows(rows,key):return sorted(rows,key=lambda r:(-float(r[key]),int(r['horseNo'])))
def spearman(a,b):
    hs=sorted(set(a)&set(b));n=len(hs)
    if n<2:return 0.0
    ra={h:i for i,h in enumerate(sorted(hs,key=lambda h:(-a[h],h)),1)};rb={h:i for i,h in enumerate(sorted(hs,key=lambda h:(-b[h],h)),1)}
    d=sum((ra[h]-rb[h])**2 for h in hs);return 1.0-6.0*d/(n*(n*n-1))
def race_row(rows):
    a=rank_rows(rows,'abilityScore');m=rank_rows(rows,'marketScore');field=len(a);date=str(a[0]['raceDate']);month=int(date[5:7])
    am={int(r['horseNo']):float(r['abilityScore']) for r in a};mm={int(r['horseNo']):float(r['marketScore']) for r in m}
    ar={int(r['horseNo']):i for i,r in enumerate(a,1)};mr={int(r['horseNo']):i for i,r in enumerate(m,1)}
    topa=[int(r['horseNo']) for r in a[:3]];topm=[int(r['horseNo']) for r in m[:3]];winner=next((int(r['horseNo']) for r in rows if int(r.get('finishPosition') or 0)==1),None)
    pop_by_h={int(r['horseNo']):max(1,int(r.get('marketPopularity') or field+1)) for r in rows}
    captured=winner is not None and ar.get(winner,999)<=3;winner_pop=pop_by_h.get(winner,1)
    target=math.log1p(min(18,winner_pop)) if captured else 0.0
    vals=[float(r['abilityScore']) for r in a];mvals=[float(r['marketScore']) for r in m]
    return {'raceId':str(a[0]['raceId']),'raceDate':date,'venueCode':int(a[0]['venueCode']),'raceNo':int(a[0]['raceNo']),'fieldSize':field,'monthSin':math.sin(2*math.pi*month/12),'monthCos':math.cos(2*math.pi*month/12),'abilityMargin12':vals[0]-vals[1] if field>1 else 0.0,'abilityMargin13':vals[0]-vals[2] if field>2 else 0.0,'abilityStd':float(np.std(vals)),'marketMargin12':mvals[0]-mvals[1] if field>1 else 0.0,'marketStd':float(np.std(mvals)),'top1Agreement':int(topa[0]==topm[0]),'top3Overlap':len(set(topa)&set(topm)),'abilityTop1Popularity':pop_by_h[topa[0]],'abilityTop2Popularity':pop_by_h[topa[1]] if field>1 else pop_by_h[topa[0]],'abilityTop3Popularity':pop_by_h[topa[2]] if field>2 else pop_by_h[topa[0]],'abilityTop1MarketRank':mr[topa[0]],'marketTop1AbilityRank':ar[topm[0]],'scoreCorrelation':spearman(am,mm),'targetValueProxy':target,'abilityTop1Win':int(winner==topa[0]),'abilityTop3CapturedWinner':int(captured),'winnerPopularity':winner_pop if winner is not None else 0}
def model():return LGBMRegressor(objective='huber',n_estimators=260,learning_rate=0.035,num_leaves=23,min_child_samples=100,subsample=.85,colsample_bytree=.85,reg_alpha=.7,reg_lambda=4.0,random_state=20260811,n_jobs=-1,verbosity=-1)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--predictions-dir',required=True);ap.add_argument('--out',required=True);ap.add_argument('--meta',required=True);a=ap.parse_args()
    races=collections.defaultdict(list)
    for p in sorted(Path(a.predictions_dir).glob('all-race-ranker-20*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r=json.loads(line);races[str(r['raceId'])].append(r)
    rows=[race_row(v) for v in races.values()];rows.sort(key=lambda r:(r['raceDate'],r['venueCode'],r['raceNo']))
    if len(rows)<34000:raise RuntimeError(f'ALL_RACE_COVERAGE_TOO_LOW:{len(rows)}')
    years=sorted({r['raceDate'][:4] for r in rows});selected=[];struct=[];year_diag={};prior=[]
    for y in years:
        cur=[r for r in rows if r['raceDate'].startswith(y)]
        if len(prior)>=2000:
            tr=pd.DataFrame(prior);ev=pd.DataFrame(cur);mdl=model();mdl.fit(tr[FEATURES],tr['targetValueProxy']);scores=mdl.predict(ev[FEATURES]);method='past_oos_huber_value_proxy'
        else:
            scores=np.array([r['abilityMargin13']+.12*math.log1p(min(8,r['abilityTop1Popularity']))+.05*r['top3Overlap'] for r in cur]);method='fixed_warmup_heuristic'
        for r,s in zip(cur,scores):r['selectionScore']=float(s)
        by=collections.defaultdict(list)
        for r in cur:by[(r['raceDate'],r['venueCode'])].append(r)
        chosen_year=[]
        for (date,venue),rr in sorted(by.items()):
            rr.sort(key=lambda r:(-r['selectionScore'],r['raceNo']))
            if len(rr)<5:
                struct.append({'date':date,'venueCode':venue,'eligible':len(rr)});continue
            chosen_year.extend(rr[:5])
        selected.extend(chosen_year)
        year_diag[y]={'method':method,'allRaces':len(cur),'selectedRaces':len(chosen_year),'top1WinnerAccuracy':round(sum(r['abilityTop1Win'] for r in chosen_year)/len(chosen_year),6) if chosen_year else None,'top3WinnerCoverage':round(sum(r['abilityTop3CapturedWinner'] for r in chosen_year)/len(chosen_year),6) if chosen_year else None,'avgAbilityTop1Popularity':round(sum(r['abilityTop1Popularity'] for r in chosen_year)/len(chosen_year),4) if chosen_year else None,'avgTargetValueProxy':round(sum(r['targetValueProxy'] for r in chosen_year)/len(chosen_year),6) if chosen_year else None}
        prior.extend(cur)
    selected.sort(key=lambda r:(r['raceDate'],r['venueCode'],r['raceNo']))
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w',encoding='utf-8') as f:
        for r in selected:f.write(json.dumps({'raceId':r['raceId'],'raceDate':r['raceDate'],'venueCode':r['venueCode'],'raceNo':r['raceNo'],'selectionScore':round(r['selectionScore'],8),'requiredMarkets':['win','umaren','wide','umatan','trio','trifecta'],'targetDayResultsUsedForSelection':False,'futureYearResultsUsedForSelection':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False},ensure_ascii=False,separators=(',',':'))+'\n')
    meta={'purpose':'research_only_meta_reselection_five_per_venue_day','allEvaluationRaces':len(rows),'selectedRaces':len(selected),'selectedByYear':{y:sum(1 for r in selected if r['raceDate'].startswith(y)) for y in years},'diagnosticsByYear':year_diag,'structuralCancellationExceptions':struct,'targetDayResultsUsedForSelection':False,'futureYearResultsUsedForSelection':False,'officialOddsUsedForSelection':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    Path(a.meta).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(meta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
