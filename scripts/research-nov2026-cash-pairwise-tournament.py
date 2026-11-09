#!/usr/bin/env python3
"""Research-only: cash-weighted pairwise ticket tournament, NOT official T-15."""
import json
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
CUT=[0,10,55,100,190,310,1030]
FEATURES=('rankMin','rankMax','oddsGeom','rankGap','favOdds','fieldSize')
def design(z,lo,hi,rows):
    blocks=[]
    for k in FEATURES:
        x=z[k][rows,lo:hi].astype(int)
        n=int(z[k].max())+1
        blocks.append(np.eye(n,dtype=np.float32)[x])
    return np.concatenate(blocks,axis=2)
def fit_tournament(X,Y,years,train_year):
    # Learn ticket ranking by cash differences within the SAME race/market.
    # A centered cash target is the exact all-pairs squared ranking objective
    # (sum_ij ((score_i-score_j)-(cash_i-cash_j))**2).
    # Weight races by historical recency; never use the evaluation year.
    n,d=X.shape[1:]
    target=np.minimum(Y,np.quantile(Y,.997))
    target=target-target.mean(axis=1,keepdims=True)
    weight=np.power(.85,train_year-years).astype(np.float32)
    weight/=weight.sum()
    x=X-X.mean(axis=1,keepdims=True)
    # Ridge solves cash difference ranking without optimizing hit probability.
    gram=np.einsum('r,rnd,rne->de',weight,x,x,optimize=True)/n
    rhs=np.einsum('r,rnd,rn->d',weight,x,target,optimize=True)/n
    beta=np.linalg.solve(gram+np.eye(d)*30.,rhs)
    return beta
def run():
    with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as raw:
        z={k:raw[k] for k in FEATURES}
        paid=raw['payout'].astype(np.float32)
    races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
    years=np.array([int(r['month'][:4]) for r in races])
    out={}
    for year in (2023,2024,2025,2026):
        train=np.flatnonzero((years>=2015)&(years<year))
        test=np.flatnonzero(years==year)
        if not len(train) or not len(test):continue
        scores=[];indices=[]
        for market in range(6):
            lo,hi=CUT[market:market+2]
            Xtrain=design(z,lo,hi,train)
            beta=fit_tournament(Xtrain,paid[train,lo:hi],years[train],year)
            del Xtrain
            Xtest=design(z,lo,hi,test)
            s=np.einsum('rnd,d->rn',Xtest,beta)
            del Xtest
            # Add historical mean cash by market, never test payouts.
            s+=np.minimum(paid[train,lo:hi],np.quantile(paid[train,lo:hi],.997)).mean()
            j=np.argmax(s,axis=1)
            scores.append(s[np.arange(len(test)),j]);indices.append(lo+j)
        scores=np.array(scores).T;indices=np.array(indices).T
        groups=defaultdict(list)
        for j,i in enumerate(test):
            a,b=sorted(range(6),key=lambda m:(-scores[j,m],m))[:2]
            r=races[int(i)]
            key=(r.get('venue',r['id'][4:6]),r.get('day',r['id'][:8]))
            groups[key].append((float(scores[j,a]+scores[j,b]),int(i),a,b,int(indices[j,a]),int(indices[j,b])))
        chosen=[]
        for rows in groups.values():
            rows.sort(key=lambda q:(-q[0],races[q[1]]['id']))
            chosen.extend(rows[:5])
        # Dataset payout is in 100-yen units. Two 100-yen tickets per race.
        cash=np.array([100*(paid[i,x]+paid[i,y]) for _,i,a,b,x,y in chosen])
        stake=200*len(chosen);gross=float(cash.sum())
        result=dict(trainYears=[int(years[train].min()),int(years[train].max())],
                    evaluationYear=year,candidateRaces=len(test),selectedRaces=len(chosen),
                    tickets=2*len(chosen),marketPairs=dict(Counter(f'{a}-{b}' for _,i,a,b,x,y in chosen)),
                    stakeYen=stake,payoutYen=round(gross),
                    roiPct=round(100*gross/stake,3) if stake else None,
                    minusMaxPayoutRoiPct=round(100*(gross-cash.max())/stake,3) if stake else None,
                    previouslyInspected=year>=2025)
        out[str(year)]=result
        print('CASH_TOURNAMENT',json.dumps(result,ensure_ascii=False),flush=True)
    path=ROOT/'analysis-results/nov2026-cash-pairwise-tournament.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(dict(hypothesis='within-race cash-weighted all-pairs ranking learns relative ticket value; not ANOVA, nearest-neighbor or payout threshold selection',officialT15=False,adopted=False,results=out),indent=2)+'\n')
if __name__=='__main__':run()
