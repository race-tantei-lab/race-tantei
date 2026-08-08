import gc
import gzip
import itertools
import json
import math
import os
import pickle
import tempfile
from collections import defaultdict
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "artifacts" / "speed-analysis-input"
RUN = ROOT / "artifacts" / "speed-runner-oos"
OUT = ROOT / "artifacts" / "speed-light-evaluation"
OUT.mkdir(parents=True, exist_ok=True)

with gzip.open(IN / "completion-analysis-dataset.pkl.gz", "rb") as f:
    D = pickle.load(f)
meta = pd.read_pickle(RUN / "runner-meta.pkl.gz").reset_index(drop=True)
Xr = np.load(RUN / "runner-features.npy", mmap_mode="r")
probs = np.load(RUN / "runner-oos-probabilities.npz")
modelP = probs["modelP"].astype(np.float64)
residP = probs["residualP"].astype(np.float64)
top3P = probs["top3P"].astype(np.float64)
F = Xr.shape[1]
if len(meta) != Xr.shape[0]:
    raise RuntimeError("RUNNER_META_FEATURE_MISMATCH")

races = D["races"]
race_ids = [r["raceId"] for r in races]
N = len(race_ids)
race_index = {rid: i for i, rid in enumerate(race_ids)}
dates = []
for r in races:
    if not dates or dates[-1] != r["raceDate"]:
        dates.append(r["raceDate"])
date_index = {d: i for i, d in enumerate(dates)}
race_date_idx = np.array([date_index[r["raceDate"]] for r in races], dtype=np.int16)

# Official odds are already ordered exactly by fixed race archive.
odds_records = []
with gzip.open(IN / "all7695-official-odds.jsonl.gz", "rt", encoding="utf-8") as f:
    for line in f:
        odds_records.append(json.loads(line))
if len(odds_records) != N or [x["raceId"] for x in odds_records] != race_ids:
    raise RuntimeError("OFFICIAL_ODDS_ORDER_MISMATCH")

# Actual payout map; no inferred settlement.
payout = defaultdict(lambda: defaultdict(dict))
name_map = {"単勝": "win", "ワイド": "wide", "馬連": "umaren"}
for x in D["payouts"]:
    bt = name_map.get(x["betType"])
    if not bt:
        continue
    try:
        tup = tuple(int(z) for z in str(x["combination"]).split("-"))
    except Exception:
        continue
    if bt in ("wide", "umaren"):
        tup = tuple(sorted(tup))
    payout[x["raceId"]][bt][tup] = max(int(x["payoutYen"]), payout[x["raceId"]][bt].get(tup, 0))

# Runner rows by race and horse.
race_rows = defaultdict(dict)
for i, r in meta.iterrows():
    race_rows[r["raceId"]][int(r["horseNo"])] = int(i)


def structs(horses):
    pairs = list(itertools.combinations(horses, 2))
    return pairs


def pl_top2_pair(p, ia, ib):
    pa, pb = p[ia], p[ib]
    return pa * pb / max(1e-9, 1 - pa) + pb * pa / max(1e-9, 1 - pb)


def pl_top3_pair(p, ia, ib):
    total = 0.0
    n = len(p)
    for ic in range(n):
        if ic in (ia, ib):
            continue
        for a, b, c in ((ia, ib, ic), (ia, ic, ib), (ib, ia, ic), (ib, ic, ia), (ic, ia, ib), (ic, ib, ia)):
            total += p[a] * p[b] / max(1e-9, 1 - p[a]) * p[c] / max(1e-9, 1 - p[a] - p[b])
    return total


def norm_prob(values, mass=1.0):
    inv = np.array([0.0 if v is None or float(v) <= 0 else 1.0 / float(v[0] if isinstance(v, list) else v) for v in values], dtype=float)
    s = inv.sum()
    return inv / s * mass if s > 0 else inv


def race_runner_prob(ri, horses, arr):
    vals = np.array([float(arr[race_rows[race_ids[ri]][int(h)]]) for h in horses], dtype=float)
    s = vals.sum()
    return vals / s if s > 0 else np.ones(len(horses)) / len(horses)

