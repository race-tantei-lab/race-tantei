#!/usr/bin/env python3
"""Optimize an entire 136-month portfolio jointly, not one condition = one model.

All six JRA bet types, 1030 actual ticket positions per race, 24,120
causally predicted base betting policies. Each venue x quarter may choose
its own policy; the GLOBAL calendar-wide joint policy must hit cash ROI>=200%,
ROI>=200% even with the single highest paid race removed, >=20% paid-hit
races, and >=3 independent bought races every venue-day.

The sub-200 intermediate policies are mathematical inputs, NEVER models.
Candidate objects are constructed only when the complete joint cash ledger
passes every condition. Objective: maximize REAL net yen, no fictitious hit
rate rewards. This uses all years for portfolio selection and can therefore
overfit despite causal race-level predictions; adoption requires independent
Aug-Nov holdout verification and official T-15 odds, not available here.

Research only; never modify main, D1, production, or historical entries.
"""
from __future__ import annotations
import collections, csv, gzip, heapq, importlib.util, json, time, sys, math
from pathlib import Path
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-136month-joint-venue-quarter-roi200-hit20.json"
LED=ROOT/"analysis-results/20261114-136month-joint-venue-quarter-roi200-hit20-ledger.csv.gz"
KEEP=18
HIT_SHADOW=(0.,500.,2500.,10000.,50000.,250000.)
MAXPEN=(0.,.75,1.5)
COST_MODES=(1.,2.)
OBJECTIVES=tuple((h,j,c) for h in HIT_SHADOW for j in MAXPEN for c in COST_MODES)
MIP_TIMEOUT=160
def imported(path,name):
    p=ROOT/path
    s=importlib.util.spec_from_file_location(name,p)
    if s is None or s.loader is None:raise RuntimeError("MISSING_DEPENDENCY:"+str(p))
    m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m)
    return m
def all_cells(races):
    groups=collections.defaultdict(set)
    for row in races:
      k=int(row["venue"])*4+(int(row["month"][4:])-1)//3
      groups[k].add((row["day"],int(row["venue"])))
    return {k:len(v) for k,v in groups.items()}
def build_options(base,races,paid,picked,score):
    venuequarter=all_cells(races)
    known=set(venuequarter)
    grouped={k:[[] for _ in OBJECTIVES] for k in venuequarter}
    serial=0
    scanned=0
    for v,method in enumerate(base.MODES):
      for mask,markets in base.MASKS.items():
        for sel in base.SELECT_MODES:
          ranking="top_margin" if sel=="top_margin" else "top_score"
          selection="top_score_plus_positive" if sel=="top_score_plus_positive" else "top_score"
          for slate in base.SLATES:
            for stake in base.STAKEPLANS:
              if stake.startswith("pair") and len(markets)<2:continue
              m,cell=base.policy_arrays(races,paid,picked[:,v],score[:,v],
                  markets,stake,slate,ranking,selection,cellbreakdown=True)
              if m is None:continue
              scanned+=1
              if not cell or set(cell)!=known:raise RuntimeError("INCOMPLETE_QUARTER_CELL_SET")
              policy={"forecast":method,"marketSubset":mask,
                "raceSlate":slate,"stakePlan":stake,"selection":sel}
              for k,z in cell.items():
                if z["races"]<3*venuequarter[k]:
                    raise RuntimeError("QUARTER_CELL_HAS_BELOW_3_PER_VENUE_DAY")
                stake_yen=z["stakeYen"];paid_yen=z["paidYen"]
                maxpay=z["maxRacePayoutYen"];hit=z["hitRaces"]
                riskless_hit=hit-.2*z["races"]
                for oi,(bonus,penalty,costfactor) in enumerate(OBJECTIVES):
                  # This is a LOCAL numeric search score, never a model,
                  # threshold qualification, or amount of synthetic profit.
                  rank=(paid_yen-costfactor*stake_yen
                        -penalty*maxpay+bonus*riskless_hit)
                  heap=grouped[k][oi]
                  if len(heap)==KEEP and rank<=heap[0][0]:continue
                  serial+=1
                  payload={"policy":policy,"cell":k,**z,"venueDays":venuequarter[k]}
                  item=(float(rank),serial,payload)
                  if len(heap)<KEEP:heapq.heappush(heap,item)
                  else:heapq.heapreplace(heap,item)
      print("WHOLE_HISTORICAL_GLOBAL_MIX_FORECAST_FAMILY_SCANNED",json.dumps({
          "forecast":method,"baseCashCalculations":scanned,
          "venueQuarterGroups":len(grouped)}),flush=True)
    options={}
    for k in sorted(grouped):
      uniq={}
      for heap in grouped[k]:
        for _,_,z in heap:
          p=z["policy"]
          sig=tuple(p.values())
          uniq[sig]=z
      options[k]=list(uniq.values())
    count=sum(map(len,options.values()))
    print("WHOLE_PERIOD_JOINT_CASH_MILP_INPUT",json.dumps({
      "baseCashCalculations":scanned,"venueQuarterGroups":len(options),
      "localObjectiveWeights":len(OBJECTIVES),"inputJointChoices":count,
      "minimumRacesPerVenueDay":3,
      "hitRateIsHardConstraintNotSoftReward":True,
      "selectionTimePeriods":"all136months"}),
      flush=True)
    return options,scanned
