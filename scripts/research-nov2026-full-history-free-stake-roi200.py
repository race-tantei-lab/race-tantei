#!/usr/bin/env python3
"""Whole-period ONLY cash200 discovery, no fixed 2,000-yen stake and NO hit gate.

Research-only historical optimisation, not an out-of-sample model:
- Every available 2015-01..2026-04 payout month is used TOGETHER.
- The entire cash-return objective is total cash paid / total yen invested.
- Only actual cash ROI>=200% AND ROI after ONE largest race excluded >=200%
  enters the candidate results; no "failed candidate" records.
- Per-race stake, 1 or 2 markets, stake split, slate (>=3 separate races
  per venue-date) and venue-quarter switches are searchable decisions.
- Each ticket stake is a multiple of 100 yen as JRA allows; NO other
  per-race stake floor and NO hit-rate gate.
- This searches a finite real-money stake grid; it does not prove a global
  maximum over all conceivable staking methods. Historical final odds
  are NOT official JRA T-15 and payout mirror is not JRA-reconciled.
"""
from __future__ import annotations
import collections, csv, gzip, importlib.util, json, sys, time
from pathlib import Path
import numpy as np

R=Path(__file__).resolve().parents[1]
OUT=R/"analysis-results/nov2026-full-cash-free-stake-roi200-only.json"
BETS=R/"analysis-results/nov2026-full-cash-free-stake-roi200-bets.csv.gz"
SRC=R/"scripts/research-nov2026-whole-period-only-roi200.py"
SLATES=(3,4,5,6,8,10,12)
AMOUNTS_ONE=(100,200,500,1000,3000,10000,20000)
AMOUNTS_TWO=(200,400,1000,3000,10000,20000)
SHARES_TWO=(.1,.5,.9)
def helper():
    sp=importlib.util.spec_from_file_location("whole_roi200_cash_ref",SRC)
    m=importlib.util.module_from_spec(sp);sys.modules[sp.name]=m
    sp.loader.exec_module(m);return m
def stakes(one_market):
    if one_market:
      return [(a,0) for a in AMOUNTS_ONE]
    return sorted(set((int(round(a*p/100))*100,a-int(round(a*p/100))*100)
       for a in AMOUNTS_TWO for p in SHARES_TWO
       if 100<=int(round(a*p/100))*100<a))
def proposals(base):
    for pair in base.SETTINGS["pairs"]:
      for slate in SLATES:
        for order in base.SETTINGS["selection"]:
          yield (f"{str(pair)}|{slate}|{order}",(pair,slate,order))
def money(cells):
    if not cells:return None
    paid=sum(int(z["paidYen"]) for z in cells)
    spend=sum(int(z["stakeYen"]) for z in cells)
    race_count=sum(int(z["races"]) for z in cells)
    days=sum(int(z["venueDays"]) for z in cells)
    maximum=max(int(z["maxRacePayoutYen"]) for z in cells)
    if days<=0 or spend<100*race_count or race_count<3*days:
        raise RuntimeError("INVALID_REAL_CASH_COVERAGE")
    return {"races":race_count,"venueDays":days,
       "stakeYen":spend,"paidYen":paid,"profitYen":paid-spend,
       "maxRacePayoutYen":maximum,
       "cashRoiPct":round(100*paid/spend,4),
       "minusLargestRaceCashRoiPct":round(100*(paid-maximum)/spend,4)}
def qualifies(v):
    return v is not None and 100*v["paidYen"]>=200*v["stakeYen"] and (
        100*(v["paidYen"]-v["maxRacePayoutYen"])>=200*v["stakeYen"])
