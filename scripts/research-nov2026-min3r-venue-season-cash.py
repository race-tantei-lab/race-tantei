#!/usr/bin/env python3
"""Nested cash-only JRA venue x calendar quarter selection (isolated study).

Every venue-date buys >=3 and <=5 separate races for exactly 2,000 yen each.
The underlying ticket signal was frozen on 2017-2019 alone. For target
year t, choose the complete market, stake split, and slate separately for
each venue-quarter using ONLY settled cash from the last three years.
Pool/shrink venue experts against all-venue quarter experts to discourage
a few high payouts dominating tiny local cohorts. Read-only historical
payout labels; final odds proxy is not officially established T-15.
"""
import collections, importlib.util, json, sys, time
from pathlib import Path
import numpy as np

R=Path(__file__).resolve().parents[1]
OUT=R/"analysis-results/nov2026-min3r-venue-season-cash-1113.json"
SRC=R/"scripts/research-nov2026-min3r-rolling-regime-cash.py"
YEARS=tuple(range(2020,2027))
EVAL=(2023,2024,2025,2026)
OBJECTIVES=("recent2_robust","three_year_robust","worst_year")
ALPHAS=(0.,.25,.50,.75,1.)
def source():
  sp=importlib.util.spec_from_file_location("rolling_venue_three_races",SRC)
  m=importlib.util.module_from_spec(sp);sys.modules[sp.name]=m;sp.loader.exec_module(m)
  return m
def q_of(row):
  return (int(row["date"][4:6])-1)//3
def cash(rows,days):
  if not rows:return None
  amounts=[int(r["paidYen"]) for r in rows]
  paid=sum(amounts);stake=len(rows)*2000;top=max(amounts)
  if len(rows)<days*3 or len(rows)>days*5:raise RuntimeError("VENUE_DAY_COVERAGE_BROKEN")
  if any(int(r["stake1Yen"])+int(r["stake2Yen"])!=2000 for r in rows):
    raise RuntimeError("STAKE_PER_RACE_BROKEN")
  hits=sum(a>0 for a in amounts)
  return {"races":len(rows),"venueDays":days,
       "stakeYen":stake,"paidYen":paid,"profitYen":paid-stake,
       "maxRacePayoutYen":top,"hitRaceCount":hits,
       "hitRacePct":round(100*hits/len(rows),4),
       "cashRoiPct":round(100*paid/stake,4),
       "minusLargestRaceCashRoiPct":round(100*(paid-top)/stake,4)}
def combine(parts):
  parts=[p for p in parts if p]
  if not parts:return None
  n=sum(x["races"] for x in parts);d=sum(x["venueDays"] for x in parts)
  stake=sum(x["stakeYen"] for x in parts)
  paid=sum(x["paidYen"] for x in parts)
  mx=max(x["maxRacePayoutYen"] for x in parts)
  hits=sum(x["hitRaceCount"] for x in parts)
  if n<3*d or n>5*d or stake!=n*2000:
    raise RuntimeError("INVALID_FULL_CASH_PORTFOLIO_COVERAGE")
  return {"races":n,"venueDays":d,"stakeYen":stake,"paidYen":paid,
      "profitYen":paid-stake,"maxRacePayoutYen":mx,
      "hitRaceCount":hits,"hitRacePct":round(100*hits/n,4),
      "cashRoiPct":round(100*paid/stake,4),
      "minusLargestRaceCashRoiPct":round(100*(paid-mx)/stake,4)}
def objective(stats, mode):
  if not stats or len(stats)<2:return -1.e40
  a=combine(stats);s=a["stakeYen"];cash=(a["paidYen"]-a["maxRacePayoutYen"])/s
  individual=[(x["paidYen"]-x["maxRacePayoutYen"])/x["stakeYen"] for x in stats]
  if mode=="three_year_robust":return cash
  if mode=="worst_year":return min(individual)
  if mode=="recent2_robust":
    b=combine(stats[-2:])
    return (b["paidYen"]-b["maxRacePayoutYen"])/b["stakeYen"]
  raise RuntimeError("UNKNOWN_OBJECTIVE")
def qualify(a,b,total):
  if not a or not b or not total:return False
  return all(v["cashRoiPct"]>=200 and
             v["minusLargestRaceCashRoiPct"]>=200 and
             v["hitRacePct"]>=20 for v in (a,b,total))
