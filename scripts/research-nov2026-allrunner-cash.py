#!/usr/bin/env python3
"""All-runner bounded cash discovery: 18-runner 6-market ticket enumeration.

Enumerate every purchasable rank tuple for each available field (10..18
runners) from third-party payout archives, then all 255 nonempty subsets of
eight pre-result categorical attributes (six JRA markets and EVERY observed
categorical cell). Candidate conditions/portfolio recipes use only 2015-22.
Evaluate frozen policies on 2023,24,25,26-JanApr. Never use payouts as input.
Not official JRA T-15 odds or independently JRA-verified payout evidence.
"""
from __future__ import annotations
from itertools import combinations,permutations
from pathlib import Path
from collections import defaultdict,Counter
import csv,gzip,importlib.util,json,math,sys,time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-allrunner-conditional-cash.json"
BETS=ROOT/"analysis-results/nov2026-allrunner-conditional-bets.csv.gz"
RULES=ROOT/"analysis-results/nov2026-allrunner-conditional-rules.csv.gz"
DIMS=(6,5,5,4,10,3,4,3,6)
NAMES=("market","rankMinBand","rankMaxBand","rankGapBand","venue",
       "fieldSizeBand","quarter","raceNumberBand","ticketOddsGeomBand")
UNORDERED={1,2,4}
YEAR_TEST=(2023,2024,2025,2026)
KEEP=(70,200,500)
HIT_WEIGHT=(0.,0.5,2.0)
POOLS=((0,1,2,3,4,5),(1,2,3,4,5),(2,3,4,5))
RACE_LIMIT=(3,5)
OVERLAY_STAKE=(100,500,2000)
MIN_TRAIN=75
MIN_VALID=25

def source():
    spec=importlib.util.spec_from_file_location(
        "allrunner_cash_archive",ROOT/"scripts/research-nov2026-decade-roi-first-sixmarkets.py")
    a=importlib.util.module_from_spec(spec);sys.modules[spec.name]=a;spec.loader.exec_module(a)
    pay=importlib.util.spec_from_file_location(
        "allrunner_cash_payparser",ROOT/"scripts/research-nov2026-sixmarket-real-paid-cash.py")
    b=importlib.util.module_from_spec(pay);sys.modules[pay.name]=b;pay.loader.exec_module(b)
    return a,b

def tickets(n):
    result=[]
    for market in range(6):
        if market==0:opts=[(i,) for i in range(n)]
        elif market in (1,2):opts=list(combinations(range(n),2))
        elif market==3:opts=list(permutations(range(n),2))
        elif market==4:opts=list(combinations(range(n),3))
        else:opts=list(permutations(range(n),3))
        idx=np.asarray(opts,dtype=np.int16)
        lookup={tuple(t):k for k,t in enumerate(opts)}
        result.append((idx,lookup))
    return result

def features(r,templates):
    h=r["horses"]
    n=len(h)
    no2rank={int(x[0]):i for i,x in enumerate(h)}
    prices=np.log(np.maximum(1.,np.asarray([x[1] for x in h],np.float64)))
    field=int(np.digitize(n,[12,15]))
    venue=int(r["venue"])-1
    q=(int(r["month"][4:])-1)//3
    band=(int(r["raceNo"])-1)//4
    codes=[];pays=[]
    for market,(pos,lookup) in enumerate(templates):
        lower=pos.min(axis=1)
        upper=pos.max(axis=1)
        diff=upper-lower
        minb=np.digitize(lower,[1,3,6,10])
        maxb=np.digitize(upper,[1,3,6,10])
        gapb=np.digitize(diff,[1,3,6])
        g=np.exp(prices[pos].mean(axis=1))
        odds=np.digitize(g,[2.5,4.5,8,16,40])
        num=len(pos)
        codes.append(np.ravel_multi_index((
            np.full(num,market),minb,maxb,gapb,
            np.full(num,venue),np.full(num,field),np.full(num,q),
            np.full(num,band),odds),DIMS).astype(np.int32))
        pay=np.zeros(num,dtype=np.int32)
        for horses,amount in r["payout"][market].items():
            if not all(int(x) in no2rank for x in horses):continue
            ranks=tuple(no2rank[int(x)] for x in horses)
            if market in UNORDERED:ranks=tuple(sorted(ranks))
            loc=lookup.get(ranks)
            if loc is not None:pay[loc]+=int(amount)
        pays.append(pay)
    return codes,pays