BLENDS = np.array([0.0, 0.25, 0.5, 0.75, 1.0], dtype=float)
TOPK = 12
blocks = [(30, 90), (90, 150), (150, 210), (210, 244)]
model_params = {"objective": "binary", "metric": "binary_logloss", "learning_rate": 0.04, "num_leaves": 21,
                "min_data_in_leaf": 100, "feature_fraction": 0.8, "max_bin": 63, "verbosity": -1,
                "num_threads": 4, "seed": 20260810, "force_col_wise": True}

# Outputs per bet type: [blend, race, rank]
candidates = {}
cold = {}
ticket_metrics = []


def build_type(bt):
    if bt == "win":
        total = sum(len(rec["horses"]) for rec in odds_records)
        dim = F + 7
    else:
        total = sum(len(rec["umaren"] if bt == "umaren" else rec["wide"]) for rec in odds_records)
        dim = 2 * F + 8
    tmp = Path(tempfile.mkdtemp(prefix=f"rt-{bt}-"))
    X = np.lib.format.open_memmap(tmp / "X.npy", mode="w+", dtype=np.float32, shape=(total, dim))
    y = np.lib.format.open_memmap(tmp / "y.npy", mode="w+", dtype=np.int8, shape=(total,))
    ret = np.lib.format.open_memmap(tmp / "ret.npy", mode="w+", dtype=np.float32, shape=(total,))
    rr = np.lib.format.open_memmap(tmp / "race.npy", mode="w+", dtype=np.int32, shape=(total,))
    offsets = np.zeros(len(dates) + 1, dtype=np.int64)
    cS = np.full((N, TOPK), np.nan, np.float32); cR = np.zeros((N, TOPK), np.int32); cC = np.zeros(N, np.int8)
    pos = 0
    for ri, rec in enumerate(odds_records):
        rid = rec["raceId"]; horses = [int(x) for x in rec["horses"]]
        mkt = norm_prob(rec[bt], 3.0 if bt == "wide" else 1.0)
        pm = race_runner_prob(ri, horses, modelP); pr = race_runner_prob(ri, horses, residP)
        pt3 = np.array([float(top3P[race_rows[rid][h]]) for h in horses], dtype=float)
        if bt == "win":
            combos = [(h,) for h in horses]; oddsvals = rec["win"]
        else:
            combos = structs(horses); oddsvals = rec[bt]
        cold_scores = []
        for j, combo in enumerate(combos):
            if bt == "win":
                h = combo[0]; ix = race_rows[rid][h]; official = float(oddsvals[j])
                p1 = float(pm[j]); p2 = float(pr[j]); p3 = float(pt3[j])
                X[pos, :F] = Xr[ix]
                X[pos, F:] = [official, mkt[j], p1, p2, p3, p1 / max(mkt[j], 1e-9), p2 / max(mkt[j], 1e-9)]
                cold_prob = 0.5 * mkt[j] + 0.5 * p1
            else:
                a, b = combo; ia = horses.index(a); ib = horses.index(b); xa = race_rows[rid][a]; xb = race_rows[rid][b]
                official = float(oddsvals[j][0] if isinstance(oddsvals[j], list) else oddsvals[j])
                va = np.asarray(Xr[xa]); vb = np.asarray(Xr[xb])
                X[pos, :F] = (va + vb) * 0.5; X[pos, F:2 * F] = np.abs(va - vb)
                if bt == "wide":
                    p1 = pl_top3_pair(pm, ia, ib); p2 = pl_top3_pair(pr, ia, ib)
                    p3 = min(1.0, max(0.0, pt3[ia])) * min(1.0, max(0.0, pt3[ib]))
                else:
                    p1 = pl_top2_pair(pm, ia, ib); p2 = pl_top2_pair(pr, ia, ib); p3 = float(pt3[ia] * pt3[ib])
                X[pos, 2 * F:] = [official, mkt[j], p1, p2, p3, p1 / max(mkt[j], 1e-9), p2 / max(mkt[j], 1e-9), p3 / max(mkt[j], 1e-9)]
                cold_prob = 0.5 * mkt[j] + 0.5 * p1
            actual = payout[rid][bt].get(tuple(sorted(combo)) if bt in ("wide", "umaren") else combo, 0)
            y[pos] = 1 if actual > 0 else 0; ret[pos] = actual / 100.0; rr[pos] = ri
            cold_scores.append((cold_prob * official, actual, j))
            pos += 1
        # fixed cold-start candidate ranking; no result is used in ranking
        cold_scores.sort(key=lambda x: (-x[0], x[2]))
        k = min(TOPK, len(cold_scores)); cC[ri] = k
        for rank, (score, actual, _) in enumerate(cold_scores[:k]):
            cS[ri, rank] = score; cR[ri, rank] = actual
        offsets[race_date_idx[ri] + 1] = pos
    if pos != total:
        raise RuntimeError(f"TICKET_TOTAL:{bt}:{pos}:{total}")
    # Fill cumulative date boundaries (all dates exist but multiple races share a date).
    for i in range(1, len(offsets)):
        if offsets[i] == 0:
            offsets[i] = offsets[i - 1]
    offsets[-1] = total
    S = np.full((len(BLENDS), N, TOPK), np.nan, np.float32)
    R = np.zeros((len(BLENDS), N, TOPK), np.int32)
    C = np.zeros((len(BLENDS), N), np.int8)
    for b, nxt in blocks:
        a = int(offsets[b]); z = int(offsets[nxt])
        params = dict(model_params); params["min_data_in_leaf"] = 50 if bt == "win" else 100
        mdl = lgb.train(params, lgb.Dataset(X[:a], label=y[:a]), num_boost_round=120, callbacks=[lgb.log_evaluation(0)])
        pred = mdl.predict(X[a:z]); market = X[a:z, F + 1] if bt == "win" else X[a:z, 2 * F + 1]
        official = X[a:z, F] if bt == "win" else X[a:z, 2 * F]
        test_race = np.asarray(rr[a:z]); test_ret = np.asarray(ret[a:z])
        ticket_metrics.append({"betType": bt, "start": b, "end": nxt, "rows": int(z - a),
                               "auc": float(roc_auc_score(y[a:z], pred)), "marketAuc": float(roc_auc_score(y[a:z], market))})
        st = 0
        for ri in np.unique(test_race):
            en = st
            while en < len(test_race) and test_race[en] == ri:
                en += 1
            for bi, w in enumerate(BLENDS):
                pp = (1 - w) * market[st:en] + w * pred[st:en]
                score = pp * official[st:en]
                valid = np.flatnonzero(np.isfinite(score) & (score >= 0))
                k = min(TOPK, len(valid)); C[bi, ri] = k
                if k:
                    if len(valid) <= k:
                        pick = valid[np.argsort(-score[valid], kind="stable")]
                    else:
                        sub = valid[np.argpartition(score[valid], -k)[-k:]]
                        pick = sub[np.argsort(-score[sub], kind="stable")]
                    pick = pick[:k]
                    S[bi, ri, :k] = score[pick].astype(np.float32)
                    R[bi, ri, :k] = np.rint(test_ret[st:en][pick] * 100).astype(np.int32)
            st = en
        print(json.dumps(ticket_metrics[-1]), flush=True)
        del mdl, pred
        gc.collect()
    del X, y, ret, rr
    gc.collect()
    for p in tmp.glob("*"):
        try: p.unlink()
        except Exception: pass
    try: tmp.rmdir()
    except Exception: pass
    return (S, R, C), (cS, cR, cC)

