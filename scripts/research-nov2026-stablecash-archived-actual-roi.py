#!/usr/bin/env python3
"""TRAIN NEW cash-return ML against REAL 2016-Aug2026 JRA settled tickets NOW.

No D1/network: 9 immutable gzip/base64 ten-year archive chunks stored in repo.
The tickets contain ACTUAL cash returned for a Light course ¥1000 wager, and
archived FINAL JRA market odds, both certified by the source archive schema.

Critical limitations:
* These 2 original tickets per race were selected by an earlier model fitted
  to the WHOLE archive, hence they are NOT a previously untouched holdout.
* Final market odds are NOT proven to be purchasable at T−15. This is only an
  actual-paid-ticket historical experiment, not real-money ROI evidence.
* Only existing archived combinations were observable; do not claim that new
  model searched every historical six-market combination.

New StableCash learns realized *money*, not horse winner probabilities:
train through 2024; choose return model and ticket/stake/race policy only using
2025 realized JRA payouts; refit through 2025 and settle 2026 with frozen
portfolio rules, original stake denominator and maximum ticket/race removal.
"""
from __future__ import annotations
from collections import defaultdict,Counter
import argparse
import base64
import datetime as dt
import gzip
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
CHUNKS=ROOT/"src/v1/ten-year-history-data"
REPORT=ROOT/"analysis-results/nov2026-stablecash-new-model-real-archive-return.json"
VENUES=("札幌","函館","福島","新潟","東京","中山","中京","京都","阪神","小倉")
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
MODELS=("raw_cash","capped_cash","era_min_cash","stable_cash","stable_aggressive_cash")
STAKING=("top_only","half_half","eighty_twenty","ninety_ten")
K_RACES=(0,1,2,3,4,5)  # 0: every pre-selected race above threshold
MIN_ROI_SAMPLE=100
SEED=20261108

def cash_code():
    path=ROOT/"scripts/research-nov2026-stablecash-direct-payoff.py"
    spec=importlib.util.spec_from_file_location("direct_stablecash_v1",path)
    assert spec and spec.loader
    m=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=m
    spec.loader.exec_module(m)
    return m

def read_exact_paid_archive():
    paths=sorted(CHUNKS.glob("bin-*.ts"))
    if len(paths)!=9:raise RuntimeError("GITHUB_JRA_ARCHIVE_INCOMPLETE")
    stream=""
    for file in paths:
        s=file.read_text(encoding="utf-8").strip()
        if not s.startswith("export default ") or not s.endswith(";"):
            raise RuntimeError("JRA_ARCHIVE_CHUNK_FORMAT_CHANGED")
        stream+=json.loads(s[len("export default "):-1])
    p=json.loads(gzip.decompress(base64.b64decode(stream)))
    if p["start"]!="2016-08-10" or p["end"]!="2026-08-09" or len(p["races"])!=34566:
        raise RuntimeError("JRA_HISTORICAL_ARCHIVE_DATA_CHANGED")
    return p["races"]

