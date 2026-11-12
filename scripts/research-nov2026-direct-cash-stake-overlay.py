#!/usr/bin/env python3
"""Direct-YEN walk-forward search of differentiated base and overlay stakes.
A separately scored high-hit base ticket is combined with a high-cash payout
ticket of a DISTINCT market, with pre-registered stake allocations.
No evaluation-year cash selects a recipe. No production or D1 mutations.
Historical third-party payout and final odds are not JRA T-15 verified.
"""
from __future__ import annotations
import csv,gzip,importlib.util,json,sys
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-direct-cash-stake-overlay.json"
BETS=ROOT/"analysis-results/nov2026-direct-cash-stake-overlay-bets.csv.gz"
PRIOR=(50,300,1200)
TRIM=(0.,1.)
OVERLAY_YEN=(100,400,1400,4900)
OVERLAY_POOL=((1,2,3,4,5),(2,3,4,5),(0,1,2,3,4,5))
BOUNDS=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))

def prior_module():
    s=importlib.util.spec_from_file_location(
      "hierarchical_cash_source",ROOT/"scripts/research-nov2026-hierarchical-cash-policy.py")
    x=importlib.util.module_from_spec(s);sys.modules[s.name]=x
    s.loader.exec_module(x);return x

def cash_stats(bets):
    stake=sum(x["stakeYen"] for x in bets)
    paid=sum(x["paidYen"] for x in bets)
    biggest=max((x["paidYen"] for x in bets),default=0)
    return {"races":len(bets),"stakeYen":stake,"paidYen":paid,
      "roiPct":round(100*paid/stake,5) if stake else None,
      "minusMaxRaceRoiPct":round(100*(paid-biggest)/stake,5) if stake else None,
      "hitRacePct":round(100*sum(x["paidYen"]>0 for x in bets)/len(bets),5)
        if bets else None,"biggestRaceYen":biggest}

