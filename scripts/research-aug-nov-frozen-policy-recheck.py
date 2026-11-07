#!/usr/bin/env python3
"""Frozen 2026 12+ runners / odds 10..30 / one-per-venue win-ticket recheck.

Only outcomes 2026-08-10..2026-11-07. Refit the ORIGINAL 56-feature
500-tree family on data strictly BEFORE 2026, as in 2026 chronological study;
replay past race results into per-day features without same-day results.
Re-fetch OFFICIAL JRA HISTORICAL FINAL win odds. Official historical FINAL
odds are never called pre-race T-15 snapshots. Actual payouts come only from
read-only stored JRA settlement rows. No site/model/Worker/D1 mutations.

Research policy FROZEN from previous 2024/25/26 exploration:
  field_size >=12, choose highest model-win-probability horse in each race,
  accept only historical FINAL win odds 10 <= odds < 30 and p*odds >= 1;
  at most one race per (date, venue), highest p*odds, lower race_no ties.
"""
from __future__ import annotations
import collections
import concurrent.futures
import datetime as dt
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.request

import numpy as np
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/research-aug-nov-frozen-12plus-official-final-odds-20261107.json"
START,END="2026-08-10","2026-11-08"
STAKE_YEN=100
BET_TYPE="単勝"
MIN_ODDS,MAX_ODDS=10.0,30.0
EV_FLOOR=1.0
MONTHS=("2026-08","2026-09","2026-10","2026-11")
JRA_WORKERS=4

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("MODULE_UNAVAILABLE:"+str(path))
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj

def d1_query(sql,params):
    url=(f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}"
         f"/d1/database/{os.environ['CLOUDFLARE_D1_DATABASE_ID']}/query")
    req=urllib.request.Request(url,method="POST",
        data=json.dumps({"sql":sql,"params":params}).encode(),
        headers={"Authorization":"Bearer "+os.environ["CLOUDFLARE_API_TOKEN"],
                 "Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=55) as response:
        data=json.loads(response.read().decode("utf-8"))
    if not data.get("success"):
        raise RuntimeError("D1_SELECT_FAILED "+str(data.get("errors"))[:400])
    return (data.get("result") or [{}])[0].get("results") or []

def paged(sql,args,limit=700):
    out=[]
    for offset in range(0,6000,limit):
        xs=d1_query(sql+" LIMIT ? OFFSET ?",[*args,limit,offset])
        out.extend(xs)
        if len(xs)<limit:return out
    raise RuntimeError("D1_PAGE_LIMIT_EXCEEDED_REFUSING_PARTIAL_DATA")

def d1_bundles():
    by_date=collections.defaultdict(list)
    counts={}
    for month in MONTHS:
        start=month+"-"
        next_m=(dt.date.fromisoformat(month+"-01")+dt.timedelta(days=35)).replace(day=1).isoformat()[:7]
        end=next_m+"-"
        races=d1_query("""SELECT race_id raceId,race_date raceDate,venue,meeting_no meetingNo,
            meeting_day meetingDay,race_no raceNo,race_name raceName,conditions,surface,
            distance_m distanceM,direction,start_time_jst startTimeJst,
            start_time_utc startTimeUtc,weather,track_condition trackCondition,
            entry_url entryUrl,result_url resultUrl,status FROM rt_races
            WHERE race_date>=? AND race_date<? ORDER BY race_date,venue,race_no LIMIT 400""",
            [month+"-01",next_m+"-01"])
        if len(races)>=400:raise RuntimeError("RACE_SELECT_TRUNCATED")
        runner_sql=("SELECT race_id raceId,horse_no horseNo,frame_no frameNo,horse_name horseName,"
            "sex_age sexAge,coat_color coatColor,horse_weight horseWeight,weight_change weightChange,"
            "jockey,assigned_weight assignedWeight,trainer,stable,win_odds winOdds,"
            "popularity,runner_status runnerStatus FROM rt_runners WHERE race_id>=? AND race_id<? "
            "ORDER BY race_id,horse_no")
        result_sql=("SELECT race_id raceId,horse_no horseNo,finish_position finishPosition,"
            "result_status resultStatus,time_text timeText,margin_text marginText,final3f "
            "FROM rt_results WHERE race_id>=? AND race_id<? ORDER BY race_id,horse_no")
        runners=paged(runner_sql,[start,end])
        results=paged(result_sql,[start,end])
        pays=d1_query("""SELECT race_id raceId,bet_type betType,combination,
            payout_yen payoutYen FROM rt_payouts
            WHERE race_id>=? AND race_id<? AND bet_type=? ORDER BY race_id LIMIT 450""",
            [start,end,BET_TYPE])
        if len(pays)>=450:raise RuntimeError("PAYOUTS_TRUNCATED")
        bundled={r["raceId"]:{"race":r,"runners":[],"results":[],"payouts":[]}
                 for r in races}
        for typ,items in (("runners",runners),("results",results),("payouts",pays)):
            for x in items:
                rid=x["raceId"]
                if rid not in bundled:
                    raise RuntimeError("D1_ROW_OUTSIDE_REQUESTED_RACE:"+rid)
                bundled[rid][typ].append(x)
        for bundle in bundled.values():
            day=bundle["race"]["raceDate"]
            if START<=day<END:by_date[day].append(bundle)
        counts[month]={"raceRows":len(races),"runnerRows":len(runners),
                       "resultsRows":len(results),"winPayoutRows":len(pays),
                       "finishedRaces":sum(r["status"]=="finished" for r in races)}
        print("AUG_NOV_D1_MONTH",month,json.dumps(counts[month]),flush=True)
    return by_date,counts

def train_and_predict(by_date,base,core):
    archive=base.load_public_archive()
    historical=base.load_bundles(archive)
    X,y,counts,dates,offsets,winners,_,_,_=base.chronological_features(core,historical)
    train_ix=np.where(dates<"2026-01-01")[0]
    if len(train_ix)<20000 or str(dates[train_ix[-1]])>="2026-01-01":
        raise AssertionError("MODEL_TRAINING_USES_2026_TARGET_OUTCOMES")
    model=base.fit(X,y,offsets,train_ix,base.CANDIDATES["adopted_complexity_500x127"])
    print("AUG_NOV_2026_FROZEN_MODEL_TRAINED",json.dumps({
        "trainRaceCount":int(train_ix.size),"lastTrainDate":str(dates[train_ix[-1]]),
        "nTrees":500,"trainUses2026Labels":False}),flush=True)
    state=base.fresh_feature_state()
    for date,day in sorted(historical.items()):
        core.update_feature_state_for_date(state,day)
        state["throughDate"]=date
    if state["throughDate"]!="2026-08-09":
        raise AssertionError("FEATURE_STATE_MISSING_AUG_9")
    features=tuple(core.load_config()["runnerProbabilityModel"]["features"])
    if len(features)!=56:raise AssertionError("MODEL_FEATURES_NOT_56")
    predictions=[]
    venue_day_problems=collections.defaultdict(set)
    incomplete_history_dates=[]
    for date,day in sorted(by_date.items()):
        day_x=[];meta=[]
        for bundle in sorted(day,key=lambda z:(z["race"]["venue"],int(z["race"]["raceNo"]))):
            race=bundle["race"]
            venue=race["venue"]
            group=(date,venue)
            active=sorted((r for r in bundle["runners"] if
                           r.get("runnerStatus") in (None,"","active")),
                          key=lambda x:int(x["horseNo"]))
            if race["status"]!="finished":
                incomplete_history_dates.append(date)
                if len(active)>=12:venue_day_problems[group].add("UNFINISHED_12PLUS_RACE")
                continue
            if len(active)<12:continue
            result_winners=[int(r["horseNo"]) for r in bundle["results"] if r.get("finishPosition")==1]
            if len(result_winners)!=1:
                venue_day_problems[group].add("NO_UNIQUE_SETTLED_WINNER")
                continue
            if len(active)<3:continue
            if not race.get("resultUrl"):
                venue_day_problems[group].add("JRA_RESULT_LINK_MISSING")
                continue
            x=np.asarray([[float(core.ml_feature_row(state,race,r,len(active))[f])
                            for f in features] for r in active],dtype=np.float32)
            if not np.all(np.isfinite(x)):
                venue_day_problems[group].add("INVALID_PRE_RACE_FEATURE_VECTOR")
                continue
            day_x.append(x)
            meta.append((race,active,result_winners[0],bundle))
        if day_x:
            matrix=np.concatenate(day_x,axis=0)
            raw=model.predict_proba(matrix)[:,1]
            offset=0
            for race,active,winner,bundle in meta:
                p=raw[offset:offset+len(active)]
                offset+=len(active)
                p=np.maximum(p,1e-12);p=p/p.sum()
                ix=int(np.argmax(p))
                chosen=int(active[ix]["horseNo"])
                payout_by_no={}
                for row in bundle["payouts"]:
                    if re.fullmatch(r"\d+",str(row["combination"])):
                        n=int(row["combination"])
                        q=int(row["payoutYen"] or 0)
                        if n in payout_by_no and payout_by_no[n]!=q:
                            raise AssertionError("CONFLICTING_WIN_PAYOUT")
                        payout_by_no[n]=q
                if winner not in payout_by_no:
                    venue_day_problems[(date,race["venue"])].add("NO_WINNER_PAYOUT_IN_D1")
                predictions.append({"date":date,"venue":race["venue"],"raceNo":int(race["raceNo"]),
                    "raceId":race["raceId"],"resultUrl":race["resultUrl"],
                    "fieldSize":len(active),"horseNo":chosen,"modelProbability":float(p[ix]),
                    "winnerHorseNo":winner,"winnerPayout100":payout_by_no.get(winner)})
            assert offset==len(raw)
        # Same-day results are updated only AFTER every race on that date has been predicted.
        core.update_feature_state_for_date(state,day)
        state["throughDate"]=date
    print("AUG_NOV_PRE_RESULT_MODEL_CANDIDATES",json.dumps({
        "12PlusValidWinnerCandidates":len(predictions),
        "affectedVenueDays":len(venue_day_problems),
        "incompleteHistoricalDates":sorted(set(incomplete_history_dates))}),flush=True)
    return predictions,venue_day_problems,sorted(set(incomplete_history_dates))

def get_official_final_win(row,historic):
    url=row["resultUrl"]
    raw_url=__import__("urllib.parse").parse.unquote(url)
    match=re.search(r"pw01sde(?:10|01)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})",raw_url,re.I)
    if not match:
        raise ValueError("OFFICIAL_JRA_RESULT_URL_NOT_RECOGNIZED")
    venue,year,meeting,day,race_no,ymd=match.groups()
    if ymd!=row["date"].replace("-","") or int(race_no)!=row["raceNo"]:
        raise ValueError("JRA_RESULT_RACE_IDENTITY_MISMATCH")
    jar=historic.http.cookiejar.CookieJar()
    opener=historic.urllib.request.build_opener(historic.urllib.request.HTTPCookieProcessor(jar))
    req=historic.urllib.request.Request(url,
        headers={"User-Agent":historic.USER_AGENT,"Accept-Language":"ja-JP,ja;q=0.9"})
    raw,_=historic.open_retry(opener,req,attempts=3,timeout=25)
    page=raw.decode("cp932","replace")
    marker=f"10{venue}{year}{meeting}{day}{race_no}{ymd}"
    candidates=historic.extract_odds_cnames(page,"pw151ou",marker)
    if len(candidates)!=1:
        raise RuntimeError("JRA_HISTORICAL_WIN_LINK_MISSING_OR_DUPLICATED:"+str(len(candidates)))
    html,source=historic.post_odds(opener,candidates[0],url)
    quotes=historic.parse_win(BeautifulSoup(html,"html.parser"))
    odd=quotes.get(row["horseNo"])
    if not isinstance(odd,(float,int)) or not math.isfinite(odd) or odd<1:
        raise RuntimeError("SELECTED_HORSE_FINAL_ODDS_MISSING")
    if len(quotes)<max(3,row["fieldSize"]-2):
        raise RuntimeError("HISTORICAL_WIN_QUOTE_FIELD_INCOMPLETE")
    return {"odds":float(odd),"jraCname":candidates[0],
            "jraHistoricalWinUrl":source,"quoteCount":len(quotes),
            "oddsMoment":"post-race historical FINAL odds, NOT T-minus-15"}

def evaluate(predictions,problems,incomplete_history,quotes,failures):
    by_date=collections.defaultdict(list)
    for row in predictions:
        by_date[(row["date"],row["venue"])].append(row)
    for row in predictions:
        rid=row["raceId"]
        group=(row["date"],row["venue"])
        if rid in failures:problems[group].add("JRA_FINAL_ODDS_FETCH_MISSING")
        elif rid not in quotes:problems[group].add("JRA_WIN_ODDS_NOT_FETCHED")
    all_groups=set(by_date)|set(problems)
    chosen=[]
    skipped=collections.Counter()
    blocked={}
    group_counts=collections.Counter()
    month_rows=collections.defaultdict(list)
    for group in sorted(all_groups):
        date,venue=group
        group_counts["eligibleVenueDays"]+=1
        if problems.get(group):
            blocked[date+"|"+venue]=sorted(problems[group])
            group_counts["blockedVenueDays"]+=1
            continue
        available=[]
        for row in by_date[group]:
            odd=quotes[row["raceId"]]["odds"]
            score=row["modelProbability"]*odd
            if MIN_ODDS<=odd<MAX_ODDS and score>=EV_FLOOR:
                available.append((score,row))
        if not available:
            skipped[date[:7]]+=1
            group_counts["noQualifyingHorseVenueDays"]+=1
            continue
        available.sort(key=lambda z:(-z[0],z[1]["raceNo"]))
        ev,row=available[0]
        payout100=(row["winnerPayout100"] if row["winnerHorseNo"]==row["horseNo"] else 0)
        if payout100 is None:
            raise AssertionError("MISSING_WINNING_PAYOUT_CHOSEN_TICKET")
        rec={
            "date":date,"venue":venue,"raceId":row["raceId"],"raceNo":row["raceNo"],
            "fieldSize":row["fieldSize"],"horseNo":row["horseNo"],
            "modelProbability":round(row["modelProbability"],8),
            "archivedFinalOfficialOdds":quotes[row["raceId"]]["odds"],
            "modelImpliedEVOnHistoricalFinalOdds":round(ev,6),
            "winningHorseNo":row["winnerHorseNo"],
            "win":row["horseNo"]==row["winnerHorseNo"],
            "stakeYen":STAKE_YEN,"actualJraPayout100Yen":int(payout100),
            "jraHistoricalWinUrl":quotes[row["raceId"]]["jraHistoricalWinUrl"],
            "oddsSourceCname":quotes[row["raceId"]]["jraCname"],
        }
        chosen.append(rec)
        month_rows[date[:7]].append(rec)
        group_counts["chosenVenueDays"]+=1
    def summary(xs):
        stake=sum(r["stakeYen"] for r in xs)
        returned=sum(r["actualJraPayout100Yen"] for r in xs)
        max_ticket=max((r["actualJraPayout100Yen"] for r in xs),default=0)
        return {"bets":len(xs),"wins":sum(x["win"] for x in xs),
            "stakeYen":stake,"actualJraReturnYen":returned,
            "roiPct":round(100*returned/stake,2) if stake else None,
            "roiWithoutLargestTicketReturnPct":round(100*(returned-max_ticket)/stake,2) if stake else None}
    month_names=("2026-08","2026-09","2026-10","2026-11")
    monthly={m:{**summary(month_rows[m]),"skippedVenueDaysNoQualifiedHorse":skipped[m],
        "blockedVenueDays":sum(key.startswith(m) for key in blocked)}
        for m in month_names}
    complete=not blocked and not incomplete_history and not failures
    return {
      "status":"RETROSPECTIVE_JRA_FINAL_ODDS_RESEARCH_NOT_T15",
      "candidateFixedBeforeThisRecheck":True,
      "candidate":{
        "horseSelection":"highest chronological 56-feature LightGBM winner probability per race",
        "fieldSizeMinimum":12,"minArchivedFinalWinOddsInclusive":MIN_ODDS,
        "maxArchivedFinalWinOddsExclusive":MAX_ODDS,
        "minModelProbabilityTimesArchivedFinalOdds":EV_FLOOR,
        "maxSelectedRacesPerVenueDay":1,"racePriority":"highest probability x final odds",
        "stakeYen":STAKE_YEN,"ticketType":"単勝",
        "trainingCutoffExclusive":"2026-01-01",
        "referenceResult2026JanAug9RoiPct":145.14,
      },
      "periodStart":START,"periodEndInclusive":"2026-11-07",
      "priorYearLearningUsedForModel":True,
      "JraOddsAreVerifiedPreT15":False,
      "usesOfficialHistoricalFinalOdds":True,
      "actualJraPayoutReconciledFromPersistedD1":True,
      "sameDayResultLeakageInModelFeatures":False,
      "completeCohortProof":complete,
      "incompleteHistoricalResultsDates":incomplete_history,
      "candidateRaceQuoteFetchFailures":failures,
      "blockedVenueDays":blocked,
      "aggregate":summary(chosen),"byMonth":monthly,
      "groupCounts":dict(group_counts),
      "candidateRaceCount":len(predictions),
      "officialFinalOddsFetchedCount":len(quotes),
      "detailedSelectedWagers":chosen,
      "limitations":[
        "Official JRA odds are post-race FINAL; there is NO proven 15-minute-before-start price",
        "The deployed website requires TWO different ticket types; this is only single-win diagnostic",
        "Absent historical runner results distort subsequent feature-state updates",
        "Venue-days with any missing candidate odds or incomplete result are blocked, never imputed",
        "Archived race context/horse weights may differ from exact real-time feature inputs",
        "Candidate was chosen by inspecting 2024/25/26 archive; this 2026 Aug-Nov recheck is retrospective, not prospectively untouched",
        "A positive retrospective ROI cannot guarantee future returns or permit production promotion",
      ],
      "productionPromotionAuthorized":False,
      "productionOrD1Mutated":False,
    }

def self_test():
    assert MIN_ODDS==10 and MAX_ODDS==30 and EV_FLOOR==1.0
    fake=[
      {"date":"2026-08-15","venue":"東京","raceNo":1,"raceId":"a","fieldSize":13,
       "horseNo":3,"modelProbability":0.2,"winnerHorseNo":3,"winnerPayout100":1260},
      {"date":"2026-08-15","venue":"東京","raceNo":2,"raceId":"b","fieldSize":13,
       "horseNo":7,"modelProbability":0.3,"winnerHorseNo":1,"winnerPayout100":240}]
    quotes={"a":{"odds":12.6,"jraHistoricalWinUrl":"https://www.jra.go.jp/",
                "jraCname":"pw151oufoo"},
            "b":{"odds":20,"jraHistoricalWinUrl":"https://www.jra.go.jp/",
                "jraCname":"pw151oubar"}}
    a=evaluate(fake,collections.defaultdict(set),[],quotes,{})
    assert a["aggregate"]["bets"]==1
    assert a["detailedSelectedWagers"][0]["raceNo"]==2
    assert a["aggregate"]["roiPct"]==0
    fake[1]["modelProbability"]=0.1
    b=evaluate(fake,collections.defaultdict(set),[],quotes,{})
    assert b["aggregate"]["roiPct"]==1260
    assert b["completeCohortProof"] is True
    blocked=evaluate(fake,collections.defaultdict(set),[],{"a":quotes["a"]},{"b":"HTTP_403"})
    assert blocked["aggregate"]["bets"]==0
    assert blocked["completeCohortProof"] is False
    print("AUG_NOV_FROZEN_POLICY_SELFTEST_OK",flush=True)

def main():
    if "--self-test" in sys.argv:
        self_test();return
    begun=time.monotonic()
    base=load("scripts/research-chronological-56feature-validation.py","chronological_56_base")
    core=base.core_module()
    historical=load("scripts/research-enrich-official-history-odds.py","official_historical_win_reader")
    by_date,source_counts=d1_bundles()
    predictions,issues,incomplete_history=train_and_predict(by_date,base,core)
    if len(predictions)<350:
        raise AssertionError("INSUFFICIENT_RETRIEVED_12PLUS_RACES")
    quotes={}
    failures={}
    total=len(predictions)
    with concurrent.futures.ThreadPoolExecutor(max_workers=JRA_WORKERS) as pool:
        tasks={pool.submit(get_official_final_win,row,historical):row for row in predictions}
        for i,future in enumerate(concurrent.futures.as_completed(tasks),1):
            row=tasks[future]
            try:
                quotes[row["raceId"]]=future.result()
            except Exception as exc:
                failures[row["raceId"]]=type(exc).__name__+":"+str(exc)[:180]
            if i%50==0 or i==total:
                print("AUG_NOV_JRA_OFFICIAL_FINAL_ODDS_PROGRESS",json.dumps({
                    "processed":i,"total":total,"quotesRetrieved":len(quotes),
                    "failures":len(failures),"elapsedSeconds":round(time.monotonic()-begun,1)}),flush=True)
    report=evaluate(predictions,issues,incomplete_history,quotes,failures)
    report["D1SourceCoverageByMonth"]=source_counts
    report["elapsedSeconds"]=round(time.monotonic()-begun,1)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("AUG_NOV_FROZEN_OFFICIAL_FINAL_ODDS_ROI",json.dumps({
        "aggregate":report["aggregate"],"byMonth":report["byMonth"],
        "candidateRaceCount":report["candidateRaceCount"],
        "officialFinalOddsFetchedCount":report["officialFinalOddsFetchedCount"],
        "groupCounts":report["groupCounts"],
        "blockedVenueDays":len(report["blockedVenueDays"]),
        "incompleteHistoricalResultsDates":report["incompleteHistoricalResultsDates"],
        "elapsedSeconds":report["elapsedSeconds"],"promotionAuthorized":False,
        "preT15OddsVerified":False,
    },ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