def money_features(race,ticket):
    bet_type,combo,quoted_odds,_paid=ticket
    bet_type=str(bet_type)
    if bet_type not in MARKETS:raise ValueError("UNKNOWN_REAL_JRA_TICKET_MARKET")
    price=float(quoted_odds)
    if not 1<=price<=999999 or not math.isfinite(price):
        raise ValueError("INVALID_ARCHIVED_JRA_FINAL_QUOTE")
    date=dt.date.fromisoformat(str(race[1]))
    no=int(race[3]);venue=str(race[2])
    typ=[float(bet_type==m) for m in MARKETS]
    venue_oh=[float(venue==v) for v in VENUES]
    surface=str(race[6] or "")
    surf_oh=[float(surface in values) for values in (
      ("芝","turf","Turf"),("ダート","dirt","Dirt"),("障害","obstacle"))]
    odd=[
      math.log(price),math.sqrt(price)/100.,1/price,
      math.log1p(price)/10.,price/(price+100.),math.log1p(price)/math.log(1000000)
    ]
    dist=int(race[7] or 0)
    context=[
      no/12.,dist/4000.,
      math.sin(2*math.pi*date.month/12),math.cos(2*math.pi*date.month/12)
    ]
    horses=[int(z) for z in str(combo).split("-")]
    if not 1<=len(horses)<=3 or len(set(horses))!=len(horses):
        raise ValueError("INVALID_OFFICIAL_TICKET_COMBINATION")
    combos=[
      len(horses)/3,min(horses)/18,max(horses)/18,sum(horses)/54,
      (max(horses)-min(horses))/18,horses[0]/18,horses[-1]/18
    ]
    calendar=[
      (date.year-2016)/12.,date.month/12.,float(date.weekday()>=5),date.day/31.
    ]
    row=typ+venue_oh+surf_oh+odd+context+combos+calendar
    if len(row)!=40 or not all(math.isfinite(x) for x in row):
        raise AssertionError("NEW_MONETARY_MODEL_40_PRESOURCE_FEATURES_INVALID")
    return row

def ticket_dataset(raw):
    """Read saved bets: real JRA returnLightYen is actual cash on ¥1000 stake."""
    X=[];y=[];meta=[];saved=[];missing=Counter()
    last_date=""
    for r in raw:
        raceid=str(r[0]);date=str(r[1]);tickets=r[8]
        if date<last_date:raise RuntimeError("JRA_ARCHIVE_NOT_CHRONOLOGICAL")
        last_date=date
        if tickets is None:continue
        if not isinstance(tickets,list) or len(tickets)!=2:
            missing["not_exact_two_saved_tickets"]+=1;continue
        rows=[]
        for bet in tickets:
            if len(bet)!=4:
                raise ValueError("JRA_ARCHIVE_TICKET_SCHEMA_CHANGED")
            try:
                feat=money_features(r,bet)
                paid=int(bet[3])
                if paid<0 or paid%10:
                    raise ValueError("ACTUAL_JRA_LIGHT_STAKE_NOT_DIVISIBLE_BY_TEN")
                rows.append((feat,bet,paid))
            except (ValueError,TypeError,OverflowError) as error:
                missing["invalid_archived_quote_or_combo"]+=1
                rows=[]
                break
        if len(rows)!=2:continue
        if rows[0][1][0]==rows[1][1][0] and rows[0][1][1]==rows[1][1][1]:
            raise RuntimeError("DUPLICATE_SAME_JRA_BET_IN_SAVED_PREDICTION")
        day=(date,str(r[2]))
        context={"raceId":raceid,"raceNo":int(r[3]),"date":date,
                 "venue":str(r[2]),"startTimeJst":r[5]}
        for feat,b,paid in rows:
            # The model fits actual per-¥100 gross cash RETURN.
            # A full ¥1000 historical Light stake pays paid yen; its
            # 100-yen JRA settlement equivalent is exactly paid/10.
            X.append(feat)
            y.append(paid/10.)
            meta.append((day,context,((str(b[0]),tuple(map(int,str(b[1]).split("-")))),
                                       (),0.,int(paid/10))))
        saved.append(context)
    if len(meta)!=len(y) or len(y)!=len(X) or len(meta)!=2*len(saved):
        raise AssertionError("JRA_PAIRED_REAL_CASH_METADATA_MISMATCH")
    arr=np.asarray(X,dtype=np.float32)
    labels=np.asarray(y,dtype=np.float64)
    if arr.shape[1]!=40 or np.any(labels<0):
        raise RuntimeError("INVALID_CASH_RETURN_ARCHIVE")
    return arr,labels,meta,saved,dict(missing)


def build_groups(X:np.ndarray,labels:np.ndarray,meta:list,model,mode:str):
    estimates=model.cash_scores(model,X) if False else None
    del estimates
    scores=model.cash_scores(model._fitted,X)[mode] if hasattr(model,"_fitted") else None
    raise RuntimeError("UNUSED_BUILD_GROUPS_SHOULD_NOT_RUN")


