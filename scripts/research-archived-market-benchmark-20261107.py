#!/usr/bin/env python3
"""Research-only archived market favorite baseline. NO pre-T15 claim, NO ROI.

These archived runner win odds have no independently validated capture timestamp.
This is a retrospective benchmark against a market, NOT a deployable strategy
or a causal prediction accessible at T-15. Never use results to retune the
already-once-opened 2026 model holdout.
"""
from __future__ import annotations
import collections
import gzip
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
D=ROOT/"data/ten-year-runners"
GROUPS={"2024":("2024-01-01","2025-01-01"),
        "2025":("2025-01-01","2026-01-01"),
        "2026":("2026-01-01","2026-08-10")}

def analyze():
    manifest=json.loads((D/"manifest.json").read_text(encoding="utf-8"))
    assert manifest["races"]==34566
    out={y:{"raceCount":0,"favoriteHits":0,"logLossSum":0.0,
            "missingMarketRaces":0,"invalidWinnerRaces":0}
         for y in GROUPS}
    for month in sorted(manifest["months"]):
        if month[:4] not in GROUPS:continue
        with gzip.open(D/(month+".json.gz"),"rt",encoding="utf-8") as f:
            races=json.load(f)
        for rid,raw in races:
            date=rid[:10]
            key=next((k for k,(a,b) in GROUPS.items() if a<=date<b),None)
            if key is None:continue
            acc=out[key]
            active=[r for r in raw if r[14] in (None,"","active")]
            winners=[r for r in active if r[11]==1]
            if len(active)<3 or len(winners)!=1:
                acc["invalidWinnerRaces"]+=1;continue
            parsed=[]
            for row in active:
                try:
                    odds=float(row[10])
                except (ValueError,TypeError):
                    parsed=[];break
                if not math.isfinite(odds) or odds<=1.0:
                    parsed=[];break
                parsed.append((int(row[0]),odds))
            if len(parsed)!=len(active):
                acc["missingMarketRaces"]+=1;continue
            total=sum(1./o for _,o in parsed)
            weights={h:(1./o)/total for h,o in parsed}
            winner=int(winners[0][0])
            favorite=min(parsed,key=lambda x:(x[1],x[0]))[0]
            acc["raceCount"]+=1
            acc["favoriteHits"]+=int(favorite==winner)
            acc["logLossSum"]+=-math.log(max(1e-12,weights[winner]))
    return {key:{
        "raceCount":val["raceCount"],
        "archivedMarketTopFavoriteWinPct":round(100*val["favoriteHits"]/val["raceCount"],3) if val["raceCount"] else None,
        "archivedMarketWinnerLogLoss":round(val["logLossSum"]/val["raceCount"],7) if val["raceCount"] else None,
        "missingMarketRaces":val["missingMarketRaces"],
        "invalidWinnerRaces":val["invalidWinnerRaces"],
    } for key,val in out.items()}

if __name__=="__main__":
    result={"status":"research_noncausal_baseline",
        "oddsSource":"archived winOdds; independently validated pre-T15 timestamp unavailable",
        "notSameAsLiveT15":True,
        "forbiddenUse":"do not deploy, market odds not independently T15",
        "comparisonLimitation":"sample parity with 56-feature model must be checked; winner/bodweight context differ",
        "years":analyze(),"promotionEligible":False}
    print("ARCHIVED_MARKET_NONCAUSAL_BASELINE",json.dumps(result,ensure_ascii=False))