def choose(races,cash,year,quarter,ix,base_signal,overlay_signal,recipe):
    prior,trim,second_stake,pool=recipe
    if second_stake%100!=0 or second_stake<100:raise RuntimeError("BAD_STAKE")
    candidates=defaultdict(list)
    for row,i in enumerate(ix):
        i=int(i)
        base=[]
        # Favor stable cash-paying, frequent-hit base candidates.
        for market in (0,1,2):
            lo,hi=BOUNDS[market]
            j=lo+int(np.argmax(base_signal[row,lo:hi]))
            base.append((float(base_signal[row,j]),market,j))
        first=max(base,key=lambda z:(z[0],-z[1]))
        # The direct payout overlay can choose ANY of six markets excluding
        # the base market; this is not a fixed historical regime-pair.
        overlays=[]
        for market in pool:
            if market==first[1]:continue
            lo,hi=BOUNDS[market]
            j=lo+int(np.argmax(overlay_signal[row,lo:hi]))
            overlays.append((float(overlay_signal[row,j]),market,j))
        if not overlays:raise RuntimeError("OVERLAY_MARKET_MISSING")
        second=max(overlays,key=lambda z:(z[0],-z[1]))
        total=100+second_stake
        p=int(cash[i,first[2]]+cash[i,second[2]]*(second_stake//100))
        candidates[(str(races[i]["day"]),str(races[i]["venue"]))].append({
          "raceId":str(races[i]["id"]),"day":str(races[i]["day"]),
          "venue":str(races[i]["venue"]),"year":int(year[i]),
          "quarter":int(quarter[i]),"baseMarket":first[1],
          "baseTicket":first[2],"baseYen":100,
          "overlayMarket":second[1],"overlayTicket":second[2],
          "overlayYen":second_stake,"stakeYen":total,"paidYen":p,
          "priorityCash":round(second[0]+0.05*first[0],8)})
    result=[];freq=Counter()
    for group in candidates.values():
        chosen=sorted(group,key=lambda x:(-x["priorityCash"],x["raceId"]))[:5]
        result.extend(chosen);freq[len(chosen)]+=1
    if any(x["baseMarket"]==x["overlayMarket"] for x in result):
        raise RuntimeError("DUPLICATE_MARKET")
    if len({x["raceId"] for x in result})!=len(result):
        raise RuntimeError("DUPLICATE_RACE")
    return result,{"observedVenueDays":len(candidates),
      "selected3to5":sum(n for k,n in freq.items() if k>=3),
      "selected5":freq[5],"under3":sum(n for k,n in freq.items() if k<3)}

def main():
    if "--self-test" in sys.argv:
        assert cash_stats([{"stakeYen":100,"paidYen":300},
                           {"stakeYen":100,"paidYen":100}])["minusMaxRaceRoiPct"]==50.
        assert all(a>=100 and a%100==0 for a in OVERLAY_YEN)
        print("DIRECT_CASH_STAKE_OVERLAY_SELFTEST_OK",flush=True);return
    m=prior_module()
    races,paid,cat,widths,types,_,year,quarter,_=m.load()
    n=len(races)
    cash=paid.reshape(n,336)
    if n<16000 or len(paid)!=336*n:raise RuntimeError("BROKEN_FINANCIAL_UNIVERSE")
    code=m.make_codes(n,types,cat,widths)
    recipes=[(p,t,s,q) for p in PRIOR for t in TRIM
             for s in OVERLAY_YEN for q in OVERLAY_POOL]
    valid={}
    for yy in (2021,2022):
        train=np.flatnonzero((year>=2017)&(year<yy))
        test=np.flatnonzero(year==yy)
        groups=m.train_cohorts(cash,types,code,train)
        # Hit-aware baseline trained on previous years, payout-aware overlays
        # are separately estimated in yen rather than from horse winner labels.
        stable=m.scores_for(groups,code,types,test,1200,1.0,8.0)
        states={}
        for p in PRIOR:
            for t in TRIM:
                signal=m.scores_for(groups,code,types,test,p,t,0.)
                for s in OVERLAY_YEN:
                    for q in OVERLAY_POOL:
                        recipe=(p,t,s,q)
                        bets,cov=choose(races,cash,year,quarter,test,stable,signal,recipe)
                        states[str(recipe)]=(cash_stats(bets),cov)
        valid[yy]=states
        print("CASH_STAKE_PRE2023_VALIDATION",yy,len(states),flush=True)
    def rank(recipe):
        a=valid[2021][str(recipe)][0];b=valid[2022][str(recipe)][0]
        if a["races"]<100 or b["races"]<100:return (-1e6,-1e6)
        floor=min(a["minusMaxRaceRoiPct"],b["minusMaxRaceRoiPct"])
        # Penalize recipes that cannot generate a 20%-hit portfolio.
        if min(a["hitRacePct"],b["hitRacePct"])<20.0:floor-=100.
        robust=100*(a["paidYen"]-a["biggestRaceYen"]+
                    b["paidYen"]-b["biggestRaceYen"])/(a["stakeYen"]+b["stakeYen"])
        return floor,robust
    chosen=max(recipes,key=lambda rec:(rank(rec),-recipes.index(rec)))
    print("DIRECT_CASH_STAKE_PRE2023_WINNER",chosen,rank(chosen),flush=True)
    periods={};cover={};all_bets=[]
    for yy in (2023,2024,2025,2026):
        train=np.flatnonzero((year>=2017)&(year<yy))
        test=np.flatnonzero(year==yy)
        obj=m.train_cohorts(cash,types,code,train)
        stable=m.scores_for(obj,code,types,test,1200,1.0,8.0)
        overlay=m.scores_for(obj,code,types,test,chosen[0],chosen[1],0.)
        picks,cov=choose(races,cash,year,quarter,test,stable,overlay,chosen)
        periods[str(yy)]=cash_stats(picks);cover[str(yy)]=cov;all_bets.extend(picks)
        print("DIRECT_CASH_STAKE_YEAR",yy,periods[str(yy)],flush=True)
    totals=cash_stats(all_bets)
    gate=(totals["minusMaxRaceRoiPct"] is not None and
          totals["minusMaxRaceRoiPct"]>=200 and totals["hitRacePct"]>=20 and
          all(periods[str(yy)]["minusMaxRaceRoiPct"]>=200 for yy in
              (2023,2024,2025,2026)) and
          all(v["under3"]==0 for v in cover.values()))
    report={"researchOnly":True,"qualifyingCashPatternFound":bool(gate),
      "adoptable":False,
      "evaluationNoFutureCashForSelection":True,
      "selectionBefore2023Years":[2021,2022],
      "candidateRecipes":len(recipes),
      "selected":{"overlayPrior":chosen[0],"largestReturnRemovedFraction":chosen[1],
         "baseStakeYen":100,"overlayStakeYen":chosen[2],
         "eligibleOverlayMarkets":list(chosen[3])},
      "trainingOnlyCheck":{str(y):valid[y][str(chosen)] for y in (2021,2022)},
      "years":periods,"combined":totals,"coverage":cover,
      "thirdPartySettlementNotIndependentlyVerified":True,
      "historicalFinalWinOddsNotOfficialT15":True,
      "2025And2026PreviouslyExamined":True,"officialVenueDayCoverageVerified":False,
      "mainD1WorkersUnchanged":True}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    with gzip.open(BETS,"wt",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(all_bets[0]));w.writeheader();w.writerows(all_bets)
    print("DIRECT_CASH_STAKE_OVERLAY_FINAL",json.dumps(report,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
