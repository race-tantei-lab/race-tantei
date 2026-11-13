#!/usr/bin/env python3
"""FULL-ARCHIVE real-yen ROI>=200% discovery (research only).

No year is withheld for candidate selection: all 2017 through available
2026 JRA historical payout months form ONE objective. Calendar quarter and
venue-quarter may switch policies, but there is no chronological holdout
used as a gate or separate period in this discovery.

Candidate list contains ONLY portfolios with ROI>=200% AND ROI>=200%
after removing the ONE largest race payout, without reducing spend.
Every venue on every race date buys 3-5 distinct races, exactly 2000 yen
per race. Prior 20% hit-rate preference is reported independently.

All 1030 top-ten ticket formations from 6 markets are available per race.
Historical ticket-score calculation uses whole period but *subtracts the
row's own payout* (conservative leave-one-out) so a race's payoff cannot
by itself create that same race's ticket-selection signal.

This is retrospective mining and NOT independently forward verified:
historical final WIN odds are NOT verified JRA official T-15 odds and
external payout mirror has not been matched to JRA's official payouts.
Never deploy a mined pattern as a verified predictive model.
"""
from __future__ import annotations
import collections, csv, gzip, importlib.util, json, sys, time
from pathlib import Path
import numpy as np

R=Path(__file__).resolve().parents[1]
OUT=R/"analysis-results/nov2026-whole-period-only-roi200-search.json"
LED=R/"analysis-results/nov2026-whole-period-roi200-selected-bets.csv.gz"
SOURCE=R/"scripts/research-nov2026-min3r-three-year-cash-selection.py"
YEARS=tuple(range(2017,2027))
APPROACHES=("flat","quarter","venue_quarter")
TRIMS=(0, 1, 2)
HIT_PRICES=(0, 3000, 9000, 20000, 50000, 100000, 200000, 500000)
BUDGET=2000
def load():
    s=importlib.util.spec_from_file_location("full_archive_cash_rules",SOURCE)
    m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
    return m
def specs(base):
    for pair in base.SETTINGS["pairs"]:
      for slate in base.SETTINGS["slates"]:
       for split in base.SETTINGS["split"]:
        if pair=="one_market" and split!=1000:continue
        for rank in base.SETTINGS["selection"]:
          yield (str(pair)+"_"+str(slate)+"_"+str(split)+"_"+rank,
                 (pair,slate,split,rank))
def payout_metrics(rows,number_days):
    if not rows:raise RuntimeError("NO_BETS_IN_FULL_COHORT")
    payouts=np.asarray([int(r["paidYen"]) for r in rows],dtype=np.int64)
    hits=int(np.count_nonzero(payouts))
    cost=len(rows)*BUDGET
    if len(rows)<3*number_days or len(rows)>5*number_days:
      raise RuntimeError("NOT_THREE_TO_FIVE_EACH_DAY")
    if any(int(r["stake1Yen"])+int(r["stake2Yen"])!=BUDGET for r in rows):
      raise RuntimeError("STAKE_MISMATCH")
    return {"races":len(rows),"venueDays":number_days,"stakeYen":cost,
      "paidYen":int(payouts.sum()),"profitYen":int(payouts.sum())-cost,
      "maxRacePayoutYen":int(payouts.max()),"hitRaces":hits,
      "cashRoiPct":round(100*int(payouts.sum())/cost,4),
      "minusLargestRaceCashRoiPct":round(100*(int(payouts.sum())-int(payouts.max()))/cost,4),
      "hitRacePct":round(100*hits/len(rows),4)}
def total(cells):
    if not cells:return None
    paid=sum(v["paidYen"] for v in cells)
    cost=sum(v["stakeYen"] for v in cells)
    races=sum(v["races"] for v in cells)
    days=sum(v["venueDays"] for v in cells)
    hits=sum(v["hitRaces"] for v in cells)
    largest=max(v["maxRacePayoutYen"] for v in cells)
    if races<3*days or races>5*days or cost!=BUDGET*races:
        raise RuntimeError("FULL_ARCHIVE_SPEND_OR_COVERAGE_BROKEN")
    return {"races":races,"venueDays":days,"stakeYen":cost,
            "paidYen":paid,"profitYen":paid-cost,
            "maxRacePayoutYen":largest,"hitRaces":hits,
            "cashRoiPct":round(paid*100/cost,4),
            "minusLargestRaceCashRoiPct":round((paid-largest)*100/cost,4),
            "hitRacePct":round(100*hits/races,4)}
def roi200(m):
    return m is not None and m["cashRoiPct"]>=200 and m["minusLargestRaceCashRoiPct"]>=200
