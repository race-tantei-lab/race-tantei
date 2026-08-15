#!/usr/bin/env python3
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'scripts'/'live-recency-learning.py'
spec=importlib.util.spec_from_file_location('live_recency_learning_tested',PATH);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
cut='2026-08-15T11:00:00Z'
weights=[m.recency_weight('2026-08-15T08:00:00Z','2026-08-15',cut,'2026-08-15'),m.recency_weight('2026-08-14T08:00:00Z','2026-08-14',cut,'2026-08-15'),m.recency_weight('2026-08-09T08:00:00Z','2026-08-09',cut,'2026-08-15'),m.recency_weight('2026-07-18T08:00:00Z','2026-07-18',cut,'2026-08-15')]
assert weights[0]>weights[1]>weights[2]>weights[3],weights
assert m.recency_weight('2026-08-15T12:00:00Z','2026-08-15',cut,'2026-08-15')==0
rows=[]
for no,(j,odd,pos) in enumerate([('JGOOD',10,1),('JBAD',2,2),('JX',5,3),('JY',8,4)],1):
    rows.append({'raceId':'r1','raceDate':'2026-08-15','startTimeUtc':'2026-08-15T08:00:00Z','venue':'新潟','surface':'芝','horseNo':no,'horseName':f'H{no}','jockey':j,'trainer':'T'+str(no),'winOdds':odd,'finishPosition':pos})
current=[{'horseNo':1,'horseName':'NEW1','jockey':'JGOOD','trainer':'TN'},{'horseNo':2,'horseName':'NEW2','jockey':'JBAD','trainer':'TN'},{'horseNo':3,'horseName':'NEW3','jockey':'JX','trainer':'TN'}]
factors,_,audit=m.build_runner_learning(rows,{'venue':'新潟','surface':'芝'},current,cut,'2026-08-15')
assert factors[0]>factors[1],factors
assert audit['sameDayFinishedRaces']==1,audit
bets=[{'raceId':'r1','raceDate':'2026-08-15','startTimeUtc':'2026-08-15T08:00:00Z','venue':'新潟','betType':'単勝','stakeYen':1000,'returnYen':5000,'assumedOdds':5},{'raceId':'r1','raceDate':'2026-08-15','startTimeUtc':'2026-08-15T08:00:00Z','venue':'新潟','betType':'ワイド','stakeYen':1000,'returnYen':0,'assumedOdds':5}]
st=m.build_bet_learning(bets,cut,'2026-08-15')
assert m.bet_factor(st,'単勝','新潟',5)>m.bet_factor(st,'ワイド','新潟',5)
print({'status':'LIVE_RECENCY_LEARNING_TEST_OK','weights':weights,'runnerFactors':factors})
