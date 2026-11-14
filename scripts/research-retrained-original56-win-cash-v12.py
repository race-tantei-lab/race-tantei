#!/usr/bin/env python3
"""First real 56-feature LightGBM forward-money research, read-only.

DATA LIMITATIONS MATTER:
- The exact original 56-feature CSV was deleted from GitHub Actions, and
  the reconstructed 56-column archive has unknown pre-2024 weather/track/
  direction, so this is not byte-identical to the current production model.
- The recorded official JRA WIN payout D1 archive starts in May 2024.
- Historical runner WIN odds are FINAL, not a verified T-minus-15 snapshot.
- Only WIN is cash-settled here. The original production policy used two
  DIFFERENT types across six markets; this experiment does not reproduce
  that policy. It is the first genuinely time-causal 56-feature baseline
  which can later extend to all types with recorded pre-T15 prices.

Fit the exact original FEATURES and LightGBM architecture with different
lookbacks/embargoes every target month. The original frozen whole-archive
model is a **LEAKY reference**, never a valid forward baseline. Optimize
purchase policies using 2025 only. Evaluate 2026 Jan-Aug only when the
2025 development ledger passes 200% ROI, 200% minus largest paid race,
20% paid-race hit and >=3 actually purchased races per venue/day.

No below-200 policy becomes a serialized "model". Nothing changes D1,
production tickets, training history or GitHub main.
"""
from __future__ import annotations
import argparse
import collections
import dataclasses
import datetime as dt
import itertools
import json
import math
from pathlib import Path
import time
import numpy as np
import pandas as pd
import lightgbm as lgb

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/"config/ten-year-completed-model.json"
MODEL=ROOT/"models/ten-year-completed-model.txt"
HORIZONS=(3,6,12,24,36,60,96)
EMBARGO_MONTHS=(0,12)
RACE_SCORING=("probability","canonical_ev_power","full_ev")
RACE_ORDERING=("confidence","edge")
SLATES=(3,5)
RESEARCH_START="2025-01-01"
INDEPENDENT_START="2026-01-01"
INDEPENDENT_END="2026-08-09"
MIN_TRAIN_RUNNERS=1200


@dataclasses.dataclass(frozen=True)
class Method:
    horizon_months: int
    embargo_months: int
    score: str
    slate: int
    rank: str

    def data(self):
        return dataclasses.asdict(self)


def metrics(tickets):
    if not tickets:return None
    stake=sum(int(x["stakeYen"]) for x in tickets)
    received=sum(int(x["returnYen"]) for x in tickets)
    biggest=max(int(x["returnYen"]) for x in tickets)
    hit=sum(int(x["returnYen"]>0) for x in tickets)
    day_counts=collections.Counter((x["date"],x["venue"]) for x in tickets)
    valid=bool(day_counts) and min(day_counts.values())>=3
    return {
        "races":len(tickets),
        "venueDays":len(day_counts),
        "minimumPerVenueDay":min(day_counts.values(),default=0),
        "stakeYen":stake,
        "returnYen":received,
        "profitYen":received-stake,
        "roiPct":round(100*received/stake,6),
        "minusLargestRaceRoiPct":round(100*(received-biggest)/stake,6),
        "hitRaces":hit,
        "hitPct":round(100*hit/len(tickets),6),
        "largestPaidRaceYen":biggest,
        "qualified":bool(valid and len(day_counts)>=25 and
                         received>=2*stake+biggest and hit*5>=len(tickets))
    }


def payouts(path):
    result={}
    by_race=collections.defaultdict(dict)
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():continue
            r=json.loads(line)
            if r.get("source")!="D1_stored_JRA_return_not_independently_verified":
                raise RuntimeError("PAYOUT_SOURCE_PROVENANCE_INVALID")
            if r.get("betType")!="単勝":raise RuntimeError("WIN_ONLY_SETTLEMENT_EXPECTED")
            key=(str(r["raceId"]),int(r["combination"]))
            ret=int(r["payoutYenPer100"])
            if key in result or ret<=0:raise RuntimeError("INVALID_OR_DUPLICATE_SETTLEMENT")
            result[key]=ret
            by_race[key[0]][key[1]]=ret
    if len(by_race)<5000:raise RuntimeError("OFFICIAL_D1_WIN_PAYOUT_SOURCE_INCOMPLETE")
    return result,set(by_race)


