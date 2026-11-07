#!/usr/bin/env python3
"""Large, forward-by-year exploratory grid: 0..5 race days, odds bands, ticket
selection, abstention, race context and pre-race ranking.

NO production, no D1, no official T15, no two-distinct-type bet. This is a
single-win hypothesis filter on historical FINAL win odds only. It must never
certify a profitable live strategy. The 2026 archive is already opened and
cannot be called untouched for post-hoc search.

The grid is *specified in code* before outcomes are used for picking a policy;
the strongest 2024 candidates are frozen before inspecting their 2025 outcomes.
"""
from __future__ import annotations
import collections
import importlib.util
import json
import math
from pathlib import Path
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
MAIN=ROOT/"scripts/research-chronological-56feature-validation.py"
OUT=ROOT/"analysis-results/research-wide-flexible-oof-20261107.json"
MIN_YEAR_BETS=80
TOP_TRAIN=100
MODE_NAMES=("model_top","market_favorite","max_ev","max_edge",
            "prob_price_04","prob_price_07","model_rank_two",
            "market_rank_two","model_late_market","model_price_1")
ODDS_BANDS={"all":(1,100000),"2_10":(2,10),"5_50":(5,50),
    "10_30":(10,30),"30_100":(30,100),"100_1000":(100,1000)}
EV_MIN=(0.0,1.0,2.0,3.0)
CONTEXTS=("all","turf","dirt","field_under_12","field_12_up")
PRIORITIES=("ev","model_probability")
RACE_COUNTS=(1,2,3,4,5)

def get_oos():
    spec=importlib.util.spec_from_file_location("research_base",MAIN)
    if not spec or not spec.loader:raise RuntimeError("research base missing")
    mod=importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod

def metadata(by_date):
    out=[]
    for date,day in sorted(by_date.items()):
        for bundle in day:
            runners=sorted((x for x in bundle["runners"] if x.get("runnerStatus") in
                (None,"","active")),key=lambda x:x["horseNo"])
            positions={x["horseNo"]:x["finishPosition"] for x in bundle["results"]}
            if len(runners)<3 or sum(positions.get(x["horseNo"])==1 for x in runners)!=1:
                continue
            r=bundle["race"]
            out.append((date,str(r["venue"]),int(r["raceNo"]),str(r.get("surface") or ""),
                        len(runners)))
    return out

def raw_records(mod,arrays,labels,counts,dates,offsets,winners,markets,meta,year):
    start=year+"-01-01";end=str(int(year)+1)+"-01-01"
    train=np.where(dates<start)[0]
    ix=np.where((dates>=start)&(dates<end))[0]
    assert ix.size>1000 and train.size>8000 and dates[train[-1]]<start
    fit=mod.fit(arrays,labels,offsets,train,mod.CANDIDATES["adopted_complexity_500x127"])
    baseline=int(offsets[ix[0]])
    raw=fit.predict_proba(arrays[baseline:int(offsets[ix[-1]+1])])[:,1]
    recs=[]
    for i in ix:
        odds=markets[i]
        if len(odds)!=int(counts[i]) or not all(
            v is not None and math.isfinite(v) and v>1.0 for v in odds):
            continue
        a,b=int(offsets[i])-baseline,int(offsets[i+1])-baseline
        p=np.maximum(raw[a:b],1e-12)
        p/=p.sum()
        o=np.asarray(odds,dtype=float)
        q=1/o;q/=q.sum()
        order=np.argsort(-p,kind="stable")
        market_order=np.argsort(o,kind="stable")
        selections={
          "model_top":int(order[0]),
          "market_favorite":int(market_order[0]),
          "max_ev":int(np.argmax(p*o)),
          "max_edge":int(np.argmax(p/q)),
          "prob_price_04":int(np.argmax(np.log(p)+0.4*np.log(o))),
          "prob_price_07":int(np.argmax(np.log(p)+0.7*np.log(o))),
          "model_rank_two":int(order[1]),
          "market_rank_two":int(market_order[1]),
          "model_late_market":int(max(range(len(o)),key=lambda t:(p[t] if o[t]>=10 else -1,t*-1))),
          "model_price_1":int(np.argmax(np.log(p)+np.log(o))),
        }
        d,v,number,surface,field=meta[i]
        assert d==str(dates[i])
        horses={}
        for mode,choice in selections.items():
            horses[mode]=(float(o[choice]),float(p[choice]),float(p[choice]*o[choice]),
                          float(p[choice]/q[choice]),
                          int(choice==int(winners[i])),float(o[choice]) if choice==int(winners[i]) else 0.0)
        recs.append((d,v,number,surface,field,horses))
    del fit,raw
    return recs

