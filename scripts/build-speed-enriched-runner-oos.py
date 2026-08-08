import gzip
import json
import math
import pickle
import re
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "artifacts" / "speed-analysis-input"
OUT = ROOT / "artifacts" / "speed-runner-oos"
OUT.mkdir(parents=True, exist_ok=True)

with gzip.open(IN / "completion-analysis-dataset.pkl.gz", "rb") as f:
    D = pickle.load(f)
with gzip.open(IN / "fixed-race-context.json.gz", "rt", encoding="utf-8") as f:
    context_payload = json.load(f)
context = {r["raceId"]: r for r in context_payload["rows"]}
races = D["races"]
race_order = [r["raceId"] for r in races]
if len(race_order) != 7695:
    raise RuntimeError(f"RACE_COUNT:{len(race_order)}")
race_index = {rid: i for i, rid in enumerate(race_order)}

dates = []
for r in races:
    if not dates or dates[-1] != r["raceDate"]:
        dates.append(r["raceDate"])
date_index = {d: i for i, d in enumerate(dates)}
if len(dates) != 244:
    raise RuntimeError(f"DATE_COUNT:{len(dates)}")

runners_by_race = defaultdict(list)
for r in D["runners"]:
    runners_by_race[r["raceId"]].append(r)
results_by_race = defaultdict(dict)
for r in D["results"]:
    results_by_race[r["raceId"]][int(r["horseNo"])] = r


def parse_time(text):
    if not text:
        return None
    m = re.fullmatch(r"\s*(\d+):(\d{1,2})\.(\d)\s*", str(text))
    if m:
        return int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 10.0
    try:
        return float(text)
    except Exception:
        return None


def parse_age(sex_age):
    m = re.search(r"(\d+)", str(sex_age or ""))
    return int(m.group(1)) if m else 0


def sex(sex_age):
    s = str(sex_age or "")
    if "牡" in s:
        return "male"
    if "牝" in s:
        return "female"
    if "セ" in s or "騸" in s:
        return "gelding"
    return "unknown"


def normalize_context(rid, race):
    c = context.get(rid, {})
    txt = " ".join(str(c.get(k) or "") for k in ("raceName", "conditions", "courseText"))
    raw = str(c.get("surface") or race.get("surface") or "")
    if "障害" in txt or raw == "障害" or "芝・ダート" in txt:
        surf = "obstacle"
    elif "ダート" in raw or "ダ" == raw:
        surf = "dirt"
    elif "芝" in raw:
        surf = "turf"
    else:
        surf = "unknown"
    dist = c.get("distanceM") or race.get("distanceM")
    try:
        dist = int(dist)
        if not 800 <= dist <= 5000:
            dist = 0
    except Exception:
        dist = 0
    if not dist:
        bucket = "unknown"
    elif dist < 1400:
        bucket = "sprint"
    elif dist <= 1800:
        bucket = "mile_mid"
    elif dist <= 2400:
        bucket = "middle"
    else:
        bucket = "long"
    if surf == "obstacle" or "障害" in txt:
        cls = "obstacle"
    elif "新馬" in txt:
        cls = "new"
    elif "未勝利" in txt:
        cls = "maiden"
    elif re.search(r"1\s*勝", txt):
        cls = "1w"
    elif re.search(r"2\s*勝", txt):
        cls = "2w"
    elif re.search(r"3\s*勝", txt):
        cls = "3w"
    elif any(x in txt for x in ("オープン", "OPEN", "G1", "G2", "G3", "GI", "GII", "GIII", "リステッド", "重賞")):
        cls = "open"
    else:
        cls = "other"
    direction = str(c.get("direction") or race.get("direction") or "unknown")
    track = str(c.get("trackCondition") or race.get("trackCondition") or "unknown")
    weather = str(c.get("weather") or race.get("weather") or "unknown")
    return surf, dist, bucket, cls, direction, track, weather


