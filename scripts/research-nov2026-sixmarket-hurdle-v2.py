#!/usr/bin/env python3
"""Genuinely new six-market payout-head architecture (no production changes).

2024/25 historical JRA outcomes train the model; 2026 payouts only settle.
Each of six bet types has a separate LightGBM probability head and separately
capped conditional-payout head, shrunk toward the shared two-part baseline.
No synthetic/postrace odds used as a feature. Historical runner T-15 provenance
is not established, so all results are research only.
"""
from __future__ import annotations

import importlib.util
import json
import math
from collections import defaultdict
from pathlib import Path
import sys

import numpy as np
from lightgbm import LGBMClassifier, LGBMRegressor

ROOT=Path(__file__).resolve().parents[1]
HERE="scripts/research-nov2026-fresh-robust200.py"
OUT=ROOT/"analysis-results/nov2026-sixmarket-calibrated-hurdle-actual-JRA.json"
TYPES=("単勝","ワイド","馬連","馬単","3連複","3連単")

def load_base():
    spec=importlib.util.spec_from_file_location("nov26base",ROOT/HERE)
    assert spec and spec.loader
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod

class SixMarketHurdle:
    def __init__(self,shared,per_market):
        self.shared=shared
        self.per_market=per_market

def fit_payout_v2(base,X,paid,hit):
    if X.shape[1]!=40 or len(X)!=len(hit) or len(X)!=len(paid):
        raise ValueError("SIXMARKET_TICKET_SHAPE_INVALID")
    if not (np.isfinite(X).all() and np.isfinite(paid).all()):
        raise ValueError("NONFINITE_MARKET_TRAINING")
    if not set(np.unique(hit)).issubset({0,1}):
        raise ValueError("NONBINARY_TICKET_OUTCOMES")
    shared=base.fit_payout_v1(X,paid,hit)
    per_market={}
    for idx,kind in enumerate(TYPES):
        selected=X[:,idx]>.5
        rows=np.flatnonzero(selected)
        winners=np.flatnonzero(selected&(hit==1))
        if len(rows)<1500 or len(winners)<25:
            raise ValueError(f"SIXMARKET_MIN_TRAINING:{kind}:{len(rows)}:{len(winners)}")
        # Remove redundant one-hot market columns: type is fixed per head.
        xx=np.asarray(X[rows,6:],dtype=np.float32)
        yy=np.asarray(hit[rows],dtype=np.int8)
        ph=LGBMClassifier(
            objective="binary",n_estimators=100,learning_rate=.035,
            num_leaves=12,min_child_samples=130,
            colsample_bytree=.85,reg_lambda=17,reg_alpha=1.0,
            random_state=20261108,n_jobs=2,verbosity=-1)
        ph.fit(xx,yy)
        # The p90 tail cap is determined using training labels only.
        paid_win=np.asarray(paid[winners],dtype=np.float64)/100.0
        cap=float(max(1.0,np.quantile(paid_win,.90)))
        capped=np.log(np.clip(paid_win,1.0,cap))
        sh=LGBMRegressor(
            objective="regression",n_estimators=100,learning_rate=.035,
            num_leaves=9,min_child_samples=35,
            colsample_bytree=.8,reg_lambda=24,reg_alpha=1.5,
            random_state=20261108,n_jobs=2,verbosity=-1)
        sh.fit(np.asarray(X[winners,6:],dtype=np.float32),capped)
        hit_prior=float((len(winners)+12)/(len(rows)+80))
        paid_prior=float(np.mean(np.minimum(paid_win,cap)))
        per_market[kind]={
            "hitHead":ph,"paidHead":sh,"trainingCap":cap,
            "empiricalHitPrior":hit_prior,
            "empiricalPaidPrior":paid_prior,
            "trainCandidateTickets":int(len(rows)),
            "trainPaidTickets":int(len(winners))}
    return SixMarketHurdle(shared,per_market)

