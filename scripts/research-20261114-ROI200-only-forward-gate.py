#!/usr/bin/env python3
"""No sub-200 model may exist, including in the Aug-Nov replay.

Read historical complete-search artifact first. If zero models satisfied
ROI200, maximum-event-removed ROI200, hit20, min3, there is NOTHING to replay.
Never promote a failed internal sweep calculation to a "model".
"""
from __future__ import annotations
import importlib.util,json,sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
INPUT=ROOT/"analysis-results/20261114-broad-causal-cash-sweep.json"
OUT=ROOT/"analysis-results/20261114-ROI200-only-forward-qualified-models.json"

def load(path,name):
    s=importlib.util.spec_from_file_location(name,ROOT/path)
    if s is None or s.loader is None:raise RuntimeError("MISSING_SOURCE:"+path)
    m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m

def main():
    broad=load("scripts/research-20261114-broad-causal-cash-sweep.py","roi200_only_model_verifier")
    if "--self-test" in sys.argv:
        broad.selftest()
        print("ROI200_ONLY_FORWARD_MODEL_CONTRACT_SELFTEST_OK",flush=True)
        return
    before=json.loads(INPUT.read_text(encoding="utf8"))
    candidates=before.get("search",{}).get("models",[])
    if not all(broad.strict_model_only(x["money"]) for x in candidates):
        raise RuntimeError("SUB200_MODEL_PRESENT_IN_HISTORICAL_ARTIFACT")
    approved=[]
    tested=0
    venue_day_coverage=None
    if candidates:
        core,races,paid,feat,market,slots=broad.historic_cash()
        _,_,state,months=broad.monthly_frozen_predictions(races,paid,feat,market,slots)
        if len(months)!=136 or any(int(x)>=202608 for x in months):
            raise RuntimeError("FUTURE_OUTCOME_USED_TO_FORM_STRATEGY")
        provider=load("scripts/research-20261114-net-profit-first-forward.py","official_jra_cash_replay")
        forward,venue_day_coverage=provider.d1_races()
        old_cache,old_rcache=core.CACHE,core.RACE_CACHE
        try:
            core.CACHE=ROOT/"analysis-results/roi200-only-forward-data-matrix.npz"
            core.RACE_CACHE=ROOT/"analysis-results/roi200-only-forward-races.json"
            core.CACHE.parent.mkdir(parents=True,exist_ok=True)
            core.full_features(forward)
            with np.load(core.CACHE,allow_pickle=False) as z:
                cash=np.asarray(z["payout"],np.int32)
                c={k:np.asarray(z[k],np.uint8) for k in broad.FEATURES}
        finally:
            core.CACHE,core.RACE_CACHE=old_cache,old_rcache
        t=np.arange(len(market),dtype=np.int32)[None,:]
        scores=broad.month_scores(state,c,market,slots,t)
        p=np.empty((len(forward),len(broad.MODES),6),np.int16)
        v=np.empty((len(forward),len(broad.MODES),6),np.float32)
        for m in range(6):
            tickets=np.flatnonzero(market==m)
            arg=np.argmax(scores[:,:,tickets],axis=2)
            p[:,:,m]=tickets[arg]
            v[:,:,m]=np.take_along_axis(scores[:,:,tickets],
                                        arg[:,:,None],axis=2)[:,:,0]
        for candidate in candidates:
            tested+=1
            m,_=broad.config_replay(forward,cash,p,v,candidate["policy"])
            if broad.strict_model_only(m):
                approved.append({"policy":candidate["policy"],
                                 "historical":candidate["money"],
                                 "forward":m})
    if not all(broad.strict_model_only(x["historical"]) and
               broad.strict_model_only(x["forward"]) for x in approved):
        raise RuntimeError("ROI200_CONTRACT_FAILED_AFTER_FORWARD")
    output={
        "status":"FULLY_VERIFIED_ROI200_MODELS" if approved else "NO_MODEL_CREATED",
        "historicalStrictQualifiedModelCount":len(candidates),
        "postAugustQualifiedModelCount":len(approved),
        "forwardEvaluations":tested,
        "models":approved,
        "noSub200Fallback":True,
        "noBelow200ModelsInOutput":True,
        "usedOfficialFinalOddsNotT15":tested>0,
        "venueDayCoverage":venue_day_coverage,
        "productionModified":False}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n")
    print("ONLY_STRICT_ROI200_CANDIDATE_FORWARD_RESULT",json.dumps({
        "status":output["status"],
        "historyModelCount":len(candidates),
        "forwardModelCount":len(approved),
        "forwardEvaluations":tested,
        "noFallback":True,
        "productionModified":False},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