def context_ok(ctx,surface,field):
    if ctx=="all":return True
    if ctx=="turf":return "芝" in surface
    if ctx=="dirt":return "ダート" in surface
    if ctx=="field_under_12":return field<12
    if ctx=="field_12_up":return field>=12
    raise ValueError(ctx)

def year_experiment(records,mode,band,min_ev,context,priority):
    a,b=ODDS_BANDS[band]
    by=collections.defaultdict(list)
    for date,venue,number,surface,field,tickets in records:
        if not context_ok(context,surface,field):continue
        odds,prob,ev,edge,hit,payout=tickets[mode]
        if not (a<=odds<b and ev>=min_ev):continue
        score=ev if priority=="ev" else prob
        by[(date,venue)].append((score,number,date,payout))
    # One top-scored horse per selected race (single-win diagnostic only)
    ledgers=[[] for _ in RACE_COUNTS]
    for group in by.values():
        group.sort(key=lambda z:(-z[0],z[1]))
        for k,ledger in zip(RACE_COUNTS,ledgers):
            ledger.extend((x[2],x[3]) for x in group[:k])
    return [metrics(rows) for rows in ledgers]

def metrics(rows):
    n=len(rows);gross=sum(x[1] for x in rows)
    hits=sum(x[1]>0 for x in rows)
    largest=max((x[1] for x in rows),default=0)
    unique_dates=len({x[0] for x in rows})
    return {"bets":n,"dates":unique_dates,"hitCount":hits,
        "roiPct":round(100*gross/n,2) if n else None,
        "roiExcludingLargestRacePct":round(100*(gross-largest)/n,2) if n else None}

def strategies():
    for mode in MODE_NAMES:
        for band in ODDS_BANDS:
            for ev in EV_MIN:
                for context in CONTEXTS:
                    for priority in PRIORITIES:
                        yield {"horse":mode,"oddsBand":band,"minimumModelEV":ev,
                               "context":context,"racePriority":priority}