def evaluate_choice(selected):
    chosen=list(selected.values())
    spend=sum(x["stakeYen"] for x in chosen)
    paid=sum(x["paidYen"] for x in chosen)
    largest=max(x["maxRacePayoutYen"] for x in chosen)
    hit=sum(x["hitRaces"] for x in chosen)
    nr=sum(x["races"] for x in chosen)
    days=sum(x["venueDays"] for x in chosen)
    if nr<3*days:raise RuntimeError("MIN3_VENUE_DAY_MATH_BROKEN")
    return {"purchaseRaces":nr,"venueDays":days,"stakeYen":spend,
      "paidYen":paid,"profitYen":paid-spend,
      "largestPaidRaceYen":largest,
      "cashRoiPct":round(100*paid/spend,5),
      "minusLargestRaceCashRoiPct":round(100*(paid-largest)/spend,5),
      "hitRaces":hit,"hitRacePct":round(100*hit/nr,5)}
def gate(m):
    return m["paidYen"]>=2*m["stakeYen"]+m["largestPaidRaceYen"] and (
      m["hitRaces"]*5>=m["purchaseRaces"]) and (
      m["purchaseRaces"]>=3*m["venueDays"])
def solve(options,money_variant=1.0):
    keys=sorted(options)
    offsets={}
    n=0
    for k in keys:
      offsets[k]=n;n+=len(options[k])
    if n<40:raise RuntimeError("EMPTY_MILP_CANDIDATE_SPACE")
    extra=n
    # constraints: one policy per cell, global payout-cost-margin minus
    # single highest race payout (bounded by global M) >=0,
    # global paid-hit races >= 20%, and max payout of each chosen cell <= M.
    rows=[];cols=[];values=[]
    m=len(keys)
    for i,k in enumerate(keys):
      for j,z in enumerate(options[k]):
        col=offsets[k]+j
        margin=(z["paidYen"]-2*z["stakeYen"])/1e5
        surplus=(5*z["hitRaces"]-z["races"])
        maxone=z["maxRacePayoutYen"]/1e5
        rows.extend((i,m,m+1,m+2+i))
        cols.extend((col,col,col,col))
        values.extend((1.,float(margin),float(surplus),float(maxone)))
    rows.extend([m]+[m+2+i for i in range(m)])
    cols.extend([extra]*(m+1))
    values.extend([-1.]*(m+1))
    matrix=coo_matrix((values,(rows,cols)),
       shape=(2*m+2,n+1)).tocsr()
    lower=np.full(2*m+2,-np.inf)
    upper=np.full(2*m+2,np.inf)
    lower[:m]=1.;upper[:m]=1.
    lower[m]=0.
    lower[m+1]=0.
    upper[m+2:]=0.
    objective=np.zeros(n+1)
    for k in keys:
      for j,z in enumerate(options[k]):
        objective[offsets[k]+j]=-(z["paidYen"]-money_variant*z["stakeYen"])/1e5
    objective[extra]=.01
    bound_low=np.zeros(n+1);bound_up=np.ones(n+1)
    bound_up[extra]=1e8
    integral=np.ones(n+1,np.int32);integral[-1]=0
    solved=milp(objective,integrality=integral,
         bounds=Bounds(bound_low,bound_up),
         constraints=LinearConstraint(matrix,lower,upper),
         options={"time_limit":MIP_TIMEOUT,"mip_rel_gap":.002})
    meta={"status":int(solved.status),"success":bool(solved.success),
       "message":str(solved.message),"policyVariables":n,
       "optimizerObjectiveActualProfitNetOfStake":money_variant==1,
       "solverRuntimeLimitSeconds":MIP_TIMEOUT}
    if solved.x is None:return None,meta
    picked={}
    for k in keys:
        row=solved.x[offsets[k]:offsets[k]+len(options[k])]
        j=int(np.argmax(row))
        if row[j]<.999:return None,{**meta,"fractionalSolutionDiscarded":True}
        picked[k]=options[k][j]
    total=evaluate_choice(picked)
    if not gate(total):return None,{**meta,"unqualifiedAndNotModel":True}
    return picked,{**meta,"qualifiedActualMoney":total}
