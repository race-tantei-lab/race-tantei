#!/usr/bin/env python3
"""Research-only chronological holdout of the adopted 56-feature LightGBM family.

This script deliberately DOES NOT estimate betting ROI. The archived monthly
runner data omits complete T-15 combination-odds snapshots and some context
fields. It measures only out-of-time winner probabilities. No D1, no network,
no settlement modifications, no production promotion.
"""
from __future__ import annotations

import base64
import collections
import datetime as dt
import gzip
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import time

import lightgbm as lgb
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = ROOT / "src/v1/ten-year-history-data"
RUNNER_DIR = ROOT / "data/ten-year-runners"
OUT = ROOT / "analysis-results/research-chronological-56feature-validation-20261107.json"
HOLDOUT_START = "2026-01-01"
VALIDATIONS = [("2024", "2024-01-01", "2025-01-01"),
               ("2025", "2025-01-01", "2026-01-01")]
CANDIDATES = {
    "adopted_complexity_500x127": dict(n_estimators=500, learning_rate=0.04,
                                      num_leaves=127, min_child_samples=30,
                                      reg_lambda=4, reg_alpha=0.2,
                                      colsample_bytree=0.9, random_state=20260812),
    "regularized_150x31": dict(n_estimators=150, learning_rate=0.04,
                                 num_leaves=31, min_child_samples=80,
                                 reg_lambda=10, reg_alpha=0.5,
                                 colsample_bytree=0.8, random_state=20260812),
}

def core_module():
    path = ROOT / "scripts/ten-year-production-core.py"
    spec = importlib.util.spec_from_file_location("ten_year_oos_core", path)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m

def load_public_archive():
    chunks = sorted(ARCHIVE_DIR.glob("bin-*.ts"))
    assert len(chunks) == 9, "expected immutable nine-chunk public archive"
    encoded = ""
    for path in chunks:
        src = path.read_text(encoding="utf-8").strip()
        assert src.startswith("export default ") and src.endswith(";")
        encoded += json.loads(src[len("export default "):-1])
    payload = json.loads(gzip.decompress(base64.b64decode(encoded)))
    assert payload["start"] == "2016-08-10"
    assert payload["end"] == "2026-08-09"
    assert len(payload["races"]) == 34566
    # Public archive contains historical completed bets; DO NOT use tickets
    # anywhere in training, evaluation or selection to avoid in-sample leakage.
    return {str(r[0]): {
        "raceId":str(r[0]),"raceDate":str(r[1]),"venue":str(r[2]),
        "raceNo":int(r[3]),"raceName":r[4],"startTimeJst":r[5],
        "surface":r[6],"distanceM":r[7]
    } for r in payload["races"]}

