#!/usr/bin/env python3
"""Reconstruct historical 56-column *schema* from retained source races, safely.

The ORIGINAL 56-feature CSV artifact has expired (GitHub artifact 9087261097,
HTTP 404), and D1 contains races only from 2024-05 onward. We do NOT mislabel
this as byte-identical canonical data: the retained 10-year public calendar
does not contain pre-2024 weather, track condition or complete directions.
These are explicitly marked unknown, not silently imputed as actual weather.

Uses immutable public calendar (34,566 races) and original 480,441 runner
snapshots including past finishes. Every racing DAY is featurized in its
entirety BEFORE that day's outcomes update the causal state. Never edits
historical tips or production D1.

Output is for retrospective candidate research only, NOT an official T-15
feature/odds dataset and NOT permission to promote a profitable model.
"""
from __future__ import annotations
import argparse
import base64
import collections
import csv
import datetime as dt
import gzip
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNNER_COLUMNS=("horseNo","frameNo","horseName","sexAge","assignedWeight",
                "jockey","trainer","horseWeight","weightChange","popularity",
                "winOdds","finishPosition","timeText","final3f","runnerStatus")
CALENDAR_FIELDS=("raceId","raceDate","venue","raceNo","raceName",
                 "startTimeJst","surface","distanceM","originalTickets")


