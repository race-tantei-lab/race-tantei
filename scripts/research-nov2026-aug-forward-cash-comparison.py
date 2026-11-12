#!/usr/bin/env python3
"""Research only: apply the 2026-11-12 pre-frozen 18,900-recipe cash overlay to
real Aug 15-Nov 8 frozen production tickets, with identical-race cash baseline.

No rerunning/retro-generating original picks. D1 SELECT only, 4 indexed queries.
Reject missing/late tickets and unsettled races at the VENUE-DAY level. No
unverified T-15 records enter final results. No write, deployment or promotion.
Historical overlay money-training stops at 2026-08-09, before live cohort.

This is retrospective overlay application to real forward bets, NOT an
independent prospective validation of overlay decided Nov 12.
"""
from __future__ import annotations
import collections,datetime as dt,importlib.util,json,os,urllib.request,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
START="2026-08-15"
END="2026-11-09" # exclusive, last finished day 2026-11-08
REPORT=ROOT/"analysis-results/nov2026-aug-nov-forward-direct-cash.json"
LEDGER=ROOT/"analysis-results/nov2026-aug-nov-forward-direct-cash-ledger.json"
COURSE="ライト"
JST=dt.timezone(dt.timedelta(hours=9))
MARKET_REGIME=("market","odds","raceNo")
PAY_CAP=30000
PRIOR=40
STAKING_POWER=4.0
RACE_PICK=3
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")

def canonical():
    p=ROOT/"scripts/research-nov2026-canonical-cash-direct.py"
    s=importlib.util.spec_from_file_location("frozen_cash_rules",p)
    m=importlib.util.module_from_spec(s)
    sys.modules[s.name]=m
    s.loader.exec_module(m)
    return m

def query(sql,params):
    account=os.environ["CLOUDFLARE_ACCOUNT_ID"]
    database=os.environ["CLOUDFLARE_D1_DATABASE_ID"]
    token=os.environ["CLOUDFLARE_API_TOKEN"]
    url=f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{database}/query"
    req=urllib.request.Request(url,method="POST",
        data=json.dumps({"sql":sql,"params":params},ensure_ascii=False).encode("utf8"),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+token})
    with urllib.request.urlopen(req,timeout=45) as f:data=json.loads(f.read())
    if not data.get("success"):raise RuntimeError("D1_READ_FAILED:"+str(data.get("errors"))[:350])
    return (data.get("result") or [{}])[0].get("results") or []

def within_t15(date,start_jst,value):
    try:
        start=dt.datetime.fromisoformat(date+"T"+str(start_jst)[:5]+":00+09:00")
        lock=dt.datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return lock.tzinfo is not None and lock<=start-dt.timedelta(minutes=15)
    except (ValueError,TypeError):
        return False

def money(rows):
    n=len(rows)
    total=sum(int(x["stakeYen"]) for x in rows)
    ret=sum(int(x["paidYen"]) for x in rows)
    largest=max((int(x["paidYen"]) for x in rows),default=0)
    hits=sum(int(x["paidYen"]>0) for x in rows)
    return dict(races=n,stakeYen=total,paidYen=ret,
      roiPct=round(100*ret/total,5) if total else None,
      minusMaxRaceRoiPct=round(100*(ret-largest)/total,5) if total else None,
      hitRacePct=round(100*hits/n,5) if n else None,
      biggestRaceReturnYen=largest)

def scaled_per100(row):
    stake=int(row["stakeYen"] or 0)
    ret=row["returnYen"]
    if row["settlement"]!="settled" or ret is None or stake<=0 or stake%100!=0:
        raise ValueError("UNSETTLED_OR_INVALID_STAKE")
    ret=int(ret)
    if ret<0 or ret*100%stake:
        raise ValueError("RETURN_NOT_RECONCILABLE_TO_100YEN")
    return ret*100//stake

def build_ticket(original,mod):
    if original["betType"] not in MARKETS:raise ValueError("UNSUPPORTED_MARKET")
    odd=float(original["assumedOdds"])
    if not (1<=odd<1e7):raise ValueError("MISSING_OR_INVALID_PRE_FROZEN_ODDS")
    return {
      "market":original["betType"],
      "odds":int(__import__("numpy").searchsorted(mod.BINS,odd,side="right")-1),
      "oddsReal":odd,
      "slot":int(original["slot"]),
      "combination":original["combination"],
      "per100":scaled_per100(original),
      "originalLockedAt":original["lockedAt"]
    }