CTX = {r["raceId"]: normalize_context(r["raceId"], r) for r in races}

# Aggregate: n, wins, top3, sum_finish_pct, sum_f3_pct, sum_market_resid,
# sum_behind_winner_sec, sum_speed_resid, n_speed
AGG_SIZE = 9
aggs = defaultdict(lambda: np.zeros(AGG_SIZE, dtype=np.float64))
recent = defaultdict(lambda: deque(maxlen=5))
last_run = {}
condition_exact = defaultdict(lambda: [0, 0.0])
condition_vsd = defaultdict(lambda: [0, 0.0])
condition_sd = defaultdict(lambda: [0, 0.0])


def agg_feat(key):
    a = aggs.get(key)
    if a is None or a[0] <= 0:
        return [0.0] * 9
    n = a[0]
    ns = a[8]
    return [math.log1p(n), a[1] / n, a[2] / n, a[3] / n, a[4] / n,
            a[5] / n, a[6] / n, a[7] / ns if ns > 0 else 0.0, ns / n]


def mean_last(hist, name, k):
    vals = [x[name] for x in list(hist)[-k:] if x.get(name) is not None and np.isfinite(x[name])]
    return float(np.mean(vals)) if vals else 0.0


def baseline_for(venue, surf, dist, track, cls):
    candidates = [condition_exact.get((venue, surf, dist, track, cls)),
                  condition_vsd.get((venue, surf, dist)), condition_sd.get((surf, dist))]
    for item in candidates:
        if item and item[0] >= 8:
            return item[1] / item[0], item[0]
    for item in candidates:
        if item and item[0] > 0:
            return item[1] / item[0], item[0]
    return 0.0, 0

# Stable categorical code maps fixed before outcome use.
venue_values = sorted({r["venue"] for r in races})
cat_maps = {
    "venue": {x: i + 1 for i, x in enumerate(venue_values)},
    "surface": {x: i + 1 for i, x in enumerate(["unknown", "turf", "dirt", "obstacle"])},
    "bucket": {x: i + 1 for i, x in enumerate(["unknown", "sprint", "mile_mid", "middle", "long"])},
    "class": {x: i + 1 for i, x in enumerate(["other", "new", "maiden", "1w", "2w", "3w", "open", "obstacle"])},
    "direction": {}, "track": {}, "weather": {}, "sex": {x: i + 1 for i, x in enumerate(["unknown", "male", "female", "gelding"])},
}
for name, pos in (("direction", 4), ("track", 5), ("weather", 6)):
    vals = sorted({CTX[rid][pos] for rid in race_order})
    cat_maps[name] = {x: i + 1 for i, x in enumerate(vals)}

agg_names = ["horse", "jockey", "trainer", "horseSurf", "horseSD", "horseVenue", "horseClass",
             "jockeySD", "jockeyVenue", "trainerSD", "trainerVenue", "trainerClass", "horseJockey"]
agg_metric_names = ["logN", "winRate", "top3Rate", "avgFinishPct", "avgF3Pct", "marketResid",
                    "avgBehindSec", "avgSpeedResid", "speedCoverage"]
feature_names = [
    "logOdds", "marketP", "popNorm", "frameNorm", "assignedWeight", "horseWeight", "weightChange", "age",
    "fieldSize", "raceNo", "distanceM", "baselineWinnerTime", "baselineWinnerTimeN",
    "recentFinish1", "recentFinish3", "recentFinish5", "recentF3_1", "recentF3_3", "recentF3_5",
    "recentBehind1", "recentBehind3", "recentBehind5", "recentSpeed1", "recentSpeed3", "recentSpeed5",
    "recentMarketResid3", "sameSurfacePrev", "distanceDeltaPrev", "sameClassPrev", "daysSincePrev", "hasPrev"
]
for n in agg_names:
    for m in agg_metric_names:
        feature_names.append(f"{n}_{m}")