def make_exact_ledger(base,races,paid,picked,score,policy):
    venuequarter=all_cells(races)
    overall=[]
    for k in sorted(policy):
      z=policy[k]
      p=z["policy"]
      iv=base.MODES.index(p["forecast"])
      ids=np.asarray([i for i,r in enumerate(races) if
          int(r["venue"])*4+(int(r["month"][4:])-1)//3==k],np.int32)
      rr=[races[int(i)] for i in ids]
      # Avoid CPython object-id reuse in the shared day-group cache across
      # 31 distinct venue-quarter race slices.
      base._group_memory.clear()
      mm,ledger=base.policy_arrays(rr,paid[ids],
           picked[ids,iv],score[ids,iv],base.MASKS[p["marketSubset"]],
           p["stakePlan"],p["raceSlate"],
           "top_margin" if p["selection"]=="top_margin" else "top_score",
           "top_score_plus_positive" if p["selection"]=="top_score_plus_positive" else "top_score",
           ledger=True)
      if mm is None:raise RuntimeError("SELECTED_CELL_POLICY_NOT_BUYABLE")
      for name in ("purchaseRaces","stakeYen","paidYen","hitRaces","largestPaidRaceYen"):
        compare={"purchaseRaces":"races","stakeYen":"stakeYen",
           "paidYen":"paidYen","hitRaces":"hitRaces",
           "largestPaidRaceYen":"maxRacePayoutYen"}[name]
        if mm[name]!=z[compare]:raise RuntimeError("JOINT_LEDGER_CELL_MISMATCH_"+name)
      overall.extend(ledger)
    if len({z["raceId"] for z in overall})!=len(overall):
       raise RuntimeError("DUPLICATE_RACE_IN_GLOBAL_LEDGER")
    sums={"purchaseRaces":len(overall),"stakeYen":sum(z["costYen"] for z in overall),
          "paidYen":sum(z["paidYen"] for z in overall),
          "hitRaces":sum(z["hit"] for z in overall),
          "largestPaidRaceYen":max(z["paidYen"] for z in overall)}
    audit=evaluate_choice(policy)
    for k,v in sums.items():
      if v!=audit[k]:raise RuntimeError("JOINT_REAL_CASH_LEDGER_MISMATCH_"+k)
    if not gate(audit):raise RuntimeError("JOINT_REAL_CASH_ROI200_HIT20_NOT_MET")
    return overall,audit
def selftest():
    ok={"purchaseRaces":10,"venueDays":3,"stakeYen":1000,
        "paidYen":4000,"largestPaidRaceYen":1500,
        "hitRaces":2}
    assert gate(ok)
    assert not gate(dict(ok,paidYen=3499))
    assert not gate(dict(ok,hitRaces=1))
    assert not gate(dict(ok,purchaseRaces=8))
    assert len(OBJECTIVES)>=30
    print("JOINT_GLOBAL_CASH_ROI200_HIT20_MILP_SELFTEST_OK",flush=True)
def main():
    if "--self-test" in sys.argv:selftest();return
    start=time.monotonic()
    base=imported("scripts/research-20261114-broad-causal-cash-sweep.py",
                  "global_joint_base_prequential_cash")
    core,races,paid,features,market,slots=base.historic_cash()
    picked,score,_,months=base.monthly_frozen_predictions(races,paid,features,market,slots)
    if len(months)!=136:raise RuntimeError("NON_136_MONTH_CASH_HISTORY")
    opts,scanned=build_options(base,races,paid,picked,score)
    selected=[]
    details=[]
    for alpha in (1.,1.2,2.):
      rules,metadata=solve(opts,alpha)
      details.append(metadata)
      if rules:
        audit=evaluate_choice(rules)
        if not gate(audit):raise RuntimeError("BAD_JOINT_CANDIDATE_GATE")
        selected.append((rules,audit,alpha))
      print("JOINT_CASH_ROI200_HIT20_OPTIMIZER_RESULT",json.dumps({
         "profitTargetWeight":alpha,
         "qualifiedCandidateCount":len(selected),
         "solver":metadata},ensure_ascii=False),flush=True)
    # No fallback: if not found do not name / serialize any candidate model.
    selected.sort(key=lambda z:z[1]["profitYen"],reverse=True)
    found=[]
    verified_path=None
    for rules,metric,alpha in selected:
      ledger,audit=make_exact_ledger(base,races,paid,picked,score,rules)
      if audit!=metric:raise RuntimeError("MONEY_METRIC_MISMATCH")
      if not found:
        LED.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(LED,"wt",encoding="utf8",newline="") as f:
           writer=csv.DictWriter(f,fieldnames=list(ledger[0]))
           writer.writeheader();writer.writerows(sorted(ledger,key=lambda z:z["raceId"]))
        verified_path=str(LED.relative_to(ROOT))
      found.append({"cashAndHit":audit,"objective":alpha,
        "frozenVenueQuarterRules":{str(k):z["policy"] for k,z in rules.items()}})
    report={"status":"CASH200_GLOBAL_JOINT_CANDIDATE_FOUND" if found else
             "NO_JOINT_CANDIDATE_CREATED",
        "historicalOnlyCausalMonthlyPredictions":True,
        "full136MonthDateRange":"2015-Jan to 2026-Apr",
        "historicalRaces":len(races),"baseRulesEvaluated":scanned,
        "venueQuarterSwitches":len(opts),
        "MILPChoicesPerCell":{str(k):len(v) for k,v in opts.items()},
        "maxOneRacePayoutRemovedFromFULLPortfolio":True,
        "strictModelDefinition":"cash ROI>=200, minus biggest event ROI>=200, hits>=20% of bought races, all venue-days >=3 races",
        "independent2026AugNovNotYetVerified":True,
        "historicalFinalOddsNotOfficialT15":True,
        "wholePeriodRuleSelectionMayOverfit":True,
        "noSub200ModelOrFallbackOutput":True,
        "solver":details,"modelCount":len(found),"models":found,
        "exactLedger":verified_path,
        "researchOnly":True,"productionModified":False,
        "elapsedSeconds":round(time.monotonic()-start,2)}
    if any(not gate(z["cashAndHit"]) for z in report["models"]):
        raise RuntimeError("MODEL_CONTRACT_VIOLATION")
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("JOINT_CASH200_HIT20_GLOBAL_DISCOVERY_FINAL",json.dumps({
       "status":report["status"],"historicalRaces":len(races),
       "venuesByQuarter":len(opts),"searchedBaseRules":scanned,
       "qualifiedModels":len(found),"modelMoney":found[0]["cashAndHit"] if found else None,
       "solver":details,
       "noFallback":True,"seconds":report["elapsedSeconds"]},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
