#!/usr/bin/env python3
"""Read-only retrospective FINAL-ODDS collection, only independent-selected races.

Uses JRA official historical pages, never canonical final ticket combinations
or inferred market prices. A prospective T-15 claim is NOT made here.
"""
import concurrent.futures,json,os,re,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/"scripts/export-selected-historical-official-odds.py").read_text()
source=source.split("selection = json.loads(SELECTION.read_text")[0]
# Apply official archive exporter corrections without modifying production.
source=source.replace(r"pw01sde10(\d{2})",r"pw01sde(?:10|01)(\d{2})")
source=source.replace("tab[m.group(2)] = m.group(1)","tab['15' + m.group(2)] = m.group(1)")
scope={"__name__":"retrospective_odds_functions","__file__":str(ROOT/"scripts/export-selected-historical-official-odds.py")}
exec(compile(source,"historic-jra-final-odds-importer","exec"),scope)
INPUT=ROOT/"artifacts/independent-final-odds-plan.json"
OUT=ROOT/"artifacts/independent-retro-odds.json"
data=json.loads(INPUT.read_text())
rows=list({p["raceId"]:{"raceId":p["raceId"],"raceDate":p["race"]["raceDate"],"venue":p["race"]["venue"],"raceNo":p["race"]["raceNo"],"resultUrl":p["race"]["resultUrl"]} for p in data["races"]}.values())
print("RETROSPECTIVE_OFFICIAL_FINAL_ODDS_RACES",len(rows),flush=True)
results=[];failures=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
 futures={pool.submit(scope["fetch_race"],x):x for x in rows}
 for fut in concurrent.futures.as_completed(futures):
  row=futures[fut]
  try:
   got=fut.result()
   results.append(got)
   print("JRA_FINAL_ODDS_OK",got["raceId"],len(got["horses"]),got["present"],flush=True)
  except Exception as err:
   failures.append({"raceId":row["raceId"],"error":type(err).__name__+":"+str(err)[:300]})
   print("JRA_FINAL_ODDS_FAILED",row["raceId"],type(err).__name__,str(err)[:250],flush=True)
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps({"date":data["date"],"races":results,"errors":failures,"requested":len(rows)},ensure_ascii=False,separators=(",",":"))+"\n")
print("INDEPENDENT_FINAL_ODDS_RETRIEVAL",json.dumps({"requested":len(rows),"success":len(results),"failed":len(failures),"sample":failures[:6]},ensure_ascii=False),flush=True)
if not results:raise RuntimeError("NO_HISTORICAL_FINAL_ODDS_ACQUIRED")