def metrics(rows):
    stake=sum(int(r["stakeYen"]) for r in rows)
    received=sum(int(r["paidYen"]) for r in rows)
    largest=max((int(r["paidYen"]) for r in rows),default=0)
    hit=sum(int(r["paidYen"]>0) for r in rows)
    return dict(races=len(rows),stakeYen=stake,paidYen=received,
        roiPct=round(100*received/stake,5) if stake else None,
        minusMaxRaceRoiPct=round(100*(received-largest)/stake,5) if stake else None,
        hitRacePct=round(100*hit/len(rows),5) if rows else None,
        biggestPaidRaceYen=largest)

def mine(h):
    count,raw,capped,hits=h
    state=[x.reshape(DIMS) for x in (count[0],count[1],raw[0],raw[1],
                capped[0],capped[1],hits[0],hits[1])]
    candidates=[];audit=Counter()
    for mask in range(1,256):
        cols=tuple(i for i in range(1,len(DIMS)) if mask&(1<<(i-1)))
        omit=tuple(i for i in range(1,len(DIMS)) if i not in cols)
        n0,n1,p0,p1,c0,c1,h0,h1=[
            x.sum(axis=omit,dtype=np.int64) if omit else x for x in state]
        support=(n0>=MIN_TRAIN)&(n1>=MIN_VALID)&(h0>=3)&(h1>=1)
        audit["schemas"]+=1
        audit["observedValueMarketCells"]+=int(np.count_nonzero(n0))
        audit["supportedCells"]+=int(np.count_nonzero(support))
        valid=np.flatnonzero(support.ravel())
        if not len(valid):continue
        nn=n0.ravel()[valid];nv=n1.ravel()[valid]
        ctrain=c0.ravel()[valid]/(100*nn)
        cvalid=c1.ravel()[valid]/(100*nv)
        htrain=h0.ravel()[valid]/nn
        hvalid=h1.ravel()[valid]/nv
        reliability=np.sqrt(nn/(nn+250.))*np.sqrt(nv/(nv+100.))
        cash_score=(np.minimum(ctrain,12.)+np.minimum(cvalid,12.))/2*reliability
        hit_score=(htrain+hvalid)/2*reliability
        chosen=set()
        for value in (cash_score,hit_score):
            k=min(len(valid),10)
            chosen.update(int(x) for x in np.argpartition(value,-k)[-k:])
        shape=n0.shape
        for offset in chosen:
            idx=int(valid[offset]);coordinates=np.unravel_index(idx,shape)
            market=int(coordinates[0])
            candidates.append(dict(market=market,columns=cols,
               values=tuple(int(x) for x in coordinates[1:]),
               trainCount=int(nn[offset]),validCount=int(nv[offset]),
               trainPaidYen=int(p0.ravel()[valid[offset]]),
               validPaidYen=int(p1.ravel()[valid[offset]]),
               trainHits=int(h0.ravel()[valid[offset]]),
               validHits=int(h1.ravel()[valid[offset]]),
               cashScore=float(cash_score[offset]),
               hitScore=float(hit_score[offset])))
        if mask%32==0:print("ALLRUNNER_CASH_CONDITION_PROGRESS",mask,flush=True)
    # Balanced market-specific retained rules, with bounded tail cash scores.
    keep=[]
    for m in range(6):
        c=[r for r in candidates if r["market"]==m]
        for score in ("cashScore","hitScore"):
            keep.extend(sorted(c,key=lambda z:(-z[score],-z["trainCount"]))[:650])
    uniques={}
    for r in keep:uniques[(r["market"],r["columns"],r["values"])]=r
    out=list(uniques.values())
    audit["candidateCashOrHitCells"]=len(candidates)
    audit["retainedDistinctRules"]=len(out)
    audit["theoreticalCategoricalValueAssignments"]=6*(
        math.prod(1+DIMS[i] for i in range(1,len(DIMS)))-1)
    return out,dict(audit)

def lookup_rules(rules,lim):
    # Build direct pre-race lookup for every rank-combination, including
    # rank 11-18; all conditions were selected using <=2022 money.
    a=np.zeros(DIMS,dtype=np.float32)
    b=np.zeros(DIMS,dtype=np.float32)
    for m in range(6):
        cohort=[r for r in rules if r["market"]==m]
        picks={}
        for score in ("cashScore","hitScore"):
            for r in sorted(cohort,key=lambda x:-x[score])[:lim]:
                picks[(r["columns"],r["values"])]=r
        for r in picks.values():
            sl=[slice(None)]*len(DIMS);sl[0]=m
            for col,v in zip(r["columns"],r["values"]):sl[col]=v
            sl=tuple(sl)
            a[sl]+=min(7.,r["cashScore"])
            b[sl]+=min(1.,r["hitScore"])*5
    return a.ravel(),b.ravel()

