#!/usr/bin/env python3
"""Audit the *cash-label source*, not a prediction model.

A systemic payout parsing or 2026 coverage failure can make every
high-ROI model look unprofitable. This audit measures by year and by
Jan-Apr season: finished races, six-market positive settled ticket rates,
an auditable fixed 100-yen favorite-win ticket, settlement nonnegativity,
and implausible nonzero winner multiplicity per race. No model is promoted.
"""
from __future__ import annotations
import collections
import importlib.util
import json
import sys
import time
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-cash-data-year-integrity.json"
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")


def imported(path,name):
    p=ROOT/path
    s=importlib.util.spec_from_file_location(name,p)
    if s is None or s.loader is None:raise RuntimeError("MISSING_SOURCE:"+str(p))
    m=importlib.util.module_from_spec(s)
    sys.modules[name]=m;s.loader.exec_module(m)
    return m


def audit_slice(races,paid,market,inds):
    if not len(inds):return None
    sl=paid[inds]
    if np.any(sl<0):raise RuntimeError("NEGATIVE_SETTLEMENT_SOURCE")
    f=sl[:,0]
    per_market={}
    for m,name in enumerate(MARKETS):
        cells=np.flatnonzero(market==m)
        on=(sl[:,cells]>0)
        winners=np.count_nonzero(on,axis=1)
        max_nonzero=3 if m==1 else 1
        per_market[name]={
            "nTicketTemplates":int(len(cells)),
            "racesWithAnyWinningRankedTicket":int(np.count_nonzero(winners)),
            "pctRacesWithAnyWinningRankedTicket":round(100*np.count_nonzero(winners)/len(sl),5),
            "racesWithImplausiblyManyWinningTemplates":int(np.count_nonzero(winners>max_nonzero)),
            "positiveTicketEntries":int(np.count_nonzero(on)),
            "sumAllIndexedWinningPayoutsYenPer100":int(np.sum(sl[:,cells],dtype=np.int64)),
        }
    return {
        "races":int(len(inds)),
        "dates":str(races[int(inds[0])]["month"])+".."+str(races[int(inds[-1])]["month"]),
        "favoriteWinStakedYen":int(len(inds)*100),
        "favoriteWinReceivedYen":int(np.sum(f,dtype=np.int64)),
        "favoriteWinPct":round(100*np.sum(f,dtype=np.int64)/(100*len(inds)),5),
        "favoriteWinHitPct":round(100*np.count_nonzero(f)/len(inds),5),
        "allSixMarketPositiveEntries":int(np.count_nonzero(sl)),
        "markets":per_market,
    }


def main():
    if "--self-test" in sys.argv:
        fake=np.array([[220,0,0,0,0,0],[0,500,0,0,0,0]],np.int32)
        rr=[{"month":"202501"},{"month":"202502"}]
        x=audit_slice(rr,fake,np.arange(6,dtype=np.int8),np.array([0,1]))
        assert x["races"]==2
        assert x["favoriteWinStakedYen"]==200
        assert x["favoriteWinReceivedYen"]==220
        assert x["markets"]["単勝"]["racesWithAnyWinningRankedTicket"]==1
        print("PAYOUT_MIRROR_INTEGRITY_SELFTEST_OK",flush=True)
        return
    start=time.monotonic()
    src=imported("scripts/research-20261114-broad-causal-cash-sweep.py","audit_cash_source")
    core,races,payout,cat,market,slots=src.historic_cash()
    if len(races)<30000 or payout.shape!=(len(races),1030):
        raise RuntimeError("HISTORICAL_SOURCE_INCOMPLETE")
    months=np.asarray([r["month"] for r in races])
    snapshots={}
    for year in range(2015,2027):
        idx=np.flatnonzero(np.char.startswith(months,str(year)))
        if len(idx):
            snapshots[str(year)]=audit_slice(races,payout,market,idx)
            print("SETTLEMENT_COVERAGE_YEAR",json.dumps({
                "year":year,"sourceRaces":len(idx),
                "favoriteWinRoiPct":snapshots[str(year)]["favoriteWinPct"],
                "sixMarketPositiveTicketCount":snapshots[str(year)]["allSixMarketPositiveEntries"]
            },ensure_ascii=False),flush=True)
    seasonal={}
    for year in range(2022,2027):
        idx=np.flatnonzero(np.logical_and(
            np.char.startswith(months,str(year)),
            np.asarray([r["month"][4:] in ("01","02","03","04") for r in races])))
        if len(idx):
            seasonal[str(year)]=audit_slice(races,payout,market,idx)
    markers=[]
    if "2025" in seasonal and "2026" in seasonal:
        prev=seasonal["2025"];curr=seasonal["2026"]
        for m in MARKETS:
            r1=prev["markets"][m]["pctRacesWithAnyWinningRankedTicket"]
            r2=curr["markets"][m]["pctRacesWithAnyWinningRankedTicket"]
            if r1 and r2<.5*r1:markers.append("SHARP_WINNING_TICKET_COVERAGE_DROP_2026_"+m)
        if prev["favoriteWinHitPct"]>2*curr["favoriteWinHitPct"]:
            markers.append("FAVORITE_WIN_HIT_RATE_OVER_50_PERCENT_DECLINE")
    report={
        "purpose":"Check whether supposedly losing 2026 models are instead being evaluated on corrupt or differently covered payout labels",
        "totalRaces":len(races),
        "historicalRacesByYear":snapshots,
        "calendarMatchedJanuaryToApril":seasonal,
        "possiblePayoutSourceDataAnomalies":markers,
        "notEvidenceOf200PctModel":True,
        "source":"pinned third-party retrospective payout mirror; not official pre-T15 odds",
        "researchOnly":True,
        "productionModified":False,
        "elapsedSeconds":round(time.monotonic()-start,2),
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("CASH_SOURCE_YEAR_INTEGRITY_FINAL",json.dumps({
        "races":len(races),"seasonal2025":seasonal.get("2025"),
        "seasonal2026":seasonal.get("2026"),
        "possibleAnomalies":markers,"seconds":report["elapsedSeconds"]
    },ensure_ascii=False),flush=True)


if __name__=="__main__":main()