def feature_frame(path,feat):
    df=pd.read_csv(path,compression="gzip",dtype={"raceId":str,"raceDate":str},
                   low_memory=False)
    need={"raceId","raceDate","labelWin","originalDemandSelected",
          "horseNoRaw","winOddsFinal"}|set(feat)
    missing=need-set(df)
    if missing:raise RuntimeError(f"RECONSTRUCTED_FEATURES_MISSING:{sorted(missing)}")
    if len(df)<470000:raise RuntimeError(f"RECONSTRUCTED_RUNNER_COUNT_LOW:{len(df)}")
    if df["originalDemandSelected"].sum()<180000:
        raise RuntimeError("CANONICAL_SELECTED_RUNNERS_MISSING")
    df["winOddsFinal"]=pd.to_numeric(df["winOddsFinal"],errors="coerce")
    df["date"]=pd.to_datetime(df["raceDate"])
    df["month"]=df["date"].dt.to_period("M")
    df["horseNoRaw"]=pd.to_numeric(df["horseNoRaw"],errors="coerce")
    arr=df[feat].to_numpy(dtype=np.float32)
    if not np.isfinite(arr).all():
        raise RuntimeError("TRAINING_FEATURES_NONFINITE")
    labels=df["labelWin"].to_numpy(dtype=np.int8)
    if not np.isin(labels,[0,1]).all():raise RuntimeError("INVALID_WIN_LABEL")
    return df,arr,labels


def preevent_training_indices(df,month,horizon,embargo):
    # STRICT: the target month's race outcomes never enter model.fit.
    first_day=month.to_timestamp()
    end=first_day-pd.DateOffset(months=embargo)
    start=end-pd.DateOffset(months=horizon)
    mask=(df["date"]<end)&(df["date"]>=start)&(df["originalDemandSelected"]==1)
    chosen=np.flatnonzero(mask.to_numpy())
    if len(chosen)<MIN_TRAIN_RUNNERS:
        return None
    if df.iloc[chosen]["raceId"].nunique()<70:
        return None
    if not df.iloc[chosen]["date"].max()<end:
        raise AssertionError("TARGET_RESULT_LEAKED_INTO_TRAINING")
    return chosen


def money_candidates(df,target_indices,raw_probs,paid,score_style):
    # Each row was selected using its historical pre-race features. The
    # odds were final race odds and are NOT certifiably tradable at T-15.
    by_race=collections.defaultdict(list)
    odds=df["winOddsFinal"].to_numpy()
    nums=df["horseNoRaw"].to_numpy()
    rid=df["raceId"].to_numpy()
    date=df["raceDate"].to_numpy()
    for j,absidx in enumerate(target_indices):
        hno=int(nums[absidx])
        final_odds=float(odds[absidx])
        if not math.isfinite(final_odds) or final_odds<1.0:continue
        p=float(raw_probs[j])
        if not math.isfinite(p) or p<0:continue
        if score_style=="probability":
            score=p
        elif score_style=="canonical_ev_power":
            score=p*(final_odds**0.4)
        elif score_style=="full_ev":
            score=p*final_odds
        else:raise ValueError("UNKNOWN_CHOICE_SCORE")
        by_race[str(rid[absidx])].append((score,p,final_odds,hno,j,absidx))
    output=[]
    for race_id,entries in by_race.items():
        if not entries:continue
        entries.sort(key=lambda x:(-x[0],-x[1],x[3]))
        z=entries[0]
        _,p,odd,hno,_,absidx=z
        venue = ""  # canonical race ID decoding is separately audited
        output.append({
            "raceId":race_id,
            "date":str(date[absidx]),
            "winner":hno,
            "betType":"単勝",
            "priceFinalOdds":odd,
            "predictedProbability":p,
            "ticketScore":float(z[0]),
            "edge":float(p*odd),
            "returnYen":int(paid.get((race_id,hno),0)),
            "stakeYen":100,
        })
    return output


def venue_for_race(rid,calendar):
    try:
        return calendar[rid]
    except KeyError:
        raise RuntimeError(f"RACE_NOT_IN_FROZEN_CALENDAR:{rid}")


