#!/usr/bin/env python3
"""Research-only marginal cash ensemble. Historical outcomes NEVER select same-year tickets.
Select rule bundles by marginal portfolio cash, not individual-rule ROI.
"""
import csv,gzip,json,sys,math
from pathlib import Path
from collections import Counter
import numpy as np
import importlib.util
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wf",ROOT/"scripts/research-nov2026-walkforward-joint-cash.py")
wf=importlib.util.module_from_spec(spec);sys.modules[spec.name]=wf;spec.loader.exec_module(wf)
base=wf.base
OUT=ROOT/"analysis-results/nov2026-marginal-portfolio-cash.json"
BETS=ROOT/"analysis-results/nov2026-marginal-portfolio-bets.csv.gz"
WINDOWS=(3,5,99)
MAX_STEPS=24
def stats(bets):
    return base.cash_metrics(bets)
def program_days(races,lo,hi):
    return {(r["day"],r["venue"]) for r in races if lo<=int(r["month"][:4])<=hi}
def objective(bets,days):
    s=stats(bets)
    if not bets:return -1e8
    coverage=Counter((b["day"],b["venue"]) for b in bets)
    n3=sum(v>=3 for v in coverage.values())
    n5=sum(v>=5 for v in coverage.values())
    # Cash-based objective with explicit concentration and coverage penalties.
    return (s["minusMaxRaceRoiPct"]-100)*math.sqrt(s["races"])*(0.1+0.4*n3/max(days,1)+0.5*n5/max(days,1))
def main():
    rules=base.load_premine()
    data=base.obtain_rows()
    races,cash,cats,widths,types,rid,year,quarter,joint=data
    yrow=year[rid];qrow=quarter[rid]
    encoded={};indices=[]
    for i,r in enumerate(rules):
        fields=r["fields"]
        if fields not in encoded:encoded[fields]=joint.mixed(types,cats,widths,fields)[0]
        mask=encoded[fields]==r["code"]
        tr=mask&np.isin(yrow,base.TRAIN_YEARS)
        if int(tr.sum())!=r["n"] or int(cash[tr].sum(dtype=np.int64))!=r["paid"]:
            raise RuntimeError("SOURCE_RULE_MISMATCH:"+str(i))
        indices.append(np.flatnonzero(mask).astype(np.int32))
    reports={};forward=[]
    for target in range(2023,2027):
        # Each target year uses ONLY prior-year settlements; no future-year payout access.
        candidates=[]
        for win in WINDOWS:
            lo=max(2017,target-win)
            days=len(program_days(races,lo,target-1))
            votes=np.zeros(len(cash),dtype=np.float32)
            selected=[];baseline=-1e8
            # Greedy joint cash selection: adding a rule may improve or hurt
            # total cash, including ticket deduplication and two-market choice.
            # Limit candidates using historical ticket support only, not forward results.
            ranked=[]
            for i,idx in enumerate(indices):
                hist=idx[(yrow[idx]>=lo)&(yrow[idx]<target)]
                if len(hist)<20:continue
                for q in range(1,5):
                    h=hist[qrow[hist]==q]
                    if len(h)<10:continue
                    # Only a prefilter for compute budget; no ROI threshold.
                    ranked.append((len(h),i,q))
            ranked.sort(reverse=True)
            ranked=ranked[:240]
            for step in range(MAX_STEPS):
                best=None
                for support,i,q in ranked:
                    if (i,q) in selected:continue
                    idx=indices[i];idx=idx[qrow[idx]==q]
                    votes[idx]+=1
                    picks=wf.select(votes,data,year_min=lo,year_max=target-1)
                    score=objective(picks,days)
                    votes[idx]-=1
                    if best is None or score>best[0]:
                        best=(score,i,q)
                if best is None or best[0]<=baseline+1e-7:break
                baseline,i,q=best
                idx=indices[i];idx=idx[qrow[idx]==q]
                votes[idx]+=1
                selected.append((i,q))
            training=wf.select(votes,data,year_min=lo,year_max=target-1)
            candidates.append((objective(training,days),win,votes,selected,stats(training)))
        _,win,votes,selected,training=max(candidates,key=lambda x:(x[0],-x[1]))
        bought=wf.select(votes,data,year_min=target,year_max=target)
        for b in bought:forward.append({"selectionYear":target,**b})
        all_days=program_days(races,target,target)
        counts=Counter((b["day"],b["venue"]) for b in bought)
        reports[str(target)]={"window":win,"selectedRuleQuarterPairs":selected,
          "trainingCash":training,"forwardCash":stats(bought),
          "programDays":len(all_days),"daysAtLeast3":sum(n>=3 for n in counts.values()),
          "daysAtLeast5":sum(n>=5 for n in counts.values())}
        print("MARGINAL_CASH_YEAR",json.dumps({"year":target,"cash":stats(bought),"rules":len(selected)},ensure_ascii=False),flush=True)
    summary={"researchOnly":True,"independentJraPayoutVerified":False,
      "officialT15Verified":False,"futureBlind2025And2026":False,
      "cashObjective":"marginal deduplicated portfolio minus-largest-race ROI times coverage",
      "maxRules":MAX_STEPS,"windowChoices":WINDOWS,
      "yearly":reports,"forwardCombined":stats(forward),"adoptable":False}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    with gzip.open(BETS,"wt",encoding="utf8",newline="") as f:
        columns=("selectionYear","raceId","day","venue","month","year","quarter","market1","market2","ticket1","ticket2","paidYen","payout1Yen","payout2Yen")
        w=csv.DictWriter(f,fieldnames=columns,extrasaction="ignore");w.writeheader();w.writerows(forward)
    print("MARGINAL_CASH_FINAL",json.dumps(summary["forwardCombined"],ensure_ascii=False),flush=True)
if __name__=="__main__":main()
