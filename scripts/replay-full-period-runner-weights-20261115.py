#!/usr/bin/env python3
"""Offline historical horse-probability replay on all archived 2016-2026 races.

Uses the exact deployed frozen LightGBM weights and same 56-feature function
as canonical ten-year core, with chronological-only feature state. Race weather,
track and directional metadata missing from published compact archive use
documented UNKNOWN fallback: such output is an approximation, NOT a certified
original historical pre-T15 replay.
No canonical ticket combinations or recent public bets are used.
"""
import base64
import collections
import datetime as dt
import gzip
import importlib.util
import json
import os
from pathlib import Path
import sys

import lightgbm as lgb
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"scripts/ten-year-production-core.py"
SPEC=importlib.util.spec_from_file_location("ten_year_core_for_independent_replay",SOURCE)
core=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)
FEATURES=core.load_config()["runnerProbabilityModel"]["features"]
assert len(FEATURES)==56
MODEL=lgb.Booster(model_file=str(ROOT/"models/ten-year-completed-model.txt"))
SELECTION=ROOT/"artifacts/independent-full-period-selections.json"
OUT=ROOT/"artifacts/independent-full-period-horse-weights.jsonl.gz"
YEAR=os.environ.get("AUDIT_YEAR","all")
if YEAR!="all" and not(YEAR.isdigit() and 2016<=int(YEAR)<=2026):raise RuntimeError("BAD_YEAR")
overrides={}
if YEAR!="all":
    official=ROOT/f"artifacts/independent-year-result-{YEAR}.json"
    if official.is_file():
        overrides={x["raceId"]:x.get("race",{}) for x in json.loads(official.read_text())["races"]}
print("INDEPENDENT_OFFICIAL_HISTORY_CONTEXT",json.dumps({"year":YEAR,"availableOfficialRaceMetadata":len(overrides)}),flush=True)
plans=json.loads(SELECTION.read_text())["modeResults"]
target=collections.defaultdict(set)
for row in plans:
    for r in row["selected"]:
        target[row["date"]].add(r["raceId"])
print("INDEPENDENT_FULL_PERIOD_TARGET",json.dumps({"year":YEAR,"months":121,"dates":len(target),"targets":sum(len(x) for x in target.values())}),flush=True)
parts=sorted((ROOT/"src/v1/ten-year-history-data").glob("bin-*.ts"))
b64="".join(json.loads(p.read_text().strip()[len("export default "):-1]) for p in parts)
archive=json.loads(gzip.decompress(base64.b64decode(b64)))["races"]
metadata={r[0]:r for r in archive}
runners={}
for path in sorted((ROOT/"data/ten-year-runners").glob("????-??.json.gz")):
    with gzip.open(path,"rt",encoding="utf8") as fh:
        for raceId,entries in json.load(fh):
            runners[raceId]=entries
if len(runners)!=len(metadata):
    raise RuntimeError(f"ARCHIVE_RUNNERS_MISMATCH:{len(runners)}:{len(metadata)}")
def empty_state():
    names=("horse_total","horse_surface","horse_dist","horse_venue","jockey","trainer","pair")
    s={"throughDate":"2016-08-09","horse_hist":collections.defaultdict(lambda:collections.deque(maxlen=5))}
    for k in names:s[k]=collections.defaultdict(lambda:[0,0,0])
    return s
