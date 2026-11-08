#!/usr/bin/env python3
"""Reproducible worker asset export from frozen independent-year 2026 research.

Never retrains, reads D1, or changes public bets. The uploaded joblib is an
unvalidated forward-production candidate, not an established profitable model.
"""
from pathlib import Path
import hashlib, json, joblib

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"research-frozen-2026-pooled-lambdarank-hurdle.joblib"
TARGET=ROOT/"src/v1/nov2026-payout-hurdle-model.json"
SOURCE_SHA="0af2775a4974e108a8008d3af953e8560b666c30ab1e17fb9ebe579e87d5496b"

def light_trees(model):
    def convert(node,out):
        ix=len(out);out.append(None)
        if "leaf_value" in node:
            out[ix]=[1,float(node["leaf_value"])]
        else:
            l=convert(node["left_child"],out)
            r=convert(node["right_child"],out)
            out[ix]=[0,int(node["split_feature"]),float(node["threshold"]),l,r,
                bool(node.get("default_left",False)),str(node.get("missing_type","None"))]
        return ix
    trees=[]
    for tree in model.booster_.dump_model()["tree_info"]:
        out=[];convert(tree["tree_structure"],out);trees.append(out)
    return trees

def hgb_trees(model):
    trees=[]
    for stage in model._predictors:
        assert len(stage)==1
        nodes=stage[0].nodes
        out=[]
        for n in nodes:
            if n["is_leaf"]:out.append([1,float(n["value"])])
            else:out.append([0,int(n["feature_idx"]),float(n["num_threshold"]),
                int(n["left"]),int(n["right"]),bool(n["missing_go_to_left"])])
        trees.append(out)
    return {"baseline":float(model._baseline_prediction[0,0]),"trees":trees}

def main():
    assert SOURCE.is_file(), "EXACT_TRAINED_MODEL_ASSET_MISSING"
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==SOURCE_SHA, "MODEL_SHA_MISMATCH"
    m=joblib.load(SOURCE)
    assert m["researchOnly"] is True and m["horseFeatureCount"]==56
    assert m["ticketFeatureCount"]==40 and m["2026OutcomesUsedToTrain"] is False
    assert m["notProvenProfitablyForward"] is True
    out={
      "name":"nov2026-frozen-pooled-twohead-research",
      "trainThrough":"2025-12-28",
      "evalPeriod":"2026-01-04..2026-08-09",
      "validationHitPct":33.58,
      "validationRoiPct":127.95,
      "validationRoiWithoutLargestPct":63.21,
      "notProductionValidated":True,
      "horseFeatureCount":56,
      "ticketFeatureCount":40,
      "ranker":light_trees(m["horseRanker"]),
      "top3":hgb_trees(m["horseTop3"]),
      "hit":hgb_trees(m["ticketHits"]),
      "paid":hgb_trees(m["ticketConditionalPaidMultiplier"]),
      "priors":m["typeBaseRatePriors"]
    }
    assert len(out["ranker"])==190
    assert [len(out[k]["trees"]) for k in ("top3","hit","paid")]==[120,110,115]
    TARGET.parent.mkdir(parents=True,exist_ok=True)
    TARGET.write_text(json.dumps(out,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
    print("NOV2026_EXACT_JOBLIB_WORKER_PORT_ASSET_OK",
          hashlib.sha256(TARGET.read_bytes()).hexdigest(),TARGET.stat().st_size)
if __name__=="__main__":main()
