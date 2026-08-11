#!/usr/bin/env python3
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from lightgbm import LGBMRanker

DROP={'raceId','raceDate','horseNoRaw','finishPosition','labelWin','labelTop3'}

def group_sizes(df):return df.groupby('raceId',sort=False).size().to_numpy()
def relevance(pos):
    p=np.asarray(pos,dtype=int);return np.where(p==1,3,np.where(p==2,2,np.where(p==3,1,0))).astype(int)
def model_params():
    return dict(objective='lambdarank',metric='ndcg',n_estimators=220,learning_rate=0.045,num_leaves=31,max_depth=-1,min_child_samples=80,subsample=0.85,colsample_bytree=0.85,reg_alpha=0.5,reg_lambda=3.0,random_state=20260811,n_jobs=-1,verbosity=-1,lambdarank_truncation_level=6,label_gain=[0,1,3,7])
def prep_features(df,market):
    x=df.copy()
    if 'marketPopularity' in x.columns:
        pop=x['marketPopularity'].to_numpy(dtype=float);field=np.maximum(1.0,x['fieldSize'].to_numpy(dtype=float));fixed=np.where(pop>0,pop,field+1.0)
        x['marketPopularity']=fixed
        if market:x['marketPopularityPct']=fixed/field
        else:x=x.drop(columns=['marketPopularity'])
    return x

def metrics(pred,df):
    tmp=df[['raceId','finishPosition']].copy();tmp['pred']=pred
    top=tmp.sort_values(['raceId','pred'],ascending=[True,False]).groupby('raceId',sort=False).head(1)
    top1=float((top['finishPosition']==1).mean()) if len(top) else 0.0
    ordered=tmp.sort_values(['raceId','pred'],ascending=[True,False]);ordered['rank']=ordered.groupby('raceId',sort=False).cumcount()+1
    winners=ordered[ordered['finishPosition']==1];mrr=float((1.0/winners['rank']).mean()) if len(winners) else 0.0
    top3=ordered[ordered['rank']<=3];win3=float(top3.groupby('raceId')['finishPosition'].apply(lambda s:(s==1).any()).mean()) if len(top3) else 0.0
    return {'top1WinnerAccuracy':round(top1,6),'winnerMRR':round(mrr,6),'winnerInTop3':round(win3,6),'races':int(tmp['raceId'].nunique())}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--features',required=True);ap.add_argument('--year',required=True);ap.add_argument('--out',required=True);ap.add_argument('--meta',required=True);a=ap.parse_args()
    year=int(a.year);df=pd.read_csv(a.features);df['raceDate']=df['raceDate'].astype(str);df['raceId']=df['raceId'].astype(str)
    if year==2016:train_end='2016-08-10';eval_start='2016-08-10';eval_end='2016-12-31'
    else:train_end=f'{year}-01-01';eval_start=f'{year}-01-01';eval_end='2026-08-09' if year==2026 else f'{year}-12-31'
    train=df[df['raceDate']<train_end].copy();ev=df[(df['raceDate']>=eval_start)&(df['raceDate']<=eval_end)].copy()
    train=train.sort_values(['raceDate','raceId','horseNoRaw']).reset_index(drop=True);ev=ev.sort_values(['raceDate','raceId','horseNoRaw']).reset_index(drop=True)
    if train['raceId'].nunique()<1000 or ev['raceId'].nunique()==0:raise RuntimeError(f'FOLD_SIZE_INVALID:{year}:{train["raceId"].nunique()}:{ev["raceId"].nunique()}')
    y=relevance(train['finishPosition']);feature_cols=[c for c in df.columns if c not in DROP];outputs={};met={}
    for variant,market in [('ability',False),('market',True)]:
        Xtr=prep_features(train[feature_cols],market);Xev=prep_features(ev[feature_cols],market)
        model=LGBMRanker(**model_params());model.fit(Xtr,y,group=group_sizes(train));pred=model.predict(Xev);outputs[variant]=pred;met[variant]=metrics(pred,ev)
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w',encoding='utf-8') as f:
        for i,r in ev.iterrows():
            f.write(json.dumps({'raceId':str(r['raceId']),'raceDate':str(r['raceDate']),'horseNo':int(r['horseNoRaw']),'finishPosition':int(r['finishPosition']),'abilityScore':float(outputs['ability'][i]),'marketScore':float(outputs['market'][i]),'marketPopularity':int(r.get('marketPopularity') or 0),'fieldSize':int(r.get('fieldSize') or 0),'raceNo':int(r.get('raceNo') or 0),'venueCode':int(r.get('venue') or 0),'targetRaceResultUsedForPrediction':False},ensure_ascii=False,separators=(',',':'))+'\n')
    meta={'purpose':'research_only_all_race_year_walkforward_runner_ranker','year':year,'trainEndExclusive':train_end,'evaluationStart':eval_start,'evaluationEnd':eval_end,'trainingRaces':int(train['raceId'].nunique()),'trainingRunners':len(train),'predictionRaces':int(ev['raceId'].nunique()),'predictionRunners':len(ev),'metrics':met,'futureRowsUsedForTraining':False,'sameDayRowsUsedForTraining':False,'targetRaceResultUsedForPrediction':False,'syntheticDataUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    Path(a.meta).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'year':year,'trainRaces':meta['trainingRaces'],'evalRaces':meta['predictionRaces'],'metrics':met},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