def calendar_venues():
    import base64,gzip
    result={}
    buf=""
    for path in sorted((ROOT/"src/v1/ten-year-history-data").glob("bin-*.ts")):
        raw=path.read_text(encoding="utf-8").strip()
        buf+=json.loads(raw.removeprefix("export default ").removesuffix(";"))
    history=json.loads(gzip.decompress(base64.b64decode(buf)))["races"]
    for race in history:
        result[str(race[0])]=str(race[2])
    if len(result)!=34566:raise RuntimeError("FROZEN_VENUE_CALENDAR_INCOMPLETE")
    return result


def settle(candidates,calendar,slate,priority):
    groups=collections.defaultdict(list)
    for x in candidates:
        groups[(x["date"],venue_for_race(x["raceId"],calendar))].append(x)
    chosen=[]
    bad=[]
    for (date,venue),races in sorted(groups.items()):
        if len(races)<3:
            bad.append((date,venue,len(races)))
            continue
        score_key="ticketScore" if priority=="confidence" else "edge"
        ordered=sorted(races,key=lambda x:(-x[score_key],x["raceId"]))
        # A venue/day cannot contain fewer than 3 independent bought races.
        for r in ordered[:slate]:
            chosen.append({**r,"venue":venue})
    return chosen,bad,len(groups)


def build_model(cfg,x,labels,indices,seed=20261114):
    params=dict(cfg["runnerProbabilityModel"]["params"])
    params.update(n_estimators=300,num_leaves=63,n_jobs=3,verbosity=-1,
                  random_state=seed)
    model=lgb.LGBMClassifier(**params)
    model.fit(x[indices],labels[indices])
    return model