state=empty_state()
records=collections.defaultdict(list)
for r in archive:records[r[1]].append(r)
rows_written=0
errors=[]
stats=collections.Counter()
OUT.parent.mkdir(parents=True,exist_ok=True)
with gzip.open(OUT,"wt",encoding="utf8",compresslevel=6) as dest:
 for count,(date,day_races) in enumerate(sorted(records.items()),1):
    bundles=[]
    prediction_records=[]
    vectors=[]
    for record in day_races:
        rid,date,venue,no,name,startJst,surface,distance,bets=record
        race={"raceId":rid,"raceDate":date,"venue":venue,"raceNo":int(no),"raceName":name,"startTimeJst":startJst,"surface":surface,"distanceM":int(distance or 0),
              "weather":"","trackCondition":"","direction":"","conditions":""}
        source=overrides.get(rid,{})
        for key in ("weather","trackCondition","direction","conditions","raceName","surface","distanceM"):
            value=source.get(key)
            if value is not None and value!="":race[key]=value
        runner_rows=[]
        result_rows=[]
        for val in runners[rid]:
            hno,frame,hname,sex,weight,jockey,trainer,body,bodyDelta,pop,winOdd,finish,timeText,final3f,status=val
            horse={"raceId":rid,"horseNo":int(hno),"frameNo":int(frame or 0),"horseName":hname,"sexAge":sex or "",
                   "assignedWeight":weight or 0,"jockey":jockey or "","trainer":trainer or "",
                   "horseWeight":body or 0,"weightChange":bodyDelta or 0,
                   "popularity":pop,"winOdds":winOdd,"runnerStatus":status or "active"}
            runner_rows.append(horse)
            result_rows.append({"raceId":rid,"horseNo":int(hno),"finishPosition":finish,"timeText":timeText,"final3f":final3f})
        bundles.append({"race":race,"runners":runner_rows,"results":result_rows})
        if rid in target.get(date,set()) and (YEAR=="all" or YEAR==date[:4]):
            active=[x for x in runner_rows if x["runnerStatus"]=="active"]
            try:
                if len(active)<3:raise RuntimeError("TOO_FEW_ACTIVE_RUNNERS")
                v=[core.ml_feature_row(state,race,h,len(active)) for h in active]
                arr=np.array([[float(f[k]) for k in FEATURES] for f in v],dtype=np.float64)
                if not np.isfinite(arr).all():raise RuntimeError("NON_FINITE_FEATURES")
                prediction_records.append((race,active,result_rows,len(vectors),len(vectors)+len(active)))
                vectors.extend(arr)
            except Exception as ex:errors.append({"raceId":rid,"reason":str(ex)})
    if vectors:
        y=MODEL.predict(np.asarray(vectors,dtype=np.float64),num_threads=2)
        for race,active,res,start,end in prediction_records:
            raw=list(map(float,y[start:end]))
            summed=sum(raw)
            if not summed or not np.isfinite(summed):
                errors.append({"raceId":race["raceId"],"reason":"BAD_MODEL_PROBABILITY"});continue
            weights=[x/summed for x in raw]
            entry={"raceId":race["raceId"],"date":date,"venue":race["venue"],"raceNo":race["raceNo"],
                   "startTimeJst":race["startTimeJst"],"horseNos":[int(h["horseNo"]) for h in active],
                   "weights":weights,"finish":[r["finishPosition"] for r in res],
                   "unknownWeatherAndTrack":not all(race.get(k) for k in ("weather","trackCondition"))}
            dest.write(json.dumps(entry,ensure_ascii=False,separators=(",",":"))+"\n")
            rows_written+=1
            stats[date[:4]]+=1
    core.update_feature_state_for_date(state,bundles)
    state["throughDate"]=date
    if count%100==0:print("INDEPENDENT_FULL_PERIOD_HORSE_REPLAY_PROGRESS",json.dumps({"days":count,"totalDays":len(records),"rows":rows_written,"errors":len(errors)}),flush=True)
print("INDEPENDENT_FULL_PERIOD_HORSE_REPLAY",json.dumps({"year":YEAR,"races":rows_written,"yearly":stats,"errors":errors[:15],"errorCount":len(errors),"archiveRaces":len(metadata),"runnerRows":sum(len(v) for v in runners.values()),"modelTrees":MODEL.num_trees(),"metadataFallback":"official historical weather, track, direction when available; otherwise unknown fallback"}),flush=True)
if YEAR=="all" and rows_written<10000:raise RuntimeError("HISTORIC_MODEL_PROBABILITIES_COVERAGE_LOW:"+str(rows_written))
