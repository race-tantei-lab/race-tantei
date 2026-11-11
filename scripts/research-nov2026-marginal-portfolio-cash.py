#!/usr/bin/env python3
"""Research-only marginal cash ensemble. Historical outcomes NEVER select same-year tickets.
Select rule bundles by marginal portfolio cash, not individual-rule ROI.
"""
import csv,gzip,json,sys,math
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
import importlib.util
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wf",ROOT/"scripts/research-nov2026-walkforward-joint-cash.py")
wf=importlib.util.module_from_spec(spec);sys.modules[spec.name]=wf;spec.loader.exec_module(wf)
base=wf.base
OUT=ROOT/"analysis-results/nov2026-marginal-portfolio-cash.json"
BETS=ROOT/"analysis-results/nov2026-marginal-portfolio-bets.csv.gz"
WINDOWS=(3,5,99)
MAX_STEPS=8
MAX_CANDIDATES_PER_WINDOW=40  # Bound O(steps*candidates*races) cash evaluations.
def stats(bets):
    return base.cash_metrics(bets)
def program_days(races,lo,hi):
    return {(r["day"],r["venue"]) for r in races if lo<=int(r["month"][:4])<=hi}
def fast_select(votes,data,year_min,year_max):
    """NumPy-equivalent selection: SAME two distinct bet markets and top-5/day.

    Exactly replicates walkforward.select but evaluates all candidate markets
    in bulk, so historical marginal rule selection can finish in a job.
    Does not inspect payout data when deciding a race or ticket.
    """
    races,cash,cat,widths,types,rid,year,quarter,joint=data
    chosen_idx=np.flatnonzero((year>=year_min)&(year<=year_max))
    if not len(chosen_idx):return []
    price=votes.reshape(len(races),336)[chosen_idx]
    ranges=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
    n=len(chosen_idx)
    peak=np.empty((n,6),dtype=np.float32)
    ticket=np.empty((n,6),dtype=np.int32)
    for market,(start,stop) in enumerate(ranges):
        subset=price[:,start:stop]
        loc=np.argmax(subset,axis=1)
        peak[:,market]=subset[np.arange(n),loc]
        ticket[:,market]=start+loc
    ranked=np.argsort(-peak,axis=1,kind="stable")
    pick1=ranked[:,0];pick2=ranked[:,1]
    active=np.flatnonzero(peak[np.arange(n),pick2]>0)
    groups=defaultdict(list)
    for j in active:
        i=int(chosen_idx[j])
        r=races[i]
        a=int(pick1[j]);b=int(pick2[j])
        t1=int(ticket[j,a]);t2=int(ticket[j,b])
        first=i*336
        groups[(r["day"],r["venue"])].append({
          "raceId":r["id"],"day":r["day"],"venue":r["venue"],
          "month":r["month"],"year":int(year[i]),
          "quarter":int(quarter[i]),
          "rankScore":float(peak[j,a])+float(peak[j,b]),
          "market1":base.MARKETS[a],"market2":base.MARKETS[b],
          "ticket1":t1,"ticket2":t2,
          "paidYen":int(cash[first+t1])+int(cash[first+t2]),
          "payout1Yen":int(cash[first+t1]),
          "payout2Yen":int(cash[first+t2])})
    out=[]
    for group in groups.values():
        group.sort(key=lambda r:(-r["rankScore"],r["raceId"]))
        out.extend(group[:5])
    return out

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
    # Verify vectorized historical ticket selection exactly matches
    # the independently implemented reference (including tie breaks).
    test_votes=np.zeros(len(cash),dtype=np.float32)
    for idx in indices:
        test_votes[idx]+=1.
    reference=wf.select(test_votes,data,year_min=2022,year_max=2022)
    optimized=fast_select(test_votes,data,year_min=2022,year_max=2022)
    if reference!=optimized:
        raise RuntimeError("FAST_CASH_SELECTION_NOT_BITWISE_EQUAL_TO_REFERENCE")
    print("MARGINAL_CASH_VECTORIZED_SELECTION_PARITY_OK",
          len(optimized),flush=True)
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
            ranked=ranked[:MAX_CANDIDATES_PER_WINDOW]
            for step in range(MAX_STEPS):
                best=None
                for support,i,q in ranked:
                    if (i,q) in selected:continue
                    idx=indices[i];idx=idx[qrow[idx]==q]
                    votes[idx]+=1
                    picks=fast_select(votes,data,year_min=lo,year_max=target-1)
                    score=objective(picks,days)
                    votes[idx]-=1
                    if best is None or score>best[0]:
                        best=(score,i,q)
                if best is None or best[0]<=baseline+1e-7:break
                baseline,i,q=best
                idx=indices[i];idx=idx[qrow[idx]==q]
                votes[idx]+=1
                selected.append((i,q))
            training=fast_select(votes,data,year_min=lo,year_max=target-1)
            candidates.append((objective(training,days),win,votes,selected,stats(training)))
        _,win,votes,selected,training=max(candidates,key=lambda x:(x[0],-x[1]))
        bought=fast_select(votes,data,year_min=target,year_max=target)
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