def pick(races,bundles,idx,financial,hit,blend,pool):
    days=defaultdict(list)
    for i in idx:
        i=int(i)
        race=races[i]
        codes,payout=bundles[i]
        available=[]
        for m in range(6):
            choices=codes[m]
            score=financial[choices]+blend*hit[choices]
            chosen=int(np.argmax(score))
            available.append((float(score[chosen]),m,
                int(payout[m][chosen]),chosen))
        first=max(available[:3],key=lambda v:(v[0],-v[1]))
        nexts=[p for p in available if p[1]!=first[1] and p[1] in pool]
        if not nexts:raise RuntimeError("SECOND_MARKET_NOT_AVAILABLE")
        second=max(nexts,key=lambda v:(v[0],-v[1]))
        year=int(race["month"][:4])
        x=dict(raceId=str(race["id"]),day=str(race["day"]),
         venue=str(race["venue"]),year=year,
         marketA=first[1],marketB=second[1],
         ticketA=first[3],ticketB=second[3],
         basePayPer100Yen=first[2],overlayPayPer100Yen=second[2],
         preRaceScore=float(first[0]+second[0]))
        days[(x["day"],x["venue"])].append(x)
    for key in days:
        days[key].sort(key=lambda z:(-z["preRaceScore"],z["raceId"]))
    return days