for bt in ("win", "wide", "umaren"):
    candidates[bt], cold[bt] = build_type(bt)
    print(json.dumps({"ticketModelComplete": bt}), flush=True)

# Pre-race race-level base features from runner metadata/OOS probabilities.
venue_vals = {x: i + 1 for i, x in enumerate(sorted({r["venue"] for r in races}))}
surface_vals = {x: i + 1 for i, x in enumerate(sorted(meta["surface"].unique()))}
bucket_vals = {x: i + 1 for i, x in enumerate(sorted(meta["distBucket"].unique()))}
class_vals = {x: i + 1 for i, x in enumerate(sorted(meta["raceClass"].unique()))}
race_base = np.zeros((N, 15), dtype=np.float32)
for ri, rid in enumerate(race_ids):
    g = meta[meta["raceIndex"] == ri]
    mi = g.index.to_numpy(int)
    mp = g["marketP"].to_numpy(float); pm = modelP[mi]; pr = residP[mi]
    entropy = -float(np.sum(mp * np.log(mp + 1e-12)))
    row = g.iloc[0]
    race_base[ri] = [float(row["fieldSize"]), float(row["raceNo"]), float(row["distanceM"]),
                     float(venue_vals.get(row["venue"], 0)), float(surface_vals.get(row["surface"], 0)),
                     float(bucket_vals.get(row["distBucket"], 0)), float(class_vals.get(row["raceClass"], 0)),
                     float(np.mean(np.abs(pm - mp))), float(np.max(np.abs(pm - mp))),
                     float(np.mean(np.abs(pr - mp))), float(np.max(np.abs(pr - mp))), entropy,
                     float(np.max(mp)), float(np.max(pm)), float(np.max(pr))]