def test_all(df,x,labels,paid,calendar,feat,output):
    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    if feat!=list(cfg["runnerProbabilityModel"]["features"]):
        raise RuntimeError("NOT_ORIGINAL_56_MODEL_SCHEMA")
    independent_records=set(r for r,_ in paid)
    groups=collections.defaultdict(list)
    for i,r in enumerate(df.itertuples(index=False)):
        if (r.originalDemandSelected==1 and r.raceId in independent_records and
                RESEARCH_START<=r.raceDate<=INDEPENDENT_END):
            groups[r.month].append(i)
    if not groups:
        raise RuntimeError("NO_FINANCIAL_SETTLEMENT_EVALUATION_DATA")
    months=sorted(groups)
    months=[m for m in months if m.to_timestamp().strftime("%Y-%m-%d")>=RESEARCH_START]
    # Refit 56-feature horse probabilities from historical labels under each
    # actual past-duration, never from unseen target-month labels.
    yen_records=collections.defaultdict(list)
    counters=collections.Counter()
    for month in months:
        target_indices=np.asarray(groups[month],dtype=np.int64)
        for horizon,lag in itertools.product(HORIZONS,EMBARGO_MONTHS):
            training= preevent_training_indices(df,month,horizon,lag)
            if training is None:
                counters["insufficientTrainingRuns"]+=1
                continue
            model=build_model(cfg,x,labels,training)
            pred=model.predict_proba(x[target_indices])[:,1]
            if not np.all(np.isfinite(pred)):raise RuntimeError("INVALID_LGBM_PREDICTIONS")
            for choice in RACE_SCORING:
                tickets=money_candidates(df,target_indices,pred,paid,choice)
                for slate,order in itertools.product(SLATES,RACE_ORDERING):
                    selected,bad,ngroups=settle(tickets,calendar,slate,order)
                    if bad:
                        # An incomplete source venue/day is a research coverage
                        # problem, not a conveniently skipped losing race.
                        counters["incompleteVenueDayRuns"]+=1
                    key=Method(horizon,lag,choice,slate,order)
                    yen_records[key].extend(selected)
            counters["trainedFreshRunnerModels"]+=1
        print("CANONICAL_56_WALKFORWARD_MONTH",json.dumps({
            "month":str(month),"modelRefitsCumulative":counters["trainedFreshRunnerModels"],
            "distinctResearchMethods":len(yen_records),
            "targetRunners":len(target_indices)
        },ensure_ascii=False),flush=True)
    dev_eligible=[]
    for method,records in yen_records.items():
        dev=[r for r in records if r["date"]<INDEPENDENT_START]
        s=metrics(dev)
        if s and s["qualified"]:
            dev_eligible.append((method,s,records))
    dev_eligible.sort(key=lambda x:(x[1]["profitYen"],
                     x[1]["minusLargestRaceRoiPct"]),reverse=True)
    verified=[]
    for method,s,records in dev_eligible:
        future=[r for r in records if INDEPENDENT_START<=r["date"]<=INDEPENDENT_END]
        cash=metrics(future)
        if cash and cash["qualified"]:
            verified.append({"method":method.data(),
                "2025DevelopmentCash":s,
                "2026UntouchedCash":cash,
                "historicalFinalOddsNotT15":True,
                "preT15ProductionEligible":False})
    return {
        "status":"RESEARCH_56FEATURE_QUALIFIED_CASH_METHOD" if verified else
                "NO_PRET15_PROVEN_ROI200_MODEL",
        "originalProduction56FeaturesUsedAsSchema":True,
        "exactOriginalTrainingCorpusAvailable":False,
        "originalModelPolicyReproduced":False,
        "trainingAlgorithm":"LightGBM 56 features, 300 trees, 63 leaves, monthly refit",
        "pastDataHorizonsMonths":list(HORIZONS),
        "pastDataEmbargoesMonths":list(EMBARGO_MONTHS),
        "ticketMarketsTested":["単勝"],
        "developmentWindow":"2025-01-01..2025-12-31",
        "independentWindow":"2026-01-01..2026-08-09",
        "inputFeatureRows":len(df),
        "liveD1WinSettlementRaces":len(independent_records),
        "trainedCandidateModels":counters["trainedFreshRunnerModels"],
        "generatedPurchasingPolicies":len(yen_records),
        "developmentQualifiedModelCount":len(dev_eligible),
        "independentQualifiedModelCount":len(verified),
        "models":verified,
        "coverageDiagnostics":dict(counters),
        "full2017to2026ActualYenValidationAvailable":False,
        "researchInputDeficiencies":[
            "Historical 56-feature source artifact expired",
            "Pre-2024 track and weather source missing",
            "Only recorded 2024-2026 official cash available",
            "Final win odds, not T-15 JRA quotes",
            "Other five markets not yet cash-reconciled"],
        "researchOnly":True,
        "productionChanged":False,
        "productionPromotionAllowed":False,
    }


def self_test():
    test=[
        {"date":"2025-01-01","venue":"東京","raceId":f"r{i}",
         "returnYen":900 if i==0 else 0,"stakeYen":100}
        for i in range(3)
    ]
    m=metrics(test)
    assert m["roiPct"]==300
    assert m["minusLargestRaceRoiPct"]==0
    assert not m["qualified"]
    assert not metrics(test[:2])["qualified"]
    print("56FEATURE_REAL_YEN_ROLLING_GATE_SELFTEST_OK",flush=True)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--features")
    ap.add_argument("--payouts")
    ap.add_argument("--output")
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:
        self_test();return
    started=time.monotonic()
    if not(args.features and args.payouts and args.output):
        ap.error("--features --payouts --output are all required")
    feat=list(json.loads(CFG.read_text())["runnerProbabilityModel"]["features"])
    frame,x,y=feature_frame(args.features,feat)
    payouts_by_ticket,settled_races=payouts(args.payouts)
    venues=calendar_venues()
    report=test_all(frame,x,y,payouts_by_ticket,venues,feat,args.output)
    report["elapsedSeconds"]=round(time.monotonic()-started,2)
    out=Path(args.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("ORIGINAL56_WALKFORWARD_WIN_CASH_FINAL",json.dumps({
        "status":report["status"],
        "retrainedModels":report["trainedCandidateModels"],
        "purchasingPolicies":report["generatedPurchasingPolicies"],
        "developmentQualified":report["developmentQualifiedModelCount"],
        "independentQualified":report["independentQualifiedModelCount"],
        "onlyQualifyingModels":report["models"],
        "seconds":report["elapsedSeconds"],
        "preT15Valid":False},ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
