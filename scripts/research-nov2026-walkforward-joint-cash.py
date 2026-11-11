#!/usr/bin/env python3
"""Chronological joint-cash portfolio: year t selected solely from years < t.
Research only: mirrored payouts not independently JRA checked; no official T-15 odds.
"""
import csv,gzip,json,math,sys
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
import importlib.util
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("base",ROOT/"scripts/research-nov2026-seasonal-ensemble-cash-first.py")
base=importlib.util.module_from_spec(spec);sys.modules[spec.name]=base;spec.loader.exec_module(base)
OUT=ROOT/"analysis-results/nov2026-walkforward-joint-cash.json"
BETS=ROOT/"analysis-results/nov2026-walkforward-joint-bets.csv.gz"
# Explicit finite search; all choices evaluated on past cash only.
POOL=(4,8,16,32,64,128)
WINDOW=(3,5,99)
MIN_SUPPORT=20
def main():
    rules=base.load_premine()
    data=base.obtain_rows()
    races,cash,cats,widths,types,rid,year,quarter,joint=data
    yrow=year[rid];qrow=quarter[rid]
    encoded={}
    masks=[]
    for i,r in enumerate(rules):
        fields=r["fields"]
        if fields not in encoded:
            encoded[fields]=joint.mixed(types,cats,widths,fields)[0]
        mask=encoded[fields]==r["code"]
        # Verify fixed original training artifact without using future data.
        tr=mask&np.isin(yrow,base.TRAIN_YEARS)
        if int(tr.sum())!=r["n"] or int(cash[tr].sum(dtype=np.int64))!=r["paid"]:
            raise RuntimeError("SOURCE_CASH_MISMATCH:"+str(i))
        masks.append(np.flatnonzero(mask).astype(np.int32))
    outputs=[];diagnostics={};previous={}
    for target in range(2023,2027):
        eligible_years=list(range(2017,target))
        year_choices={}
        # Selection of global portfolio hyperparameters by chronological
        # rolling pseudo-outcomes entirely before target year.
        for win in WINDOW:
            lo=max(2017,target-win)
            historical=np.arange(lo,target)
            scores={}
            for q in range(1,5):
                ranked=[]
                for i,idx in enumerate(masks):
                    pos=idx[(qrow[idx]==q)&np.isin(yrow[idx],historical)]
                    n=len(pos)
                    if n<MIN_SUPPORT:continue
                    paid=int(cash[pos].sum(dtype=np.int64))
                    mx=base.max_race(cash[pos],rid[pos])
                    robust=100*(paid-mx)/(100*n)
                    if robust<100:continue
                    # Joint selection score penalizes concentrated single-race wins.
                    ranked.append((robust*math.log1p(n),i,n,paid))
                ranked.sort(reverse=True)
                scores[q]=ranked
            for pool in POOL:
                # Frozen past-only votes, deduplicated by ticket and market.
                votes=np.zeros(len(cash),dtype=np.float32)
                for q,ranked in scores.items():
                    for strength,i,n,paid in ranked[:pool]:
                        idx=masks[i]
                        ix=idx[qrow[idx]==q]
                        votes[ix]+=min(strength,3000)/3000
                # Only past-year settlements are used to score configurations.
                bets=select(votes,data,year_min=lo,year_max=target-1)
                metrics=base.cash_metrics(bets)
                days=len({(r["day"],r["venue"]) for r in races if lo<=int(r["month"][:4])<target})
                full=sum(n>=5 for n in Counter((b["day"],b["venue"]) for b in bets).values())
                coverage=full/max(days,1)
                # Joint cash objective (not individual-cell ROI), conservative max payout.
                score=((metrics["minusMaxRaceRoiPct"] or 0)-100)*math.sqrt(max(1,metrics["races"]))*(0.25+0.75*coverage)
                year_choices[(win,pool)]=(score,votes,metrics,coverage,{q:len(v) for q,v in scores.items()})
        winner=max(year_choices,key=lambda x:(year_choices[x][0],-x[0],-x[1]))
        score,votes,train_cash,coverage,counts=year_choices[winner]
        forward=select(votes,data,year_min=target,year_max=target)
        summary=base.cash_metrics(forward)
        diagnostics[str(target)]={"selectionWindowYears":winner[0],"poolPerQuarter":winner[1],
            "trainingJointCash":train_cash,"trainingCoverageFiveR":coverage,
            "trainingScore":round(score,5),"historicalEligibleRulesPerQuarter":counts,
            "forwardCash":summary}
        for b in forward:outputs.append({"selectionYear":target,**b})
        print("WALKFORWARD_YEAR",json.dumps(diagnostics[str(target)],ensure_ascii=False),flush=True)
    combined=base.cash_metrics(outputs)
    day_counts=Counter((b["day"],b["venue"]) for b in outputs)
    days={ (r["day"],r["venue"]) for r in races if int(r["month"][:4])>=2023 }
    summary={"researchOnly":True,"source":"third-party cash CSV, JRA independent reconciliation incomplete",
      "officialT15Verified":False,"historicalFinalOddsNotT15":True,"stakePerRaceYen":200,
      "candidateRules":len(rules),"searchSpace":{"windows":list(WINDOW),"poolSizes":list(POOL),
      "portfolioChoicesPerYear":len(WINDOW)*len(POOL)},
      "yearly":diagnostics,"forwardCombined":combined,
      "coverage":{"allProgramDays":len(days),"daysAtLeast3":sum(n>=3 for n in day_counts.values()),
                  "daysAtLeast5":sum(n>=5 for n in day_counts.values()),
                  "daysUnder3":len(days)-sum(n>=3 for n in day_counts.values())},
      "adoptable":False,"note":"No adoption without independent official payout and official T-15 verification"}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    with gzip.open(BETS,"wt",encoding="utf8",newline="") as f:
        fields=("selectionYear","raceId","day","venue","month","year","quarter","market1","market2","ticket1","ticket2","stakeYen","paidYen","payout1Yen","payout2Yen")
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(outputs)
    print("WALKFORWARD_FINAL",json.dumps({"combined":combined,"coverage":summary["coverage"],"artifact":str(OUT)},ensure_ascii=False),flush=True)
def select(votes,data,year_min,year_max):
    races,cash,cat,widths,types,rid,year,quarter,joint=data
    market_ranges=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
    groups=defaultdict(list)
    for i,r in enumerate(races):
        yr=int(r["month"][:4])
        if not year_min<=yr<=year_max:continue
        start=i*336
        options=[]
        for m,(a,b) in enumerate(market_ranges):
            v=votes[start+a:start+b]
            if not np.any(v>0):continue
            j=int(np.argmax(v));options.append((float(v[j]),m,start+a+j))
        if len(options)<2:continue
        options.sort(key=lambda x:(-x[0],x[1],x[2]))
        p1,p2=options[:2]
        groups[(r["day"],r["venue"])].append({
          "raceId":r["id"],"day":r["day"],"venue":r["venue"],"month":r["month"],
          "year":yr,"quarter":int(quarter[i]),"rankScore":p1[0]+p2[0],
          "market1":base.MARKETS[p1[1]],"market2":base.MARKETS[p2[1]],
          "ticket1":p1[2]-start,"ticket2":p2[2]-start,
          "paidYen":int(cash[p1[2]]+cash[p2[2]]),
          "stakeYen":200,
          "payout1Yen":int(cash[p1[2]]),"payout2Yen":int(cash[p2[2]])})
    out=[]
    for values in groups.values():
        values.sort(key=lambda x:(-x["rankScore"],x["raceId"]))
        out.extend(values[:5])
    return out
if __name__=="__main__":main()
