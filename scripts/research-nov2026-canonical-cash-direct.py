#!/usr/bin/env python3
"""Frozen official-quote canonical-candidate cash-policy discovery (research ONLY).

Crucial apples-to-apples analysis: use exact 14,410 previously published
official-quote candidate race pairs, frozen receipts and exact stake convention.
The historical *candidate model* was fitted to 2016-2026 outcomes; this
retrospective archive is NOT a valid OOF estimate of candidate quality!
This script only evaluates alternative cash allocations and 3-5R slates, each
using training-year payouts BEFORE the target year. It never asserts that
the original historical 431% is prospective or T-15 verified.
No live/D1 writes, no historical changes.
"""
from __future__ import annotations
import base64,collections,gzip,itertools,json,math,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-canonical-direct-money-allocator.json"
LEDGER=ROOT/"analysis-results/nov2026-canonical-direct-money-allocator-bets.jsonl.gz"
BINS=(0,1.5,2.5,4,6,10,16,25,40,65,100,200,400,800,1600,5000,1e18)
BET_TYPES=("単勝","ワイド","馬連","馬単","3連複","3連単")
CONTEXTS=("venue","surface","distance","raceNo","odds","market","slot")
REGIMES=(
 ("market",),
 ("market","odds"),
 ("market","venue"),
 ("market","surface"),
 ("market","distance"),
 ("market","raceNo"),
 ("market","slot"),
 ("market","odds","venue"),
 ("market","odds","surface"),
 ("market","odds","distance"),
 ("market","odds","raceNo"),
 ("market","odds","slot"),
 ("market","surface","distance"),
 ("market","venue","surface"),
 ("market","venue","distance"),
 ("market","venue","raceNo"),
 ("market","odds","surface","distance"),
 ("market","odds","venue","surface"),
 ("market","odds","venue","raceNo"),
 ("market","odds","distance","raceNo"),
 ("market","odds","slot","venue"),
)
PRIORS=(10,40,150,600,2400)
CAPS=(None,10000,30000,100000)
POWER=(0.0,0.5,1.0,2.0,4.0)
SLATES=(3,4,5)
RANKINGS=("both","first","max")
BASE_STAKE=2000
VALID_YEARS=(2021,2022)
TEST_YEARS=(2023,2024,2025,2026)

