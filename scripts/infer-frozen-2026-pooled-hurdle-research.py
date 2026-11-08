#!/usr/bin/env python3
"""Offline-only inference for frozen research model artifact.

Input: race with EXACT canonical 56-feature runner rows reconstructed from
pre-result data. This tool never fetches odds, results, or wagers and never
treats modeled ROI as actual payout or real-world profit.

The frozen artifact is joblib, not Cloudflare Workers compatible.
Model lacks verified feature timestamp provenance and calibrated pre-T15
JRA market probabilities; no real-money or public production promotion.
"""
from __future__ import annotations
import argparse
import importlib.util,json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_MODEL=ROOT/"analysis-results/research-frozen-2026-pooled-lambdarank-hurdle.joblib"

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("DEPENDENCY_MISSING")
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod)
    return mod

def validate_input(inp):
    for field in ("date","venue","raceNo","horseNos","features56"):
        if field not in inp:raise ValueError("MISSING_FIELD:"+field)
    h=inp["horseNos"]
    try:x=np.asarray(inp["features56"],dtype=np.float32)
    except (ValueError,TypeError) as exc:raise ValueError("BAD_PRE_RESULT_56_FEATURE_INPUT") from exc
    if x.ndim!=2 or x.shape!=(len(h),56) or len(h)<3 or len(h)>18:
        raise ValueError("EXPECTED_VALID_RUNNER_56_MATRIX")
    if not np.isfinite(x).all():raise ValueError("NON_FINITE_RUNNER_FEATURES")
    if any(not isinstance(n,int) or n<1 or n>18 for n in h) or len(set(h))!=len(h):
        raise ValueError("INVALID_JRA_HORSE_NUMBERS")
    if not isinstance(inp["raceNo"],int) or not 1<=inp["raceNo"]<=12:
        raise ValueError("INVALID_JRA_RACE_NUMBER")
    return x

def choose(model,inp,struct,tickets):
    X=validate_input(inp)
    if model.get("researchOnly") is not True or model.get("horseFeatureCount")!=56:
        raise ValueError("NOT_THE_FROZEN_RESEARCH_MODEL")
    score=model["horseRanker"].predict(X)
    rawtop=model["horseTop3"].predict_proba(X)[:,1]
    if len(score)!=len(X) or len(rawtop)!=len(X):
        raise RuntimeError("MODEL_RUNNER_VECTOR_MISMATCH")
    p=struct.softmax(score,temp=1.4)
    p3=np.clip(rawtop,1e-6,1)
    row={"probs":p,"horses":tuple(inp["horseNos"]),"date":inp["date"],
          "raceNo":inp["raceNo"],"venue":inp["venue"],"payout":{}}
    candidates=tickets.enumerate_tickets(row)
    order=np.argsort(-p,kind="stable")
    place_ranks={int(h):i+1 for i,h in enumerate(np.argsort(-p3,kind="stable"))}
    feats=[]
    for ticket in candidates:
        key,ix,pr,_=ticket
        chosen=np.asarray([p3[i] for i in ix],dtype=np.float64)
        ranks=[place_ranks[i] for i in ix]
        extra=[
         *[float(p3[int(i)]) for i in order[:3]],
         float(sum(sorted(p3,reverse=True)[:3])/3),
         float(chosen.mean()),float(chosen.min()),
         float(chosen.prod()),float(sum(ranks)/36),
         float(max(ranks)/18),float(len(candidates)/200)
        ]
        feats.append(tickets.features(row,ticket)+extra)
    fx=np.asarray(feats,dtype=np.float32)
    if fx.shape[1]!=model["ticketFeatureCount"]:
        raise ValueError("TICKET_HEAD_FEATURE_COUNT_MISMATCH")
    pa=model["ticketHits"].predict_proba(fx)[:,1]
    amount=model["ticketConditionalPaidMultiplier"].predict(fx)
    priors=model["typeBaseRatePriors"]
    bytype={}
    for i,(key,ix,pr,_) in enumerate(candidates):
        name=key[0]
        prior=priors[name]
        hit=.87*float(pa[i])+.13*float(prior["hitPrior"])
        positive=.87*float(amount[i])+.13*float(prior["wonReturnPrior"])
        predicted=hit*positive
        data={"betType":name,"combination":"-".join(map(str,key[1])),
            "modelEstimatedWinProbability":round(hit,6),
            "modelEstimatedReturnPerYen":round(predicted,6),
            "modelPlackettLuceProbability":round(float(pr),6)}
        cur=bytype.get(name)
        if cur is None or predicted>cur[0]:
            bytype[name]=(predicted,data)
    if len(bytype)!=6:raise ValueError("INCOMPLETE_JRA_SIX_MARKET_CANDIDATES")
    ordered=sorted(bytype.values(),key=lambda x:-x[0])
    pairs=[]
    for i,a in enumerate(ordered):
        for b in ordered[i+1:]:
            if max(a[1]["modelEstimatedWinProbability"],b[1]["modelEstimatedWinProbability"])<.20:
                continue
            stake1,stake2=(1900,100) if a[0]>=b[0] else (100,1900)
            ev=a[0]*stake1+b[0]*stake2
            pairs.append((ev,a,b,stake1,stake2))
    if not pairs:
        return {"researchOnly":True,"noTicketPairWithModelHitProbability20Pct":True}
    ev,a,b,stake1,stake2=max(pairs,key=lambda row:row[0])
    return {
       "researchOnly":True,
       "bettable":False,
       "label":"UNVERIFIED_HISTORICAL_PAYOUT_MODEL_NOT_TRUE_T15",
       "race":{"date":inp["date"],"venue":inp["venue"],"raceNo":inp["raceNo"]},
       "horseModelTrainedThrough":"2025-12-28",
       "matchedResearchBudgetYen":2000,
       "ticket1":{**a[1],"stakeYen":stake1},
       "ticket2":{**b[1],"stakeYen":stake2},
       "hypotheticalModelEstimatedRoiPct":round(100*ev/2000,2),
       "notAnActualJraPayout":True,
       "noOddsTimestampProven":True,
       "noRealMoneyReadiness":True,
    }