def score_payout_v2(X,metadata,models):
    shared_hit,shared_conditional,shared_caps,shared_priors=models.shared
    by_race=defaultdict(list)
    if X.shape[1]!=40 or len(X)!=len(metadata):
        raise ValueError("MARKET_PREDICTION_ALIGNMENT_INVALID")
    sh=np.clip(shared_hit.predict_proba(X)[:,1],1e-8,1.0)
    sc=np.exp(np.clip(shared_conditional.predict(X),-30,30))
    for idx,kind in enumerate(TYPES):
        choices=np.flatnonzero(X[:,idx]>.5)
        if len(choices)==0:continue
        other=models.per_market[kind]
        xx=np.asarray(X[choices,6:],dtype=np.float32)
        local_prob=np.clip(other["hitHead"].predict_proba(xx)[:,1],1e-7,1)
        local_paid=np.exp(np.clip(other["paidHead"].predict(xx),-30,30))
        cap=float(other["trainingCap"])
        hit_prior=float(other["empiricalHitPrior"])
        paid_prior=float(other["empiricalPaidPrior"])
        shrunk_prob=.75*local_prob+.20*sh[choices]+.05*hit_prior
        shrunk_paid=.65*np.clip(local_paid,1,cap)+.20*np.clip(sc[choices],1,cap)+.15*paid_prior
        # The real historical payout labels are NEVER capped on settlement.
        # This learned utility deliberately discounts single-ticket jackpots.
        penalty=1/(1+.2*np.maximum(0,shrunk_paid-12)/12)
        estimates=shrunk_prob*shrunk_paid*penalty
        for j,p,h,ev in zip(choices,shrunk_prob,shrunk_paid,estimates):
            if not (np.isfinite(p) and np.isfinite(h) and np.isfinite(ev)):
                raise ValueError("SIXMARKET_NONFINITE_SCORE")
            day,r,t=metadata[int(j)]
            if t[0][0]!=kind:raise ValueError("JRA_MARKET_HEAD_TYPE_MISMATCH")
            by_race[(day,r["raceId"])].append({
                "key":t[0],"payout100":int(t[3]),
                "hitP":float(p),"riskAdjustedE":float(ev)})
    return by_race

def self_test():
    # Stationary synthetic ONLY for numerical type/head smoke verification;
    # never confuse this with genuine JRA historical performance.
    b=load_base()
    b.fit_payout_v1=b.fit_payout
    rng=np.random.default_rng(20261108)
    n=12000
    X=np.zeros((n,40),dtype=np.float32)
    y=np.zeros(n,dtype=np.int8)
    paid=np.zeros(n,dtype=np.float64)
    for i in range(n):
        typ=i%6
        X[i,typ]=1.0
        X[i,6:]=rng.normal(size=34)
        p=.27 + .08*np.tanh(X[i,6])-.02*typ
        y[i]=int(rng.random()<p)
        if y[i]: paid[i]=100*max(1,(2+typ)*math.exp(.2*float(X[i,7])+float(rng.normal(0,.35))))
    m=fit_payout_v2(b,X,paid,y)
    assert set(m.per_market)==set(TYPES)
    assert all(v["trainPaidTickets"]>25 and v["trainingCap"]>1
               for v in m.per_market.values())
    mock=[]
    for i in range(n):
        kind=TYPES[i%6]
        mock.append((("2025-01-01","東京"),
                     {"raceId":f"race{i//6}"},
                     ((kind,(1,)),(1,),0.2,int(paid[i]))))
    scores=score_payout_v2(X,mock,m)
    assert len(scores)==2000 and all(len(a)==6 for a in scores.values())
    assert all(np.isfinite(x["riskAdjustedE"]) and 0<x["hitP"]<1
               for rows in scores.values() for x in rows)
    # A market-specific change should NOT leak into another market head.
    p=m.per_market["単勝"]["trainingCap"]
    assert p==float(np.quantile(paid[(X[:,0]>.5)&(y==1)]/100,.90))
    print("NOV2026_SIXMARKET_TWO_PART_HEADS_SYNTHETIC_UNIT_OK")

def main():
    if "--self-test" in sys.argv:
        self_test();return
    base=load_base()
    base.fit_payout_v1=base.fit_payout
    base.fit_payout=lambda X,paid,hit:fit_payout_v2(base,X,paid,hit)
    base.estimate_payout=lambda X,metadata,models:score_payout_v2(X,metadata,models)
    base.OUT=OUT
    base.main()
    evidence=json.loads(OUT.read_text(encoding="utf-8"))
    evidence["researchVersion"]="nov2026-six-market-shrunk-two-part-p90-tail-v2"
    evidence["separateMarketHeads"]=list(TYPES)
    evidence["priorBase"]="shared two-head HGB; market-specific LightGBM classifiers and log-paid regressors"
    evidence["notProven2026NovT15"]=True
    evidence["productionPromotionAllowed"]=False
    OUT.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NOV2026_SIXMARKET_V2_MODEL_RESEARCH",json.dumps({
        "metrics":evidence["metrics"],
        "numericGatePassed":evidence["numericGatePassed"],
        "productionPromotionAllowed":False},ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
