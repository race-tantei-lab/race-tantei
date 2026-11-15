#!/usr/bin/env python3
"""Learn a NEW rolling money-prediction model while retaining the existing winner.

The research search must contain at least the already-existing original
"ten-year-completed-model" as an immutable positive control. Previous v10-v14
runs mistakenly omitted it and imposed a new independent-2025/26
qualification gate that the user NEVER requested.

In this experiment, unlike only adjusting thresholds, NEW cash-forecast
models are independently refit each target month from the preceding 3,
6, 12, 24, 36, 60 or 96 months (or at a 12-month information embargo).
They learn money-return and hit interactions for market, displayed odds,
venue, surface, distance and seasonal features of *previously selected*
tickets. These predictors forecast whether each old baseline ticket and
race is worth buying, and choose 3, 4 or 5 races per active venue-day
and prospective stake splits across the two different market tickets.

Acceptance gate is EXACTLY what was requested:
  - Actual historical yen ROI >=200% over 2017..2026-08-09
  - Largest SINGLE RACE payout removed, original full stake retained,
    ROI still >=200%.
  - Hit bought-race rate >=20%.
  - At least 3 bought races per active venue day.
There is NO extra qualification gate on independent 2025 or 2026,
and in-sample benchmark MUST be present (ROI ~426.45% on 2017 onward).
Annual cash reports and comparison to baseline are still generated for
transparency, but annual subperiods do NOT newly invalidate a model.

IMPORTANT RESEARCH LIMITS: archived baseline bets were selected by a
frozen runner model trained on the full 2016-2026 archive and quotes in
original historical ticket records are retrospective FINAL odds, not
verified pre-T-15 market prices. This research can establish historical
settled-cash ROI for NEW online cash models built ON TOP of the baseline,
but it cannot establish prospective out-of-sample tradability or a newly
independent six-market horse-prediction engine. NEVER auto-promote to main,
change D1 or replace live picks.
"""
from __future__ import annotations
import argparse
import base64
import collections
import dataclasses
import datetime as dt
import gzip
import itertools
import json
import math
import time
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261115-baseline-inclusive-online-money-model-v16.json"
YEARS=tuple(range(2017,2027))
TARGET_START="2017-01-01"
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
VENUES=("東京","中山","京都","阪神","中京","新潟","福島","小倉","札幌","函館")
HORIZONS=(3,6,12,24,36,60,96)
LAGS=(0,12)
OBJECTIVES=("cash20","cash80","hit_cash")
STAKE_MODES=("equal","favour_predicted_70","favour_predicted_90","favor_first","favor_second")
SLATES=(3,4,5)
PRIORITIES=("expected_cash","hit_stable","cash_minus_volatility")
FIELDS=("paid","stake","hit","races","days","max_paid")
MONTH_KEYS=tuple(f"{y:04d}-{m:02d}" for y in range(2016,2027) for m in range(1,13)
                 if "2016-08"<=f"{y:04d}-{m:02d}"<="2026-08")
MIN_EXPECTED_ENTRIES=14410
STAKE_PER_RACE=2000
N_VENUES=len(VENUES)
MAX_MODELS_IN_REPORT=40


def months_ordinal(m):
    year,month=map(int,m.split("-"))
    return 12*year+month