def selftest():
    struct=load("scripts/research-structural-ranker-twohead-2025.py","infer_struct_test")
    tickets=load("scripts/research-two-stage-payout-value-2024-2025.py","infer_ticket_test")
    class PredictRanker:
        def predict(self,X):return np.array([2.1,1.0,.4])
    class PredictTop:
        def predict_proba(self,X):return np.array([[.4,.6],[.5,.5],[.7,.3]])
    class PredictHit:
        def predict_proba(self,X):return np.column_stack([np.full(len(X),.65),np.full(len(X),.35)])
    class PredictValue:
        def predict(self,X):return np.full(len(X),3.0)
    model={"researchOnly":True,"horseFeatureCount":56,
           "ticketFeatureCount":None,
           "horseRanker":PredictRanker(),"horseTop3":PredictTop(),
           "ticketHits":PredictHit(),"ticketConditionalPaidMultiplier":PredictValue(),
           "typeBaseRatePriors":{t:{"hitPrior":.2,"wonReturnPrior":5.0}
               for t in tickets.TYPES}}
    inp={"date":"2026-11-08","venue":"東京","raceNo":1,
         "horseNos":[1,2,3],"features56":[[0.]*56]*3}
    r={"probs":struct.softmax([2.1,1.,.4],temp=1.4),"horses":(1,2,3),
       "raceNo":1,"payout":{}}
    model["ticketFeatureCount"]=len(tickets.features(r,tickets.enumerate_tickets(r)[0]))+10
    out=choose(model,inp,struct,tickets)
    assert out["researchOnly"] and out["ticket1"]["betType"]!=out["ticket2"]["betType"]
    assert out["ticket1"]["stakeYen"]+out["ticket2"]["stakeYen"]==2000
    assert out["noRealMoneyReadiness"] and out["hypotheticalModelEstimatedRoiPct"]>0
    try:choose(model,{**inp,"horseNos":[1,1,3]},struct,tickets)
    except ValueError:pass
    else:raise AssertionError("RUNNER_DUPLICATE_GATE_FAILED")
    print("FROZEN_RESEARCH_MODEL_CAN_INFER_OFFLINE_SELFTEST_OK",flush=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--model",default=str(DEFAULT_MODEL))
    parser.add_argument("--input")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:selftest();return
    if not args.input:parser.error("--input required")
    import joblib
    struct=load("scripts/research-structural-ranker-twohead-2025.py","infer_struct")
    tickets=load("scripts/research-two-stage-payout-value-2024-2025.py","infer_ticket")
    with open(args.input,encoding="utf-8") as f: inp=json.load(f)
    result=choose(joblib.load(args.model),inp,struct,tickets)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
