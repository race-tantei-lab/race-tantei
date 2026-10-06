#!/usr/bin/env python3
import json, os, re, urllib.request
from collections import defaultdict
from datetime import datetime, timezone, timedelta

ACCOUNT=os.environ["CLOUDFLARE_ACCOUNT_ID"]; DB=os.environ["CLOUDFLARE_D1_DATABASE_ID"]; TOKEN=os.environ["CLOUDFLARE_API_TOKEN"]
URL=f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DB}/query"
KEY="public_daily_performance_history:v1"; VERSION="daily-performance-history-v1"; START="2026-09-19"
JST=timezone(timedelta(hours=9)); through=(datetime.now(JST).date()-timedelta(days=1)).isoformat()
COURSES=("ライト","スタンダード","プレミアム"); DEFAULT_STAKE={"ライト":2000,"スタンダード":5000,"プレミアム":10000}

def q(sql,params=None):
    req=urllib.request.Request(URL,data=json.dumps({"sql":sql,"params":params or []},ensure_ascii=False).encode(),method="POST",headers={"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r: out=json.loads(r.read().decode())
    if not out.get("success"): raise RuntimeError(out)
    z=out.get("result") or []
    return (z[0].get("results") or []) if z else []

def horse_nos(c): return [int(x) for x in re.findall(r"\d{1,2}",str(c)) if 1<=int(x)<=18]
def refund_set(raw):
    try:return {int(x) for x in json.loads(raw or "[]")}
    except:return set()
def target_count(raw):
    try:return len({str(x.get("raceId")) for x in json.loads(raw or "{}").get("selected",[]) if x.get("raceId")})
    except:return 0

state=q("SELECT state_value value FROM rt_system_state WHERE state_key=? LIMIT 1",[KEY])
existing=None
if state and state[0].get("value"):
    try:existing=json.loads(state[0]["value"])
    except:pass
if existing and existing.get("version")==VERSION and str(existing.get("throughDate") or "")>=through:
    print(json.dumps({"DAILY_HISTORY_BACKFILL":"up_to_date","throughDate":existing.get("throughDate"),"days":len(existing.get("days") or [])},ensure_ascii=False)); raise SystemExit

bets=q("""SELECT r.race_date raceDate,b.race_id raceId,b.course,b.bet_type betType,b.combination,
 b.stake_yen stakeYen,b.return_yen returnYen,b.settlement_status settlementStatus,r.refund_horse_nos_json refundsJson
 FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
 WHERE r.race_date>? AND r.race_date<=? AND b.source_prediction_id=-2
 ORDER BY r.race_date,b.race_id,b.course,b.id""",[START,through])
sels=q("""SELECT substr(state_key,23) raceDate,state_value value FROM rt_system_state
 WHERE state_key LIKE 'final_daily_selection:%' AND state_key>? AND state_key<=? ORDER BY state_key""",
 [f"final_daily_selection:{START}",f"final_daily_selection:{through}"])
selmap={str(x["raceDate"]):x.get("value") for x in sels}
bydate=defaultdict(list)
for x in bets: bydate[str(x["raceDate"])].append(x)

def summarize(date,rows,target):
    courses=[]
    for course in COURSES:
        rr=[x for x in rows if x["course"]==course]; byr=defaultdict(list)
        for x in rr: byr[str(x["raceId"])].append(x)
        finalized=settled=hits=refundr=finalstake=settledstake=ret=0
        for rid,rs in byr.items():
            if len(rs)!=2: continue
            finalized+=1
            stake=sum(int(x.get("stakeYen") or 0) for x in rs) if all(x.get("stakeYen") is not None for x in rs) else DEFAULT_STAKE[course]
            finalstake+=stake
            if not all(x.get("settlementStatus")=="settled" for x in rs): continue
            settled+=1;settledstake+=stake;refunds=refund_set(rs[0].get("refundsJson"));genuine=False;has_refund=False
            for x in rs:
                refunded=any(h in refunds for h in horse_nos(x.get("combination")))
                has_refund|=refunded
                rv=int(x.get("returnYen") or 0);ret+=rv
                if (not refunded) and rv>0:genuine=True
            hits+=int(genuine);refundr+=int(has_refund)
        courses.append({"course":course,"finalizedRaces":finalized,"settledRaces":settled,"hitRaces":hits,"refundRaces":refundr,
          "finalizedStakeYen":finalstake,"settledStakeYen":settledstake,"returnYen":ret,"pendingStakeYen":max(0,finalstake-settledstake),
          "profitYen":ret-settledstake,"roiPct":(ret/settledstake*100 if settledstake else None)})
    light=next(x for x in courses if x["course"]=="ライト")
    return {**light,"date":date,"courses":courses,"targetRaces":target}

dates=sorted(set(bydate)|set(selmap))
days=[summarize(d,bydate.get(d,[]),target_count(selmap.get(d))) for d in dates]
unresolved=[d["date"] for d in days if any(c["finalizedRaces"]>c["settledRaces"] for c in d["courses"])]
payload={"version":VERSION,"throughDate":through,"updatedAt":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
 "unresolvedDates":unresolved,"days":sorted(days,key=lambda x:x["date"],reverse=True)[:30]}
q("""INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
 ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP""",[KEY,json.dumps(payload,ensure_ascii=False,separators=(",",":"))])
print(json.dumps({"DAILY_HISTORY_BACKFILL":"updated","throughDate":through,"days":len(payload["days"]),"unresolvedDates":unresolved,
 "dates":[x["date"] for x in payload["days"]]},ensure_ascii=False))