def whole_archive_loo_scores(base):
    sparse=base.load("scripts/research-nov2026-frozen-sparse-cash-model.py","whole_sparse_source")
    core,races,years,paid,cat=sparse.archive()
    if paid.shape[1]!=1030 or len(races)<26000:
        raise RuntimeError("FULL_TOP10_ARCHIVE_MISSING")
    if set(int(x) for x in np.unique(years))!=set(YEARS):
        raise RuntimeError("MISSING_YEAR_IN_WHOLE_ARCHIVE")
    n,k=paid.shape
    best=np.zeros((n,k),dtype=np.float32)
    template=np.arange(k,dtype=np.int32)[None,:]
    win=np.asarray(paid>0,dtype=bool)
    payout=np.asarray(paid,dtype=np.float32)
    for i,schema in enumerate(sparse.SCHEMAS):
      key,size=sparse.sample_group_code(cat,template,schema)
      flat=key.ravel()
      count=np.bincount(flat,minlength=size).astype(np.float32)
      sums=np.bincount(flat,weights=payout.ravel(),minlength=size).astype(np.float32)
      hits=np.bincount(flat,weights=win.ravel(),minlength=size).astype(np.float32)
      maximum=np.zeros(size,dtype=np.float32)
      nz=np.flatnonzero(win.ravel())
      np.maximum.at(maximum,flat[nz],payout.ravel()[nz])
      # Conservative leave-ONE-race-out, with full original group max
      # still removed. This never inflates a ticket's self outcome.
      denominator=np.maximum(1,count[key]-1)
      cash_rest=(sums[key]-payout-maximum[key])/denominator
      hits_rest=hits[key]-win
      eligible=(count[key]>=13)&(hits_rest>=2)&(cash_rest>=200)
      # Confidence scores are historical actual-yen only.
      strength=np.minimum(np.maximum(cash_rest,0),15000)
      strength*=np.power(np.minimum(200,denominator)/200,.25)
      strength*=np.minimum(hits_rest,15)/15
      np.maximum(best,np.where(eligible,strength,0),out=best)
      if (i+1)%5==0:
        print("WHOLE_PERIOD_LOO_CASH_PATTERN_SCHEMAS",json.dumps({"evaluated":i+1,
             "total":len(sparse.SCHEMAS),"venueYears":list(YEARS)}),flush=True)
      del key,flat,count,sums,hits,maximum,cash_rest,hits_rest,eligible,strength
    rank,market=core.fixed_template()
    chosen=np.empty((n,6),dtype=np.int16)
    signal=np.empty((n,6),dtype=np.float32)
    fallback=[]
    for m in range(6):
      templates=np.flatnonzero(market==m)
      option=np.argmax(best[:,templates],axis=1)
      chosen[:,m]=templates[option]
      signal[:,m]=best[np.arange(n),chosen[:,m]]
      money=paid[:,templates].astype(np.int64)
      collected=money.sum(axis=0)-money.max(axis=0)
      best_fb=int(templates[np.argmax(collected)])
      fallback.append(best_fb)
      chosen[:,m]=np.where(signal[:,m]>0,chosen[:,m],best_fb)
    print("WHOLE_PERIOD_CASH_SIGNALS_READY",json.dumps({
        "races":n,"cashTicketEvents":int(paid.size),
        "schemaCount":len(sparse.SCHEMAS),
        "fullPeriodPayoutsOnly":True,"leaveOneRaceOutSignals":True,
        "cashFallbackTicketTemplates":fallback}),flush=True)
    del best
    return core,races,years,paid,cat,chosen,signal,market,rank
def rank_cell(v,remove_max,money_per_hit):
    return v["paidYen"]-remove_max*v["maxRacePayoutYen"]-2*v["stakeYen"]+money_per_hit*(v["hitRaces"]-.20*v["races"])