# Blend selector state: realized top-10 returns on strictly prior dates only.
prior_n = 40.0; prior_sum = 32.0
stats = {bt: [[0.0, 0] for _ in BLENDS] for bt in ("win", "wide", "umaren")}

def shr(bt, bi):
    s, n = stats[bt][bi]
    return (s + prior_sum) / (n + prior_n)

def choose_blend(bt):
    vals = [shr(bt, i) for i in range(len(BLENDS))]
    mx = max(vals)
    if abs(vals[2] - mx) < 1e-12:
        return 2
    return max(range(len(BLENDS)), key=lambda i: (vals[i], -i))


def summarize(sc, perf, blend_index):
    s = np.asarray(sc, dtype=float); s = s[np.isfinite(s)]
    if len(s) == 0:
        s = np.array([0.0])
    vals = [float(s[0]), float(s[:3].mean()), float(s[:5].mean()), float(s[:5].std()), float(perf)]
    one = [0.0] * len(BLENDS); one[blend_index] = 1.0
    return vals + one


def allocate(parts):
    units = {}; total = 0
    for bt, (sc, rt, ct, perf, bi) in parts.items():
        if ct < 1:
            raise RuntimeError(f"NO_TICKET:{bt}")
        units[(bt, 0)] = 1; total += 1
    pool = []
    for bt, (sc, rt, ct, perf, bi) in parts.items():
        for j in range(int(ct)):
            if np.isfinite(sc[j]):
                pool.append((max(0.0, float(sc[j])) * max(0.0, float(perf)), bt, j))
    pool.sort(key=lambda x: (-x[0], x[1], x[2]))
    rem = 20 - total
    for util, bt, j in pool:
        if rem <= 0:
            break
        cur = units.get((bt, j), 0); cap = 2 - cur
        if cap <= 0:
            continue
        add = min(cap, rem); units[(bt, j)] = cur + add; rem -= add
    if rem:
        raise RuntimeError(f"LIGHT_BUDGET_UNFILLED:{rem}")
    ret_yen = 0; largest = 0; type_stake = defaultdict(int)
    for (bt, j), u in units.items():
        value = int(parts[bt][1][j]) * u
        ret_yen += value; largest = max(largest, value); type_stake[bt] += u * 100
    if sum(type_stake.values()) != 2000 or any(type_stake[x] < 100 for x in ("win", "wide", "umaren")):
        raise RuntimeError("LIGHT_STRUCTURE_GATE")
    return ret_yen, largest