def archived_races():
    folder=ROOT/"src/v1/ten-year-history-data"
    paths=sorted(folder.glob("bin-*.ts"))
    if len(paths)!=9:
        raise RuntimeError(f"BASELINE_RESEARCH_CONTROL_ARCHIVE_MISSING:{len(paths)}")
    packed=""
    for p in paths:
        raw=p.read_text(encoding="utf8").strip()
        if not raw.startswith("export default "):
            raise RuntimeError("NONCANONICAL_FROZEN_HISTORY_CHUNK")
        packed+=json.loads(raw.removeprefix("export default ").removesuffix(";"))
    archive=json.loads(gzip.decompress(base64.b64decode(packed)))
    if len(archive["races"])!=34566:
        raise RuntimeError("FROZEN_FULL_RACE_COUNT_MISMATCH")
    out=[]
    by_day=collections.defaultdict(list)
    years=collections.Counter()
    for record in archive["races"]:
        rid,date,venue,race_no,title,start,surface,distance,tickets=record
        if not tickets:continue
        if len(tickets)!=2 or len({t[0] for t in tickets})!=2:
            raise RuntimeError(f"INVALID_ORIGINAL_TWO_MARKET_TICKETS:{rid}")
        if any(str(t[0]) not in MARKETS for t in tickets):
            raise RuntimeError("UNKNOWN_MARKET_IN_ORIGINAL_BASELINE")
        bets=[]
        for bet in tickets:
            odds=float(bet[2])
            paid=int(bet[3])
            if not math.isfinite(odds) or odds<=0 or paid<0:
                raise RuntimeError(f"INVALID_SETTLED_TICKET:{rid}")
            bets.append((str(bet[0]),str(bet[1]),odds,paid))
        row={
            "id":str(rid),"date":str(date),"month":str(date)[:7],
            "venue":str(venue),"race_no":int(race_no),
            "surface":str(surface),"distance":int(distance or 0),
            "ticket":tuple(bets),
        }
        if row["venue"] not in VENUES:
            raise RuntimeError(f"UNKNOWN_VENUE:{row['venue']}")
        out.append(row)
        by_day[(row["date"],row["venue"])].append(row)
        years[row["date"][:4]]+=1
    if len(out)!=MIN_EXPECTED_ENTRIES:
        raise RuntimeError(f"EXPECTED_EXACTLY_14410_BASELINE_SELECTED_RACES:{len(out)}")
    if len(by_day)!=2882 or any(len(x)!=5 for x in by_day.values()):
        raise RuntimeError("ORIGINAL_FIVE_RACES_PER_VENUE_DAY_MISSING")
    if sum(years.values())!=14410:
        raise RuntimeError("BASELINE_COVERAGE_COUNT_MISMATCH")
    return out,by_day


def bucket(odd):
    bounds=(2,3,5,8,12,20,35,60,100,200,400)
    return next((i for i,v in enumerate(bounds) if odd<v),len(bounds))