feature_names += ["venueCode", "surfaceCode", "distBucketCode", "classCode", "directionCode", "trackCode", "weatherCode", "sexCode"]

rows_meta = []
features = []
race_baseline = {}
race_market = {}

races_by_date = defaultdict(list)
for r in races:
    races_by_date[r["raceDate"]].append(r)

for di, date in enumerate(dates):
    # FEATURE FREEZE FOR THE ENTIRE DATE.
    for race in races_by_date[date]:
        rid = race["raceId"]
        venue = race["venue"]
        surf, dist, bucket, cls, direction, track, weather = CTX[rid]
        rs = sorted(runners_by_race[rid], key=lambda x: int(x["horseNo"]))
        active = [x for x in rs if str(x.get("runnerStatus") or "active") == "active" and x.get("winOdds") and float(x["winOdds"]) > 0]
        inv = np.array([1.0 / float(x["winOdds"]) for x in active], dtype=float)
        inv = inv / inv.sum() if inv.sum() > 0 else np.ones(len(active)) / max(1, len(active))
        mp = {int(x["horseNo"]): float(p) for x, p in zip(active, inv)}
        race_market[rid] = mp
        base, base_n = baseline_for(venue, surf, dist, track, cls)
        race_baseline[rid] = base if base_n else None
        field = len(active)
        current_dt = datetime.strptime(date, "%Y-%m-%d").date()
        for rr in active:
            h = str(rr.get("horseName") or "")
            j = str(rr.get("jockey") or "")
            t = str(rr.get("trainer") or "")
            hn = int(rr["horseNo"])
            hist = recent.get(h, deque())
            prev = last_run.get(h)
            f = [
                math.log(max(float(rr["winOdds"]), 1.0001)), mp.get(hn, 0.0),
                float(rr.get("popularity") or 0) / max(1, field), float(rr.get("frameNo") or 0) / max(1, field),
                float(rr.get("assignedWeight") or 0), float(rr.get("horseWeight") or 0), float(rr.get("weightChange") or 0),
                float(parse_age(rr.get("sexAge"))), float(field), float(race["raceNo"]), float(dist), float(base), float(base_n),
                mean_last(hist, "finish", 1), mean_last(hist, "finish", 3), mean_last(hist, "finish", 5),
                mean_last(hist, "f3", 1), mean_last(hist, "f3", 3), mean_last(hist, "f3", 5),
                mean_last(hist, "behind", 1), mean_last(hist, "behind", 3), mean_last(hist, "behind", 5),
                mean_last(hist, "speed", 1), mean_last(hist, "speed", 3), mean_last(hist, "speed", 5),
                mean_last(hist, "marketResid", 3),
                1.0 if prev and prev["surface"] == surf else 0.0,
                float(dist - prev["distance"]) if prev and dist and prev["distance"] else 0.0,
                1.0 if prev and prev["class"] == cls else 0.0,
                float((current_dt - prev["date"]).days) if prev else 0.0,
                1.0 if prev else 0.0,
            ]
            keys = [
                ("horse", h), ("jockey", j), ("trainer", t), ("horseSurf", h, surf),
                ("horseSD", h, surf, bucket), ("horseVenue", h, venue), ("horseClass", h, cls),
                ("jockeySD", j, surf, bucket), ("jockeyVenue", j, venue),
                ("trainerSD", t, surf, bucket), ("trainerVenue", t, venue), ("trainerClass", t, cls),
                ("horseJockey", h, j),
            ]
            for key in keys:
                f.extend(agg_feat(key))
            f.extend([
                float(cat_maps["venue"].get(venue, 0)), float(cat_maps["surface"].get(surf, 0)),
                float(cat_maps["bucket"].get(bucket, 0)), float(cat_maps["class"].get(cls, 0)),
                float(cat_maps["direction"].get(direction, 0)), float(cat_maps["track"].get(track, 0)),
                float(cat_maps["weather"].get(weather, 0)), float(cat_maps["sex"].get(sex(rr.get("sexAge")), 0)),
            ])
            result = results_by_race[rid].get(hn)
            finish = result.get("finishPosition") if result else None
            eligible = isinstance(finish, int) and finish > 0
            rows_meta.append({"raceId": rid, "raceDate": date, "dateIndex": di, "raceIndex": race_index[rid],
                              "venue": venue, "raceNo": int(race["raceNo"]), "horseNo": hn, "horseName": h,
                              "odds": float(rr["winOdds"]), "marketP": mp.get(hn, 0.0), "eligible": eligible,
                              "winY": 1 if eligible and finish == 1 else 0, "top3Y": 1 if eligible and finish <= 3 else 0,
                              "surface": surf, "distanceM": dist, "distBucket": bucket, "raceClass": cls, "fieldSize": field})
            features.append(f)
    # RESULTS UPDATE ONLY AFTER ALL FEATURES FOR DATE HAVE BEEN FROZEN.
    for race in races_by_date[date]:
        rid = race["raceId"]; venue = race["venue"]
        surf, dist, bucket, cls, direction, track, weather = CTX[rid]
        rs = {int(x["horseNo"]): x for x in runners_by_race[rid]}
        result_rows = [x for x in results_by_race[rid].values() if isinstance(x.get("finishPosition"), int) and x["finishPosition"] > 0]
        if not result_rows:
            continue
        nfield = len(result_rows)
        times = {int(x["horseNo"]): parse_time(x.get("timeText")) for x in result_rows}
        valid_times = [x for x in times.values() if x is not None]
        winner_time = min(valid_times) if valid_times else None
        f3_valid = sorted((float(x["final3f"]), int(x["horseNo"])) for x in result_rows if x.get("final3f") is not None)
        f3_rank = {hn: i for i, (_, hn) in enumerate(f3_valid)}
        base = race_baseline.get(rid)
        mp = race_market.get(rid, {})
        current_dt = datetime.strptime(date, "%Y-%m-%d").date()
        for x in result_rows:
            hn = int(x["horseNo"]); rr = rs.get(hn)
            if not rr:
                continue
            h = str(rr.get("horseName") or ""); j = str(rr.get("jockey") or ""); t = str(rr.get("trainer") or "")
            finish = int(x["finishPosition"])
            fin_pct = (finish - 1) / max(1, nfield - 1)
            f3_pct = f3_rank.get(hn, 0) / max(1, len(f3_valid) - 1) if f3_valid else 0.5
            tm = times.get(hn); behind = (tm - winner_time) if tm is not None and winner_time is not None else 0.0
            speed = (base - tm) if base is not None and tm is not None else None
            resid = (1.0 if finish == 1 else 0.0) - mp.get(hn, 0.0)
            perf = [1.0, 1.0 if finish == 1 else 0.0, 1.0 if finish <= 3 else 0.0,
                    fin_pct, f3_pct, resid, behind, speed if speed is not None else 0.0, 1.0 if speed is not None else 0.0]
            keys = [
                ("horse", h), ("jockey", j), ("trainer", t), ("horseSurf", h, surf),
                ("horseSD", h, surf, bucket), ("horseVenue", h, venue), ("horseClass", h, cls),
                ("jockeySD", j, surf, bucket), ("jockeyVenue", j, venue),
                ("trainerSD", t, surf, bucket), ("trainerVenue", t, venue), ("trainerClass", t, cls),
                ("horseJockey", h, j),
            ]
            for key in keys:
                aggs[key] += perf
            recent[h].append({"finish": fin_pct, "f3": f3_pct, "behind": behind, "speed": speed,
                              "marketResid": resid, "surface": surf, "distance": dist, "class": cls, "date": current_dt})
            last_run[h] = {"surface": surf, "distance": dist, "class": cls, "date": current_dt}
        if winner_time is not None and dist:
            for store, key in ((condition_exact, (venue, surf, dist, track, cls)),
                               (condition_vsd, (venue, surf, dist)), (condition_sd, (surf, dist))):
                store[key][0] += 1; store[key][1] += winner_time
    if di % 25 == 0:
        print(json.dumps({"featureDateIndex": di, "date": date, "rows": len(features)}), flush=True)