Xhist = []; yhist = []
selector = None
selected = []
total_stake = 0; total_return = 0; largest_ticket = 0
periods = defaultdict(lambda: [0, 0])
trace = []
for di, date in enumerate(dates):
    idx = np.flatnonzero(race_date_idx == di)
    if di < 30:
        chosen = {bt: 2 for bt in ("win", "wide", "umaren")}; perf = {bt: 0.8 for bt in chosen}
    else:
        chosen = {bt: choose_blend(bt) for bt in ("win", "wide", "umaren")}
        perf = {bt: shr(bt, chosen[bt]) for bt in chosen}
    dayX = []; dayY = []; dayInfo = []; coldScore = []
    for ri in idx:
        feat = list(race_base[ri])
        parts = {}
        cs = []
        for bt in ("win", "wide", "umaren"):
            bi = chosen[bt]
            if di < 30:
                sc, rt, ct = cold[bt]; s = sc[ri]; r = rt[ri]; c = int(ct[ri])
            else:
                sc, rt, ct = candidates[bt]; s = sc[bi, ri]; r = rt[bi, ri]; c = int(ct[bi, ri])
            parts[bt] = (s, r, c, perf[bt], bi)
            feat.extend(summarize(s[:c], perf[bt], bi))
            ss = np.asarray(s[:c]); ss = ss[np.isfinite(ss)]
            cs.append(float(ss[:3].mean()) if len(ss) else 0.0)
        ret_yen, lg = allocate(parts)
        dayX.append(feat); dayY.append(ret_yen / 2000.0); dayInfo.append((ret_yen, lg)); coldScore.append(float(np.mean(cs)))
    dayX = np.asarray(dayX, dtype=np.float32); dayY = np.asarray(dayY, dtype=np.float32)
    if di in (30, 90, 150, 210):
        params = {"objective": "huber", "learning_rate": 0.04, "num_leaves": 15, "min_data_in_leaf": 80,
                  "feature_fraction": 0.8, "max_bin": 63, "verbosity": -1, "num_threads": 4,
                  "seed": 20260810, "force_col_wise": True}
        selector = lgb.train(params, lgb.Dataset(np.asarray(Xhist, np.float32), label=np.asarray(yhist, np.float32)),
                             num_boost_round=100, callbacks=[lgb.log_evaluation(0)])
    score = np.asarray(coldScore) if di < 30 or selector is None else selector.predict(dayX)
    byvenue = defaultdict(list)
    for loc, ri in enumerate(idx):
        byvenue[races[ri]["venue"]].append(loc)
    day_selected = []
    for venue, locs in byvenue.items():
        locs = sorted(locs, key=lambda j: (-float(score[j]), int(races[idx[j]]["raceNo"])))[:5]
        if len(locs) != 5:
            raise RuntimeError(f"FIVE_RACE_GATE:{date}:{venue}:{len(locs)}")
        day_selected.extend(locs)
    for loc in day_selected:
        ri = int(idx[loc]); r, lg = dayInfo[loc]
        selected.append(ri); total_stake += 2000; total_return += r; largest_ticket = max(largest_ticket, lg)
        half = f"{date[:4]}-H{1 if int(date[5:7]) <= 6 else 2}"
        periods[half][0] += 2000; periods[half][1] += r
    # selector history can use every race only after date decisions are frozen
    Xhist.extend(dayX.tolist()); yhist.extend(dayY.tolist())
    # update all counterfactual blend returns only after the date ends
    if di >= 30:
        for bt in ("win", "wide", "umaren"):
            S, R, C = candidates[bt]
            for bi in range(len(BLENDS)):
                for ri in idx:
                    k = min(10, int(C[bi, ri]))
                    if k:
                        stats[bt][bi][0] += float(np.asarray(R[bi, ri, :k], dtype=float).sum() / 100.0)
                        stats[bt][bi][1] += k
    if di in (0, 29, 30, 89, 90, 149, 150, 209, 210, 243):
        trace.append({"dateIndex": di, "date": date, "selected": len(selected),
                      "roiPct": 100.0 * total_return / total_stake if total_stake else 0.0,
                      "chosenBlend": {bt: float(BLENDS[chosen[bt]]) for bt in chosen}})
        print(json.dumps(trace[-1], ensure_ascii=False), flush=True)

result = {
    "status": "not_a_model_unless_completion_gates_pass",
    "races": len(selected), "selectedUnique": len(set(selected)), "expectedRaces": 3210,
    "stakeYen": total_stake, "returnYen": total_return,
    "roiPct": 100.0 * total_return / total_stake,
    "largestTicketReturnYen": largest_ticket,
    "trimmedRoiPct": 100.0 * (total_return - largest_ticket) / total_stake,
    "ticketMetrics": ticket_metrics,
    "periods": {k: {"stake": v[0], "return": v[1], "roiPct": 100.0 * v[1] / v[0]} for k, v in sorted(periods.items())},
    "trace": trace,
    "finalBlendStats": {bt: {str(float(BLENDS[i])): shr(bt, i) for i in range(len(BLENDS))} for bt in stats},
    "officialOddsOnly": True, "syntheticOddsUsed": False, "sameDateLeakage": False,
    "completionGatePass": bool((100.0 * total_return / total_stake) >= 200.0 and (100.0 * (total_return - largest_ticket) / total_stake) >= 100.0 and len(selected) == 3210)
}
(OUT / "speed-light-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False), flush=True)