def ticket_features(row,j):
    typ,combo,odds,paid=row["ticket"][j]
    v=row["venue"];s=row["surface"];n=row["race_no"]
    ob=bucket(odds)
    return (
        ("type",typ),
        ("typeOdds",typ,ob),
        ("typeVenue",typ,v),
        ("typeRace",typ,0 if n<=4 else 1 if n<=8 else 2),
        ("typeSurface",typ,s),
        ("typeSeason",typ,(int(row["month"][5:7])-1)//3),
        ("typeDistance",typ,min(6,row["distance"]//400)),
        ("typeOddsVenue",typ,ob,v),
        ("odds",ob),
    )


@dataclasses.dataclass(frozen=True)
class Forecast:
    horizon:int
    lag:int
    objective:str

    def export(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class Policy:
    horizon:int
    lag:int
    objective:str
    stakeMode:str
    racesPerVenueDay:int
    racePriority:str

    def export(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class Meta:
    lookback:int
    scope:str
    objective:str
    priorRaces:int

    def export(self):
        return dataclasses.asdict(self)


def all_policies():
    return [Policy(*args) for args in itertools.product(
        HORIZONS,LAGS,OBJECTIVES,STAKE_MODES,SLATES,PRIORITIES)]


def all_meta():
    return [Meta(*args) for args in itertools.product(
        (3,6,12,24),("venue","global"),("cash","trimmed"),(30,300))]


def fit_money_model(month,horizon,lag,objective,by_month,feat):
    cutoff=months_ordinal(month)-lag
    start=cutoff-horizon
    stats=collections.defaultdict(lambda:[0,0.0,0])
    global_sum=0.
    global_count=0
    global_hits=0
    bound=20 if objective=="cash20" else 80 if objective=="cash80" else 40
    for hist_month in by_month:
        idx=months_ordinal(hist_month)
        if not(start<=idx<cutoff):
            continue
        if not idx<months_ordinal(month):
            raise RuntimeError("FUTURE_OUTCOME_LEAKAGE")
        for row in by_month[hist_month]:
            for j in (0,1):
                paid=int(row["ticket"][j][3])
                normalized=min(float(paid)/1000.0,bound)
                didwin=int(paid>0)
                global_sum+=normalized
                global_count+=1
                global_hits+=didwin
                for key in feat[(row["id"],j)]:
                    a=stats[key]
                    a[0]+=1;a[1]+=normalized;a[2]+=didwin
    global_prior=max(.25,global_sum/max(1,global_count))
    hit_prior=max(.05,global_hits/max(1,global_count))
    return stats,global_prior,hit_prior,global_count


def score_ticket(keys,fit,objective):
    stats,prior,hitprior,total=fit
    # Generalize cash yield from market, historical final odds and venue.
    weights=(.25,.22,.16,.07,.08,.05,.07,.05,.05)
    shrink=(10,20,30,30,35,55,45,65,30)
    cash=hit=0.
    for key,w,k in zip(keys,weights,shrink):
        count,paid,hits=stats.get(key,(0,0.,0))
        estimate=(paid+k*prior)/(count+k)
        likely=(hits+k*hitprior)/(count+k)
        cash+=w*estimate
        hit+=w*likely
    if objective=="hit_cash":
        cash=.66*cash+.34*(hit*min(25.,prior/max(.1,hitprior)))
    return max(.01,cash),min(.99,max(.01,hit))


def stake_split(mode,first,second):
    if mode=="equal":
        return 1000,1000
    if mode=="favor_first":
        return 1500,500
    if mode=="favor_second":
        return 500,1500
    if mode in ("favour_predicted_70","favour_predicted_90"):
        hi,lo=(1400,600) if mode.endswith("70") else (1800,200)
        return (hi,lo) if first>=second else (lo,hi)
    raise RuntimeError(f"UNKNOWN_STAKE_SCHEME:{mode}")


def model_prediction_for_race(row,score0,score1,mode,priority):
    v0,h0=score0
    v1,h1=score1
    stake0,stake1=stake_split(mode,v0,v1)
    gross=(v0*stake0+v1*stake1)/1000.
    hit_prob=1-(1-h0)*(1-h1)
    if priority=="expected_cash":
        rank=gross
    elif priority=="hit_stable":
        rank=2.3*hit_prob+.25*gross
    elif priority=="cash_minus_volatility":
        rank=.75*gross+1.0*hit_prob
    else:
        raise RuntimeError("UNRECOGNIZED_CASH_PREDICTOR")
    realized=(row["ticket"][0][3]*stake0+
              row["ticket"][1][3]*stake1)//1000
    return rank,int(realized),stake0+stake1


def summarized_values(paid,stake,hit,nr,days,largest):
    if not stake:
        return None
    qualified=bool(paid>=2*stake+largest and hit*5>=nr and
                   nr>=3*days and days>0)
    return {
        "stakeYen":int(stake),
        "receivedYen":int(paid),
        "profitYen":int(paid-stake),
        "roiPct":round(100*paid/stake,6),
        "afterLargestPaidRaceRoiPct":round(100*(paid-largest)/stake,6),
        "hitPct":round(100*hit/nr,6),
        "hitRaces":int(hit),
        "boughtRaces":int(nr),
        "venueDays":int(days),
        "maxPaidSingleRaceYen":int(largest),
        "qualified":qualified,
    }


def report_from_ledger(ledger,month_indices,year=None):
    if year is None:
        sel=[t for t,m in enumerate(month_indices) if "2017-01"<=m<="2026-08"]
    else:
        sel=[t for t,m in enumerate(month_indices) if m[:4]==str(year)]
    if not sel:
        return None
    sub=ledger[sel]
    paid=int(np.sum(sub[:,:,0],dtype=np.int64))
    stake=int(np.sum(sub[:,:,1],dtype=np.int64))
    hits=int(np.sum(sub[:,:,2],dtype=np.int64))
    races=int(np.sum(sub[:,:,3],dtype=np.int64))
    days=int(np.sum(sub[:,:,4],dtype=np.int64))
    largest=int(np.max(sub[:,:,5]))
    return summarized_values(paid,stake,hits,races,days,largest)


def baseline_row(row):
    paid=sum(x[3] for x in row["ticket"])
    return int(paid),STAKE_PER_RACE,int(paid>0)


def baseline_ledger(by_day,months):
    data=np.zeros((len(months),N_VENUES,6),dtype=np.int64)
    mid={m:i for i,m in enumerate(months)}
    vid={v:i for i,v in enumerate(VENUES)}
    for (date,venue),rows in by_day.items():
        m=date[:7]
        if m not in mid:
            continue
        paid=sum(baseline_row(row)[0] for row in rows)
        hits=sum(baseline_row(row)[2] for row in rows)
        dayslot=data[mid[m],vid[venue]]
        dayslot[0]+=paid
        dayslot[1]+=len(rows)*STAKE_PER_RACE
        dayslot[2]+=hits
        dayslot[3]+=len(rows)
        dayslot[4]+=1
        dayslot[5]=max(int(dayslot[5]),max(baseline_row(row)[0] for row in rows))
    return data


def month_causal_learning(by_month,by_day,months,policies,model_target_months):
    idx={m:i for i,m in enumerate(months)}
    venue_idx={v:i for i,v in enumerate(VENUES)}
    ledger=np.zeros((len(policies),len(months),N_VENUES,6),dtype=np.int64)
    feat={(row["id"],j):ticket_features(row,j)
          for group in by_month.values() for row in group for j in (0,1)}
    day_month=collections.defaultdict(list)
    for (date,venue),rows in sorted(by_day.items()):
        day_month[date[:7]].append((date,venue,rows))
    starts={}
    for i,method in enumerate(policies):
        key=(method.horizon,method.lag,method.objective)
        starts.setdefault(key,[]).append((i,method))
    for count,month in enumerate(model_target_months):
        start=time.monotonic()
        if month not in idx:
            raise RuntimeError(f"MISSING_MONTH:{month}")
        t=idx[month]
        for modelkey,variants in starts.items():
            horizon,lag,objective=modelkey
            fitted=fit_money_model(month,horizon,lag,objective,by_month,feat)
            signals={}
            for row in by_month[month]:
                a=score_ticket(feat[(row["id"],0)],fitted,objective)
                b=score_ticket(feat[(row["id"],1)],fitted,objective)
                signals[row["id"]]=(a,b)
            for date,venue,rows in day_month[month]:
                v=venue_idx[venue]
                # The model and EVERY method has seen only earlier months.
                predicted={}
                for mode in STAKE_MODES:
                    for priority in PRIORITIES:
                        scored=[]
                        for row in rows:
                            a,b=signals[row["id"]]
                            rank,ret,stake=model_prediction_for_race(row,a,b,mode,priority)
                            scored.append((rank,row["race_no"],row["id"],ret,stake))
                        scored.sort(key=lambda x:(-x[0],x[1],x[2]))
                        predicted[(mode,priority)]=scored
                for k,policy in variants:
                    scored=predicted[(policy.stakeMode,policy.racePriority)]
                    selected=scored[:policy.racesPerVenueDay]
                    if len(selected)<3:
                        raise RuntimeError("THREE_BOUGHT_RACES_VIOLATED")
                    val=ledger[k,t,v]
                    val[0]+=sum(x[3] for x in selected)
                    val[1]+=sum(x[4] for x in selected)
                    val[2]+=sum(x[3]>0 for x in selected)
                    val[3]+=len(selected)
                    val[4]+=1
                    val[5]=max(int(val[5]),max(x[3] for x in selected))
        if (count+1)%12==0 or count==0 or count==len(model_target_months)-1:
            print("BASELINE_INCLUDED_NEW_PREDICTION_MODELS_LEARNED",
                  json.dumps({"throughMonth":month,
                    "targetMonthsCompleted":count+1,
                    "targetMonthsTotal":len(model_target_months),
                    "distinctNewMoneyMethods":len(policies),
                    "trainingPeriodsPerMonth":len(starts),
                    "targetMonthResultsWereInputs":False,
                    "secondsThisMonth":round(time.monotonic()-start,2)}),
                  flush=True)
    return ledger


def build_online_picks(new_ledger,baselines,months,meta):
    n=len(months)
    mcount=new_ledger.shape[0]
    allchoices=np.concatenate([baselines[None,:,:,:],new_ledger],axis=0)
    cash=allchoices[:,:,:,0]
    stake=allchoices[:,:,:,1]
    hit=allchoices[:,:,:,2]
    bought=allchoices[:,:,:,3]
    prefix={}
    for name,arr in (("cash",cash),("stake",stake),("hit",hit),("bought",bought)):
        prefix[name]=np.pad(np.cumsum(arr,axis=1,dtype=np.int64),
             ((0,0),(1,0),(0,0)))
    chosen=np.zeros((n,N_VENUES),dtype=np.int32)
    for t,month in enumerate(months):
        if month<"2017-01":
            continue
        start=max(0,t-meta.lookback)
        for v in range(N_VENUES):
            if meta.scope=="venue":
                pc=prefix["cash"][:,t,v]-prefix["cash"][:,start,v]
                st=prefix["stake"][:,t,v]-prefix["stake"][:,start,v]
                hits=prefix["hit"][:,t,v]-prefix["hit"][:,start,v]
                nobs=prefix["bought"][:,t,v]-prefix["bought"][:,start,v]
                biggest=allchoices[:,start:t,v,5].max(axis=1) if start<t else np.zeros(mcount+1)
            else:
                pc=(prefix["cash"][:,t]-prefix["cash"][:,start]).sum(axis=1)
                st=(prefix["stake"][:,t]-prefix["stake"][:,start]).sum(axis=1)
                hits=(prefix["hit"][:,t]-prefix["hit"][:,start]).sum(axis=1)
                nobs=(prefix["bought"][:,t]-prefix["bought"][:,start]).sum(axis=1)
                biggest=allchoices[:,start:t,:,5].max(axis=(1,2)) if start<t else np.zeros(mcount+1)
            metric=pc if meta.objective=="cash" else pc-biggest
            ratio=100*metric/np.maximum(st,1)
            shrink=100+(ratio-100)*nobs/(nobs+meta.priorRaces)
            shrink=np.where(nobs>=15,shrink,-1e9)
            selected=int(np.argmax(shrink))
            chosen[t,v]=selected
    # One model family is selected for each venue MONTH, without using
    # any payout from the chosen target month to select that model.
    answer=np.zeros((n,N_VENUES,6),dtype=np.int64)
    for t in range(n):
        for v in range(N_VENUES):
            answer[t,v]=allchoices[chosen[t,v],t,v]
    return answer


def dynamic_outcome(ledger,months):
    stat=report_from_ledger(ledger,months)
    if stat is None:
        return None
    return {
        "total":stat,
        "annual":{str(yr):report_from_ledger(ledger,months,yr)
                  for yr in YEARS},
    }


def verify_baseline(baselines,months):
    full=np.sum(baselines,axis=(0,1),dtype=np.int64)
    if int(full[0])!=124401700 or int(full[1])!=28820000:
        raise RuntimeError("ORIGINAL_431_PERCENT_CONTROL_NOT_REPRODUCED")
    years=dynamic_outcome(baselines,months)
    c=years["total"]
    if c["boughtRaces"]!=13860 or not(426.45<c["roiPct"]<426.46):
        raise RuntimeError(f"KNOWN_2017_TO_2026_CONTROL_NOT_INCLUDED:{c}")
    if not c["qualified"] or c["afterLargestPaidRaceRoiPct"]<200:
        raise RuntimeError("KNOWN_ADMITTED_MODEL_LOST")
    return years


def report(ledger,baselines,months,policies,meta_list):
    benchmark=verify_baseline(baselines,months)
    baseline_roi=benchmark["total"]["roiPct"]
    accepted=[]
    all_accepted=1 # original positive control always included
    new_qualified=0
    best_cash=None
    best_roi=None
    for k,policy in enumerate(policies):
        # Buying all original five races for 1,000 + 1,000 is the
        # IDENTICAL original model, even if a newly fitted predictor
        # assigns different scores. Never misreport such clones as new.
        if policy.racesPerVenueDay==5 and policy.stakeMode=="equal":
            continue
        score=report_from_ledger(ledger[k],months)
        if score is None or not score["qualified"]:
            continue
        all_accepted+=1
        new_qualified+=1
        candidate=("new_causal_cash_forecaster",policy.export(),score,ledger[k])
        if best_cash is None or score["profitYen"]>best_cash[2]["profitYen"]:
            best_cash=candidate
        if best_roi is None or score["roiPct"]>best_roi[2]["roiPct"]:
            best_roi=candidate
        accepted.append({"family":"new_causal_cash_forecaster",
                         "method":policy.export(),"money":score})
    meta_qualified=0
    for m in meta_list:
        dynamic=build_online_picks(ledger,baselines,months,m)
        # If an adaptive program simply picks the existing baseline
        # on every month/venue, it is NOT an independently new method.
        if np.array_equal(dynamic,baselines):
            continue
        score=report_from_ledger(dynamic,months)
        if score is None or not score["qualified"]:
            continue
        all_accepted+=1
        meta_qualified+=1
        candidate=("new_online_learned_forecast_method",m.export(),score,dynamic)
        if best_cash is None or score["profitYen"]>best_cash[2]["profitYen"]:
            best_cash=candidate
        if best_roi is None or score["roiPct"]>best_roi[2]["roiPct"]:
            best_roi=candidate
        accepted.append({"family":"new_online_learned_forecast_method",
                         "method":m.export(),"money":score})
    accepted.sort(key=lambda r:(r["money"]["profitYen"],
                             r["money"]["afterLargestPaidRaceRoiPct"]),reverse=True)
    distinct_model_count=1+len(policies)+len(meta_list)
    result={
        "status":"BASELINE_INCLUDED_ROLLING_NEW_MONEY_SEARCH_COMPLETED",
        "modelCountSearched":distinct_model_count,
        "baselineExistingModelIncluded":True,
        "baselineQualifiedCount":1,
        "newCausalCashModelsSearched":len(policies),
        "newOnlineLearnedMethodologiesSearched":len(meta_list),
        "totalHistoricalQualified":all_accepted,
        "newCausalCashModelsQualified":new_qualified,
        "newOnlineLearnedMethodologiesQualified":meta_qualified,
        "baseline":benchmark,
        "bestNewByProfit":({
            "family":best_cash[0],"method":best_cash[1],
            "money":dynamic_outcome(best_cash[3],months),
            "profitImprovementOverBaselineYen":
                best_cash[2]["profitYen"]-benchmark["total"]["profitYen"]
        } if best_cash else None),
        "bestNewByRoi":({
            "family":best_roi[0],"method":best_roi[1],
            "money":dynamic_outcome(best_roi[3],months),
            "roiPointImprovementOverBaseline":
                round(best_roi[2]["roiPct"]-baseline_roi,6)
        } if best_roi else None),
        "allQualifiedNewMethods":accepted[:MAX_MODELS_IN_REPORT],
        "additionalQualifiedNewMethodsNotInTopList":max(0,len(accepted)-MAX_MODELS_IN_REPORT),
        "qualificationBasis":{
            "period":"2017-01-01..2026-08-09",
            "actualPaidYenRoiThresholdPct":200,
            "afterSingleLargestRacePaidRemovedRoiThresholdPct":200,
            "minimumPaidRaceHitPct":20,
            "minimumBoughtRacesPerActiveVenueDay":3,
            "additionalSeparateYearHoldoutGate":False,
        },
        "informationControls":{
            "directCashForecastTrainingMonths":list(HORIZONS),
            "informationEmbargoMonths":list(LAGS),
            "cashForecastRefitEachPredictionMonth":True,
            "trainAndPickCashModelWithoutTargetMonthSettlements":True,
            "newModelGeneratedDistinctUnderlyingHorsePredictions":False,
            "newModelLearnsCashReturnsAndBettingMethodForExistingFrozenTicketPairs":True,
            "originalFrozenHorseModelTrainedOnCompleteArchive":True,
            "originalArchivedTicketOddsAreRetrospectiveFinalNotOfficialT15":True,
            "multipleMethodsSelectedUsingFullHistoricalEvaluationPeriod":True,
            "independentOutOfSampleRoi200Certified":False,
            "validProductionReadyModelProven":False,
        },
        "productionModified":False,
        "productionPromotionAllowed":False,
    }
    if all_accepted<1:
        raise RuntimeError("INCONSISTENT_ZERO_RESULTS_WHILE_BASELINE_QUALIFIES")
    return result


def selftest():
    assert len(all_policies())==len(HORIZONS)*len(LAGS)*len(OBJECTIVES)*len(STAKE_MODES)*len(SLATES)*len(PRIORITIES)
    assert len(all_meta())==4*2*2*2
    assert all(months_ordinal("2026-08")>months_ordinal(x) for x in ("2025-08","2026-07"))
    assert stake_split("favour_predicted_70",2,1)==(1400,600)
    assert stake_split("favour_predicted_90",2,1)==(1800,200)
    assert summarized_values(14000,6000,2,3,1,1000)["qualified"] is True
    assert summarized_values(13000,6000,2,3,1,2000)["qualified"] is False
    assert summarized_values(14000,6000,0,3,1,1000)["qualified"] is False
    assert summarized_values(14000,6000,2,2,1,1000)["qualified"] is False
    print("BASELINE_INCLUSIVE_CASH_PREDICTION_SELFTEST_OK",flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",default=str(OUT))
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:
        selftest();return
    t0=time.monotonic()
    rows,by_day=archived_races()
    by_month=collections.defaultdict(list)
    for row in rows:
        by_month[row["month"]].append(row)
    months=sorted(by_month)
    if months[0]!="2016-08" or months[-1]!="2026-08" or len(months)!=121:
        raise RuntimeError("FULL_ARCHIVED_BASELINE_MONTHS_NOT_AVAILABLE")
    control=baseline_ledger(by_day,months)
    verify_baseline(control,months)
    models=all_policies()
    target_months=[m for m in months if m>="2017-01"]
    ledger=month_causal_learning(by_month,by_day,months,models,target_months)
    r=report(ledger,control,months,models,all_meta())
    r["durationSeconds"]=round(time.monotonic()-t0,3)
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",
                    encoding="utf8")
    print("BASELINE_INCLUDED_NEW_METHOD_SEARCH_FINAL",json.dumps({
        "status":r["status"],
        "searched":r["modelCountSearched"],
        "baselineIncluded":r["baselineQualifiedCount"],
        "newQualified":r["newCausalCashModelsQualified"]+
                            r["newOnlineLearnedMethodologiesQualified"],
        "qualifiedTotal":r["totalHistoricalQualified"],
        "baselineRoi":r["baseline"]["total"]["roiPct"],
        "bestNewByProfit":r["bestNewByProfit"]["money"]["total"] if r["bestNewByProfit"] else None,
        "bestNewByRoi":r["bestNewByRoi"]["money"]["total"] if r["bestNewByRoi"] else None,
        "seconds":r["durationSeconds"]},ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