def main():
    base=load()
    if "--self-test" in sys.argv:
      assert len(list(specs(base)))==780
      x=total([{"races":3,"venueDays":1,"stakeYen":6000,"paidYen":18000,
        "maxRacePayoutYen":5000,"hitRaces":1}])
      assert roi200(x) and x["minusLargestRaceCashRoiPct"]==216.6667
      assert not roi200(dict(x,paidYen=6000,cashRoiPct=100.))
      print("WHOLE_ARCHIVE_ROI200_ONLY_SELFTEST_OK")
      return
    started=time.monotonic()
    core,races,years,paid,cat,chosen,signal,market,rank=whole_archive_loo_scores(base)
    ix=np.arange(len(races),dtype=np.int32)
    daygroups=base.choose_day_groups(races,ix)
    full_day_ids={(r["day"],int(r["venue"])) for r in races}
    if len(full_day_ids)!=len(daygroups):raise RuntimeError("VENUE_DAY_POPULATION_MISMATCH")
    universe={}
    quarter_day=collections.defaultdict(set)
    for r in races:
      v=int(r["venue"]);q=(int(r["month"][4:])-1)//3
      quarter_day[(v,q)].add((r["day"],v))
    allcells=sorted(quarter_day)
    quarter_keys=sorted({q for _,q in allcells})
    if len(allcells)<25 or len(quarter_keys)!=4:raise RuntimeError("MISSING_MARKET_VENUE_QUARTER")
    for key,spec in specs(base):
      _,rows=base.decisions(races,ix,paid,chosen,signal,daygroups,*spec,True)
      byday=collections.Counter((r["date"],int(r["venue"])) for r in rows)
      if len(byday)!=len(full_day_ids) or set(byday)!=full_day_ids or any(c<3 or c>5 for c in byday.values()):
          raise RuntimeError("POLICY_DID_NOT_COVER_ALL_JRA_VENUE_DAYS")
      bycell=collections.defaultdict(list)
      byquarter=collections.defaultdict(list)
      for r in rows:
        q=(int(r["date"][4:6])-1)//3
        bycell[(int(r["venue"]),q)].append(r)
        byquarter[q].append(r)
      cellm={}
      for cell,rm in bycell.items():
        cellm[cell]=payout_metrics(rm,len(quarter_day[cell]))
      if set(cellm)!=set(allcells):raise RuntimeError("ONE_VENUE_QUARTER_MISSING")
      quarm={}
      for q,rm in byquarter.items():
        qdays=sum(len(quarter_day[c]) for c in allcells if c[1]==q)
        quarm[q]=payout_metrics(rm,qdays)
      universe[key]={"spec":spec,"cells":cellm,"quarters":quarm,
                     "all":total(list(cellm.values()))}
      if len(universe)%100==0:print("WHOLE_PERIOD_MONEY_POLICIES_PROCESSED",
                    json.dumps({"policies":len(universe),"allYears":list(YEARS),
                    "venueDays":len(full_day_ids)}),flush=True)
    print("WHOLE_ARCHIVE_CASH_POLICY_MATRIX",json.dumps({
        "policies":len(universe),"venueQuarterCells":len(allcells),
        "cashLabeledRaces":len(races),"allVenueDays":len(full_day_ids)}),flush=True)
    # Search across the FULL archive; no year, season or other period is
    # treated as a training-only gate or an out-of-sample rejection test.
    accepted=[]
    seen=set()
    examined=0
    def add(method, choices, metadata):
       nonlocal examined
       examined+=1
       used=[universe[p]["cells"][cell] for cell,p in choices.items()]
       m=total(used)
       if not roi200(m):return
       sig=tuple(sorted((str(k),v) for k,v in choices.items()))
       if sig in seen:return
       seen.add(sig)
       accepted.append({"approach":method,"parameters":metadata,"fullPeriodCash":m,
                        "hitRateAtLeast20":m["hitRacePct"]>=20,
                        "venueQuarterSelections":{
                          f"{v}_Q{q+1}":choices[(v,q)] for v,q in allcells}})
    for key in universe:
      add("whole_period_flat",{c:key for c in allcells},{"policy":key})
    # Single deterministic selection for each cell/quarter from all 780
    # candidates, thousands of combinations of 3-5 races, two markets,
    # dynamic/static ticket formulas, and JPY2000 allocations.
    for approach in ("whole_period_quarter","whole_period_venue_quarter"):
      for trim in TRIMS:
       for price in HIT_PRICES:
        if approach.endswith("_quarter"):
          qwin={q:max(universe,key=lambda k:(rank_cell(universe[k]["quarters"][q],trim,price),k))
                for q in quarter_keys}
          cells={c:qwin[c[1]] for c in allcells}
        else:
          cells={c:max(universe,key=lambda k:(rank_cell(universe[k]["cells"][c],trim,price),k))
               for c in allcells}
        add(approach,cells,{"maximumPayoutPenalty":trim,"cashBonusPerHit":price})
    # Venue, season, market diversification: select local policies by
    # payout-minus-largest but with pooled quarter objectives as tie-breaker.
    for weight in (0,.25,.5,.75,1.):
      for price in HIT_PRICES:
        cells={}
        for c in allcells:
          q=c[1]
          cells[c]=max(universe,key=lambda k:(
              (1-weight)*rank_cell(universe[k]["quarters"][q],1,price)/
                   max(1,universe[k]["quarters"][q]["stakeYen"])*1e6+
              weight*rank_cell(universe[k]["cells"][c],1,price)/
                   max(1,universe[k]["cells"][c]["stakeYen"])*1e6,k))
        add("whole_period_blended_venue_season",cells,
            {"venueWeight":weight,"cashBonusPerHit":price})
    accepted.sort(key=lambda c:(c["hitRateAtLeast20"],
          c["fullPeriodCash"]["minusLargestRaceCashRoiPct"],
          c["fullPeriodCash"]["hitRacePct"]),reverse=True)
    # A discovery found on ALL historical years is not a forward prediction
    # guarantee and MUST NOT change live publication.
    top=accepted[:25]
    report={"status":"FULL_PERIOD_ROI200_PATTERNS_FOUND" if accepted else
            "FULL_PERIOD_SEARCH_NO_ROI200_PATTERNS_YET",
        "period":"2017-01 through 2026-04 (available historical payoff archive)",
        "allHistoricalYearsUsedSimultaneously":list(YEARS),
        "splitOrHoldoutUsedForCandidateFiltering":False,
        "searchMethod":"full historical archive ROI-first static and regime combination mining",
        "profitCriterion":"gross real-yen ROI>=200 and subtract exactly one largest paid race with full original stake >=200",
        "candidateDefinition":"ONLY full-archive ROI>=200 and after-max>=200; no below-200 entries",
        "selectedRacesPerVenueDay":[3,5],"stakeYenPerRace":BUDGET,
        "allVenueDaysIncluded":len(full_day_ids),
        "policiesScanned":len(universe),
        "compositeStrategiesScanned":examined,
        "roi200CandidateCount":len(accepted),
        "roi200AndHit20Count":sum(x["hitRateAtLeast20"] for x in accepted),
        "roi200CandidatesTop25":top,
        "jraOfficialT15Verified":False,
        "payoutMirrorIndependentlyJraVerified":False,
        "historicalInSampleDiscoveryNotForwardEvidence":True,
        "productionModified":False,"seconds":round(time.monotonic()-started,2)}
    if accepted:
        winner=accepted[0]
        rows=[]
        mapping={(int(k.split("_")[0]),int(k.split("_Q")[1])-1):v for k,v
                 in winner["venueQuarterSelections"].items()}
        for cell,policy_name in mapping.items():
          # Rebuild exact chronological ledger by rerunning only the chosen
          # 780-candidate policy on that quarter's venue-day population.
          cellidx=np.asarray([j for j,r in enumerate(races) if
                 int(r["venue"])==cell[0] and (int(r["month"][4:])-1)//3==cell[1]],dtype=np.int32)
          group=base.choose_day_groups(races,cellidx)
          _,part=base.decisions(races,cellidx,paid,chosen,signal,group,
                              *universe[policy_name]["spec"],True)
          rows.extend(part)
        if len(set(r["raceId"] for r in rows))!=len(rows):
           raise RuntimeError("DUPLICATE_LEDGER_RACES")
        byday=collections.Counter((r["date"],int(r["venue"])) for r in rows)
        if set(byday)!=full_day_ids or any(x<3 or x>5 for x in byday.values()):
           raise RuntimeError("FINAL_LEDGER_FAILS_VENUE_DAY_MINIMUM")
        money=payout_metrics(rows,len(full_day_ids))
        expected=winner["fullPeriodCash"]
        for k in ("races","venueDays","stakeYen","paidYen","maxRacePayoutYen","hitRaces"):
          if money[k]!=expected[k]:
            raise RuntimeError("DETAILED_BETS_DISAGREE_WITH_ACCEPTED_CANDIDATE_"+k)
        LED.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(LED,"wt",encoding="utf8",newline="") as f:
          w=csv.DictWriter(f,fieldnames=list(rows[0]))
          w.writeheader();w.writerows(sorted(rows,key=lambda r:(r["date"],r["venue"],r["raceNo"])))
        report["topCandidateCashLedgerSaved"]=str(LED.relative_to(R))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str)+"\n",encoding="utf8")
    print("WHOLE_ARCHIVE_ROI200_ONLY_FINAL",json.dumps({
        "status":report["status"],"years":list(YEARS),
        "policies":len(universe),"searches":examined,
        "onlyAtLeast200Candidates":len(accepted),
        "alsoHit20":report["roi200AndHit20Count"],
        "bestCandidate":top[0]["fullPeriodCash"] if top else None,
        "seconds":report["seconds"],"productionChanged":False},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
