#!/usr/bin/env python3
"""Direct cash ROI over complete two-market portfolios: variable 3/4/5 R
and 100/300 yen split. R&D only, never adopted below 200 robust overall.

Uses a 2022 cash blind policy screen (2017-2021 source training) to
choose the entire season-venue bet allocation policy. Refits on
2017-2022 payout and freezes one policy for 2023-26 out-of-time.
No test-year payout or T-15 snapshot is used as a predictor.
"""
from __future__ import annotations
import csv,json,importlib.util,math,sys,time
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"scripts/research-nov2026-direct-paid-yen-regime-search.py"
spec=importlib.util.spec_from_file_location("direct_cash_source",PATH)
core=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=core
spec.loader.exec_module(core)

OUT=ROOT/"analysis-results/nov2026-direct-cash-stake-allocation-search.json"
BETS=ROOT/"analysis-results/nov2026-direct-cash-stake-allocation-bets.csv"
MARKETS=core.MARKETS
MODES=("both_highest","win_plus_wide","wide_plus_tail",
       "win_plus_tail","wide_or_win_plus_tail","no_win_tail_pair")
CAPS=(20000.,60000.,180000.)
RACES_PER_DAY=(3,4,5)
STAKES=((100,100),(100,300),(300,100),(100,700),(700,100))

def summary(rows):
    stake=sum(r["stakeYen"] for r in rows)
    payout=sum(r["paidYen"] for r in rows)
    maxpaid=max((r["paidYen"] for r in rows),default=0)
    hits=sum(r["paidYen"]>0 for r in rows)
    return dict(races=len(rows),bets=2*len(rows),stakeYen=stake,
       paidYen=payout,netYen=payout-stake,
       roiPct=round(100*payout/stake,4) if stake else None,
       minusBiggestRaceRoiPct=round(100*(payout-maxpaid)/stake,4) if stake else None,
       hitRaces=hits,hitRacePct=round(100*hits/len(rows),4) if rows else None,
       biggestRacePaidYen=maxpaid)