def solve(options,cells,timeout):
    from scipy.optimize import Bounds,LinearConstraint,milp
    from scipy.sparse import coo_matrix
    n=sum(len(options[c]) for c in cells)
    offsets=[];loc=0
    for c in cells:
      offsets.append(loc)
      loc+=len(options[c])
    if n!=loc:raise RuntimeError("BAD_OPTIMIZATION_INDEX")
    # 1 binary per real-money stake/ticket/venue-quarter option.
    # Plus ONE scalar for largest race payout over all selected bets.
    objective=np.empty(n+1,dtype=np.float64)
    lb=np.zeros(n+1,dtype=np.float64)
    ub=np.ones(n+1,dtype=np.float64)
    ub[-1]=10000
    integrality=np.ones(n+1,dtype=np.int8)
    integrality[-1]=0
    scale=100000.
    idx=[];col=[];val=[]
    for i,cell in enumerate(cells):
      for j,z in enumerate(options[cell]):
        k=offsets[i]+j
        surplus=(z["paidYen"]-2*z["stakeYen"])/scale
        big=z["maxRacePayoutYen"]/scale
        objective[k]=-surplus
        idx.extend((i,len(cells),len(cells)+1+i))
        col.extend((k,k,k))
        val.extend((1.,surplus,big))
    idx.extend([len(cells)]+[len(cells)+1+i for i in range(len(cells))])
    col.extend([n]*(1+len(cells)))
    val.extend([-1.]*(1+len(cells)))
    objective[-1]=1.
    lower=np.full(2*len(cells)+1,-np.inf)
    upper=np.full(2*len(cells)+1,np.inf)
    lower[:len(cells)]=1.;upper[:len(cells)]=1.
    lower[len(cells)]=0.
    upper[len(cells)+1:]=0.
    A=coo_matrix((val,(idx,col)),shape=(2*len(cells)+1,n+1)).tocsr()
    print("FREE_STAKE_MONEY_ONLY_SOLVER_START",json.dumps({
      "moneyOptions":n,"venueQuarterCells":len(cells),
      "minRacesPerVenueDay":3,"oneMarketAllowed":True,
      "noHitRateThreshold":True,"noFixedStakeYen":True}),flush=True)
    res=milp(objective,integrality=integrality,bounds=Bounds(lb,ub),
        constraints=LinearConstraint(A,lower,upper),
        options={"time_limit":timeout,"mip_rel_gap":.004})
    info={"solverStatus":int(res.status),"solverMessage":str(res.message),
      "moneyOptions":n}
    if res.x is None:return None,info
    chosen={}
    for i,cell in enumerate(cells):
      vals=res.x[offsets[i]:offsets[i]+len(options[cell])]
      j=int(np.argmax(vals))
      if vals[j]<.999:return None,{**info,"fractionalSolution":True}
      chosen[cell]=options[cell][j]
    summary=money(list(chosen.values()))
    if not qualifies(summary):
      return None,{**info,"cash200ExactCheckFailed":True}
    return chosen,{**info,"fullPeriodCash":summary}
