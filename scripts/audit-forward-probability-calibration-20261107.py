#!/usr/bin/env python3
"""Read-only, forward holdout calibration audit of production's locked tickets.

Only actual T-15 frozen selected tickets. Does not reinterpret payout from
unchosen combinations as known. Evaluates predictive accuracy, not profitability
of a hypothetical different portfolio. No D1 mutation or model deployment.
"""
import collections
import datetime as dt
import json
import math
import os
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9))
START = "2026-08-10"
END = "2026-11-08"
TRAIN_END = "2026-10-01"  # The October/November holdout does not fit parameters.
ODDS_BUCKETS = (3, 10, 30, 100)
EPS = 1e-8

def query(sql, params):
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    db = os.environ["CLOUDFLARE_D1_DATABASE_ID"]
    token = os.environ["CLOUDFLARE_API_TOKEN"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{db}/query"
    req = urllib.request.Request(url, data=json.dumps({"sql":sql,"params":params}).encode(),
        method="POST", headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=65) as r:
        obj=json.loads(r.read())
    if not obj.get("success"):
        raise RuntimeError("D1_QUERY_NOT_SUCCESS "+str(obj.get("errors"))[:300])
    return (obj.get("result") or [{}])[0].get("results") or []

def trim_prob(p):
    return max(EPS, min(1-EPS, p))

def metrics(rows, alpha):
    if not rows:
        return {"count":0}
    logloss = 0
    brier = 0
    expected_hits = 0
    expected_payout = 0
    actual_hits = 0
    stake = 0
    returned = 0
    for x in rows:
        p=trim_prob(alpha*x["modelP"]+(1-alpha)*x["marketP"])
        y=x["hit"]
        logloss -= y*math.log(p)+(1-y)*math.log(1-p)
        brier += (p-y)**2
        expected_hits += p
        expected_payout += p*x["odds"]*x["stake"]
        actual_hits += y
        stake += x["stake"]
        returned += x["returned"]
    n=len(rows)
    return {"count":n,"logLoss":round(logloss/n,5),"brier":round(brier/n,5),
            "expectedHits":round(expected_hits,2),"actualHits":actual_hits,
            "modelExpectedROI":round(expected_payout/stake*100,2),
            "actualROI":round(returned/stake*100,2),
            "stakeYen":stake,"returnYen":returned}

def evaluate(rows):
    alpha_grid=[0,0.05,0.1,0.2,0.3,0.4,0.5,0.6,0.75,1.0]
    train=[x for x in rows if x["date"]<TRAIN_END]
    hold=[x for x in rows if x["date"]>=TRAIN_END]
    if len(train)<50 or len(hold)<50:
        raise RuntimeError("NOT_ENOUGH_DISJOINT_HISTORY:"+str((len(train),len(hold))))
    by_type={}
    for typ in sorted({x["type"] for x in rows}):
        local_train=[x for x in train if x["type"]==typ]
        local_hold=[x for x in hold if x["type"]==typ]
        chosen=min(alpha_grid,key=lambda a:metrics(local_train,a).get("logLoss",math.inf)) if len(local_train)>=20 else None
        if chosen is not None:
            by_type[typ]={"trainCount":len(local_train),"holdCount":len(local_hold),"chosenAlphaOnTrain":chosen,
              "holdUnadjusted":metrics(local_hold,1),"holdMarketOnly":metrics(local_hold,0),
              "holdCalibrated":metrics(local_hold,chosen)}
        else:
            by_type[typ]={"trainCount":len(local_train),"holdCount":len(local_hold),"reason":"not enough training tickets"}
    best=min(alpha_grid,key=lambda a:metrics(train,a)["logLoss"])
    return {"basis":"T15 locked settled tickets only, selected tickets only, no counterfactual ROI",
            "trainBefore":TRAIN_END,"trainCount":len(train),"holdCount":len(hold),
            "bestGlobalAlphaOnTrain":best,
            "trainCurve":[{"alpha":a,"metrics":metrics(train,a)} for a in alpha_grid],
            "heldoutUnadjusted":metrics(hold,1),
            "heldoutMarketOnly":metrics(hold,0),
            "heldoutTrainCalibrated":metrics(hold,best),
            "holdByBetType":by_type,
            "holdOddsBuckets":{name:{"count":len(xs),"actualROI":metrics(xs,1).get("actualROI"),
                     "actualHits":metrics(xs,1).get("actualHits"),
                     "modelExpectedHits":metrics(xs,1).get("expectedHits")}
                     for name,xs in [
                      ("1-3",[x for x in hold if x["odds"]<3]),
                      ("3-10",[x for x in hold if 3<=x["odds"]<10]),
                      ("10-30",[x for x in hold if 10<=x["odds"]<30]),
                      ("30-100",[x for x in hold if 30<=x["odds"]<100]),
                      ("100+",[x for x in hold if 100<=x["odds"]])]},
            "caveat":"Market implied probability 1/quoted odds is not takeout-free; direct holdout checks prediction calibration only."}

def main():
    states=query("""
      SELECT state_key AS k,state_value AS v
      FROM rt_system_state
      WHERE state_key>=? AND state_key<?
      ORDER BY state_key LIMIT 200
    """,["final_daily_selection:"+START,"final_daily_selection:"+END])
    frozen=query("""
      SELECT state_key AS k,state_value AS v
      FROM rt_system_state
      WHERE state_key>=? AND state_key<?
      ORDER BY state_key LIMIT 600
    """,["worker_live_final:"+START,"worker_live_final:"+END])
    bets=query("""
      SELECT b.race_id AS rid,b.bet_type AS typ,b.combination AS combo,
             b.stake_yen AS stake,b.return_yen AS returned,b.assumed_odds AS assumed,
             b.settlement_status AS settlement,b.locked_at AS locked,
             r.refund_horse_nos_json AS refunds
      FROM rt_public_bets b
      JOIN rt_races r ON r.race_id=b.race_id
      WHERE b.race_id>=? AND b.race_id<? AND b.course='ライト'
        AND b.source_prediction_id=-2
      ORDER BY b.race_id,b.id LIMIT 1500
    """,[START+"-",END+"-"])
    selections={}
    for state in states:
        day=state["k"].split(":")[-1]
        for race in json.loads(state["v"]).get("selected") or []:
            selections[race["raceId"]]=(day,race)
    finals={s["k"].removeprefix("worker_live_final:"):json.loads(s["v"]) for s in frozen}
    rows=[]
    excluded=collections.Counter()
    bet_map=collections.defaultdict(list)
    for b in bets:
        bet_map[b["rid"]].append(b)
    for rid,bs in bet_map.items():
        if rid not in selections:
            excluded["not_selected"]+=len(bs);continue
        date,race=selections[rid]
        if len(bs)!=2 or any(b["settlement"]!="settled" for b in bs):
            excluded["not_two_settled"]+=len(bs);continue
        try:
            cutoff=dt.datetime.fromisoformat(date+"T"+race["startTimeJst"][:5]+":00+09:00")-dt.timedelta(minutes=15)
            if any(dt.datetime.fromisoformat(b["locked"].replace("Z","+00:00"))>cutoff for b in bs):
                excluded["late"]+=len(bs);continue
        except (KeyError,TypeError,ValueError):
            excluded["time_invalid"]+=len(bs);continue
        if rid not in finals:
            excluded["no_final_snapshot"]+=len(bs);continue
        archive=finals[rid]
        prediction_map={(x["betType"],str(x["combination"])):x for x in archive.get("tickets",[])}
        for b in bs:
            if b["refunds"] and json.loads(b["refunds"]):
                # Do not count refunded tickets as an ordinary loss or successful hit.
                horses=[int(x) for x in b["combo"].split("-")]
                refunds={int(x) for x in json.loads(b["refunds"])}
                if refunds.intersection(horses):
                    excluded["refunded"]+=1;continue
            t=prediction_map.get((b["typ"],str(b["combo"])))
            if t is None:
                excluded["no_matching_prediction"]+=1;continue
            try:
                p=float(t["predictedProbability"]);odds=float(t["officialOdds"])
                stake=int(b["stake"]);returned=int(b["returned"])
            except (TypeError,ValueError,KeyError):
                excluded["invalid_prob_or_return"]+=1;continue
            if not (0<p<1 and odds>=1 and stake>0 and returned>=0):
                excluded["nonsensical_values"]+=1;continue
            rows.append({"date":date,"rid":rid,"type":b["typ"],"modelP":p,
                 "marketP":min(0.999,1/odds),"odds":odds,"stake":stake,"returned":returned,"hit":int(returned>0)})
    result=evaluate(rows)
    result["exclusions"]=dict(excluded)
    result["rowsWithProbability"]=len(rows)
    print("FULL_PERIOD_FORWARD_CALIBRATION_DIAGNOSTIC",json.dumps(result,ensure_ascii=False,separators=(",",":")))

if __name__=="__main__":
    main()