def main():
  old=source();base=old.baseline()
  if "--self-test" in sys.argv:
    assert len(list(old.policy_options(base)))==780
    rows=[{"date":"20230101","venue":1,"paidYen":5000,
           "stake1Yen":1000,"stake2Yen":1000}]*3
    x=cash(rows,1);assert x["races"]==3 and x["stakeYen"]==6000
    assert x["minusLargestRaceCashRoiPct"]==166.6667
    assert not qualify(x,x,x)
    print("VENUE_SEASON_CASH_SELFTEST_OK");return
  start=time.monotonic()
  core,races,years,paid,cat,opts,signals,markets,ranks=base.feature_races()
  ids={y:np.flatnonzero(years==y) for y in YEARS}
  options=dict(old.policy_options(base))
  # Every policy in every year is settled against exactly the same entire
  # JRA venue-date population. No profitable dates can be cherry-picked.
  cache={}
  cells={}
  for yr in YEARS:
    idx=ids[yr]
    days=base.choose_day_groups(races,idx)
    full_cells=collections.defaultdict(list)
    for i in idx:
      r=races[int(i)]
      full_cells[(int(r["venue"]), (int(r["month"][4:])-1)//3)].append(int(i))
    cells[yr]={k:np.asarray(v,dtype=np.int32) for k,v in full_cells.items()}
    cache[yr]={}
    for name,spec in options.items():
      _,rows=base.decisions(races,idx,paid,opts,signals,days,*spec,True)
      buckets=collections.defaultdict(list)
      quarters=collections.defaultdict(list)
      for r in rows:
        k=(int(r["venue"]),q_of(r));buckets[k].append(r);quarters[k[1]].append(r)
      bycell={k:cash(v,len({(r["date"],r["venue"]) for r in v})) for k,v in buckets.items()}
      byq={q:cash(v,len({(r["date"],r["venue"]) for r in v})) for q,v in quarters.items()}
      cache[yr][name]={"cells":bycell,"quarters":byq}
    print("VENUE_SEASON_CACHE_DONE",json.dumps({"year":yr,
      "policies":len(options),"venueQuarterCells":len(cells[yr]),"raceCount":len(idx)}),flush=True)
  output={}
  for mode in OBJECTIVES:
    for alpha in ALPHAS:
      name=f"{mode}_venue_{alpha:.2f}"
      year_stats={};selection={}
      for target in EVAL:
        past=(target-3,target-2,target-1)
        selected_by_cell={}
        for (venue,q),ix in sorted(cells[target].items()):
          keys=[]
          for key in options:
            global_set=[cache[y][key]["quarters"].get(q) for y in past]
            if any(v is None for v in global_set):continue
            local_set=[cache[y][key]["cells"].get((venue,q)) for y in past]
            local_set=[x for x in local_set if x is not None]
            pooled=objective(global_set,mode)
            local=objective(local_set,mode) if len(local_set)>=2 else pooled
            # Penalize unstable small cash pools by limiting venue weight.
            active=sum(v["races"] for v in local_set)
            support=active/(active+90.)
            merit=(1-alpha*support)*pooled+alpha*support*local
            keys.append((merit,key))
          if not keys:raise RuntimeError("NO_PREVIOUS_YEAR_VENUE_POLICY")
          best=max(keys)[1]
          selected_by_cell[(venue,q)]=best
        rows=[]
        for k,key in selected_by_cell.items():
          ix=cells[target][k]
          groups=base.choose_day_groups(races,ix)
          _,bets=base.decisions(races,ix,paid,opts,signals,groups,*options[key],True)
          rows.extend(bets)
        byday=collections.Counter((r["date"],int(r["venue"])) for r in rows)
        expected={(races[int(i)]["day"],int(races[int(i)]["venue"]))
                  for i in ids[target]}
        if set(byday)!=expected or not all(3<=cnt<=5 for cnt in byday.values()):
          raise RuntimeError("MISSING_RACE_DAY_OR_NOT_THREE_RACES")
        m=cash(rows,len(byday))
        year_stats[str(target)]=m
        selection[str(target)]={f"{k[0]}_Q{k[1]+1}":v for k,v in selected_by_cell.items()}
      val=combine([year_stats[str(y)] for y in (2023,2024,2025)])
      held=year_stats["2026"]
      all_=combine([year_stats[str(y)] for y in EVAL])
      ok=qualify(val,held,all_)
      output[name]={"yearly":year_stats,"validation2023To2025":val,
          "later2026JanToApr":held,"entireForward":all_,
          "meets200CashAnd20Hit":ok,
          "venueSeasonPoliciesByYear":selection}
      print("VENUE_SEASON_RESULT",json.dumps({"method":name,
         "forward":all_,"holdout":held,"qualifies":ok}),flush=True)
  good=[k for k,v in output.items() if v["meets200CashAnd20Hit"]]
  report={"status":"VENUE_SEASON_RESEARCH_ONLY_AWAIT_T15" if good else "NO_VENUE_SEASON_200_CASH_QUALIFIER",
       "allVenuesEveryRaceDay":True,"minimumDifferentRaces":3,
       "yenPerRace":2000,"historicPriorYearSelectionOnly":True,
       "prespecifiedMethods":len(output),"cashPolicies":len(options),
       "productionChanged":False,"officialT15Verified":False,
       "JRAOfficialPayoutReconciliation":False,
       "qualifyingResearchStrategies":good,"strategies":output,
       "durationSeconds":round(time.monotonic()-start,2)}
  OUT.parent.mkdir(parents=True,exist_ok=True)
  OUT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
  print("VENUE_SEASON_FINAL",json.dumps({"status":report["status"],
       "completedMethods":len(output),"qualified":good,"durationSeconds":report["durationSeconds"]}),flush=True)
if __name__=="__main__":main()
