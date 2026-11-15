#!/usr/bin/env python3
"""Read-only export of Aug10-Nov15 2026 completed races, results, payouts,
all pre-known runner fields and preceding canonical cash observations.
No D1 write; race-day settlement status must be FINISHED.
"""
import collections,gzip,json,os,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"artifacts"/"independent-late-2026-d1.json.gz"
A=os.environ["CLOUDFLARE_ACCOUNT_ID"];D=os.environ["CLOUDFLARE_D1_DATABASE_ID"];TOKEN=os.environ["CLOUDFLARE_API_TOKEN"]
URL=f"https://api.cloudflare.com/client/v4/accounts/{A}/d1/database/{D}/query"
START="2026-08-10";END="2026-11-15"
def d1(sql,params=[]):
 if not sql.upper().lstrip().startswith("SELECT "):raise RuntimeError("ONLY_READS_ALLOWED")
 req=urllib.request.Request(URL,method="POST",data=json.dumps({"sql":sql,"params":params}).encode(),
  headers={"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json"})
 with urllib.request.urlopen(req,timeout=90) as response:res=json.load(response)
 if not res.get("success"):raise RuntimeError("D1_QUERY_FAILED:"+str(res.get("errors"))[:500])
 return res["result"][0].get("results",[])
def fetch_all(name,query,limit=400):
 data=[]
 for off in range(0,90000,limit):
  rows=d1(query+" LIMIT ? OFFSET ?",[START,END,limit,off])
  data.extend(rows)
  if len(rows)<limit:break
 else:raise RuntimeError("RESEARCH_D1_PAGING_OVERFLOW:"+name)
 print("RESEARCH_LATE_D1_EXPORT",json.dumps({"table":name,"rows":len(data)}),flush=True)
 return data
races=fetch_all("races","SELECT race_id AS raceId,race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,race_no AS raceNo,race_name AS raceName,conditions,surface,distance_m AS distanceM,direction,weather,track_condition AS trackCondition,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,entry_url AS entryUrl,result_url AS resultUrl,status FROM rt_races WHERE race_date>=? AND race_date<=? AND status='finished' ORDER BY race_date,venue,race_no")
runners=fetch_all("runners","SELECT ru.race_id AS raceId,ru.horse_no AS horseNo,ru.frame_no AS frameNo,ru.horse_name AS horseName,ru.sex_age AS sexAge,ru.assigned_weight AS assignedWeight,ru.jockey,ru.trainer,ru.horse_weight AS horseWeight,ru.weight_change AS weightChange,ru.popularity,ru.win_odds AS winOdds,ru.runner_status AS runnerStatus FROM rt_runners ru JOIN rt_races ra ON ra.race_id=ru.race_id WHERE ra.race_date>=? AND ra.race_date<=? AND ra.status='finished' ORDER BY ru.race_id,ru.horse_no")
results=fetch_all("results","SELECT re.race_id AS raceId,re.horse_no AS horseNo,re.finish_position AS finishPosition,re.time_text AS timeText,re.final3f FROM rt_results re JOIN rt_races ra ON ra.race_id=re.race_id WHERE ra.race_date>=? AND ra.race_date<=? AND ra.status='finished' ORDER BY re.race_id,re.horse_no")
payouts=fetch_all("payouts","SELECT pa.race_id AS raceId,pa.bet_type AS betType,pa.combination,pa.payout_yen AS payoutYen FROM rt_payouts pa JOIN rt_races ra ON ra.race_id=pa.race_id WHERE ra.race_date>=? AND ra.race_date<=? AND ra.status='finished' ORDER BY pa.race_id,pa.bet_type,pa.combination")
canonical=fetch_all("original_past_settled","SELECT b.race_id AS raceId,b.bet_type AS betType,b.combination,b.stake_yen AS stakeYen,b.assumed_odds AS assumedOdds,b.locked_at AS lockedAt,b.return_yen AS returnYen,b.settlement_status AS settlementStatus,r.race_date AS raceDate,r.venue,r.race_no AS raceNo,r.race_name AS raceName,r.surface,r.distance_m AS distanceM,r.start_time_utc AS startTimeUtc,r.start_time_jst AS startTimeJst FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id WHERE r.race_date>=? AND r.race_date<=? AND b.course='ライト' AND b.source_prediction_id=-2 AND b.settlement_status='settled' ORDER BY b.race_id,b.id")
if not races:raise RuntimeError("NO_ARCHIVED_LATE_RACES")
by={}
for r in races:by[r["raceId"]]={"race":r,"runners":[],"results":[],"payouts":[]}
for key,values in (("runners",runners),("results",results),("payouts",payouts)):
 for r in values:
  v=by.get(r["raceId"])
  if v is not None:v[key].append(r)
records=sorted(by.values(),key=lambda x:(x["race"]["raceDate"],x["race"]["venue"],x["race"]["raceNo"]))
document={"start":START,"end":END,"races":records,"pastOriginalSettled":canonical,"readOnly":True,"dataSource":"Cloudflare D1 settled JRA, original tickets only as prior cash observations"}
OUT.parent.mkdir(parents=True,exist_ok=True)
with gzip.open(OUT,"wt",encoding="utf8",compresslevel=6) as f:json.dump(document,f,ensure_ascii=False,separators=(",",":"))
print("INDEPENDENT_LATE_2026_COMPLETE_DATA",json.dumps({"races":len(races),"runners":len(runners),"results":len(results),"payouts":len(payouts),"pastSettledTickets":len(canonical),"dates":len(set(x["race"]["raceDate"] for x in records))}),flush=True)