def settle(days,rc,second):
    rows=[]
    for group in days.values():
        for r in group[:rc]:
            x=r.copy()
            x["stakeYen"]=100+second
            x["paidYen"]=int(r["basePayPer100Yen"]+r["overlayPayPer100Yen"]*(second//100))
            rows.append(x)
    return rows

def main():
    if "--self-test" in sys.argv:
        assert len(tickets(18)[5][0])==18*17*16
        assert sum(len(x[0]) for x in tickets(18))==6342
        assert metrics([dict(stakeYen=200,paidYen=500),
                        dict(stakeYen=200,paidYen=100)])["minusMaxRaceRoiPct"]==25.
        toy={"horses":[(1,2.,4,56.),(2,3.,4,56.),(3,4.,4,56.)],
          "venue":1,"month":"202201","raceNo":1,
          "payout":[{(1,):200},{(1,2):300},{(1,2):400},{(1,2):500},{(1,2,3):600},{(1,2,3):700}]}
        cod,pay=features(toy,tickets(3))
        assert sum(len(a) for a in cod)==sum(len(a) for a in pay)==3+3+3+6+1+6
        assert [sum(x) for x in pay]==[200,300,400,500,600,700]
        print("ALLRUNNER_ACTUAL_CASH_SELFTEST_OK",flush=True);return
    start=time.monotonic()
    sourcemod,parser=source()
    races=sourcemod.read_all_races(parser.parse_payments)
    n=len(races)
    if n<25000:raise RuntimeError("MISSING_HISTORICAL_FULL_RUNNER_UNIVERSE")
    templates={field:tickets(field) for field in range(10,19)}
    # Two chronological discovery periods; no 2023+ settlement used here.
    size=int(np.prod(DIMS))
    count=np.zeros((2,size),dtype=np.int32)
    raw=np.zeros((2,size),dtype=np.int64)
    capped=np.zeros((2,size),dtype=np.int64)
    hits=np.zeros((2,size),dtype=np.int32)
    bundles={}
    years=np.asarray([int(r["month"][:4]) for r in races],dtype=np.int16)
    stage=Counter()
    for i,r in enumerate(races):
        codes,pays=features(r,templates[len(r["horses"])])
        yr=int(years[i])
        slot=(0 if 2015<=yr<=2020 else 1 if 2021<=yr<=2022 else -1)
        if slot>=0:
            for code,pay in zip(codes,pays):
                np.add.at(count[slot],code,1)
                positive=pay>0
                if np.any(positive):
                    np.add.at(raw[slot],code[positive],pay[positive])
                    np.add.at(capped[slot],code[positive],
                         np.minimum(30000,pay[positive]))
                    np.add.at(hits[slot],code[positive],1)
        else:bundles[i]=(codes,pays)
        if yr in (2021,2022):bundles[i]=(codes,pays)
        stage[str(yr)]+=1
        if (i+1)%5000==0:print("ALLRUNNER_CASH_TICKET_ENUMERATION",i+1,n,flush=True)
    rules,discovery=mine((count,raw,capped,hits))
    if len(rules)<100:raise RuntimeError("INSUFFICIENT_ALL_RUNNER_CANDIDATE_RULES")
    validations=np.flatnonzero((years>=2021)&(years<=2022))
    holdout=np.flatnonzero(years>=2023)
    templates_cache={k:lookup_rules(rules,k) for k in KEEP}
    comparisons=[]
    winner=None
    for k,(cash_score,hit_score) in templates_cache.items():
        for blend in HIT_WEIGHT:
          for pool in POOLS:
            days=pick(races,bundles,validations,cash_score,hit_score,blend,pool)
            for rc in RACE_LIMIT:
              for extra in OVERLAY_STAKE:
                val=settle(days,rc,extra)
                each={y:metrics([x for x in val if x["year"]==y]) for y in (2021,2022)}
                allstats=metrics(val)
                if min(each[y]["races"] for y in (2021,2022))<300:continue
                # Optimize WORST validation year after removing largest paid
                # race. All input cash is dated before 2023.
                floor=min(each[y]["minusMaxRaceRoiPct"] for y in (2021,2022))
                if min(each[y]["hitRacePct"] for y in (2021,2022))<20:floor-=100
                key=(floor,allstats["minusMaxRaceRoiPct"],allstats["hitRacePct"])
                recipe=(k,blend,pool,rc,extra)
                comparisons.append({"recipe":recipe,"rank":key})
                if winner is None or key>winner[0]:winner=(key,recipe,each,allstats)
    if winner is None:raise RuntimeError("NO_VALID_PRE2023_MONEY_POLICY")
    k,blend,pool,rc,extra=winner[1]
    days=pick(races,bundles,holdout,*templates_cache[k],blend,pool)
    final=settle(days,rc,extra)
    yearly={str(y):metrics([r for r in final if r["year"]==y]) for y in YEAR_TEST}
    combined=metrics(final)
    program=Counter((r["day"],r["venue"]) for r in final)
    observed={(races[i]["day"],str(races[i]["venue"])) for i in holdout}
    coverage={"observedVenueDays":len(observed),
      "with3to5R":sum(3<=program[d]<=5 for d in observed),
      "with5R":sum(program[d]==5 for d in observed),
      "under3R":sum(program[d]<3 for d in observed)}
    gate=bool(combined["minusMaxRaceRoiPct"] is not None and
        combined["minusMaxRaceRoiPct"]>=200 and
        combined["hitRacePct"] is not None and combined["hitRacePct"]>=20 and
        all(yearly[str(y)]["minusMaxRaceRoiPct"] is not None and
            yearly[str(y)]["minusMaxRaceRoiPct"]>=200 for y in YEAR_TEST) and
        coverage["under3R"]==0)
    RULES.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(RULES,"wt",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=["market","columns","values","trainCount","validCount",
         "trainPaidYen","validPaidYen","trainHits","validHits","cashScore","hitScore"])
        w.writeheader()
        for r in rules:
            x=dict(r);x["columns"]=",".join(NAMES[i] for i in r["columns"])
            x["values"]=",".join(str(i) for i in r["values"])
            w.writerow(x)
    with gzip.open(BETS,"wt",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=list(final[0]) if final else ["raceId"])
        w.writeheader();w.writerows(final)
    report={"researchOnly":True,"adoptable":False,
      "cashGateSatisfiedOnHistoricalMirror":gate,
      "officialJraT15Verified":False,
      "independentJraPayoutVerification":False,
      "2026DataEndsAtApril":True,
      "venueDaysAgainstAllOfficialDatesUnverified":True,
      "2025And2026PreviouslyInspected":True,
      "productionChanged":False,
      "all18RunnerMarketsLegalTicketEnumeration":True,
      "possibleTicketsFor18Runners":6342,
      "races":len(races),"yearCounts":dict(stage),
      "conditionAxes":list(NAMES),"everyNonemptySubsetOfEightAxes":255,
      "discovery":discovery,"rulesRetained":len(rules),
      "cashPortfolioRecipesEvaluatedBefore2023":len(comparisons),
      "frozenBefore2023":{"topK":k,"hitWeight":blend,"overlayMarketPool":pool,
          "racesPerVenueDay":rc,"overlayStakeYen":extra,
          "validationYearCash":winner[2]},
      "yearly":yearly,"combined":combined,"coverage":coverage,
      "seconds":round(time.monotonic()-start,1)}
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("ALLRUNNER_EXHAUSTIVE_CASH_FINAL",json.dumps({
      "discovery":discovery,"portfolioConfigs":len(comparisons),
      "cashGate":gate,"combined":combined,
      "yearly":yearly,"coverage":coverage,"seconds":report["seconds"]},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