def choose(races,paid,year,est_scores,target,mode,races_per_day,stake_split):
    ix=np.flatnonzero(year==target)
    if len(est_scores)!=336*len(ix):raise RuntimeError("TICKET_PREDICTION_DIMENSIONS")
    scores=est_scores.reshape(len(ix),336)
    pays=paid[ix]
    grouped=defaultdict(list)
    for k,i in enumerate(ix):
        r=races[int(i)]
        opts=[]
        for market,(lo,hi) in enumerate(core.STEPS):
            j=int(np.argmax(scores[k,lo:hi]))+lo
            opts.append((float(scores[k,j]),market,j))
        if mode=="both_highest":
            selected=sorted(opts,key=lambda z:(-z[0],z[1]))[:2]
        elif mode=="win_plus_wide":
            selected=[opts[0],opts[1]]
        elif mode=="wide_plus_tail":
            selected=[opts[1],max(opts[2:],key=lambda z:(z[0],-z[1]))]
        elif mode=="win_plus_tail":
            selected=[opts[0],max(opts[2:],key=lambda z:(z[0],-z[1]))]
        elif mode=="wide_or_win_plus_tail":
            selected=[max(opts[:2],key=lambda z:(z[0],-z[1])),
                      max(opts[2:],key=lambda z:(z[0],-z[1]))]
        elif mode=="no_win_tail_pair":
            selected=sorted(opts[1:],key=lambda z:(-z[0],z[1]))[:2]
        else:raise RuntimeError("UNKNOWN_ALL_MARKET_ALLOCATION_MODE")
        if len(set(x[1] for x in selected))!=2:raise RuntimeError("MARKET_DUPLICATED")
        a,b=stake_split
        x,y=selected
        priority=(a*x[0]+b*y[0])/(a+b)
        bet=dict(
         raceId=r["id"],day=r["day"],year=target,venue=int(r["venue"]),
         mode=mode,market1=MARKETS[x[1]],market2=MARKETS[y[1]],
         ticket1=int(x[2]),ticket2=int(y[2]),
         stake1Yen=a,stake2Yen=b,stakeYen=a+b,
         paidYen=int(pays[k,x[2]])*(a//100)+int(pays[k,y[2]])*(b//100),
         preRaceExpectedCashPer100=round(priority,5)
        )
        grouped[(r["day"],r["venue"])].append(bet)
    out=[]
    for candidates in grouped.values():
        candidates.sort(key=lambda r:(-r["preRaceExpectedCashPer100"],r["raceId"]))
        out.extend(candidates[:races_per_day])
    coverage={"programDays":len(grouped),
         "enough3":sum(len(q)>=3 for q in grouped.values()),
         "enough5":sum(len(q)>=5 for q in grouped.values()),
         "boughtRaces":len(out)}
    return out,coverage

def prep_scenarios(races,paid,year,scores,target):
    scenarios={}
    for mode in MODES:
      for racecount in RACES_PER_DAY:
        for stakes in STAKES:
            picks,cov=choose(races,paid,year,scores,target,mode,racecount,stakes)
            key=(mode,racecount,stakes)
            scenarios[key]=(summary(picks),cov)
    return scenarios

def main():
    if "--self-test" in sys.argv:
        a=[dict(stakeYen=200,paidYen=500),dict(stakeYen=400,paidYen=100)]
        assert summary(a)["minusBiggestRaceRoiPct"]==round(100*100/600,4)
        assert len(MODES)*len(RACES_PER_DAY)*len(STAKES)==90
        print("CASH_PORTFOLIO_ALLOCATION_SELFTEST_OK",flush=True)
        return
    start=time.monotonic()
    races,X,paid,year=core.source_data()
    records={};ranked=[]
    for cap in CAPS:
        est,traininfo=core.train_cash_estimator(X,paid,year,core.TRAIN,cap)
        testscore=core.score_for(est,X,year,2022)
        results=prep_scenarios(races,paid,year,testscore,2022)
        for key,(cash,cov) in results.items():
            # Optimize actual 2022 100-Yen paid-return, with one whole
            # jackpot race REMOVED but its stake still counted. No
            # forward-year cash may influence policy membership/ranking.
            robust=(cash["minusBiggestRaceRoiPct"] or 0.)
            hit=(cash["hitRacePct"] or 0.)
            coverage=(cov["enough3"]/max(cov["programDays"],1))
            acceptable=hit>=20. and coverage>=.95 and cash["races"]>=300
            # Preserve cash-first ordering, then hit/coverage.
            objective=((robust if acceptable else robust*.20)
                       *coverage*math.sqrt(max(1,cash["races"])))
            keystr=f"{cap:g}__{key[0]}__{key[1]}R__{key[2][0]}-{key[2][1]}"
            records[keystr]={"cash2022":cash,"coverage":cov,
                "historicalFit":traininfo,"eligibleOn2022":acceptable,
                "scorePastOnly":round(objective,4)}
            ranked.append((objective,acceptable,cap,key,keystr))
        print("CASH_ALLOCATION_2022_GRID",json.dumps({
           "cashCapYen":cap,
           "policies":len(results),
           "bestPriorYear":sorted(({
             "mode":key[0],"racesPerDay":key[1],"stakes":key[2],
             "cash":v[0]} for key,v in results.items()),
             key=lambda x:-(x["cash"]["minusBiggestRaceRoiPct"] or 0))[:3]
        },ensure_ascii=False),flush=True)
    score,is_eligible,cap,key,keystr=max(ranked,key=lambda v:(v[1],v[0],-v[2],v[4]))
    mode,racecount,stakes=key
    model,trained=core.train_cash_estimator(X,paid,year,tuple(range(2017,2023)),cap)
    report={};outs=[];cover={}
    for yr in core.OOS:
        pred=core.score_for(model,X,year,yr)
        bets,cov=choose(races,paid,year,pred,yr,mode,racecount,stakes)
        report[str(yr)]=summary(bets)
        cover[str(yr)]=cov
        outs.extend(bets)
        print("CASH_ALLOCATION_CHRONO_YEAR",json.dumps({
         "year":yr,"metrics":report[str(yr)],"coverage":cov
        },ensure_ascii=False),flush=True)
    combined=summary(outs)
    passed=(combined["minusBiggestRaceRoiPct"] is not None
            and combined["minusBiggestRaceRoiPct"]>=200
            and combined["hitRacePct"]>=20
            and all(report[str(y)]["minusBiggestRaceRoiPct"] is not None
                    and report[str(y)]["minusBiggestRaceRoiPct"]>=200
                    for y in core.OOS))
    output={
      "researchOnly":True,"isAcceptedModel":False,
      "retrospectiveAllYearsROI200AndHit20":passed,
      "historical2022CashOnlySelectsPolicy":True,
      "forwardYearsUnseenByFeatureAndPolicyChoice":list(core.OOS),
      "allBettingTypesSixMarkets":True,
      "ticketBetSizes100YenMultiples":True,
      "noLiveJraT15Odds":True,
      "noOfficialPayoutReconciliation":True,
      "2025And2026PriorResearchExposure":True,
      "totalDirectCashPolicyVariants":len(records),
      "pre2023Chosen":{"trainingPayoutCap":cap,"choiceMode":mode,
          "racesPerVenueDay":racecount,"stake1Yen":stakes[0],
          "stake2Yen":stakes[1],"meetsHistoricalHit20":is_eligible},
      "selectionYear2022AllCashPolicyScreens":records,
      "trainingStats":trained,"forwardCashByYear":report,
      "overallCash":combined,"coverage":cover,
      "seconds":round(time.monotonic()-start,2)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with BETS.open("w",newline="",encoding="utf-8") as f:
        names=("raceId","day","year","venue","mode","market1","market2",
               "ticket1","ticket2","stake1Yen","stake2Yen","stakeYen",
               "paidYen","preRaceExpectedCashPer100")
        w=csv.DictWriter(f,fieldnames=names);w.writeheader();w.writerows(outs)
    print("CASH_ALLOCATION_ALL_PERIODS",json.dumps({
        "testedResearchPolicies":len(records),
        "chosenPriorTo2023":output["pre2023Chosen"],
        "forwardAggregate":combined,
        "yearly":report,
        "passesWholeHorizon200":passed,
        "seconds":output["seconds"]
    },ensure_ascii=False),flush=True)

if __name__=="__main__":main()
