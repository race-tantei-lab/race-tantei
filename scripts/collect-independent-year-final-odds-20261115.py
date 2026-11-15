#!/usr/bin/env python3
"""All selected JRA official six-market FINAL odds for one historical year.
Pre-result prices are not claimed: each number is a retrospective final odd.
"""
import concurrent.futures,gzip,json,os,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
YEAR=os.environ.get("AUDIT_YEAR","2017")
INPUT=ROOT/f"artifacts/independent-year-result-{YEAR}.json"
OUT=ROOT/f"artifacts/independent-year-final-odds-{YEAR}.jsonl.gz"
META=ROOT/f"artifacts/independent-year-final-odds-{YEAR}-meta.json"
source=(ROOT/"scripts/export-selected-historical-official-odds.py").read_text()
source=source.split("selection = json.loads(SELECTION.read_text")[0]
# Offline research needs only JRA HTTPS; old exporter's D1 token gate is irrelevant.
source=source.replace("if not TOKEN:\n    raise RuntimeError('CLOUDFLARE_API_TOKEN is not set')","")
source=source.replace(r"pw01sde10(\d{2})",r"pw01sde(?:10|01)(\d{2})")
source=source.replace("tab[m.group(2)] = m.group(1)","tab['15' + m.group(2)] = m.group(1)")
scope={"__name__":"retrospective_odds_functions","__file__":str(ROOT/"scripts/export-selected-historical-official-odds.py")}
exec(compile(source,"existing-fixed-official-odds-parser","exec"),scope)
data=json.loads(INPUT.read_text())
races=[{"raceId":r["raceId"],"raceDate":r["race"]["raceDate"],"venue":"","raceNo":0,"resultUrl":r["race"]["resultUrl"]} for r in data["races"]]
failures=[];count=0;t0=time.monotonic()
OUT.parent.mkdir(parents=True,exist_ok=True)
with gzip.open(OUT,"wt",encoding="utf8",compresslevel=5) as out:
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
  futures={pool.submit(scope["fetch_race"],row):row for row in races}
  for index,fut in enumerate(concurrent.futures.as_completed(futures),1):
   race=futures[fut]
   try:
    odds=fut.result()
    out.write(json.dumps(odds,ensure_ascii=False,separators=(",",":"))+"\n")
    count+=1
   except Exception as e:
    failures.append({"raceId":race["raceId"],"error":type(e).__name__+":"+str(e)[:180]})
   if index%35==0 or index==len(races):
    print("INDEPENDENT_YEAR_OFFICIAL_FINAL_ODDS_PROGRESS",json.dumps({"year":YEAR,"done":index,"total":len(races),"success":count,"errors":len(failures),"elapsedSec":round(time.monotonic()-t0,1)}),flush=True)
meta={"year":YEAR,"requested":len(races),"success":count,"failures":failures,
 "JraOfficialHistoricalFinalOdds":True,"postRaceOddsMayDifferFromPreT15":True,"originalTicketsUsed":False}
META.write_text(json.dumps(meta,ensure_ascii=False,indent=2))
print("INDEPENDENT_YEAR_OFFICIAL_FINAL_ODDS_DONE",json.dumps({"year":YEAR,"requested":len(races),"success":count,"failed":len(failures),"sampleErrors":failures[:5]}),flush=True)
if count==0:raise RuntimeError("NO_JRA_FINAL_ODDS_FOR_YEAR:"+YEAR)
