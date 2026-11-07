#!/usr/bin/env python3
"""ONE-DAY JRA preflight, read-only, max two indexed D1 SELECTs.

Never modifies user bets, public site, D1 history, or Workers. This verifies
only the November 8 selected race roster and worker health; NOT evidence that
future odds, bets or model profits have already been fixed/verified.
"""
import collections
import json
import os
import urllib.request
import subprocess
import datetime as dt

DATE="2026-11-08"
EXPECTED={"東京","京都","福島"}
ACCOUNT=os.environ["CLOUDFLARE_ACCOUNT_ID"]
DATABASE=os.environ["CLOUDFLARE_D1_DATABASE_ID"]
TOKEN=os.environ["CLOUDFLARE_API_TOKEN"]
ROOT=f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query"

def d1(sql, params):
    request=urllib.request.Request(
        ROOT,data=json.dumps({"sql":sql,"params":params}).encode(),method="POST",
        headers={"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json"})
    with urllib.request.urlopen(request,timeout=30) as response:
        body=json.load(response)
    if body.get("success") is not True:
        raise RuntimeError("D1_READONLY_FAILED:"+str(body.get("errors"))[:200])
    return (body.get("result") or [{}])[0].get("results") or []

def health(endpoint):
    result=subprocess.run(["curl","--fail","--silent","--show-error","--location",
        "--max-time","25","--header","Accept: application/json",endpoint],
        capture_output=True,text=True,timeout=30)
    if result.returncode!=0:
        raise RuntimeError("PRODUCTION_WORKER_HEALTH_CURL_FAILED:"+endpoint+":"+result.stderr[:180])
    data=json.loads(result.stdout)
    if data.get("status")!="up" or data.get("service")!="race-tantei-live-deadline":
        raise RuntimeError("PRODUCTION_WORKER_HEALTH_UNVERIFIED:"+endpoint)
    return {"url":endpoint,"service":data["service"],"status":data["status"],"version":data.get("version")}

def main():
    now=dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    if now.date().isoformat()==DATE and now.hour<8:
        print("RACE_DAY_PREFLIGHT_NOT_YET_DUE",json.dumps({"jstNow":now.isoformat(),
          "earliestSelectionHourJst":8,"noD1Read":True,"noFailureClaim":True}),flush=True)
        return
    evidence={"jstDate":DATE,"readonly":True,"selection":None,"productionModelPromotion":False,
              "workerHealth":[],"ready":False}
    for url in ("https://race-tantei-live-deadline.race-tantei.workers.dev/health",
                "https://race-tantei-live-deadline-backup.race-tantei.workers.dev/health"):
        evidence["workerHealth"].append(health(url))
    rows=d1("""SELECT state_value stateValue,updated_at updatedAt
       FROM rt_system_state WHERE state_key=? LIMIT 1""",["final_daily_selection:"+DATE])
    if not rows:
        evidence["selection"]={"status":"MISSING","reason":"FINAL_SELECTION_NOT_IN_D1_YET"}
        print("RACE_DAY_PREFLIGHT",json.dumps(evidence,ensure_ascii=False),flush=True)
        raise RuntimeError("NOV08_SELECTION_MISSING_NOT_READY")
    parsed=json.loads(rows[0]["stateValue"])
    chosen=parsed.get("selected") or []
    by_venue=collections.Counter(str(r.get("venue")) for r in chosen)
    bad=([r.get("raceId") for r in chosen if not str(r.get("raceId","")).startswith(DATE+"-")]
         or [r.get("raceId") for r in chosen if not str(r.get("startTimeJst") or "").strip()])
    evidence["selection"]={"updatedAt":rows[0]["updatedAt"],"sourceModel":parsed.get("sourceModel"),
        "raceCount":len(chosen),"venues":dict(by_venue),
        "selected": [{"raceId":r.get("raceId"),"venue":r.get("venue"),
                      "raceNo":r.get("raceNo"),"startTimeJst":r.get("startTimeJst")}
                     for r in chosen],
        "raceSelectionUsedTargetDayResult":parsed.get("resultDataUsedForTargetDay"),
        "historicalFinalOddsUsed":parsed.get("historicalFinalOddsUsedForSelection")}
    # Fail closed on duplicate race IDs, duplicated race numbers, invalid
    # start times and races that are not from the expected three venues.
    # These invariants do not require a second D1 query or any live writes.
    ids=[str(r.get("raceId") or "") for r in chosen]
    unique_ids=len(ids)==len(set(ids))
    unique_numbers=all(len({str(r.get("raceNo")) for r in chosen
        if r.get("venue")==venue})==by_venue[venue] for venue in EXPECTED)
    valid_times=True
    for race in chosen:
        try:
            t=dt.datetime.strptime(str(race.get("startTimeJst")),"%H:%M").time()
            if not (dt.time(9,0)<=t<=dt.time(17,0)):
                valid_times=False
        except (ValueError,TypeError):
            valid_times=False
    evidence["selection"]["uniqueRaceIds"]=unique_ids
    evidence["selection"]["uniqueRaceNumbersPerVenue"]=unique_numbers
    evidence["selection"]["validRaceStartTimesJst"]=valid_times
    valid=(unique_ids and unique_numbers and valid_times and len(chosen)==15 and set(by_venue)==EXPECTED
        and all(by_venue[v]==5 for v in EXPECTED)
        and not bad
        and parsed.get("sourceModel")=="ten-year-completed-model"
        and parsed.get("resultDataUsedForTargetDay") is False
        and parsed.get("historicalFinalOddsUsedForSelection") is False)
    evidence["ready"]=valid
    evidence["preT15OfficialOddsAndTicketsStillUnverified"]=True
    evidence["actualROIAndHitStillUnverified"]=True
    print("RACE_DAY_PREFLIGHT",json.dumps(evidence,ensure_ascii=False),flush=True)
    if not valid:raise RuntimeError("NOV08_SELECTION_INVALID_OR_INCOMPLETE")

if __name__=="__main__":main()