def process(states,bets,mod,training):
    bydate={}
    records=collections.defaultdict(list)
    for r in bets:records[(str(r["raceId"]),str(r["course"]))].append(r)
    info=collections.Counter();excluded=[];blocks=[];daily=collections.defaultdict(list)
    for state in states:
        date=str(state["k"]).removeprefix("final_daily_selection:")
        if date<START or date>=END:continue
        val=json.loads(state["v"])
        if val.get("sourceModel")!="ten-year-completed-model":
            excluded.append(dict(date=date,venue="*",reason="OTHER_GENERATOR"));continue
        if val.get("resultDataUsedForTargetDay") is True:
            excluded.append(dict(date=date,venue="*",reason="TARGET_RESULT_LEAK"));continue
        s=val.get("selected")
        if not isinstance(s,list):
            excluded.append(dict(date=date,venue="*",reason="SELECTED_MISSING"));continue
        byvenue=collections.defaultdict(list)
        for a in s:byvenue[str(a.get("venue") or "UNKNOWN")].append(a)
        for venue,entries in byvenue.items():
            info["venueDaysInOriginalFinalSelection"]+=1
            if len(entries)!=5:
                excluded.append(dict(date=date,venue=venue,reason="NOT_5_ORIGINAL_SELECTED_RACES",found=len(entries)))
                continue
            vals=[]
            for item in entries:
                race_id=str(item.get("raceId") or "")
                if not race_id:raise RuntimeError("SELECTION_RACE_ID_MISSING")
                matching=records[(race_id,COURSE)]
                if len(matching)!=2:
                    excluded.append(dict(date=date,venue=venue,reason="NOT_TWO_ACTUAL_LOCKED_TICKETS",
                                         raceId=race_id,count=len(matching)))
                    break
                # Stable order by explicit D1 primary key; no result ordering.
                original=sorted(matching,key=lambda x:int(x["id"]))
                if len({t["betType"] for t in original})!=2:
                    excluded.append(dict(date=date,venue=venue,reason="SAME_MARKET_TWO_TICKETS",raceId=race_id));break
                if not all(within_t15(date,item.get("startTimeJst"),b["lockedAt"]) for b in original):
                    excluded.append(dict(date=date,venue=venue,reason="MISSING_OR_POST_T15_LOCK",raceId=race_id));break
                try:
                    tt=[build_ticket({**b,"slot":i},mod) for i,b in enumerate(original)]
                except (ValueError,TypeError) as e:
                    excluded.append(dict(date=date,venue=venue,reason=str(e),raceId=race_id));break
                info["individualRacesEligibleBeforeFullDayGate"]+=1
                race={"raceId":race_id,"day":date,"venue":venue,
                      "surface":str(item.get("surface") or "UNKNOWN"),
                      "distance":int(item.get("distanceM") or 0)//400,
                      "raceNo":int(item.get("raceNo") or 0),
                      "tickets":tt}
                score=[mod.estimate(race,t,MARKET_REGIME,training,PRIOR) for t in tt]
                a,b=score;weight_a=a**STAKING_POWER/(a**STAKING_POWER+b**STAKING_POWER)
                st_a=100*max(1,min(19,round(weight_a*20)))
                st_b=2000-st_a
                base_paid=1000*sum(t["per100"] for t in tt)//100
                new_paid=(st_a*tt[0]["per100"]+st_b*tt[1]["per100"])//100
                vals.append(dict(raceId=race_id,day=date,venue=venue,
                  raceNo=race["raceNo"],
                  expectedScore=round(a+b,8),
                  betTypes=[tt[0]["market"],tt[1]["market"]],
                  combinations=[tt[0]["combination"],tt[1]["combination"]],
                  originalOdds=[tt[0]["oddsReal"],tt[1]["oddsReal"]],
                  stakeA=st_a,stakeB=st_b,
                  baselinePaidYen=base_paid,newPaidYen=new_paid,
                  originallyPersistedStakesYen=[int(t["stakeYen"]) for t in original],
                  originallyPersistedPaidYen=sum(int(t["returnYen"]) for t in original)))
            else:
                if len(vals)!=5:raise RuntimeError("NOT_ALL_FIVE_PROCESSED")
                info["verifiedCompleteVenueDays"]+=1
                top3=sorted(vals,key=lambda r:(-r["expectedScore"],r["raceNo"],r["raceId"]))[:RACE_PICK]
                blocks.extend(top3)
                daily[date].extend(top3)
                continue
            info["rejectedVenueDays"]+=1
    scenarios=[dict(**x,stakeYen=2000,paidYen=x["newPaidYen"]) for x in blocks]
    baseline=[dict(**x,stakeYen=2000,paidYen=x["baselinePaidYen"]) for x in blocks]
    return {"new":money(scenarios),"equalStakeSameRaces":money(baseline),
        "venueAudit":dict(info),"excludedVenueDays":excluded,
        "firstDate":min(daily) if daily else None,
        "lastDate":max(daily) if daily else None,
        "byMonth":{month:{
            "new":money([x for x in scenarios if x["day"].startswith(month)]),
            "baseline":money([x for x in baseline if x["day"].startswith(month)])}
            for month in sorted({x["day"][:7] for x in blocks})},
        "byDay":{k:{"new":money([dict(**r,stakeYen=2000,paidYen=r["newPaidYen"]) for r in v]),
           "baseline":money([dict(**r,stakeYen=2000,paidYen=r["baselinePaidYen"]) for r in v])}
           for k,v in daily.items()}},blocks

