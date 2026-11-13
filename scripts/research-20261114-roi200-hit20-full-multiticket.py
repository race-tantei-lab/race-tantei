#!/usr/bin/env python3
"""NET-PROFIT-FIRST whole-archive cash ROI200 & hit20 MULTITICKET research.

Every 2015-01..2026-04 archived race is part of the SAME combinatorial cash
objective: NO year split, preselection by a short period, or OOS score gate.
Full-period cash return >=200% after excluding exactly ONE highest paid
RACE with the ORIGINAL TOTAL STAKE unchanged, and hit race rate >=20%;
minimum THREE distinct bought races per JRA venue-date. Only portfolios
meeting all four limits are called candidates.

Per-race stake NOT fixed. Explore exotic tickets (1-2 per race) with
100-yen-unit hedges (favorite win, second/third win, wide favorites and
several mixtures). The same ticket ledger drives both hit/ROI numbers.

Research only. Third-party 2015-2026 Apr payout mirror, historic FINAL WIN
odds, NOT official pre-start T-15 snapshots. In-sample retrospective mining
is not a prospective predictive guarantee.
"""
from __future__ import annotations
import collections,csv,gzip,heapq,importlib.util,json,sys,time
from pathlib import Path
import numpy as np

R=Path(__file__).resolve().parents[1]
OUT=R/"analysis-results/20261114-net-profit-first-roi200-hit20.json"
LED=R/"analysis-results/20261114-net-profit-first-roi200-hit20-ledger.csv.gz"
PARENTPATH=R/"scripts/research-nov2026-full-history-free-stake-roi200.py"
CASH_HIT_TARGET=20.
CASH_ROI_TARGET=200.
# Exotic unit stake is 100 yen, no fixed per-race budget.
STAKE1_UNITS=(1,5,20,100,200)
STAKE2_UNITS=(0,1,10,50)
# Each is an EXACT BUYABLE ticket: top-popularity rank 0/1/2 win,
# wide rank0+1, wide rank0+2, wide rank1+2, all in 100-yen units.
HEDGES={
  "win1":(1,0,0,0,0,0),
  "win1_win2":(1,1,0,0,0,0),
  "win1_wide12":(1,0,0,1,0,0),
  "win2_wide12":(0,1,0,1,0,0),
  "win1_win2_wide12":(1,1,0,1,0,0),
  "win1_win2_win3":(1,1,1,0,0,0),
  "win1_wide13":(1,0,0,0,1,0),
  "win1_wide23":(1,0,0,0,0,1),
  "wide12":(0,0,0,1,0,0),
  "three_wides":(0,0,0,1,1,1),
  "win1_three_wides":(1,0,0,1,1,1),
  "three_wins_three_wides":(1,1,1,1,1,1),
  "none":(0,0,0,0,0,0),
}
HEDGE_INDEX=(0,1,2,10,11,19)
HIT_SHADOW_PRICES=(0,)  # hit >=20% is a HARD CONSTRAINT, never a scored objective
MAX_PENALTIES=(0,1,2)
OBJECTIVES=tuple((penalty,price) for penalty in MAX_PENALTIES for price in HIT_SHADOW_PRICES)
KEEP_PER_OBJECTIVE=36
def imported():
    spec=importlib.util.spec_from_file_location("cash200_previous_module",PARENTPATH)
    m=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=m
    spec.loader.exec_module(m);return m
def metric(rows,venue_day_count):
    spend=sum(z["costYen"] for z in rows)
    paid=sum(z["paidYen"] for z in rows)
    largest=max(z["paidYen"] for z in rows)
    hit=sum(z["paidYen"]>0 for z in rows)
    profitable=sum(z["paidYen"]>z["costYen"] for z in rows)
    nr=len(rows)
    if nr<venue_day_count*3 or spend<nr*100:
      raise RuntimeError("INVALID_THREE_RACES_OR_MINIMUM_BUYABLE_BET")
    return {"races":nr,"venueDays":venue_day_count,"stakeYen":spend,
        "paidYen":paid,"profitYen":paid-spend,
        "maxRacePayoutYen":largest,"hitRaces":hit,
        "profitableRaces":profitable,"profitableRacePct":round(100*profitable/nr,4),
        "cashRoiPct":round(100*paid/spend,4),
        "minusLargestRaceCashRoiPct":round(100*(paid-largest)/spend,4),
        "hitRacePct":round(100*hit/nr,4)}