def money_prediction_groups(core,model,X,paid,meta,mode):
    scores=core.cash_scores(model,X)[mode]
    days=defaultdict(dict)
    for i,(day,r,t) in enumerate(meta):
        rid=str(r["raceId"])
        items=days[day].setdefault(rid,{"race":r,"bets":[]})
        items["bets"].append({
          "kind":t[0][0],"combo":"-".join(map(str,t[0][1])),
          "modelCashMultiple":float(scores[i]),
          # This is a label and must NEVER enter candidate ordering.
          "actualJraReturnPer100":int(paid[i]),
        })
    for day,races in days.items():
        for rid,part in races.items():
            if len(part["bets"])!=2:raise RuntimeError("PARTIAL_SAVED_JRA_RACE")
    return days


def settle(study,policy):
    mode,ranking_threshold,n_races,stakes=policy
    active=[]
    for venue_day,races in sorted(study.items()):
        candidates=[]
        for entry in races.values():
            bets=sorted(entry["bets"],key=lambda b:(
              -b["modelCashMultiple"],b["kind"],b["combo"]))
            top=bets[0]["modelCashMultiple"]
            if top<ranking_threshold:continue
            a,b=bets
            if stakes=="top_only":
                amounts=(1000,0)
            elif stakes=="half_half":
                amounts=(500,500)
            elif stakes=="eighty_twenty":
                amounts=(800,200)
            elif stakes=="ninety_ten":
                amounts=(900,100)
            else:raise ValueError("INVALID_REAL_STAKE_POLICY")
            expected=(amounts[0]*a["modelCashMultiple"]+
                      amounts[1]*b["modelCashMultiple"])/1000
            candidates.append((expected,entry["race"],bets,amounts))
        candidates.sort(key=lambda z:(-z[0],z[1]["raceNo"],z[1]["raceId"]))
        if n_races>0:candidates=candidates[:n_races]
        for expected,r,bets,amounts in candidates:
            outgoing=[]
            for bet,stake in zip(bets,amounts):
                if stake==0:continue
                returned=int(bet["actualJraReturnPer100"])*(stake//100)
                outgoing.append({"betType":bet["kind"],"combination":bet["combo"],
                    "stakeYen":stake,"returnYen":returned})
            active.append({
                "raceId":r["raceId"],"date":r["date"],"venue":r["venue"],
                "stake":sum(t["stakeYen"] for t in outgoing),
                "returned":sum(t["returnYen"] for t in outgoing),
                "tickets":outgoing
            })
    return active


def metrics(records):
    stake=sum(int(z["stake"]) for z in records)
    ret=sum(int(z["returned"]) for z in records)
    paid=max((int(t["returnYen"]) for z in records for t in z["tickets"]),default=0)
    largest_race=max((int(z["returned"]) for z in records),default=0)
    nr=len(records)
    wins=sum(z["returned"]>0 for z in records)
    if not nr or not stake:return {"races":nr,"pass200":False}
    if stake!=1000*nr:
        raise AssertionError("FIXED_RACE_BUDGET_INCONSISTENT_WITH_SAVED_TICKETS")
    return {
      "races":nr,"stakeYen":stake,"returnYen":ret,
      "profitYen":ret-stake,
      "roiPct":round(100*ret/stake,4),
      "roiMinusLargestPaidTicketPct":round(100*(ret-paid)/stake,4),
      "roiMinusLargestPaidRacePct":round(100*(ret-largest_race)/stake,4),
      "largestSinglePaidTicketYen":paid,
      "largestSinglePaidRaceYen":largest_race,
      "hitRacePct":round(100*wins/nr,4),
      "pass200": nr>=100 and wins/nr>=.20 and
        ret>=2*stake and ret-paid>=2*stake and ret-largest_race>=2*stake
    }


def choose_year2025_policy(core,archive25,thresholds,fit):
    results=[]
    allm=core.cash_scores(fit,archive25["X"])
    for mode in MODELS:
        if mode not in allm:continue
        groups=money_prediction_groups(core,fit,archive25["X"],
                        archive25["paid"],archive25["meta"],mode)
        for threshold in thresholds:
            for count in K_RACES:
                for stake in STAKING:
                    policy=(mode,threshold,count,stake)
                    out=metrics(settle(groups,policy))
                    if out["races"]<100:continue
                    results.append((policy,out))
    # In-the-year ROI choice is allowed on 2025 only.
    results.sort(key=lambda v:(
      int(v[1]["pass200"]),
      v[1]["roiMinusLargestPaidRacePct"],
      v[1]["roiMinusLargestPaidTicketPct"],
      v[1]["hitRacePct"]>=20,
      v[1]["races"],-v[0][2]),reverse=True)
    return results


def self_test():
    toy={"raceId":"2025-01-01-tokyo-01","date":"2025-01-01",
         "raceNo":1,"venue":"東京"}
    odds=[
       {"kind":"単勝","combo":"1","modelCashMultiple":1.4,"actualJraReturnPer100":400},
       {"kind":"馬連","combo":"1-2","modelCashMultiple":.9,"actualJraReturnPer100":0}
    ]
    g={("2025-01-01","東京"):{toy["raceId"]:{"race":toy,"bets":odds}}}
    p=("stable_cash",1.1,1,"eighty_twenty")
    result=settle(g,p)
    q=metrics(result)
    assert q["races"]==1 and q["stakeYen"]==1000
    assert q["returnYen"]==3200 and q["roiPct"]==320
    assert q["roiMinusLargestPaidTicketPct"]==0.
    assert q["roiMinusLargestPaidRacePct"]==0.
    assert not q["pass200"]
    empty=settle(g,("stable_cash",1.5,1,"eighty_twenty"))
    assert not empty
    print("NEW_REAL_JRA_ARCHIVED_CASH_ROI_ARITHMETIC_SELF_TEST_OK")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:self_test();return
    started=time.monotonic()
    core=cash_code()
    raw=read_exact_paid_archive()
    X,paid,meta,races,missing=ticket_dataset(raw)
    dates=np.asarray([m[0][0] for m in meta])
    def one_year(start,end):
        mask=(dates>=start)&(dates<end)
        return {"X":X[mask],"paid":paid[mask],
          "meta":[item for item,p in zip(meta,mask) if p]}
    train=one_year("2016-08-10","2025-01-01")
    val=one_year("2025-01-01","2026-01-01")
    test=one_year("2026-01-01","2026-08-10")
    if min(len(train["X"]),len(val["X"]),len(test["X"]))<300:
        raise RuntimeError("JRA_REAL_ARCHIVE_CHRONOLOGICAL_SPLIT_TOO_SMALL")
    historical_wager_roi=round(100*sum(paid/10)/len(paid)/100,6)
    # (paid is yen/100; all tickets were ¥1000 stake, so:
    #   gross ROI = sum(paid) / (100 * N) * 100).
    historical_wager_roi=round(float(np.sum(paid)/len(paid)),6)
    print("NEW_STABLECASH_REAL_JRA_PAID_TICKETS",json.dumps({
      "selectedOriginalRaces":len(races),"selectedOriginalTickets":len(meta),
      "trainingTickets":len(train["X"]),"2025ValidationTickets":len(val["X"]),
      "2026TestTickets":len(test["X"]),
      "earlierFullSampleRoiPctNotIndependent":historical_wager_roi,
      "archiveExclusions":missing},ensure_ascii=False),flush=True)
    if not 15000<=len(meta)<=40000:
        raise RuntimeError("INCOMPLETE_JRA_ARCHIVED_PAID_BETS")
    fitted=core.fit_stable_cash(train["X"],train["paid"],train["meta"])
    # Validate candidate model variant + all ticket/race/stake policies on 2025.
    trials=choose_year2025_policy(core,val,(0.,.8,1.,1.2,1.5,2.),fitted)
    if not trials:raise RuntimeError("NO_2025_REAL_JRA_PAYOUT_POLICY_TO_FREEZE")
    mode,threshold,race_count,stake_mode=trials[0][0]
    assert mode in MODELS
    print("NEW_STABLECASH_2025_MONEY_POLICY_FROZEN",json.dumps({
      "policy":trials[0][0],"2025Roi":trials[0][1],
      "hypothesesTested2025":len(trials)},ensure_ascii=False),flush=True)
    combined={
      "X":np.concatenate((train["X"],val["X"]),axis=0),
      "paid":np.concatenate((train["paid"],val["paid"]),axis=0),
      "meta":train["meta"]+val["meta"]
    }
    fitted26=core.fit_stable_cash(combined["X"],combined["paid"],combined["meta"])
    scores26=money_prediction_groups(core,fitted26,test["X"],test["paid"],
                  test["meta"],mode)
    target=settle(scores26,trials[0][0])
    evaluated=metrics(target)
    months=defaultdict(list)
    for r in target:months[r["date"][:7]].append(r)
    monthly={m:metrics(v) for m,v in sorted(months.items())}
    report={
      "status":"NEW_STABLECASH_LGBM_DIRECT_REAL_JRA_RETURN_TRAINED",
      "source":"immutable GitHub ten-year history saved REAL paid tickets only",
      "archiveSampleSource":"archived original completed model selected 2 bets per 5 races/venue-day",
      "complete2026UnrestrictedBetTypesAndRacesEvaluated":False,
      "archiveTicketSelectionTrainedOnEntire10YearArchive":True,
      "crucialLookaheadWarning":"base archived tickets were chosen by old model fitted to the same future race outcomes; 2026 NOT pristine",
      "actualJraSettledTicketReturns":True,
      "historicalFinalOddsWerePre15NotVerified":True,
      "withoutD1OrNetwork":True,
      "newDirectCashModel":"Tweedie per ¥100; capped Poisson; disjoint temporal era agreement",
      "baseTrainThrough":"2024-12-31",
      "only2025UsedForPolicySelection":True,
      "refitPayoutThrough":"2025-12-31",
      "2026OutcomeNeverUsedToFitCashModelOrChoosePolicy":True,
      "perHundredCashPayoutActual":True,
      "trainingRows":len(train["X"]),"validationRows":len(val["X"]),
      "evaluationRows":len(test["X"]),
      "originalFrozenArchiveFullRoiInSamplePct":historical_wager_roi,
      "policiesEvaluatedOn2025":len(trials),
      "topFiveFrozen2025Candidates":[{"policy":x[0],"results":x[1]} for x in trials[:5]],
      "2025ChosenPolicy":trials[0][0],
      "2026FreshCashTest":evaluated,
      "2026MonthlyActualJraPaidRoi":monthly,
      "allStakeIncludedAfterLargestPayoutRemoval":True,
      "maxSingleTicketAndRaceRemoved":True,
      "promotionEligible":False,
      "reason":"old model selected archived wagers using future outcomes + final odds not proven T15",
      "seconds":round(time.monotonic()-started,1)
    }
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NEW_STABLECASH_REAL_JRA_CASH_ROI_2026",json.dumps({
      "policy":trials[0][0],
      "tested2026Races":evaluated["races"],
      "investedYen":evaluated["stakeYen"],
      "paidYen":evaluated["returnYen"],
      "actualJraRoiPct":evaluated["roiPct"],
      "minusSingleLargestTicketPct":evaluated["roiMinusLargestPaidTicketPct"],
      "minusSingleLargestRacePct":evaluated["roiMinusLargestPaidRacePct"],
      "pass200":evaluated["pass200"],
      "notVerifiedForward":True
    },ensure_ascii=False),flush=True)


if __name__=="__main__":main()
