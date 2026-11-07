#!/usr/bin/env python3
"""Independent ExtraTrees historical year-wise walk-forward, paired JRA hit+ROI.

2024 test: train on strictly pre-2024 race labels.
2025 test: refit on strictly pre-2025 race labels.
Uses the SAME predeclared ExtraTrees structure and ticket/race rule selected
after inspecting 2026; never call 2024/25 tests pristine blind holdouts.
Past runner weights may not be documented at T-15. Historical JRA D1 payouts
are actual payouts; NO postrace final odds are used as decision inputs.
A complete venue day must contain 12 race outcome contexts and all six JRA
payout market types for each of the three selected races. No backfills.
This file performs bounded, read-only, indexed D1 SELECTs and writes local
research artifacts only. It never changes public bets or Workers.
"""
from __future__ import annotations
import collections
import datetime as dt
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import sys
import urllib.request

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results"/"research-2024-2025-extratrees-yearwise-paired-jra-roi.json"
VALIDATION_YEARS=(2024,2025)
TYPES={"単勝","ワイド","馬連","馬単","3連複","3連単"}
UNORDERED={"ワイド","馬連","3連複"}
LIMIT=4800

def module(path,name):
    p=ROOT/path
    spec=importlib.util.spec_from_file_location(name,p)
    assert spec and spec.loader
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m
    spec.loader.exec_module(m)
    return m

def read_d1(sql,params):
    account=os.environ["CLOUDFLARE_ACCOUNT_ID"]
    database=os.environ["CLOUDFLARE_D1_DATABASE_ID"]
    token=os.environ["CLOUDFLARE_API_TOKEN"]
    url=f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{database}/query"
    req=urllib.request.Request(url,method="POST",timeout=None) if False else urllib.request.Request(url,method="POST",
        data=json.dumps({"sql":sql,"params":params}).encode(),
        headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=40) as f:
        result=json.load(f)
    if not result.get("success"):
        raise RuntimeError("JRA_D1_PAYOUT_READ_FAILED:"+str(result.get("errors"))[:240])
    return (result.get("result") or [{}])[0].get("results") or []

def payout_book():
    out=collections.defaultdict(dict)
    coverage={}
    for year in VALIDATION_YEARS:
        for month in range(1,13):
            if year==2024 and month<5:continue
            first=f"{year:04d}-{month:02d}-"
            nextdate=(dt.date(year,month,1)+dt.timedelta(days=35)).replace(day=1)
            last=nextdate.strftime("%Y-%m-")
            rows=read_d1("""SELECT race_id raceId,bet_type betType,combination,
                    payout_yen payoutYen FROM rt_payouts
                    WHERE race_id>=? AND race_id<?
                    ORDER BY race_id,bet_type,combination LIMIT 4800""",
                 [first,last])
            if len(rows)>=LIMIT:raise RuntimeError("MONTH_PAYOUT_ROWS_TRUNCATED:"+first)
            for x in rows:
                typ=x["betType"]
                combo=tuple(int(s) for s in str(x["combination"]).split("-"))
                if typ not in TYPES:continue
                if len(combo) != (1 if typ=="単勝" else 3 if typ in ("3連複","3連単") else 2):
                    raise ValueError("BAD_JRA_COMBINATION:"+str(x["raceId"]))
                if len(set(combo))!=len(combo):raise ValueError("BAD_JRA_DUPLICATE_HORSE")
                if typ in UNORDERED:combo=tuple(sorted(combo))
                key=typ,combo
                amount=int(x["payoutYen"])
                if amount<0:raise ValueError("NEGATIVE_JRA_PAYOUT")
                rid=x["raceId"]
                if key in out[rid] and out[rid][key]!=amount:
                    raise AssertionError("CONFLICTING_JRA_PAYOUT")
                out[rid][key]=amount
            coverage[first]={"rows":len(rows),"races":len({x["raceId"] for x in rows})}
            print("HISTORICAL_JRA_PAYOUT_MONTH",first,coverage[first],flush=True)
    return out,coverage

def eligible_metadata(by_date):
    data=[]
    for day in sorted(by_date):
        for bundle in by_date[day]:
            active=sorted((r for r in bundle["runners"] if r.get("runnerStatus") in (None,"","active")),
                          key=lambda x:int(x["horseNo"]))
            if len(active)<3:continue
            positions={r["horseNo"]:r.get("finishPosition") for r in bundle["results"]}
            if sum(positions.get(r["horseNo"])==1 for r in active)!=1:continue
            race=bundle["race"]
            data.append({"date":day,"venue":race["venue"],"no":race["raceNo"],
                "rid":race["raceId"],"horses":tuple(r["horseNo"] for r in active),
                "field":len(active)})
    return data

def summarize(rows):
    if not rows:return {"races":0,"hitRacePct":None,"roiPct":None}
    stake=sum(r["stake"] for r in rows)
    returned=sum(r["return"] for r in rows)
    hit=sum(r["hit"] for r in rows)
    biggest=max(r["return"] for r in rows)
    return {"races":len(rows),"hitRaces":hit,"hitRacePct":round(100*hit/len(rows),2),
        "stakeYen":stake,"returnYen":returned,"roiPct":round(100*returned/stake,2),
        "profitYen":returned-stake,"roiExcludingLargestRacePayoutPct":round(100*(returned-biggest)/stake,2),
        "winningTickets":sum(r["winningTickets"] for r in rows)}