def key(spec):return json.dumps(spec,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def scan(records,spec_list):
    results={}
    for spec in spec_list:
        rows=year_experiment(records,spec["horse"],spec["oddsBand"],
                              spec["minimumModelEV"],spec["context"],spec["racePriority"])
        for k,result in zip(RACE_COUNTS,rows):
            results[key({**spec,"maxRacesPerVenue":k})]=result
    return results

def stable_priority(result):
    if result["bets"]<MIN_YEAR_BETS or result["dates"]<16:
        return -float("inf")
    # Predeclared. A single jackpot does not determine the training shortlist.
    return result["roiExcludingLargestRacePct"]

def test():
    simple=[("2024-01-06","東京",1,"芝",10,{"model_top":(7.,0.2,1.4,2.,True,7.)})]
    assert year_experiment(simple,"model_top","all",0,"all","ev")[0]["roiPct"]==700
    assert year_experiment(simple,"model_top","100_1000",0,"all","ev")[0]["bets"]==0
    assert not context_ok("dirt","芝",10)
    assert stable_priority({"bets":5,"dates":2,"roiExcludingLargestRacePct":10000})==-float("inf")
    assert len(list(strategies()))==len(MODE_NAMES)*len(ODDS_BANDS)*len(EV_MIN)*len(CONTEXTS)*len(PRIORITIES)
    print("RESEARCH_BROAD_PATTERNS_SELFTEST_OK",flush=True)

def main():
    import sys
    if "--self-test" in sys.argv:
        test();return
    started=time.monotonic()
    mod=get_oos()
    core=mod.core_module()
    archive=mod.load_public_archive()
    by_date=mod.load_bundles(archive)
    X,y,counts,dates,offsets,winners,dropped,total,markets=mod.chronological_features(core,by_date)
    meta=metadata(by_date)
    assert len(meta)==len(counts)
    specs=list(strategies())
    scenarios=len(specs)*len(RACE_COUNTS)
    print("BROAD_PATTERN_SEARCH_START",json.dumps({"scenarios":scenarios,
        "horses":len(MODE_NAMES),"oddsBands":len(ODDS_BANDS),
        "evFloors":len(EV_MIN),"contexts":len(CONTEXTS),
        "priorities":len(PRIORITIES),"raceCounts":list(RACE_COUNTS)}),flush=True)
    train=scan(raw_records(mod,X,y,counts,dates,offsets,winners,markets,meta,"2024"),specs)
    ranked=sorted(train,key=lambda name:(-stable_priority(train[name]),name))
    selected=[x for x in ranked if math.isfinite(stable_priority(train[x]))][:TOP_TRAIN]
    if len(selected)!=TOP_TRAIN:raise AssertionError("NOT_ENOUGH_TRAINING_VALID_CANDIDATES")
    print("BROAD_TRAIN_DONE",json.dumps({"validStrategies":sum(math.isfinite(stable_priority(x)) for x in train.values()),
        "shortlisted":len(selected),"best2024":train[selected[0]]}),flush=True)
    validation=scan(raw_records(mod,X,y,counts,dates,offsets,winners,markets,meta,"2025"),
                    [json.loads(k) | {"maxRacesPerVenue":None} for k in []]) if False else None
    # Evaluate frozen 2024 shortlist only in 2025, to avoid reporting a
    # retrospectively cherry-picked 2025 discovery as independent evidence.
    base_specs={key({k:v for k,v in json.loads(name).items() if k!="maxRacesPerVenue"}):
                {k:v for k,v in json.loads(name).items() if k!="maxRacesPerVenue"}
                for name in selected}
    validation=scan(raw_records(mod,X,y,counts,dates,offsets,winners,markets,meta,"2025"),
                    list(base_specs.values()))
    evaluated=[]
    for k in selected:
        v=validation[k]
        if v["bets"]>=MIN_YEAR_BETS and v["dates"]>=16:
            evaluated.append(k)
    # Keep the 2024-frozen top 100 to test the already-opened 2026 archive.
    # Do not select/retune candidates using 2025 or 2026 return outcomes.
    shadow=scan(raw_records(mod,X,y,counts,dates,offsets,winners,markets,meta,"2026"),
                list(base_specs.values()))
    def witness(k):
        return {"strategy":json.loads(k),"2024_train":train[k],
                "2025_oo_year":validation[k],"2026_already_opened":shadow[k]}
    robust=[k for k in selected if all(
        yy[k]["bets"]>=MIN_YEAR_BETS and yy[k]["dates"]>=16 and
        yy[k]["roiExcludingLargestRacePct"]>=400
        for yy in (train,validation,shadow))]
    ranked2025=sorted(evaluated,key=lambda name:(-stable_priority(validation[name]),name))
    best2025=sorted(selected,key=lambda name:(-(validation[name]["roiPct"] or 0),name))
    report={
      "status":"RESEARCH_ONLY_FINAL_WIN_ODDS_NOT_T15_NOT_PRODUCTION",
      "truthfulScope":"2016-2026 56-feature LightGBM, trained before each of three evaluation years",
      "year2016to2023TrainingAndDatesKeptSeparate":True,
      "selection":"100 candidate names selected using 2024 trimmed 100-yen single-win ROI and 80-bet/16-day minimum; frozen for 2025 and 2026",
      "attemptedSpecifications":scenarios,
      "testable2024Patterns":sum(math.isfinite(stable_priority(x)) for x in train.values()),
      "2024Shortlist":len(selected),
      "2025EligibleShortlist":len(evaluated),
      "2024_2025_2026AllYearsTrimmed400":len(robust),
      "survivors": [witness(k) for k in robust[:12]],
      "topBy2024":[witness(k) for k in selected[:12]],
      "topBy2025":[witness(k) for k in ranked2025[:12]],
      "evidenceNotes":[
        "JRA archived FINAL WIN ODDS are NOT verified as available 15 min pre-race",
        "This research only tests ONE win-type bet; deployed product requires TWO DISTINCT ticket types",
        "2026 races have already been inspected in earlier research so 2026 cannot be called untouched",
        "Selection over thousands of candidates creates major multiple-testing overfit risk",
        "The 2024 ranking is in-sample for policy search, even though runner probabilities are OOF",
        "No JRA payout-table join was made here; theoretical single-win payout assumes archived odds",
        "No future 400% ROI certification or production permission",
      ],
      "promotionEligible":False,
      "elapsedSeconds":round(time.monotonic()-started,1),
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("BROAD_PATTERN_OOF_RESEARCH_RESULT",json.dumps({
        "scenarios":scenarios,"2024Valid":report["testable2024Patterns"],
        "2025Eligible":len(evaluated),"threeYearRobust400Count":len(robust),
        "bestBy2024":report["topBy2024"][:3],
        "bestBy2025":report["topBy2025"][:3],
        "elapsedSeconds":report["elapsedSeconds"],"productionEligible":False,
    },ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
