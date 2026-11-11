#!/usr/bin/env python3
"""Broad coverage cash-first two-market walk-forward: base hits + payout overlay.
Historical settled 100JPY payouts are NOT JRA independently verified.
All selection statistics are prior-year only; no T-15 odds are available.
"""
from __future__ import annotations
import importlib.util,sys,json,csv,gzip,math
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-broad-base-overlay-walkforward.json"
BETS=ROOT/"analysis-results/nov2026-broad-base-overlay-bets.csv.gz"
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
BOUNDS=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
def source():
    p=ROOT/"scripts/research-nov2026-seasonal-ensemble-cash-first.py"
    spec=importlib.util.spec_from_file_location("seasonal_broad_source",p)
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
    return m
def summary(bets):
    stake=sum(x["stakeYen"] for x in bets)
    paid=sum(x["paidYen"] for x in bets)
    maximum=max((x["paidYen"] for x in bets),default=0)
    # Conservative max-race payout deletion: keep its stake in denominator.
    return dict(races=len(bets),tickets=2*len(bets),stakeYen=stake,paidYen=paid,
        profitYen=paid-stake,roiPct=round(100*paid/stake,4) if stake else None,
        minusMaxRaceRoiPct=round(100*(paid-maximum)/stake,4) if stake else None,
        maxRacePaidYen=maximum,hitRaces=sum(x["paidYen"]>0 for x in bets))
def choose_policy(cash,races,year,quarter,cat):
    # All six market ticket positions are genuine enumerated purchasable tickets.
    # Each market has a BASE position ranked by historical hit frequency and an
    # OVERLAY position ranked by historical max-payout-excluded cash return.
    # Venue, quarter, and field-size are pre-race regime keys.
    n=len(races)
    field=cat["fieldSize"].reshape(n,336)[:,0].astype(int)
    venues=[r["venue"] for r in races]
    decisions=[]
    diagnostics={}
    for target in (2023,2024,2025,2026):
        training=np.flatnonzero((year>=2017)&(year<target))
        testing=np.flatnonzero(year==target)
        if not len(training) or not len(testing):continue
        money=cash.reshape(n,336)
        # Regime-specific samples and global fallback; all training only.
        keys=[(venues[i],int(quarter[i]),int(field[i])) for i in range(n)]
        groups=defaultdict(list)
        for i in training:groups[keys[i]].append(int(i))
        global_idx=training
        cache={}
        def options(indices):
            values=money[np.asarray(indices,dtype=int)]
            count=len(values)
            # Aggregated cash and hit counts per actual market and ticket position.
            hits=np.count_nonzero(values>0,axis=0)
            paid=values.sum(axis=0,dtype=np.int64)
            maxpaid=values.max(axis=0)
            robust=(paid-maxpaid)/(100*count)
            hitrate=hits/count
            options=[]
            for market,(lo,hi) in enumerate(BOUNDS):
                base=int(lo+np.argmax(hitrate[lo:hi]))
                overlay=int(lo+np.argmax(robust[lo:hi]))
                options.append(dict(market=market,base=base,overlay=overlay,
                    baseHit=float(hitrate[base]),overlayRobust=float(robust[overlay]),
                    baseRobust=float(robust[base]),support=count))
            return options
        global_options=options(global_idx)
        for key,idx in groups.items():
            if len(idx)>=40:cache[key]=options(idx)
        candidates=[]
        for i in testing:
            i=int(i)
            opts=cache.get(keys[i],global_options)
            # A base-market ticket is always selected, followed by an overlay
            # from a DIFFERENT market. Both are selected from historical cash only.
            base=max(opts,key=lambda x:(x["baseHit"],x["baseRobust"],-x["market"]))
            overlay=max((o for o in opts if o["market"]!=base["market"]),
                        key=lambda x:(x["overlayRobust"],x["baseHit"],-x["market"]))
            first=i*336
            p1,p2=base["base"],overlay["overlay"]
            candidates.append(dict(raceId=races[i]["id"],day=races[i]["day"],
                venue=venues[i],year=target,quarter=int(quarter[i]),
                stakeYen=200,paidYen=int(cash[first+p1])+int(cash[first+p2]),
                baseMarket=MARKETS[base["market"]],overlayMarket=MARKETS[overlay["market"]],
                baseTicketIndex=p1,overlayTicketIndex=p2,
                trainingSupport=min(base["support"],overlay["support"]),
                preRacePriority=round(base["baseHit"]+max(0.,overlay["overlayRobust"])*0.02,8)))
        byday=defaultdict(list)
        for x in candidates:byday[(x["day"],x["venue"])].append(x)
        selected=[]
        for key,rows in byday.items():
            rows.sort(key=lambda x:(-x["preRacePriority"],str(x["raceId"])))
            selected.extend(rows[:5])
        if any(x["baseMarket"]==x["overlayMarket"] for x in selected):
            raise RuntimeError("DUPLICATE_MARKET")
        diagnostics[str(target)]=dict(trainingRaces=len(training),testRaces=len(testing),
            venueDays=len(byday),daysWith3=sum(len(v)>=3 for v in byday.values()),
            daysWith5=sum(len(v)>=5 for v in byday.values()),
            selectedVenueDaysWith5=sum(len(v)>=5 for v in byday.values()),
            trainingRegimes=len(cache),globalFallbackRaces=sum(keys[int(i)] not in cache for i in testing))
        decisions.extend(selected)
    return decisions,diagnostics
def main():
    if "--self-test" in sys.argv:
        x=[dict(stakeYen=200,paidYen=500),dict(stakeYen=200,paidYen=100)]
        assert summary(x)["minusMaxRaceRoiPct"]==25.0
        print("BROAD_CASH_SELF_TEST_OK");return
    m=source()
    races,cash,cat,widths,types,rid,year,quarter,joint=m.obtain_rows()
    if len(cash)!=336*len(races):raise RuntimeError("CASH_TICKET_DIMENSION")
    if np.any(cash<0):raise RuntimeError("NEGATIVE_PAYOUT")
    decisions,coverage=choose_policy(cash,races,year,quarter,cat)
    yearly={str(y):summary([x for x in decisions if x["year"]==y]) for y in (2023,2024,2025,2026)}
    quarters={str(y):{str(q):summary([x for x in decisions if x["year"]==y and x["quarter"]==q])
                        for q in range(1,5)} for y in (2023,2024,2025,2026)}
    combined=summary(decisions)
    passed=(combined["minusMaxRaceRoiPct"] is not None and combined["minusMaxRaceRoiPct"]>=200
            and all(yearly[str(y)]["minusMaxRaceRoiPct"] is not None
                    and yearly[str(y)]["minusMaxRaceRoiPct"]>=200 for y in (2023,2024,2025,2026))
            and all(v["daysWith3"]==v["venueDays"] for v in coverage.values()))
    report=dict(researchOnly=True,adoptable=False,passesHistoricalCashAndCoverage=passed,
        officialT15Verified=False,officialJraPayoutReconciled=False,
        knownPriorResearchExposure2025And2026=True,trainUsesOnlyEarlierYears=True,
        baselinePlusDifferentMarketOverlay=True,allSixMarketsEnumerated=True,
        year=yearly,quarters=quarters,combined=combined,coverage=coverage,
        candidateRaces=len(races),candidateTickets=len(cash))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    with gzip.open(BETS,"wt",encoding="utf8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(decisions[0]) if decisions else ["raceId"])
        writer.writeheader();writer.writerows(decisions)
    print("BROAD_BASE_OVERLAY_CASH_RESULT",json.dumps(report,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
