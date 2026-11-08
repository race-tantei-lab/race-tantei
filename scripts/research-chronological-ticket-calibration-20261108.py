#!/usr/bin/env python3
"""Research-only chronological ticket-hit calibration and value ranking.

JSON input rows: race_id, race_date, venue, bet_type, combination,
raw_hit_probability, odds, actual_payout100, stake_yen.
For each training row, observed_hit is 1 iff actual_payout100 > 0.
All odds must be recorded before the race (caller supplies proof); this
script refuses to label historical final odds as T-15. No D1 access.
"""
import argparse
import collections
import datetime as dt
import json
import math

def _validate(row):
    for k in ("race_id","race_date","venue","bet_type","combination","raw_hit_probability","odds","actual_payout100","stake_yen"):
        if k not in row: raise ValueError("missing "+k)
    dt.date.fromisoformat(row["race_date"])
    p=float(row["raw_hit_probability"]);o=float(row["odds"])
    if not math.isfinite(p) or not 0<=p<=1 or not math.isfinite(o) or o<1:
        raise ValueError("invalid probability/odds")
    if int(row["stake_yen"])!=1000 or int(row["actual_payout100"])<0:
        raise ValueError("invalid stake/payout")

def fit_isotonic(rows):
    """PAV with Laplace smoothing, grouped by bet type; train dates only."""
    models={}
    for typ in sorted({r["bet_type"] for r in rows}):
        pts=sorted((float(r["raw_hit_probability"]),int(r["actual_payout100"]>0)) for r in rows if r["bet_type"]==typ)
        if len(pts)<20:continue
        blocks=[]
        for p,y in pts:
            blocks.append([p,p,float(y),1])
            while len(blocks)>1 and blocks[-2][2]/blocks[-2][3]>blocks[-1][2]/blocks[-1][3]:
                b=blocks.pop();a=blocks[-1];a[1]=b[1];a[2]+=b[2];a[3]+=b[3]
        models[typ]=[(b[1],(b[2]+1)/(b[3]+2)) for b in blocks]
    return models

def calibrated(models,typ,p):
    blocks=models.get(typ)
    if not blocks:return None
    for right,val in blocks:
        if p<=right:return val
    return blocks[-1][1]

def evaluate(rows,models):
    grouped=collections.defaultdict(list)
    for r in rows:
        prob=calibrated(models,r["bet_type"],float(r["raw_hit_probability"]))
        if prob is None:continue
        # Odds here are supplied only for ranking. They must be independently
        # proven available before T-15; no settlement odds substitution.
        edge=prob*float(r["odds"])-1
        grouped[r["race_id"]].append((edge,r))
    races=[]
    for rid,items in sorted(grouped.items()):
        best={}
        for edge,r in items:
            typ=r["bet_type"]
            if typ not in best or edge>best[typ][0]:best[typ]=(edge,r)
        chosen=sorted(best.values(),key=lambda x:(-x[0],x[1]["bet_type"],x[1]["combination"]))[:2]
        if len(chosen)!=2:continue
        picks=[r for _,r in chosen]
        ret=sum(10*int(r["actual_payout100"]) for r in picks)
        races.append({"race_id":rid,"date":picks[0]["race_date"],"venue":picks[0]["venue"],"stake":2000,"return":ret,"hit":int(ret>0),
            "tickets":[{"type":r["bet_type"],"combination":r["combination"],"return":10*int(r["actual_payout100"])} for r in picks]})
    if not races:return {"races":0,"eligible":False}
    n=len(races);hit=sum(r["hit"] for r in races);stake=sum(r["stake"] for r in races);ret=sum(r["return"] for r in races)
    biggest=max(races,key=lambda r:r["return"])
    months=collections.defaultdict(lambda:[0,0,0])
    for r in races:
        m=months[r["date"][:7]];m[0]+=1;m[1]+=r["stake"];m[2]+=r["return"]
    return {"races":n,"hitRaces":hit,"hitPct":100*hit/n,"stakeYen":stake,"returnYen":ret,"netYen":ret-stake,
        "roiPct":100*ret/stake,"roiMinusLargestRacePct":100*(ret-biggest["return"])/(stake-biggest["stake"]) if n>1 else None,
        "eligible":5*hit>=n and ret>stake,
        "monthly":{k:{"races":v[0],"roiPct":100*v[2]/v[1]} for k,v in sorted(months.items())},
        "caveat":"Retrospective actual JRA payouts; pre-T15 odds provenance is not established by this file."}

def run(rows,train_through,test_from,test_through):
    for r in rows:_validate(r)
    if not train_through<test_from<=test_through:raise ValueError("nonchronological split")
    train=[r for r in rows if r["race_date"]<=train_through]
    test=[r for r in rows if test_from<=r["race_date"]<=test_through]
    if not train or not test:raise ValueError("empty train/test")
    if set(r["race_id"] for r in train)&set(r["race_id"] for r in test):
        raise ValueError("race leakage")
    return {"trainRows":len(train),"testRows":len(test),"calibrationTypes":sorted(fit_isotonic(train)),
            "test":evaluate(test,fit_isotonic(train))}

def self_test():
    train=[]
    for i in range(40):
        for typ in ("単勝","ワイド"):
            train.append({"race_id":f"train-{i}","race_date":"2024-06-01","venue":"東京","bet_type":typ,
                "combination":str(i+1),"raw_hit_probability":(i+1)/50,"odds":2.0,"actual_payout100":200 if i%3==0 else 0,"stake_yen":1000})
    test=[]
    for i in range(10):
        for typ in ("単勝","ワイド"):
            test.append({"race_id":f"test-{i}","race_date":"2025-06-01","venue":"東京","bet_type":typ,
                "combination":str(i+1),"raw_hit_probability":0.5,"odds":3.0,"actual_payout100":300 if i<3 else 0,"stake_yen":1000})
    v=run(train+test,"2024-12-31","2025-01-01","2025-12-31")
    assert v["test"]["races"]==10 and v["test"]["hitRaces"]==3 and v["test"]["roiPct"]==90
    assert not v["test"]["eligible"]
    try:
        run(train+test,"2025-12-31","2025-01-01","2025-12-31")
        raise AssertionError("leak not detected")
    except ValueError:pass
    print("CHRONOLOGICAL_TICKET_CALIBRATION_SELF_TEST_OK")

if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--input");ap.add_argument("--train-through");ap.add_argument("--test-from");ap.add_argument("--test-through");ap.add_argument("--self-test",action="store_true");args=ap.parse_args()
    if args.self_test:self_test()
    else:
        with open(args.input,encoding="utf-8") as f:rows=json.load(f)
        print(json.dumps(run(rows,args.train_through,args.test_from,args.test_through),ensure_ascii=False,indent=2))