def load_bundles(archive):
    manifest = json.loads((RUNNER_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["races"] == 34566 and manifest["runners"] == 480441
    by_date = collections.defaultdict(list)
    races = runners = 0
    for month in sorted(manifest["months"]):
        path = RUNNER_DIR / (month + ".json.gz")
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            rows = json.load(fh)
        assert len(rows) == manifest["months"][month]["races"], month
        for rid, raw in rows:
            rid = str(rid)
            if rid not in archive:
                raise ValueError("race ID from runner archive missing in calendar: "+rid)
            race = archive[rid]
            bundle = {"race":race,"runners":[],"results":[],"payouts":[]}
            for x in raw:
                if len(x) != 15:
                    raise ValueError("unexpected archived runner format")
                (horse_no, frame, horse_name, sex_age, assigned, jockey, trainer,
                 weight, change, _popularity, _final_odds, finish, tm, final3f, status) = x
                # IMPORTANT: popularity and win_odds are intentionally ignored.
                runner = {"horseNo":int(horse_no),"frameNo":frame,"horseName":horse_name,
                          "sexAge":sex_age,"assignedWeight":assigned,
                          "jockey":jockey,"trainer":trainer,
                          "horseWeight":weight,"weightChange":change,
                          "runnerStatus":status}
                bundle["runners"].append(runner)
                bundle["results"].append({"horseNo":int(horse_no),"finishPosition":finish,
                                          "timeText":tm,"final3f":final3f})
                runners += 1
            by_date[race["raceDate"]].append(bundle)
            races += 1
    assert races == 34566 and runners == 480441, (races,runners)
    return by_date

def fresh_feature_state():
    # Same accumulators as the canonical feature builder, but with an empty
    # state at the first historical date: never load full-archive final state.
    return {
        "throughDate":"2016-08-09",
        "horse_hist":collections.defaultdict(lambda:collections.deque(maxlen=5)),
        "horse_total":collections.defaultdict(lambda:[0,0,0]),
        "horse_surface":collections.defaultdict(lambda:[0,0,0]),
        "horse_dist":collections.defaultdict(lambda:[0,0,0]),
        "horse_venue":collections.defaultdict(lambda:[0,0,0]),
        "jockey":collections.defaultdict(lambda:[0,0,0]),
        "trainer":collections.defaultdict(lambda:[0,0,0]),
        "pair":collections.defaultdict(lambda:[0,0,0]),
    }

def chronological_features(core, by_date):
    cfg = core.load_config()
    features = list(cfg["runnerProbabilityModel"]["features"])
    assert len(features) == 56
    assert not ({"winOdds","popularity","finishPosition","raceId",
                 "raceDate","labelWin","labelTop3"} & set(features))
    state = fresh_feature_state()
    arrays, labels, race_sizes, race_winners, race_dates = [], [], [], [], []
    dropped = collections.Counter()
    total_races = 0
    first_date = None
    prev_date = ""
    for date in sorted(by_date):
        assert date > prev_date
        if first_date is None:
            first_date = date
        prev_date = date
        day = by_date[date]
        # All same-day features are emitted BEFORE any same-day outcomes touch
        # state. This is more conservative than live intraday processing.
        for b in day:
            total_races += 1
            runners = sorted([r for r in b["runners"]
                              if r.get("runnerStatus") in (None, "", "active")],
                             key=lambda r: r["horseNo"])
            if len(runners) < 3:
                dropped["few_active_runners"] += 1
                continue
            outcomes = {x["horseNo"]:x.get("finishPosition") for x in b["results"]}
            winner_idx = [i for i,r in enumerate(runners)
                          if outcomes.get(r["horseNo"]) == 1]
            if len(winner_idx) != 1:
                dropped["no_unique_winner"] += 1
                continue
            xs = [core.ml_feature_row(state,b["race"],r,len(runners)) for r in runners]
            arrays.extend([[float(x[f]) for f in features] for x in xs])
            labels.extend([int(i == winner_idx[0]) for i in range(len(runners))])
            race_sizes.append(len(runners))
            race_winners.append(winner_idx[0])
            race_dates.append(date)
        core.update_feature_state_for_date(state, day)
        state["throughDate"] = date
    X = np.asarray(arrays,dtype=np.float32)
    y = np.asarray(labels,dtype=np.int8)
    counts = np.asarray(race_sizes,dtype=np.int32)
    dates = np.asarray(race_dates)
    offsets = np.concatenate([[0],np.cumsum(counts)])
    assert len(counts) > 32000, len(counts)
    assert len(X) == len(y) == int(offsets[-1])
    assert X.shape[1] == 56
    assert np.all(np.isfinite(X))
    # Archive date range starts midweek; the first actually raced date can be later.
    assert "2016-08-10" <= first_date < "2016-09-01" and prev_date == "2026-08-09", (first_date,prev_date)
    return X,y,counts,dates,offsets,np.asarray(race_winners),dict(dropped),total_races

def score(model, X, counts, offsets, winners, ix):
    if len(ix) < 250:
        raise ValueError("evaluation has too few races")
    low, high = int(offsets[ix[0]]), int(offsets[ix[-1] + 1])
    raw = model.predict_proba(X[low:high])[:,1]
    losses=[]; top_hits=0; uniform=[]
    for index in ix:
        left = int(offsets[index])-low
        right = int(offsets[index+1])-low
        pred = np.maximum(raw[left:right],1e-12)
        pred = pred / pred.sum()
        w = int(winners[index])
        losses.append(-math.log(float(pred[w])))
        top_hits += int(np.argmax(pred)==w)
        uniform.append(math.log(int(counts[index])))
    return {
        "raceCount":len(ix),
        "winnerLogLoss":round(float(np.mean(losses)),7),
        "uniformWinnerLogLoss":round(float(np.mean(uniform)),7),
        "improvementVsUniform":round(float(np.mean(uniform)-np.mean(losses)),7),
        "topPickWinPct":round(top_hits*100/len(ix),3),
        "uniformTopPickExpectedPct":round(float(np.mean(1.0/counts[ix]))*100,3),
    }

def fit(X,y,offsets,train_ix,params):
    assert len(train_ix) >= 8000, len(train_ix)
    limit = int(offsets[train_ix[-1]+1])
    assert train_ix[0] == 0 and len(train_ix)==train_ix[-1]+1
    model = lgb.LGBMClassifier(objective="binary",n_jobs=2,verbosity=-1,**params)
    model.fit(X[:limit],y[:limit])
    return model

def main():
    start = time.monotonic()
    core=core_module()
    meta=load_public_archive()
    by_date=load_bundles(meta)
    X,y,counts,dates,offsets,winners,dropped,total=chronological_features(core,by_date)
    print("CHRONO_DATA_READY",json.dumps({
        "totalRaces":total,"eligible":len(counts),"runnerRows":len(y),
        "dropped":dropped,"first":dates[0],"last":dates[-1],
    },ensure_ascii=False),flush=True)
    report = {
        "classification":"research_only_not_deployable",
        "source":"git-archived ten-year runner history + public race calendar",
        "modelFamily":"adopted 56-feature LightGBM (retrained chronologically)",
        "featureLimitations":{
            "missingRaceContext":["direction","weather","trackCondition","conditions"],
            "preRaceSnapshotProvenance":"unverified for historic bodyweight etc",
            "liveSameDayHistory":"excluded: date-batched updates",
            "oddsAtTMinus15":"not retained for all six bet types",
            "bettingRoiComputed":False
        },
        "trainingProtocol":{
            "noFutureLabelsInTraining":True,
            "sameDayResultsUsedInFeatures":False,
            "featureNames":list(core.load_config()["runnerProbabilityModel"]["features"]),
            "selectionCandidateSearch":"two prespecified complexity levels only",
            "validationYears":[2024,2025],
            "untouchedHoldout":"2026-01-01 to 2026-08-09",
            "candidateChoice":"min aggregate 2024/25 winner log loss; if regularized within 0.005 of complex choose simpler",
        },
        "data":{"archiveRaces":total,"eligibleRaces":len(counts),"eligibleRunnerRows":len(y),"dropped":dropped},
        "candidateValidation":{},
    }
    validation_sums={}
    for name, params in CANDIDATES.items():
        scores = {}
        for label, test_start, test_end in VALIDATIONS:
            train_ix = np.where(dates < test_start)[0]
            eval_ix = np.where((dates >= test_start)&(dates < test_end))[0]
            assert len(train_ix)>8000 and len(eval_ix)>250
            assert dates[train_ix[-1]] < dates[eval_ix[0]]
            model=fit(X,y,offsets,train_ix,params)
            scores[label]=score(model,X,counts,offsets,winners,eval_ix)
            print("CHRONO_VALIDATION", name, label, json.dumps(scores[label]),flush=True)
            del model
        total_races = sum(s["raceCount"] for s in scores.values())
        val_loss = sum(s["raceCount"]*s["winnerLogLoss"] for s in scores.values())/total_races
        report["candidateValidation"][name]={"yearScores":scores,"pooledWinnerLogLoss":round(val_loss,7)}
        validation_sums[name]=val_loss
    original = validation_sums["adopted_complexity_500x127"]
    reduced = validation_sums["regularized_150x31"]
    selected = ("regularized_150x31" if reduced <= original+0.005
                else "adopted_complexity_500x127")
    # Evaluate 2026 ONCE AFTER THE SELECTED CANDIDATE IS FROZEN.
    train_ix = np.where(dates < HOLDOUT_START)[0]
    holdout_ix = np.where(dates >= HOLDOUT_START)[0]
    assert dates[train_ix[-1]] < dates[holdout_ix[0]]
    model = fit(X,y,offsets,train_ix,CANDIDATES[selected])
    report["selectedFromValidation"]=selected
    report["untouched2026Holdout"]=score(model,X,counts,offsets,winners,holdout_ix)
    report["holdoutRows"]=len(holdout_ix)
    report["elapsedSeconds"]=round(time.monotonic()-start,1)
    report["promotionEligible"]=False
    report["blockingReasons"]=[
        "No independently preserved T-15 official odds for full six-market two-ticket ROI",
        "Historical public archive lacks several required race-context feature values",
        "Feature reconstruction not byte-for-byte equivalent to deployed production",
        "No immutable forward live shadow ROI verified; no actual ROI certification",
    ]
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("CHRONO_FINAL_RESEARCH_REPORT",json.dumps({
        "selected":selected,"validation":validation_sums,
        "holdout":report["untouched2026Holdout"],
        "promotionEligible":False,"elapsedSeconds":report["elapsedSeconds"],
    },ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