def qualifies(m):
    return m and m["hitRaces"]*5>=m["races"] and (
       m["paidYen"]-m["maxRacePayoutYen"])>=2*m["stakeYen"]
def choose_mix_options(base,races,paid,chosen,signal):
    groups=base.choose_day_groups(races,np.arange(len(races),dtype=np.int32))
    day_ids={(r["day"],int(r["venue"])) for r in races}
    pattern=dict((name,spec) for name,spec in imported().proposals(base))
    n=len(races)
    idx={str(r["id"]):i for i,r in enumerate(races)}
    cell_days=collections.defaultdict(set)
    for r in races:
        cell_days[(int(r["venue"]),(int(r["month"][4:])-1)//3)].add((r["day"],int(r["venue"])))
    cells=sorted(cell_days)
    buckets={cell:[[] for _ in OBJECTIVES] for cell in cells}
    scan_count=0
    serial=0
    for pidx,(name,(pair,slate,ranking)) in enumerate(pattern.items()):
        # Selection and template may use ONLY runner final odds and
        # whole-archive leave-one-race-out cash signals; not same-race result.
        _,ledger=base.decisions(races,np.arange(n,dtype=np.int32),paid,chosen,
             signal,groups,pair,slate,1000,ranking,True)
        bycell=collections.defaultdict(list)
        byday=collections.Counter()
        for row in ledger:
            c=(int(row["venue"]),(int(row["date"][4:6])-1)//3)
            bycell[c].append((idx[str(row["raceId"])],int(row["ticket1Template"]),
                 int(row["ticket2Template"]) if row["ticket2Template"]!="" else -1))
            byday[(row["date"],int(row["venue"]))]+=1
        if len(byday)!=len(day_ids) or set(byday)!=day_ids or min(byday.values())<3:
            raise RuntimeError("BASE_RACE_SELECTION_NOT_ALL_VENUE_DAYS")
        for cell in cells:
            records=np.asarray(bycell[cell],dtype=np.int32)
            if len(records)<3*len(cell_days[cell]):
                raise RuntimeError("CELL_RACE_SELECTION_MISSING")
            ids=records[:,0]
            p1=paid[ids,records[:,1]].astype(np.int64)
            p2=np.zeros(len(ids),dtype=np.int64)
            ispair=pair!="one_market"
            if ispair:
                p2=paid[ids,records[:,2]].astype(np.int64)
            hedge_paid=paid[ids][:,HEDGE_INDEX].astype(np.int64)
            stake_opts=[(a,b) for a in STAKE1_UNITS
                        for b in (STAKE2_UNITS if ispair else (0,))]
            s1=np.asarray([z[0] for z in stake_opts],dtype=np.int64)
            s2=np.asarray([z[1] for z in stake_opts],dtype=np.int64)
            exotic=p1[:,None]*s1[None,:]+p2[:,None]*s2[None,:]
            for hedge,coefficients in HEDGES.items():
                coeff=np.asarray(coefficients,dtype=np.int64)
                hcost=int(sum(coefficients))
                hedge_cash=hedge_paid@coeff
                returns=exotic+hedge_cash[:,None]
                sum_pay=returns.sum(axis=0,dtype=np.int64)
                max_r=returns.max(axis=0)
                hit=np.count_nonzero(returns,axis=0)
                profitable=np.count_nonzero(returns>((s1+s2+hcost)*100)[None,:],axis=0)
                nrows=len(ids)
                cost=(s1+s2+hcost)*nrows*100
                # Scan ALL offered amounts; below-threshold portfolios are
                # never candidates or "failed candidate" records.
                scan_count+=len(stake_opts)
                # Rank by actual NET CASH profit; hit count never earns synthetic profit.
                net_profit=sum_pay-cost
                for oi,(penalty,bonus) in enumerate(OBJECTIVES):
                    scores=net_profit-penalty*max_r
                    best_ids=np.argsort(-scores,kind="stable")[:3]
                    heap=buckets[cell][oi]
                    for k in best_ids:
                        k=int(k)
                        serial+=1
                        z={"policy":name,"hedge":hedge,"s1":int(s1[k]),
                           "s2":int(s2[k]),"paidYen":int(sum_pay[k]),
                           "stakeYen":int(cost[k]),"maxRacePayoutYen":int(max_r[k]),
                           "hitRaces":int(hit[k]),
                           "profitableRaces":int(profitable[k]),"races":nrows,
                           "venueDays":len(cell_days[cell])}
                        item=(float(scores[k]),serial,z)
                        if len(heap)<KEEP_PER_OBJECTIVE:
                            heapq.heappush(heap,item)
                        elif item>heap[0]:
                            heapq.heapreplace(heap,item)
        if (pidx+1)%70==0 or pidx+1==len(pattern):
            print("HIT20_MULTITICKET_FULL_PERIOD_RULES_SCANNED",
              json.dumps({"rules":pidx+1,"totalRules":len(pattern),
                 "moneyOptionsEvaluated":scan_count,
                 "allHistoricalYears":list(range(2015,2027))}),flush=True)
    options={}
    for cell in cells:
        merged={}
        for h in buckets[cell]:
            for _,_,z in h:
                key=(z["policy"],z["hedge"],z["s1"],z["s2"])
                merged[key]=z
        options[cell]=list(merged.values())
    print("HIT20_FULL_ARCHIVE_MULTI_OPTION_MATRIX",json.dumps({
       "venueQuarterCells":len(cells),"distinctCashRules":len(pattern),
       "hedgeTicketStructures":len(HEDGES),
       "availableMoneyConfigsPerPair":len(STAKE1_UNITS)*len(STAKE2_UNITS),
       "fullArchiveCashVariantsExamined":scan_count,
       "optimizerInputChoices":sum(len(v) for v in options.values()),
       "minVenueDayCoverage":len(day_ids),"minRacesPerVenueDay":3,
       "hitRateFloor":20,"candidateDefinition":"cash200 after max PLUS hit20"}),
       flush=True)
    return pattern,options,cells,cell_days,day_ids,scan_count
def overall(chosen):
    xs=list(chosen.values())
    stake=sum(x["stakeYen"] for x in xs)
    paid=sum(x["paidYen"] for x in xs)
    mx=max(x["maxRacePayoutYen"] for x in xs)
    races=sum(x["races"] for x in xs)
    hits=sum(x["hitRaces"] for x in xs)
    profitable=sum(x["profitableRaces"] for x in xs)
    venue_days=sum(x["venueDays"] for x in xs)
    if races<3*venue_days:raise RuntimeError("VENUE_DAY_MINIMUM_NOT_MET")
    return {"stakeYen":stake,"paidYen":paid,"profitYen":paid-stake,
      "maxRacePayoutYen":mx,"races":races,"hitRaces":hits,
      "profitableRaces":profitable,"profitableRacePct":round(100*profitable/races,4),
      "venueDays":venue_days,"cashRoiPct":round(100*paid/stake,4),
      "minusLargestRaceCashRoiPct":round(100*(paid-mx)/stake,4),
      "hitRacePct":round(100*hits/races,4)}
def milp_solver(options,cells,seconds,weight=0.):
    from scipy.optimize import Bounds,LinearConstraint,milp
    from scipy.sparse import coo_matrix
    starts={}
    total=0
    for cell in cells:
        starts[cell]=total;total+=len(options[cell])
    X=total
    weights=np.zeros(X+1,dtype=np.float64)
    low=np.zeros(X+1,dtype=np.float64)
    high=np.ones(X+1,dtype=np.float64)
    high[-1]=1e6
    integer=np.ones(X+1,dtype=np.int8);integer[-1]=0
    rr=[];cc=[];vv=[];scale=100000.
    ncell=len(cells)
    for i,cell in enumerate(cells):
      for j,z in enumerate(options[cell]):
        k=starts[cell]+j
        premium=(z["paidYen"]-2*z["stakeYen"])/scale
        net=(z["paidYen"]-z["stakeYen"])/scale
        big=z["maxRacePayoutYen"]/scale
        hit=z["hitRaces"]-.2*z["races"]
        rr.extend((i,ncell,ncell+1,ncell+2+i))
        cc.extend((k,k,k,k))
        vv.extend((1.,premium,hit,big))
        # Optimize on actual yen, with optional preference for higher hit.
        weights[k]=-(net)  # maximize ACTUAL yen profit, subject to both cash-ROI and hit floors
    rr.extend([ncell]+[ncell+2+i for i in range(ncell)])
    cc.extend([X]*(ncell+1));vv.extend([-1.]*(ncell+1))
    weights[-1]=1.
    lower=np.full(2*ncell+2,-np.inf)
    upper=np.full(2*ncell+2,np.inf)
    lower[:ncell]=1.;upper[:ncell]=1.
    lower[ncell]=0 # paid -2*all cost - GLOBAL MAX race payout >=0.
    lower[ncell+1]=0 # ALL hit races >= 20 percent purchased races.
    upper[ncell+2:]=0 # max prize selection bound.
    mat=coo_matrix((vv,(rr,cc)),shape=(2*ncell+2,X+1)).tocsr()
    res=milp(weights,integrality=integer,bounds=Bounds(low,high),
         constraints=LinearConstraint(mat,lower,upper),
         options={"time_limit":seconds,"mip_rel_gap":.005})
    info={"status":int(res.status),"success":bool(res.success),
          "message":str(res.message),"binaryMoneyOptions":X,
          "hitShadowValue":weight}
    if res.x is None:return None,info
    chosen={}
    for cell in cells:
        v=res.x[starts[cell]:starts[cell]+len(options[cell])]
        j=int(np.argmax(v))
        if v[j]<.999:return None,{**info,"fractionalAndDiscarded":True}
        chosen[cell]=options[cell][j]
    m=overall(chosen)
    if not qualifies(m):
        return None,{**info,"fullArchiveCashAndHitAuditFailed":m}
    return chosen,{**info,"fullPeriodMetric":m}
def ledger_for_candidate(base,patterns,races,payout,opts,signal,cells,chosen,day_ids):
    idx={str(r["id"]):j for j,r in enumerate(races)}
    ledger=[]
    for cell in cells:
        z=chosen[cell]
        pair,slate,rank=patterns[z["policy"]]
        ii=np.asarray([j for j,r in enumerate(races)
                if int(r["venue"])==cell[0] and
                (int(r["month"][4:])-1)//3==cell[1]],dtype=np.int32)
        groups=base.choose_day_groups(races,ii)
        _,rows=base.decisions(races,ii,payout,opts,signal,groups,
                              pair,slate,1000,rank,True)
        hedge=HEDGES[z["hedge"]]
        for r in rows:
            j=idx[str(r["raceId"])]
            a=int(z["s1"]);b=int(z["s2"])
            e1=int(payout[j,int(r["ticket1Template"])])*a
            e2=int(payout[j,int(r["ticket2Template"])])*b if b else 0
            extras=sum(int(payout[j,k])*w for k,w in zip(HEDGE_INDEX,hedge))
            cash=e1+e2+extras
            ledger.append({"raceId":r["raceId"],"date":r["date"],
                "venue":r["venue"],"raceNo":r["raceNo"],
                "ticket1Template":r["ticket1Template"],
                "ticket2Template":r["ticket2Template"] if b else "",
                "exotic1StakeYen":a*100,"exotic2StakeYen":b*100,
                "hedge":z["hedge"],
                "hedgeStakeYen":sum(hedge)*100,
                "costYen":(a+b+sum(hedge))*100,
                "paidYen":cash,
                "hit":int(cash>0),"profitableHit":int(cash>(a+b+sum(hedge))*100),"rule":z["policy"]})
    if len(set(z["raceId"] for z in ledger))!=len(ledger):
        raise RuntimeError("DUPLICATE_RACE_ID_BET")
    byday=collections.Counter((z["date"],int(z["venue"])) for z in ledger)
    if set(byday)!=day_ids or any(v<3 for v in byday.values()):
        raise RuntimeError("FAILED_THREE_RACES_PER_VENUE_DATE")
    m=metric(ledger,len(byday))
    if not qualifies(m):raise RuntimeError("EXACT_CASH_LEDGER_DOES_NOT_QUALIFY")
    if m["profitableRaces"]!=sum(z["profitableHit"] for z in ledger):
        raise RuntimeError("PROFITABLE_RACE_AUDIT_FAILED")
    return m,ledger
def main():
    if "--self-test" in sys.argv:
        assert HEDGE_INDEX==(0,1,2,10,11,19)
        assert 100 in [100*u for u in STAKE1_UNITS]
        assert len(OBJECTIVES)>=12
        assert qualifies({"races":10,"hitRaces":2,
                          "paidYen":5000,"stakeYen":1000,
                          "maxRacePayoutYen":500})
        assert not qualifies({"races":10,"hitRaces":1,
                          "paidYen":5000,"stakeYen":1000,
                          "maxRacePayoutYen":500})
        assert not qualifies({"races":10,"hitRaces":2,
                          "paidYen":2500,"stakeYen":1000,
                          "maxRacePayoutYen":600})
        print("WHOLE_HISTORY_CASH200_HIT20_SELFTEST_OK",flush=True)
        return
    start=time.monotonic()
    previous=imported();whole=previous.helper();base=whole.load()
    core,races,years,payout,cat,opts,signal,markets,ranks=whole.whole_archive_loo_scores(base)
    if len(races)<30000 or set(map(int,np.unique(years)))!=set(range(2015,2027)):
        raise RuntimeError("NOT_ALL_HISTORICAL_YEARS_AVAILABLE")
    patterns,options,cells,cell_days,days,scans=choose_mix_options(base,races,payout,opts,signal)
    accepted=[]
    seen=set();checks=0
    def add(method,chosen,meta):
        nonlocal checks
        checks+=1
        m=overall(chosen)
        if not qualifies(m):return
        fingerprint=tuple((cell,z["policy"],z["hedge"],z["s1"],z["s2"]) for cell,z in sorted(chosen.items()))
        if fingerprint in seen:return
        seen.add(fingerprint)
        accepted.append({"method":method,"metadata":meta,"fullPeriodMoneyAndHits":m,
           "venueQuarterDecisions":{f"{k[0]}_Q{k[1]+1}":{
               "policy":z["policy"],"hedge":z["hedge"],
               "exotic1StakeYen":z["s1"]*100,"exotic2StakeYen":z["s2"]*100,
               "hedgeStakeYen":sum(HEDGES[z["hedge"]])*100} for k,z in chosen.items()}})
    # Global full-period paired objective candidate discovery.
    for price in HIT_SHADOW_PRICES:
      for penalty in MAX_PENALTIES:
        select={c:max(options[c],key=lambda z:z["paidYen"]-z["stakeYen"]-
                 penalty*z["maxRacePayoutYen"]+
                 0*(z["hitRaces"]-.2*z["races"])) for c in cells}
        add("whole_archive_multi_ticket_greedy",select,
            {"maxRacePenalty":penalty,"perHitCashShadowYen":price})
    solver=[]
    for weight in (0.,):  # no synthetic reward for making hit rate larger
        select,detail=milp_solver(options,cells,seconds=170,weight=weight)
        solver.append(detail)
        if select is not None:
           add("whole_archive_cash200_hit20_milp",select,
               {"solverStatus":detail["status"],
                "fullArchiveAllYearScore":True,
                "hitShadowPreference":weight})
    accepted.sort(key=lambda z:(
           z["fullPeriodMoneyAndHits"]["profitYen"],
           z["fullPeriodMoneyAndHits"]["minusLargestRaceCashRoiPct"]),reverse=True)
    report={"status":"FULL_ARCHIVE_ROI200_HIT20_MULTI_TICKET_FOUND" if accepted else
            "FULL_ARCHIVE_NO_ROI200_HIT20_MULTI_TICKET_FOUND_YET",
        "dateRange":"2015-01 through 2026-04",
        "yearsAllTogether":list(range(2015,2027)),
        "allYearSingleOptimization":True,"anyChronologicalSplit":False,
        "minimumRacesPerVenueDay":3,
        "noFixedBetAmount":True,"priority":"MAXIMIZE ACTUAL NET PROFIT, no hit-rate bonus; hit20 is floor only","ticketsPerRace":"one or two cash-market exotic templates plus selectable extra win/wide hedges",
        "portfolioHitRateMinPct":20,"portfolioCashRoiMinPct":200,
        "largestRaceExcludedCashRoiMinPct":200,
        "ticketCashAccounting":"100 yen-unit payouts multiplied by actual ticket stake; same race-set for hit and ROI",
        "candidateDefinition":"ALL thresholds simultaneously; every reported candidate meets ROI200 after max and hit20",
        "source":"pinned third-party 136 month race payout mirror and final win odds; NOT T15",
        "historicInSampleDiscoveryNotFutureProof":True,
        "productionChanged":False,"historicalRaces":len(races),
        "venueDays":len(days),"venueQuarterCells":len(cells),
        "basePolicies":len(patterns),"hedgeStructures":len(HEDGES),
        "moneyVariationsScanned":scans,"optimizerChoices":sum(map(len,options.values())),
        "searchMixesChecked":checks, "hitRateBonusInOptimization":0,
        "solver":solver,
        "strictlyQualifiedCandidateCount":len(accepted),
        "qualifiedCandidates":accepted[:15],
        "seconds":round(time.monotonic()-start,2)}
    if accepted:
        best=accepted[0]
        selected={}
        for cell in cells:
            d=best["venueQuarterDecisions"][f"{cell[0]}_Q{cell[1]+1}"]
            z=next((z for z in options[cell] if z["policy"]==d["policy"] and z["hedge"]==d["hedge"] and
                100*z["s1"]==d["exotic1StakeYen"] and 100*z["s2"]==d["exotic2StakeYen"]),None)
            if z is None:raise RuntimeError("MISSING_ACTUAL_CASH_BUY_OPTION")
            selected[cell]=z
        m,ledger=ledger_for_candidate(base,patterns,races,payout,opts,signal,cells,selected,days)
        check=best["fullPeriodMoneyAndHits"]
        for key in ("races","venueDays","stakeYen","paidYen","maxRacePayoutYen","hitRaces"):
            if m[key]!=check[key]:
                raise RuntimeError("EXACT_LEDGER_DISAGREES_WITH_MILP_"+key+":"+str((m[key],check[key])))
        LED.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(LED,"wt",newline="",encoding="utf8") as f:
            writer=csv.DictWriter(f,fieldnames=list(ledger[0]))
            writer.writeheader();writer.writerows(sorted(ledger,key=lambda z:(z["date"],z["venue"],z["raceNo"])))
        report["exactCashLedgerPath"]=str(LED.relative_to(R))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("FULL_HISTORY_CASH200_HIT20_FINAL",json.dumps({
        "status":report["status"],
        "allHistoryYears":list(range(2015,2027)),
        "searchOptionsScanned":scans,"optimizerInput":report["optimizerChoices"],
        "qualifyingPortfolioCount":len(accepted),
        "top":accepted[0]["fullPeriodMoneyAndHits"] if accepted else None,
        "solver":solver,"seconds":report["seconds"],
        "productionChanged":False},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