def main():
    if "--self-test" in sys.argv:
        assert money([{"stakeYen":2000,"paidYen":5000},{"stakeYen":2000,"paidYen":1000}])["minusMaxRaceRoiPct"]==25.
        assert scaled_per100({"stakeYen":1000,"returnYen":41500,"settlement":"settled"})==4150
        assert within_t15("2026-11-08","10:00","2026-11-08T00:40:00Z")
        assert not within_t15("2026-11-08","10:00","2026-11-08T00:50:00Z")
        print("AUG_FORWARD_CASH_SAME_REAL_BETS_SELFTEST_OK",flush=True);return
    mod=canonical()
    historical,_=mod.load_archive()
    if any(x["day"]>="2026-08-10" for x in historical):
        raise RuntimeError("PRE_FORWARD_TRAINING_ARCHIVE_MUST_STOP_AUG9")
    fitted=mod.fit(historical,2027,MARKET_REGIME,PAY_CAP,PRIOR)
    states=query("""SELECT state_key AS k,state_value AS v FROM rt_system_state
             WHERE state_key>=? AND state_key<? ORDER BY state_key LIMIT 100""",
            ["final_daily_selection:"+START,"final_daily_selection:"+END])
    if len(states)>=100:raise RuntimeError("SELECTED_STATE_PAGE_TRUNCATED")
    bets=query("""SELECT id,race_id AS raceId,course,bet_type AS betType,
             combination,stake_yen AS stakeYen,return_yen AS returnYen,
             settlement_status AS settlement,assumed_odds AS assumedOdds,
             locked_at AS lockedAt,source_prediction_id AS source
             FROM rt_public_bets
             WHERE race_id>=? AND race_id<?
                AND course=? AND source_prediction_id=-2
             ORDER BY race_id,id LIMIT 3000""",
             [START+"-",END+"-",COURSE])
    if len(bets)>=3000:raise RuntimeError("ACTUAL_BET_ROWS_PAGE_TRUNCATED")
    if not states or not bets:raise RuntimeError("NO_ACTUAL_LIVE_SELECTION_OR_BETS")
    report,ledger=process(states,bets,mod,fitted)
    data={"source":"D1 already persisted live final selection and pre-T15 bets",
      "period":{"from":START,"through":"2026-11-08"},
      "trainingHistoricalDataEnds":"2026-08-09",
      "overlayWasDiscoveredOn":"2026-11-12",
      "classification":"RETROSPECTIVE_APPLY_TO_LIVE_BETS_NOT_PROSPECTIVE",
      "moneyPolicy":{"context":["market","odds","raceNo"],"capYen":PAY_CAP,
         "priorCount":PRIOR,"stakePower":STAKING_POWER,
         "venueDaySelectedRaces":RACE_PICK},
      "sourceModel":"ten-year-completed-model",
      "productionUntouched":True,"databaseWrites":0,
      "officialOddsTimeMatchedToHistoricalT15":False,
      "auditableSettlements":True,
      "fullOfficialJraPayoutsIndependentRecheck":False,
      "dataRows":{"selectedStateDays":len(states),"settlementTickets":len(bets),
           "trainingHistoricalSelectedRaces":len(historical)},
      "measured":report}
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    LEDGER.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("AUG_NOV_REAL_CASH_FINANCIAL_FINAL",json.dumps({
      "period":data["period"],"new":report["new"],
      "sameRacesOriginal":report["equalStakeSameRaces"],
      "months":report["byMonth"],"venues":report["venueAudit"],
      "excluded":report["excludedVenueDays"][:20],
      "excludedCount":len(report["excludedVenueDays"])} ,
      ensure_ascii=False),flush=True)

if __name__=="__main__":main()
