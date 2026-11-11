#!/usr/bin/env python3
"""Research-only chronological complementary rule-pair cash search.

Search is over PAIRS of historical payout-mined conditions, not individual
yearly 200%-ROI classifiers. Each pair must cover distinct betting markets
in the same race. Pair choices are frozen using strictly prior-year cash.
"""
import csv,gzip,json,sys,math
from pathlib import Path
from collections import Counter
import numpy as np
import importlib.util

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("marginal",ROOT/"scripts/research-nov2026-marginal-portfolio-cash.py")
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
wf=m.wf
base=m.base
OUT=ROOT/"analysis-results/nov2026-pair-complement-cash.json"
BETS=ROOT/"analysis-results/nov2026-pair-complement-bets.csv.gz"
WINDOWS=(3,5,99)
# Predeclared finite space: 12 highest-support rules per season, all unordered pairs,
# then up to 8 jointly beneficial pairs; not an individual ROI acceptance filter.
TOP_SUPPORT=16
MAX_PAIR_CANDIDATES=40
MAX_PAIRS=8

def metric(picks,program_days):
    x=base.cash_metrics(picks)
    if not picks:return -1e12
    count=Counter((b["day"],b["venue"]) for b in picks)
    coverage3=sum(v>=3 for v in count.values())/max(1,program_days)
    coverage5=sum(v>=5 for v in count.values())/max(1,program_days)
    robust=x["minusMaxRaceRoiPct"]
    return (robust-100)*math.sqrt(x["races"])*(0.15+0.35*coverage3+0.5*coverage5)

def main():
    rules=base.load_premine()
    data=base.obtain_rows()
    races,cash,cats,widths,types,rid,year,quarter,joint=data
    yrow=year[rid];qrow=quarter[rid]
    enc={};indices=[]
    for i,r in enumerate(rules):
        fields=r["fields"]
        if fields not in enc:enc[fields]=joint.mixed(types,cats,widths,fields)[0]
        mask=enc[fields]==r["code"]
        tr=mask&np.isin(yrow,base.TRAIN_YEARS)
        if int(tr.sum())!=r["n"] or int(cash[tr].sum(dtype=np.int64))!=r["paid"]:
            raise RuntimeError("SOURCE_RULE_MISMATCH:"+str(i))
        indices.append(np.flatnonzero(mask).astype(np.int32))
    outputs=[];report={}
    for target in range(2023,2027):
        options=[]
        for win in WINDOWS:
            lo=max(2017,target-win)
            days=len(m.program_days(races,lo,target-1))
            # Candidate pair must overlap in race but belong to distinct markets.
            # Market identity comes from the fixed historical rule artifact.
            pair_pool=[]
            for q in range(1,5):
                ranked=[]
                for i,idx in enumerate(indices):
                    h=idx[(yrow[idx]>=lo)&(yrow[idx]<target)&(qrow[idx]==q)]
                    if len(h)>=10:ranked.append((len(h),i))
                ranked.sort(key=lambda z:(-z[0],z[1]))
                # Diversity across bet markets is mandatory: the highest
                # raw-support rules otherwise cluster in one market, and
                # same-market pairs can never be purchased together.
                top=[];market_support=Counter()
                for support,i in ranked:
                    market=rules[i]["market"]
                    if market_support[market]>=4:continue
                    top.append(i);market_support[market]+=1
                    if len(top)>=TOP_SUPPORT:break
                for a in range(len(top)):
                    for b in range(a+1,len(top)):
                        i,j=top[a],top[b]
                        if rules[i]["market"]==rules[j]["market"]:continue
                        # Pair interaction is the intersection of their supported races,
                        # while keeping the individual market ticket positions.
                        ia=indices[i][qrow[indices[i]]==q]
                        ib=indices[j][qrow[indices[j]]==q]
                        ra=np.unique(rid[ia]);rb=np.unique(rid[ib])
                        common=np.intersect1d(ra,rb,assume_unique=True)
                        if not len(common):continue
                        ai=ia[np.isin(rid[ia],common)]
                        bj=ib[np.isin(rid[ib],common)]
                        if not len(ai) or not len(bj):continue
                        pair_pool.append((q,i,j,ai,bj))
            # Rank pair candidates using support only, never future payouts.
            # This bounds the true-cash portfolio search while preserving
            # multi-market and quarterly candidates.
            pair_pool.sort(key=lambda x:(-min(len(x[3]),len(x[4])),x[0],x[1],x[2]))
            pair_pool=pair_pool[:MAX_PAIR_CANDIDATES]
            votes=np.zeros(len(cash),dtype=np.float32)
            chosen=[];baseline=-1e12
            for step in range(MAX_PAIRS):
                best=None
                for k,(q,i,j,ai,bj) in enumerate(pair_pool):
                    if k in chosen:continue
                    votes[ai]+=1;votes[bj]+=1
                    picks=m.fast_select(votes,data,year_min=lo,year_max=target-1)
                    score=metric(picks,days)
                    votes[ai]-=1;votes[bj]-=1
                    if best is None or score>best[0]:best=(score,k)
                if best is None or best[0]<=baseline+1e-7:break
                baseline,k=best;chosen.append(k)
                _,_,_,ai,bj=pair_pool[k]
                votes[ai]+=1;votes[bj]+=1
            training=m.fast_select(votes,data,year_min=lo,year_max=target-1)
            options.append((metric(training,days),win,votes,chosen,pair_pool,base.cash_metrics(training)))
        _,win,votes,chosen,pair_pool,training=max(options,key=lambda z:(z[0],-z[1]))
        forward=m.fast_select(votes,data,year_min=target,year_max=target)
        outputs.extend({"selectionYear":target,**b} for b in forward)
        count=Counter((b["day"],b["venue"]) for b in forward)
        report[str(target)]={"lookbackYears":win,
          "selectedPairs":[{"quarter":pair_pool[k][0],"ruleA":pair_pool[k][1],"ruleB":pair_pool[k][2]} for k in chosen],
          "trainingCash":training,"forwardCash":base.cash_metrics(forward),
          "programDays":len(m.program_days(races,target,target)),
          "daysAtLeast3":sum(v>=3 for v in count.values()),
          "daysAtLeast5":sum(v>=5 for v in count.values())}
        print("PAIR_COMPLEMENT_YEAR",target,json.dumps(report[str(target)]["forwardCash"]),flush=True)
    result={"researchOnly":True,"method":"prior-year paired market complement cash",
      "independentJraPayoutVerified":False,"officialT15Verified":False,
      "futureBlind2025And2026":False,"adoptable":False,
      "selectionUsesOnlyPriorYearSettlements":True,
      "requiresTwoDifferentMarketsPerRace":True,
      "years":report,"combined":base.cash_metrics(outputs)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    with gzip.open(BETS,"wt",encoding="utf-8",newline="") as f:
        fields=("selectionYear","raceId","day","venue","month","year","quarter","market1","market2","ticket1","ticket2","paidYen","payout1Yen","payout2Yen")
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(outputs)
    print("PAIR_COMPLEMENT_FINAL",json.dumps(result["combined"]),flush=True)

if __name__=="__main__":main()
