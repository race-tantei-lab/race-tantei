#!/usr/bin/env python3
"""Export fixed monthly sufficient cash statistics from original 2016–Aug2026 archive.

Research dashboard read-only priors. Newer settled live records must be added
from PREVIOUS months only at runtime; no forecast input uses outcomes from
its own calendar month. Underlying horse/ticket choices come from current
frozen production, NOT from independent new horse predictor models.
"""
from __future__ import annotations
import base64
from collections import defaultdict
import gzip
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"src/v1/ten-year-history-data"
OUT=ROOT/"src/v1/three-model-archived-cash-priors.json"
MARKETS={"単勝","ワイド","馬連","馬単","3連複","3連単"}
BOUNDS=(2,3,5,8,12,20,35,60,100,200,400)

def cash_keys(kind,odds,venue,race_no,surface,month,distance):
    ob=next((i for i,cap in enumerate(BOUNDS) if odds<cap),len(BOUNDS))
    return [
       ("type",kind),
       ("typeOdds",kind,ob),
       ("typeVenue",kind,venue),
       ("typeRace",kind,0 if race_no<=4 else 1 if race_no<=8 else 2),
       ("typeSurface",kind,surface),
       ("typeSeason",kind,(int(month[5:7])-1)//3),
       ("typeDistance",kind,min(6,int(distance)//400)),
       ("typeOddsVenue",kind,ob,venue),
       ("odds",ob)
    ]

def read_rows():
    chunks=sorted(SOURCE.glob("bin-*.ts"))
    if len(chunks)!=9:raise RuntimeError("FROZEN_PUBLIC_HISTORY_NOT_COMPLETE")
    zipped=""
    for path in chunks:
        s=path.read_text(encoding="utf-8").strip()
        if not(s.startswith("export default ") and s.endswith(";")):
            raise RuntimeError(f"BAD_ARCHIVE_CHUNK:{path}")
        zipped+=json.loads(s[len("export default "):-1])
    decoded=json.loads(gzip.decompress(base64.b64decode(zipped)))
    if len(decoded["races"])!=34566:
        raise RuntimeError("ARCHIVE_RACE_COUNT_NOT_34566")
    return decoded["races"]

def main():
    months=defaultdict(lambda:{"global":[0,0.,0.,0],"keys":defaultdict(lambda:[0,0.,0.,0])})
    races=0;tickets=0;min_date="9999-99-99";max_date=""
    for record in read_rows():
        rid,date,venue,no,name,start,surface,distance,bets=record
        if not bets:continue
        races+=1
        min_date=min(min_date,date);max_date=max(max_date,date)
        if len(bets)!=2 or len({x[0] for x in bets})!=2:
            raise RuntimeError("ORIGINAL_TWO_DIFFERENT_MARKETS_NOT_FOUND")
        month=date[:7]
        for bet in bets:
            kind,comb,odd,return_yen=bet
            if kind not in MARKETS or float(odd)<=0 or int(return_yen)<0:
                raise RuntimeError("UNEXPECTED_ORIGINAL_BET")
            paid=float(return_yen)/1000
            hit=int(return_yen>0)
            item=months[month]
            global_total=item["global"]
            global_total[0]+=1
            global_total[1]+=min(paid,40)
            global_total[2]+=min(paid,80)
            global_total[3]+=hit
            for key in cash_keys(kind,float(odd),venue,int(no),surface,month,int(distance or 0)):
                k=json.dumps(key,ensure_ascii=False,separators=(",",":"))
                value=item["keys"][k]
                value[0]+=1;value[1]+=min(paid,40);value[2]+=min(paid,80);value[3]+=hit
            tickets+=1
    if races!=14410 or tickets!=28820 or max_date!="2026-08-09":
        raise RuntimeError(f"FROZEN_CASH_SOURCE_NOT_EXPECTED:{races}:{tickets}:{min_date}:{max_date}")
    result={"version":"original-archive-2016-2026-research-cash-priors-v1",
            "frozenOriginalHorseModel":True,
            "originalFinalOddsNotVerifiedAtTMinus15":True,
            "sourceLastDate":max_date,
            "sourceFirstDate":min_date,
            "raceCount":races,"ticketCount":tickets,
            "monthly":{
               m:{"global":entry["global"],
                  "keys":dict(sorted(entry["keys"].items()))}
               for m,entry in sorted(months.items())
            }}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    if len(result["monthly"])!=121:
        raise RuntimeError("ORIGINAL_MONTHLY_AGGREGATION_COVERAGE_INCOMPLETE")
    print("THREE_MODEL_INITIAL_ARCHIVED_PRIORS",json.dumps({
        "months":len(result["monthly"]),
        "races":races,"tickets":tickets,"sourceLastDate":max_date,
        "jsonBytes":OUT.stat().st_size
    },ensure_ascii=False),flush=True)

def selftest():
    keys=cash_keys("ワイド",12.1,"東京",4,"芝","2026-11",1600)
    assert len(keys)==9
    assert keys[1]==("typeOdds","ワイド",5),keys
    assert keys[3]==("typeRace","ワイド",0)
    assert keys[5]==("typeSeason","ワイド",3)
    print("THREE_MODEL_ARCHIVED_CASH_PRIOR_SELFTEST_OK",flush=True)

if __name__=="__main__":
    if "--self-test" in sys.argv:selftest()
    else:main()