def main():
    full=helper();base=full.load()
    if "--self-test" in sys.argv:
      assert 2000 in AMOUNTS_ONE and 2000 not in AMOUNTS_TWO or len(AMOUNTS_TWO)>1
      assert all(a>=100 and a%100==0 and b%100==0 for a,b in stakes(False))
      assert all(b==0 for a,b in stakes(True))
      s=[{"paidYen":1500,"stakeYen":100,"races":1,"venueDays":0,"maxRacePayoutYen":1500}]
      # Whole archive check is applied to at least 3 purchased races/day.
      s=[{"paidYen":6000,"stakeYen":300,"races":3,"venueDays":1,"maxRacePayoutYen":2000}]
      assert qualifies(money(s))
      print("FREE_STAKE_ROI200_ONLY_SELFTEST_OK")
      return
    start=time.monotonic()
    core,races,years,payout,cat,ticket,signal,market,ranks=full.whole_archive_loo_scores(base)
    ix=np.arange(len(races),dtype=np.int32)
    groups=base.choose_day_groups(races,ix)
    daykeys={(r["day"],int(r["venue"])) for r in races}
    if len(groups)!=len(daykeys):raise RuntimeError("MISSING_VENUE_DAY")
    cells_byday=collections.defaultdict(set)
    for r in races:
      k=(int(r["venue"]), (int(r["month"][4:])-1)//3)
      cells_byday[k].add((r["day"],int(r["venue"])))
    cells=sorted(cells_byday)
    if len(cells)<25:raise RuntimeError("VENUE_QUARTER_COVERAGE_MISSING")
    row_map={str(r["id"]):i for i,r in enumerate(races)}
    options={k:[] for k in cells}
    patterns=dict(proposals(base))
    for k,(pair,slate,ranking) in patterns.items():
      # The pre-existing helper is only used for selecting ticket templates
      # and distinct race IDs. Its previous 2,000-yen bet calculation is
      # intentionally DISCARDED in favor of real flexible amounts.
      _,rows=base.decisions(races,ix,payout,ticket,signal,groups,
                            pair,slate,1000,ranking,True)
      grouped=collections.defaultdict(list)
      venue_day=collections.Counter()
      for r in rows:
        a=rid=row_map[str(r["raceId"])]
        b=int(r["ticket1Template"])
        c=int(r["ticket2Template"]) if r["ticket2Template"]!="" else -1
        u1=int(payout[a,b])
        u2=int(payout[a,c]) if c>=0 else 0
        cell=(int(r["venue"]), (int(r["date"][4:6])-1)//3)
        grouped[cell].append((u1,u2))
        venue_day[(r["date"],int(r["venue"]))]+=1
      if len(venue_day)!=len(daykeys) or set(venue_day)!=daykeys or min(venue_day.values())<3:
         raise RuntimeError("MISSING_THREE_DISTINCT_RACES_IN_DAY")
      one=(pair=="one_market")
      for cell in cells:
        values=np.asarray(grouped[cell],dtype=np.int64)
        if len(values)<3*len(cells_byday[cell]):
           raise RuntimeError("VENUE_QUARTER_THREE_RACE_COVERAGE")
        sum1,sum2=values.sum(axis=0)
        for a,b in stakes(one):
           pays=(values[:,0]*(a//100)+values[:,1]*(b//100))
           z={"policy":k,"stake1Yen":a,"stake2Yen":b,
               "races":len(pays),"venueDays":len(cells_byday[cell]),
               "stakeYen":int(len(pays)*(a+b)),"paidYen":int(pays.sum()),
               "maxRacePayoutYen":int(pays.max())}
           options[cell].append(z)
      if (len(patterns)-list(patterns).index(k))%50==0:
        print("FREE_STAKE_MONEY_PATTERNS_SCANNED",json.dumps({
           "done":list(patterns).index(k)+1,"total":len(patterns)}),flush=True)
    trial=0;found=[];seen=set()
    def collect(label,selected):
       nonlocal trial
       trial+=1
       m=money(list(selected.values()))
       if not qualifies(m):return
       identity=tuple(sorted((str(cell),z["policy"],z["stake1Yen"],z["stake2Yen"])
                             for cell,z in selected.items()))
       if identity in seen:return
       seen.add(identity)
       found.append({"method":label,"fullPeriodCash":m,
                     "venueQuarterDecisions":{
                       f"{k[0]}_Q{k[1]+1}":{"policy":z["policy"],
                             "stake1Yen":z["stake1Yen"],"stake2Yen":z["stake2Yen"]}
                       for k,z in selected.items()}})
    # Explicit non-optimizing portfolio alternatives for audit.
    for t in (0.,.2,.5,1.,2.,5.,10.):
      picked={}
      for cell in cells:
        picked[cell]=max(options[cell],key=lambda z:
           (z["paidYen"]-2*z["stakeYen"]-t*z["maxRacePayoutYen"],z["paidYen"]))
      collect("full_archive_cash_greedy_biggest_penalty_"+str(t),picked)
    selected,detail=solve(options,cells,timeout=260)
    if selected is not None:collect("full_archive_exact_money_milp",selected)
    found.sort(key=lambda z:(z["fullPeriodCash"]["minusLargestRaceCashRoiPct"],
          z["fullPeriodCash"]["stakeYen"]),reverse=True)
    report={"status":"FULL_ARCHIVE_ROI200_ONLY_FOUND" if found else "FULL_ARCHIVE_NO_ROI200_PATTERN_YET",
      "cashArchiveYears":list(range(2015,2027)),
      "allHistoricalYearsUsedForSingleObjective":True,
      "candidateDefinition":"ONLY cashROI>=200 and cashROI-with-largest-race-deducted>=200",
      "noOtherPeriodFiltersOrForwardScreen":True,
      "noHitRateThreshold":True,"noFixedYenPerRace":True,
      "minimumRacesPerVenueDate":3,"maximumRacesPerVenueDate":None,
      "possibleOneMarketStakeYen":list(AMOUNTS_ONE),
      "possibleTwoMarketTotalYen":list(AMOUNTS_TWO),
      "twoMarketShareSearch":list(SHARES_TWO),
      "cashTicketStakeUnitYen":100,
      "policyTypes":len(patterns),
      "moneyOptionsPerVenueQuarter":[len(options[c]) for c in cells],
      "totalMoneyOptionsExamined":sum(map(len,options.values())),
      "allVenueDateCoverage":len(daykeys),
      "wholePeriodRacesAvailable":len(races),
      "moneyOnlyOptimizer":detail,
      "searchStrategies":trial,
      "onlyCash200Patterns":len(found),
      "bestCash200Patterns":found[:15],
      "historicalInSampleNotProspectiveProof":True,
      "officialJraT15Verified":False,
      "thirdPartyPayoutJraReconciled":False,
      "productionChanged":False,
      "seconds":round(time.monotonic()-start,2)}
    if found:
      best=found[0]
      selected=best["venueQuarterDecisions"]
      buys=[]
      for cell in cells:
        sk=f"{cell[0]}_Q{cell[1]+1}"
        spec=selected[sk]
        pair,slate,ranking=patterns[spec["policy"]]
        ids=np.asarray([j for j,r in enumerate(races)
           if int(r["venue"])==cell[0] and (int(r["month"][4:])-1)//3==cell[1]],dtype=np.int32)
        group=base.choose_day_groups(races,ids)
        _,rows=base.decisions(races,ids,payout,ticket,signal,group,
            pair,slate,1000,ranking,True)
        for r in rows:
          i=row_map[str(r["raceId"])]
          a=spec["stake1Yen"];b=spec["stake2Yen"]
          cost=a+b
          paid_yen=int(payout[i,int(r["ticket1Template"])])*(a//100)
          if b:
             paid_yen+=int(payout[i,int(r["ticket2Template"])])*(b//100)
          r.update({"stake1Yen":a,"stake2Yen":b,"paidYen":paid_yen,
                    "costYen":cost,"selectedPolicy":spec["policy"]})
          buys.append(r)
      check={}
      check["races"]=len(buys)
      check["stakeYen"]=sum(x["costYen"] for x in buys)
      check["paidYen"]=sum(x["paidYen"] for x in buys)
      check["maxRacePayoutYen"]=max(x["paidYen"] for x in buys)
      for field,value in check.items():
        if value!=best["fullPeriodCash"][field]:raise RuntimeError("LEDGER_CASH_AUDIT_MISMATCH_"+field)
      counts=collections.Counter((r["date"],int(r["venue"])) for r in buys)
      if set(counts)!=daykeys or min(counts.values())<3:
        raise RuntimeError("LEDGER_MISSING_THREE_RACES_AT_VENUE")
      if len(set(r["raceId"] for r in buys))!=len(buys):
        raise RuntimeError("LEDGER_DUPLICATE_RACE")
      BETS.parent.mkdir(parents=True,exist_ok=True)
      with gzip.open(BETS,"wt",encoding="utf8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(buys[0]))
        w.writeheader();w.writerows(sorted(buys,key=lambda z:(z["date"],z["venue"],z["raceNo"])))
      report["topCandidateExactStakeLedger"]=str(BETS.relative_to(R))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("FREE_STAKE_ALL_HISTORY_ROI200_ONLY_FINAL",json.dumps({
        "status":report["status"],"period":"2015-2026Apr",
        "venueDays":len(daykeys),"policyTypes":len(patterns),
        "moneyAlternatives":report["totalMoneyOptionsExamined"],
        "cash200OnlyCount":len(found),
        "top":found[0]["fullPeriodCash"] if found else None,
        "moneySolver":detail,"productionChanged":False,
        "seconds":report["seconds"]},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