def load_archive():
    folder=ROOT/"src/v1/ten-year-history-data"
    files=sorted(folder.glob("bin-*.ts"))
    if len(files)!=9:raise RuntimeError(f"EXPECTED_NINE_CANONICAL_CHUNKS:{len(files)}")
    joined=""
    for p in files:
        txt=p.read_text(encoding="utf8").strip()
        if not txt.startswith("export default "):raise RuntimeError("BAD_BASE64_CHUNK")
        joined+=json.loads(txt[len("export default "):].rstrip(";"))
    archive=json.loads(gzip.decompress(base64.b64decode(joined)))
    if archive["start"]!="2016-08-10" or archive["end"]!="2026-08-09":
        raise RuntimeError("CANONICAL_ARCHIVE_ID_MISMATCH")
    if len(archive["races"])!=34566:raise RuntimeError("CANONICAL_CALENDAR_MISMATCH")
    rows=[];days=collections.defaultdict(list)
    for x in archive["races"]:
        if x[8] is None:continue
        if len(x[8])!=2:raise RuntimeError("NOT_TWO_MARKETS")
        if x[8][0][0]==x[8][1][0]:raise RuntimeError("NOT_DISTINCT_MARKETS")
        yy=int(x[1][:4])
        tickets=[]
        for slot,t in enumerate(x[8]):
            bt,combo,odds,returned=t
            if bt not in BET_TYPES or not math.isfinite(float(odds)) or float(odds)<=0:
                raise RuntimeError("INVALID_ARCHIVED_OFFICIAL_BET")
            if int(returned)<0:raise RuntimeError("NEGATIVE_ACTUAL_JRA_CASH")
            odds_class=int(np.searchsorted(BINS,float(odds),side="right")-1)
            tickets.append({"market":bt,"odds":odds_class,"slot":slot,
                            "oddsReal":float(odds),"returnLightYen":int(returned),
                            "combination":combo})
        r={"raceId":str(x[0]),"day":str(x[1]),"year":yy,"venue":str(x[2]),
          "raceNo":int(x[3]),"surface":str(x[6] or "UNKNOWN"),
          "distance":int(x[7] or 0)//400,"tickets":tickets}
        rid=len(rows);rows.append(r);days[(r["day"],r["venue"])].append(rid)
    if len(rows)!=14410 or len(days)!=2882 or any(len(g)!=5 for g in days.values()):
        raise RuntimeError("CANONICAL_FIVE_RACES_PER_VENUE_DAY_BROKEN")
    baseline=sum(t["returnLightYen"] for r in rows for t in r["tickets"])
    if baseline!=124401700:raise RuntimeError(f"CANONICAL_PAYOUT_RECONCILIATION:{baseline}")
    print("CANONICAL_CASH_ARCHIVE_RECONCILED",
          json.dumps({"selectedRaces":len(rows),"venueDays":len(days),
                      "baselineSpent":len(rows)*2000,
                      "baselinePaid":baseline,
                      "baselineRoiPct":100*baseline/(len(rows)*2000)},
                     ensure_ascii=False),flush=True)
    return rows,days

def finance(rows):
    n=len(rows)
    money=sum(r["stakeYen"] for r in rows)
    paid=sum(r["paidYen"] for r in rows)
    maxpaid=max((r["paidYen"] for r in rows),default=0)
    hit=sum(r["paidYen"]>0 for r in rows)
    return dict(races=n,stakeYen=money,paidYen=paid,
      roiPct=round(100*paid/money,6) if money else None,
      minusMaxRaceRoiPct=round(100*(paid-maxpaid)/money,6) if money else None,
      hitRacePct=round(100*hit/n,6) if n else None,
      largestRacePayoutYen=maxpaid)

def ticket_keys(r,t,context):
    return tuple(t.get(k,r.get(k)) for k in context)

def fit(rows,year,regime,cap,prior):
    """All costs use CASH-YEN settlement on pre-target races only."""
    base=collections.defaultdict(lambda:[0,0])
    groups=collections.defaultdict(lambda:[0,0])
    # Training on prior races only. 2016 partial is included.
    for r in rows:
        if r["year"]>=year:continue
        for t in r["tickets"]:
            ret=t["returnLightYen"]
            cash=ret if cap is None else min(ret,cap)
            m=t["market"]
            base[m][0]+=1;base[m][1]+=cash
            k=ticket_keys(r,t,regime)
            groups[k][0]+=1;groups[k][1]+=cash
    if any(base[t][0]<100 for t in BET_TYPES[:2]):
        raise RuntimeError("CANONICAL_CASH_PRIOR_TOO_SMALL")
    market={k:v[1]/(1000*v[0]) for k,v in base.items()}
    return groups,market

def estimate(r,t,regime,trained,prior):
    groups,market=trained
    known=market.get(t["market"],0.8)
    n,ret=groups.get(ticket_keys(r,t,regime),(0,0))
    return max(.01,(ret/1000+prior*known)/(n+prior))

def buy(rows,days,year,regime,trained,prior,power,slate,rank):
    lines=[];groups=collections.defaultdict(list)
    for i in ROW_INDEX_BY_YEAR[year]:
        r=rows[i]
        a,b=(estimate(r,t,regime,trained,prior) for t in r["tickets"])
        score=[a,b]
        # More cash to the ticket expected to repay more in real yen.
        if power==0:
            split=.5
        else:
            ap=a**power;bp=b**power;split=ap/(ap+bp)
        first_stake=100*max(1,min(19,round(split*20)))
        second_stake=2000-first_stake
        receipts=(r["tickets"][0]["returnLightYen"]*first_stake+
                  r["tickets"][1]["returnLightYen"]*second_stake)//1000
        if rank=="both":priority=a+b
        elif rank=="first":priority=a
        else:priority=max(a,b)
        groups[(r["day"],r["venue"])].append(
          (priority,r["raceId"],first_stake,second_stake,receipts,a,b,i))
    for d,g in groups.items():
        for priority,rid,sa,sb,p,a,b,i in sorted(g,key=lambda x:(-x[0],x[1]))[:slate]:
            lines.append({"raceId":rid,"day":d[0],"venue":d[1],"year":year,
               "ticketA":rows[i]["tickets"][0]["market"],
               "ticketB":rows[i]["tickets"][1]["market"],
               "stakeA":sa,"stakeB":sb,"stakeYen":2000,
               "paidYen":int(p),"expectedCashA":round(a,7),
               "expectedCashB":round(b,7),"preRacePriority":round(priority,7)})
    return lines

def main():
    if "--self-test" in sys.argv:
        assert sum(r for r in (100,1900))==2000
        assert finance([{"stakeYen":2000,"paidYen":10000},
                        {"stakeYen":2000,"paidYen":1000}])["minusMaxRaceRoiPct"]==25
        assert len(REGIMES)==21
        print("CANONICAL_DIRECT_CASH_FINANCIAL_SELFTEST_OK",flush=True);return
    tic=time.monotonic()
    rows,days=load_archive()
    global ROW_INDEX_BY_YEAR
    ROW_INDEX_BY_YEAR={y:[i for i,r in enumerate(rows) if r["year"]==y]
        for y in (*VALID_YEARS,*TEST_YEARS)}
    total=len(REGIMES)*len(PRIORS)*len(CAPS)*len(POWER)*len(SLATES)*len(RANKINGS)
    print("CASH_MONEY_RECIPE_SPACE",total,flush=True)
    # A nested, chronological selection test. Hyperparameters chosen ONLY
    # from 2021+2022 payouts, never 2023-26.
    objectives={}
    regime_cache={}
    for year in (*VALID_YEARS,*TEST_YEARS):
        for regime in REGIMES:
            for cap in CAPS:
                # Fitting is independent of prior coefficient.
                regime_cache[(year,regime,cap)]=fit(rows,year,regime,cap,0)
    pre={}
    for regime in REGIMES:
        for cap in CAPS:
            for prior in PRIORS:
                for power in POWER:
                    for slate in SLATES:
                        for rank in RANKINGS:
                            cfg=(regime,cap,prior,power,slate,rank)
                            summaries=[]
                            for y in VALID_YEARS:
                                ledger=buy(rows,days,y,regime,regime_cache[(y,regime,cap)],
                                           prior,power,slate,rank)
                                summaries.append(finance(ledger))
                            if any(x["races"]<400 for x in summaries):continue
                            minimum=min(x["minusMaxRaceRoiPct"] for x in summaries)
                            if min(x["hitRacePct"] for x in summaries)<20:minimum-=100
                            st=sum(x["stakeYen"] for x in summaries)
                            ret=sum(x["paidYen"]-x["largestRacePayoutYen"] for x in summaries)
                            average=100*ret/st
                            pre[cfg]=((minimum,average),summaries)
        print("CANONICAL_CASH_REGIME_FINISHED",REGIMES.index(regime)+1,
              len(REGIMES),len(pre),flush=True)
    if not pre:raise RuntimeError("NO_PRE2023_REGIME_STRATEGIES")
    selected=max(pre,key=lambda x:pre[x][0])
    score,validation=pre[selected]
    regime,cap,prior,power,slate,rank=selected
    print("CANONICAL_CASH_PRE2023_FROZEN",json.dumps({
      "regime":regime,"cap":cap,"prior":prior,"power":power,"slate":slate,
      "rank":rank,"2021":validation[0],"2022":validation[1],
      "recipes":len(pre)},ensure_ascii=False),flush=True)
    holdout=[];by_year={};baseline={}
    for year in TEST_YEARS:
        training=regime_cache[(year,regime,cap)]
        ledger=buy(rows,days,year,regime,training,prior,power,slate,rank)
        holdout.extend(ledger)
        by_year[str(year)]=finance(ledger)
        selected_ids={r["raceId"] for r in ledger}
        base=[{"stakeYen":2000,"paidYen":int(sum(
                  t["returnLightYen"] for t in r["tickets"]))}
              for r in rows if r["year"]==year and r["raceId"] in selected_ids]
        baseline[str(year)]=finance(base)
        print("CANONICAL_CASH_POLICY_EVALUATED",year,json.dumps({
          "discovered":by_year[str(year)],"sameRacesEqualStake":baseline[str(year)]},
          ensure_ascii=False),flush=True)
    summary=finance(holdout)
    all_selected_ids={x["raceId"] for x in holdout}
    base_all=[{"stakeYen":2000,"paidYen":int(sum(
          t["returnLightYen"] for t in r["tickets"]))}
        for r in rows if r["raceId"] in all_selected_ids]
    baseline_same=finance(base_all)
    # Full existing model official-quote universe is exactly verified above;
    # compare same selected race subset and stake ledger without source mix.
    pass_candidate=(summary["minusMaxRaceRoiPct"]>=200 and
         summary["hitRacePct"]>=20 and
         all(by_year[str(y)]["minusMaxRaceRoiPct"]>=200 for y in TEST_YEARS))
    out={"researchOnly":True,
         "disclaimer":"Existing ticket candidates trained on all archived outcomes; cash allocations are year-forward only, but this does not independently OOF-validate the underlying candidate generator",
         "applesToApplesCanonicalSource":True,
         "sourceCandidateModelLookaheadRisk":True,
         "sourceHistoryExactOfficialOddsTimestampT15NotVerified":True,
         "unselectedRacesCannotGenerateNewTickets":True,
         "allTestYearsPreviouslyInspected":True,
         "productionUntouched":True,
         "winnerCashPolicyMeetsRetrospectiveRoiGate":bool(pass_candidate),
         "eligibleForActualModelAdoption":False,
         "discoveredRecipe":{"regime":list(regime),"capYen":cap,
                   "priorTickets":prior,"stakePower":power,
                   "racesPerVenueDay":slate,"raceRankMode":rank},
         "trainedOnPre2023Money":True,
         "searchedAllPrespecifiedRecipes":len(pre),
         "2021And2022Validation":validation,
         "yearly":by_year,"combined":summary,
         "baselineSameRacesYearly":baseline,
         "baselineSameRacesCombined":baseline_same,
         "canonicalFullArchiveEquallyStaked":{"spent":len(rows)*2000,
               "paid":sum(t["returnLightYen"] for r in rows for t in r["tickets"]),
               "roiPct":431.6505898681471},
         "seconds":round(time.monotonic()-tic,1)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    with gzip.open(LEDGER,"wt",encoding="utf8") as f:
        for x in holdout:f.write(json.dumps(x,ensure_ascii=False)+"\n")
    print("CANONICAL_DIRECT_MONEY_FINAL",json.dumps(out,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