def chosen_ticket_result(r,book):
    predicted=sorted(range(len(r["p"])),key=lambda j:(-r["p"][j],r["horses"][j]))
    nums=[r["horses"][j] for j in predicted]
    tickets=[("ワイド",tuple(sorted((nums[0],nums[1]))),200),
             ("馬連",tuple(sorted((nums[0],nums[2]))),1800)]
    out=0
    hits=0
    for typ,comb,stake in tickets:
        paid=int(book.get((typ,comb),0))*stake//100
        hits+=int(paid>0)
        out+=paid
    return {"stake":2000,"return":out,"hit":int(hits>0),"winningTickets":hits}

def run():
    h=module("scripts/postaug-support-chronological-56feature-validation.py","historic_features")
    core=h.core_module()
    arc=h.load_public_archive()
    by_date=h.load_bundles(arc)
    X,y,counts,dates,offsets,_,_,_,_=h.chronological_features(core,by_date)
    meta=eligible_metadata(by_date)
    assert len(meta)==len(counts), "RACE_ORDER_DIFFERENT_FROM_FEATURE_BUILDER"
    assert all(meta[i]["date"]==str(dates[i]) and
        meta[i]["field"]==int(counts[i]) for i in range(len(counts)))
    payout,monthly=payout_book()
    result={"status":"HISTORICAL_BACKTEST_RESEARCH_ONLY_NOT_T15_PROVEN",
        "model":"independent_extra_trees_120",
        "modelParameters":{"n_estimators":120,"max_depth":14,"min_samples_leaf":35,
            "max_features":0.7,"random_state":20261107},
        "ticketRule":"predeclared after 2026 results: rank 3R by top3 win-probability mass; WIDE top1,2 ¥200 + QUINELLA top1,3 ¥1,800",
        "source":"race-chronological historical pre-result feature family + actual historical JRA payouts from Cloudflare D1",
        "nonBlindBecause":"Rule chosen after 2026 and 2024/25 previous studies; not a pristine independent holdout",
        "missingFeatureProvenance":"historical bodyweight and several context fields not timestamp-verified T-15",
        "noRealT15Lock":True,"yearwise":{},"payoutMonthCoverage":monthly,
        "eligibility":"only 12-race venue-days; selected 3 races must each have six official payout types",
        "profitPromotionAllowed":False}
    for year in VALIDATION_YEARS:
        train=np.where(dates<f"{year}-01-01")[0]
        if len(train)<8000 or str(dates[train[-1]])>=f"{year}-01-01":
            raise AssertionError("TARGET_YEAR_TRAINING_LEAK")
        limit=int(offsets[int(train[-1])+1])
        model=ExtraTreesClassifier(n_estimators=120,max_depth=14,min_samples_leaf=35,
                   max_features=0.7,n_jobs=2,random_state=20261107)
        model.fit(X[:limit],y[:limit])
        test_start=f"{year}-05-04" if year==2024 else f"{year}-01-01"
        target=np.where((dates>=test_start)&(dates<f"{year+1}-01-01"))[0]
        if not len(target):raise AssertionError("NO_TARGET_YEAR_RACES")
        lo=int(offsets[target[0]])
        hi=int(offsets[target[-1]+1])
        raw=model.predict_proba(X[lo:hi])[:,1]
        groups=collections.defaultdict(list)
        offset=0
        for i in target:
            row=dict(meta[i])
            n=int(counts[i])
            pp=np.maximum(raw[offset:offset+n],1e-12)
            row["p"]=pp/pp.sum()
            groups[(row["date"],row["venue"])].append(row)
            offset+=n
        assert offset==len(raw)
        exclusions=collections.Counter()
        outcomes=[]
        sessions=0
        monthlyOut=collections.defaultdict(list)
        for (day,venue),rows in groups.items():
            if len(rows)!=12 or {r["no"] for r in rows}!=set(range(1,13)):
                exclusions["not_complete_12_race_venue_day"]+=1;continue
            def rank(row):
                p=row["p"]
                return sum(sorted(p,reverse=True)[:3])
            selected=sorted(rows,key=lambda row:(-rank(row),row["no"]))[:3]
            if any(set(k[0] for k in payout.get(row["rid"],{}))!=TYPES for row in selected):
                exclusions["missing_selected_six_market_payout"]+=1;continue
            sessions+=1
            for row in selected:
                v=chosen_ticket_result(row,payout[row["rid"]])
                outcomes.append(v)
                monthlyOut[day[:7]].append(v)
        result["yearwise"][str(year)]={
            "trainThroughYear":year-1,"trainRaces":int(len(train)),
            "targetEligibleRaces":int(len(target)),
            "venueDaysEvaluated":sessions,"rejectedVenueDays":dict(exclusions),
            "matchedHitAndRoi":summarize(outcomes),
            "monthly":{month:summarize(v) for month,v in sorted(monthlyOut.items())}}
        print("HISTORICAL_EXTRA_TREES_YEAR_PAIRED",year,
              json.dumps(result["yearwise"][str(year)],ensure_ascii=False),flush=True)
        del model
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("HISTORICAL_EXTRA_TREES_YEARWISE_COMPLETE",json.dumps({
        "yearwise":result["yearwise"],
        "nonBlindBecause":result["nonBlindBecause"],
        "profitPromotionAllowed":False},ensure_ascii=False),flush=True)

if __name__=="__main__":run()
