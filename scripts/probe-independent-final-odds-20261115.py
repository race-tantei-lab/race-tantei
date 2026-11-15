#!/usr/bin/env python3
"""READ ONLY probe: JRA retrospective six-market odds and historical feature-state source."""
import json,os,urllib.request,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def d1(sql,params=[]):
  endpoint=f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/d1/database/{os.environ['CLOUDFLARE_D1_DATABASE_ID']}/query"
  request=urllib.request.Request(endpoint,data=json.dumps({"sql":sql,"params":params}).encode(),headers={"Authorization":"Bearer "+os.environ["CLOUDFLARE_API_TOKEN"],"Content-Type":"application/json"},method="POST")
  with urllib.request.urlopen(request,timeout=45) as response:body=json.load(response)
  if not body.get("success"):raise RuntimeError("D1:"+repr(body.get("errors")))
  return body["result"][0].get("results",[])
day=os.environ.get("AUDIT_DATE","2026-11-08")
meta=d1("SELECT key,value FROM rt_ml_feature_meta WHERE key IN ('throughDate','currentGeneration','ready') ORDER BY key")
model=d1("SELECT key,value FROM rt_ml_model_meta WHERE key IN ('ready','modelVersion','chunkCount','byteLength') ORDER BY key")
races=d1("SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,result_url AS resultUrl,start_time_utc AS startTimeUtc,status FROM rt_races WHERE race_date=? ORDER BY venue,race_no",[day])
print("INDEPENDENT_RETRO_PROBE",json.dumps({"date":day,"featureMeta":meta,"modelMeta":model,"races":len(races),"venues":list(set(r["venue"] for r in races)),"sample":races[:3]},ensure_ascii=False),flush=True)
if not races:raise RuntimeError("NO_RACES_IN_DATE")
src=(ROOT/"scripts/export-selected-historical-official-odds.py").read_text()
source=src.split("selection = json.loads(SELECTION.read_text")[0]
scope={"__name__":"retrospective_odds_functions","__file__":str(ROOT/"scripts/export-selected-historical-official-odds.py")}
exec(compile(source,"existing-historical-odds.py","exec"),scope)
for row in races[:5]:
  if not row["resultUrl"]:continue
  try:
    got=scope["fetch_race"](row)
    print("RETRO_FINAL_ODDS_OK",json.dumps({"raceId":row["raceId"],"horses":len(got["horses"]),"present":got["present"],"expected":got["expected"]},ensure_ascii=False),flush=True)
    break
  except Exception as e:
    print("RETRO_FINAL_ODDS_FAILED",row["raceId"],type(e).__name__,str(e)[:350],flush=True)
    if "RESULT_ID_PARSE_MISS" in str(e):
      import re,urllib.request
      raw,_=scope["open_retry"](urllib.request.build_opener(),urllib.request.Request(row["resultUrl"],headers={"User-Agent":"Mozilla/5.0"}))
      html=raw.decode("cp932","replace")
      print("HISTORICAL_RESULT_ODDS_ACTIONS",re.findall(r".{0,55}accessO\\.html.{0,125}",html)[:5],flush=True)
      print("HISTORICAL_RESULT_ODDS_CNAME",re.findall(r"pw15.{0,85}",html)[:5],flush=True)
else: raise RuntimeError("ALL_FIVE_JRA_HISTORICAL_FINAL_ODDS_FETCH_FAILED")
