#!/usr/bin/env python3
import importlib.util,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'scripts/research-continuous-walkforward-demand.py'
s=importlib.util.spec_from_file_location('continuous_core',p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
LOCAL_WEIGHT=float(os.environ.get('CONT_LOCAL_WEIGHT','0.75'))
if not (0.0 <= LOCAL_WEIGHT <= 1.0): raise RuntimeError(f'INVALID_LOCAL_WEIGHT:{LOCAL_WEIGHT}')

def ticket_score(ticket,stats,bet_stats):
    bt=ticket['bt'];bn,bret=bet_stats[bt]
    bmean=m.mean_roi(bn,bret,m.BET_PRIOR,m.PRIOR_ROI)
    comps=[]
    for key in m.smod.candidate_keys(bt,ticket['vals']):
        n,ret=stats.get(key,(0,0))
        if n<m.MIN_N:continue
        km=m.mean_roi(n,ret,m.KEY_PRIOR,bmean)
        reliability=n/(n+m.KEY_PRIOR)
        complexity=1.0 if len(key[1])==1 else 0.92
        comps.append((km,reliability*complexity,n,key))
    if not comps:return bmean*0.95
    comps.sort(key=lambda x:(x[0],x[1],x[2]),reverse=True)
    top=comps[:m.TOP_COMPONENTS]
    w=sum(x[1] for x in top)
    local=sum(x[0]*x[1] for x in top)/w if w else bmean
    return (1.0-LOCAL_WEIGHT)*bmean+LOCAL_WEIGHT*local

m.ticket_score=ticket_score
m.main()