X = np.asarray(features, dtype=np.float32)
meta = pd.DataFrame(rows_meta)
if X.shape != (106122, len(feature_names)):
    raise RuntimeError(f"FEATURE_SHAPE:{X.shape}:{len(feature_names)}")
np.save(OUT / "runner-features.npy", X)
meta.to_pickle(OUT / "runner-meta.pkl.gz", compression="gzip")

eligible = meta["eligible"].to_numpy(bool)
di = meta["dateIndex"].to_numpy(np.int16)
market = meta["marketP"].to_numpy(np.float64)
ywin = meta["winY"].to_numpy(np.int8)
yt3 = meta["top3Y"].to_numpy(np.int8)
model_p = market.copy(); resid_p = market.copy(); top3_p = np.minimum(1.0, 3.0 * market)
block_metrics = []
for b, nxt in ((30, 90), (90, 150), (150, 210), (210, 244)):
    tr = eligible & (di < b); te = eligible & (di >= b) & (di < nxt)
    params = {"learning_rate": 0.04, "num_leaves": 21, "min_data_in_leaf": 60, "feature_fraction": 0.8,
              "max_bin": 63, "verbosity": -1, "num_threads": 4, "seed": 20260810, "force_col_wise": True}
    pwin = dict(params); pwin["objective"] = "binary"
    mwin = lgb.train(pwin, lgb.Dataset(X[tr], label=ywin[tr]), num_boost_round=150, callbacks=[lgb.log_evaluation(0)])
    mt3 = lgb.train(pwin, lgb.Dataset(X[tr], label=yt3[tr]), num_boost_round=150, callbacks=[lgb.log_evaluation(0)])
    pres = dict(params); pres["objective"] = "huber"
    mres = lgb.train(pres, lgb.Dataset(X[tr], label=(ywin[tr] - market[tr])), num_boost_round=120, callbacks=[lgb.log_evaluation(0)])
    model_p[te] = mwin.predict(X[te]); top3_p[te] = mt3.predict(X[te]); resid_p[te] = np.clip(market[te] + mres.predict(X[te]), 1e-8, 1.0)
    # Renormalize win probability families race by race inside test block.
    test_idx = np.flatnonzero(te)
    for ri in np.unique(meta.loc[te, "raceIndex"].to_numpy(int)):
        loc = test_idx[meta.loc[te, "raceIndex"].to_numpy(int) == ri]
        for arr in (model_p, resid_p):
            s = arr[loc].sum()
            if s > 0:
                arr[loc] /= s
    block_metrics.append({
        "start": b, "end": nxt, "rows": int(te.sum()),
        "marketAuc": float(roc_auc_score(ywin[te], market[te])),
        "modelAuc": float(roc_auc_score(ywin[te], model_p[te])),
        "residualAuc": float(roc_auc_score(ywin[te], resid_p[te])),
        "top3Auc": float(roc_auc_score(yt3[te], top3_p[te]))
    })
    print(json.dumps(block_metrics[-1]), flush=True)

np.savez_compressed(OUT / "runner-oos-probabilities.npz", modelP=model_p.astype(np.float32),
                    residualP=resid_p.astype(np.float32), top3P=top3_p.astype(np.float32))
summary = {"rows": int(X.shape[0]), "features": len(feature_names), "dates": len(dates), "races": len(races),
           "featureNames": feature_names, "blocks": block_metrics, "sameDateFreeze": True}
(OUT / "runner-oos-meta.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"runnerOosComplete": True, "rows": X.shape[0], "features": X.shape[1], "blocks": block_metrics}), flush=True)