def load_core():
    path=ROOT/"scripts/ten-year-production-core.py"
    spec=importlib.util.spec_from_file_location("causal_research_core",path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m


def calendar():
    folder=ROOT/"src/v1/ten-year-history-data"
    chunks=sorted(folder.glob("bin-*.ts"))
    if len(chunks)!=9:raise RuntimeError(f"PUBLIC_CALENDAR_ARCHIVE_MISSING:{len(chunks)}")
    buf=""
    for path in chunks:
        raw=path.read_text(encoding="utf-8").strip()
        if not(raw.startswith("export default ") and raw.endswith(";")):
            raise ValueError(f"BAD_CALENDAR_CHUNK:{path}")
        buf+=json.loads(raw[len("export default "):-1])
    payload=json.loads(gzip.decompress(base64.b64decode(buf)))
    rows=payload["races"]
    if len(rows)!=34566:raise RuntimeError("PUBLIC_RACE_COUNT_NOT_34566")
    return {str(row[0]):dict(zip(CALENDAR_FIELDS,row)) for row in rows}


def blank_state():
    return {
        "throughDate": "2016-08-09",
        "horse_hist":collections.defaultdict(lambda:collections.deque(maxlen=5)),
        "horse_total":collections.defaultdict(lambda:[0,0,0]),
        "horse_surface":collections.defaultdict(lambda:[0,0,0]),
        "horse_dist":collections.defaultdict(lambda:[0,0,0]),
        "horse_venue":collections.defaultdict(lambda:[0,0,0]),
        "jockey":collections.defaultdict(lambda:[0,0,0]),
        "trainer":collections.defaultdict(lambda:[0,0,0]),
        "pair":collections.defaultdict(lambda:[0,0,0]),
    }


def bundles_for_month(path,months_calendar,seen):
    with gzip.open(path,"rt",encoding="utf-8") as fh:
        month=json.load(fh)
    bundles=[]
    for rid,runner_list in month:
        rid=str(rid)
        if rid in seen:raise RuntimeError(f"DUPLICATE_RACE:{rid}")
        seen.add(rid)
        base=months_calendar.get(rid)
        if not base:raise RuntimeError(f"PUBLIC_CALENDAR_RACE_MISSING:{rid}")
        race={
            "raceId":rid,"raceDate":base["raceDate"],
            "venue":base["venue"],"raceNo":base["raceNo"],
            "raceName":base["raceName"],
            "startTimeJst":base["startTimeJst"],
            "surface":base["surface"],"distanceM":base["distanceM"],
            # Unavailable in retained pre-2024 metadata. We will not
            # present them as observed or use after-race outcomes as proxies.
            "weather":None,"trackCondition":None,"direction":None,
        }
        runners=[dict(zip(RUNNER_COLUMNS,runner)) for runner in runner_list]
        results=[{"horseNo":x["horseNo"],"finishPosition":x["finishPosition"],
                  "timeText":x["timeText"],"final3f":x["final3f"]}
                 for x in runners if x.get("finishPosition") is not None]
        bundles.append({"race":race,"runners":runners,"results":results,
                        "originalTickets":base["originalTickets"]})
    return sorted(bundles,key=lambda b:(b["race"]["raceDate"],b["race"]["venue"],
                                        int(b["race"]["raceNo"] or 0)))


def self_test():
    c=load_core()
    s=blank_state()
    base={"raceId":"synthetic-1","raceDate":"2025-01-01","raceNo":1,
          "venue":"東京","surface":"芝","distanceM":1600,"raceName":"test",
          "trackCondition":None,"weather":None,"direction":None}
    r={"horseNo":1,"horseName":"TEST_HORSE","sexAge":"牡3","runnerStatus":"active"}
    earlier=c.ml_feature_row(s,base,r,3)
    assert earlier["horseStarts"]==0 and earlier["debutFlag"]==1
    b={"race":base,"runners":[r],"results":[{"horseNo":1,"finishPosition":1,
       "timeText":"1:34.0","final3f":"34.5"}]}
    c.update_feature_state_for_date(s,[b])
    later=c.ml_feature_row(s,{**base,"raceDate":"2025-01-02"},r,3)
    assert later["horseStarts"]==0  # one horse alone -> race excluded from training state
    b["runners"]=[r,{**r,"horseNo":2,"horseName":"test_two"}]
    c.update_feature_state_for_date(s,[b])
    later=c.ml_feature_row(s,{**base,"raceDate":"2025-01-02"},r,3)
    assert later["horseStarts"]==1 and later["horseWinRate"]>0
    print("RECONSTRUCTED_56_SCHEMA_TIME_CAUSAL_SELFTEST_OK",flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="/tmp/reconstructed-runner-56.csv.gz")
    p.add_argument("--meta",default="/tmp/reconstructed-runner-56-meta.json")
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:return self_test()
    core=load_core()
    features=list(core.load_config()["runnerProbabilityModel"]["features"])
    ids=calendar()
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    state=blank_state()
    record_count=runner_count=selected_count=0
    seen=set();dates=set();invalid=[]
    fields=["raceId","raceDate","labelWin","horseNoRaw","winOddsFinal",
            "originalDemandSelected"]+[x for x in features if x!="horseNoRaw"]
    with gzip.open(out,"wt",encoding="utf-8",newline="",compresslevel=6) as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        for path in sorted((ROOT/"data/ten-year-runners").glob("????-??.json.gz")):
            bundles=bundles_for_month(path,ids,seen)
            for date,days in core.group_by_date(bundles):
                # Produce all same-date rows without seeing this date's
                # results (including earlier races on the same day).
                for bundle in days:
                    race=bundle["race"];record_count+=1;dates.add(date)
                    if bundle["originalTickets"] is not None:selected_count+=1
                    active=[r for r in bundle["runners"]
                            if (r.get("runnerStatus") or "active")=="active"]
                    field=len(active)
                    if field<3:invalid.append(str(race["raceId"]));continue
                    for runner in active:
                        y=int(runner.get("finishPosition")==1)
                        datum=core.ml_feature_row(state,race,runner,field)
                        writer.writerow({"raceId":race["raceId"],"raceDate":date,
                            "labelWin":y,"horseNoRaw":datum["horseNoRaw"],
                            "winOddsFinal":runner.get("winOdds"),
                            "originalDemandSelected":int(bundle["originalTickets"] is not None),
                            **{key:datum[key] for key in features if key!="horseNoRaw"}})
                        runner_count+=1
                core.update_feature_state_for_date(state,days)
                state["throughDate"]=date
            print("CAUSAL_RUNNER_RECONSTRUCTION_MONTH",path.stem,
                  "races",record_count,"runners",runner_count,flush=True)
    if len(seen)!=34566 or record_count!=34566 or selected_count!=14410:
        raise RuntimeError(f"INCOMPLETE_RACES_OR_SELECTION:{len(seen)}:{selected_count}")
    report={"reconstructedRaceCount":record_count,"exportedRunnerRows":runner_count,
        "selectedLegacyRaceCount":selected_count,"distinctDates":len(dates),
        "featureSchemaColumns":features,
        "fullOriginalCanonicalFeatureCorpusReproduced":False,
        "missingOrUnverifiedHistoricalInputs":["weather","trackCondition","direction",
                                                "conditions","T_minus_15_odds"],
        "source":"retained 2016-2026 monthly runner gzip + frozen public calendar TS",
        "latestDate":"2026-08-09",
        "sameDayResultsUsedInOwnFeatures":False,
        "modelTrainingDataAvailability":"reconstructed causal schema; not original canonical artifact",
        "racesWithLessThanThreeActiveRunners":len(invalid),
        "sourceFiles":len(list((ROOT/"data/ten-year-runners").glob("????-??.json.gz"))),
        "productionChanged":False}
    Path(args.meta).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                              encoding="utf-8")
    print("RECONSTRUCTED_56_FEATURE_DATA_FINAL",
          json.dumps({k:v for k,v in report.items() if k!="featureSchemaColumns"},ensure_ascii=False),
          flush=True)


if __name__=="__main__":main()
