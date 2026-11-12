#!/usr/bin/env python3
"""Joint cash portfolio search, research-only. Never claims JRA T-15 verification."""
import csv,gzip,importlib.util,json,sys
from collections import defaultdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
BOUNDS=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
OUT=ROOT/"analysis-results/nov2026-joint-cash-cover.json"
BETS=ROOT/"analysis-results/nov2026-joint-cash-cover-bets.csv.gz"
def stats(rows):
    paid=sum(x["paidYen"] for x in rows);stake=sum(x["stakeYen"] for x in rows)
    peak=max((x["paidYen"] for x in rows),default=0)
    return dict(races=len(rows),stakeYen=stake,paidYen=paid,hitRaces=sum(x["paidYen"]>0 for x in rows),
        roiPct=round(100*paid/stake,4) if stake else None,
        minusMaxRaceRoiPct=round(100*(paid-peak)/stake,4) if stake else None)
def select(cash,races,year,quarter,fields):
    n=len(races);money=cash.reshape(n,336)
    venue=[str(r["venue"]) for r in races]
    band=np.where(fields<=9,0,np.where(fields<=13,1,2))
    keys=[(venue[i],int(quarter[i]),int(band[i])) for i in range(n)]
    result=[];coverage={}
    for target in (2023,2024,2025,2026):
        train=np.flatnonzero((year>=2017)&(year<target)&(year>=target-6))
        test=np.flatnonzero(year==target)
        if not len(train) or not len(test):continue
        # Generate base/high-hit and overlay/high-robust cash tickets from every market.
        # Candidate discovery uses ONLY earlier years, never the evaluation year.
        def discover(ix):
            v=money[np.asarray(ix,dtype=int)]
            hits=np.count_nonzero(v,axis=0)
            robust=v.sum(axis=0,dtype=np.int64)-v.max(axis=0)
            choices=[]
            for lo,hi in BOUNDS:
                a=sorted(range(lo,hi),key=lambda j:(hits[j],robust[j]),reverse=True)[:3]
                b=sorted(range(lo,hi),key=lambda j:(robust[j],hits[j]),reverse=True)[:4]
                choices.append(list(dict.fromkeys(a+b)))
            return [(a,b) for k,aa in enumerate(choices) for bb in choices[k+1:] for a in aa for b in bb]
        groups=defaultdict(list)
        for i in train:groups[keys[int(i)]].append(int(i))
        global_pairs=discover(train)
        # Per-regime portfolios are optimized jointly by the *actual sum of cash*,
        # with the largest single race payout removed from the combined ledger.
        # The common global fallback guarantees broad race coverage.
        policies={}
        for key in set(keys[int(i)] for i in test):
            ix=groups.get(key,[])
            parent=[int(i) for i in train if venue[int(i)]==key[0] and int(quarter[int(i)])==key[1]]
            source=ix if len(ix)>=60 else parent if len(parent)>=60 else train.tolist()
            options=list(dict.fromkeys(discover(source)+global_pairs[:80]))
            v=money[np.asarray(source,dtype=int)]
            # Joint pair cash, rather than separate ticket scores or ROI cell thresholds.
            scored=[]
            for a,b in options:
                p=v[:,a]+v[:,b]
                # Conservative robust cash return: retain the removed race's stake.
                robust=int(p.sum())-int(p.max())
                scored.append((robust, int(np.count_nonzero(p)),a,b))
            scored.sort(reverse=True)
            best=scored[0]
            policies[key]=(best[2],best[3],best[0]/(200*len(source)),len(source))
        # Coordinate-descent across regimes on a single cash ledger.
        # No test-year outcomes are consulted. Every training race has one
        # candidate pair and the objective removes the globally largest race.
        # This differs from choosing the best pair independently per cell.
        train_groups=defaultdict(list)
        for i in train:
            train_groups[keys[int(i)]].append(int(i))
        pair_options={}
        for key in policies:
            ix=train_groups.get(key,[])
            source=ix if len(ix)>=40 else train.tolist()
            candidates=discover(source)
            v=money[np.asarray(source,dtype=int)]
            scores=[]
            for a,b in candidates:
                p=v[:,a]+v[:,b]
                scores.append((int(p.sum())-int(p.max()),a,b))
            scores.sort(reverse=True)
            pair_options[key]=[(a,b) for _,a,b in scores[:12]]
        # Precompute training venue-day ordering using only known race identifiers.
        train_days=defaultdict(list)
        for i in train:
            i=int(i)
            train_days[(str(races[i]["day"]),venue[i])].append(i)
        # Training slate uses pre-outcome regime priorities, not race IDs.
        def train_priority(i):
            return policies[keys[i]][2] if keys[i] in policies else float("-inf")
        chosen_train=[i for group in train_days.values()
                      for i in sorted(group,key=lambda j:(-train_priority(j),str(races[j]["id"])))[:5]]
        chosen_groups=defaultdict(list)
        for i in chosen_train:
            if keys[i] in policies:chosen_groups[keys[i]].append(i)
        current={key:(p[0],p[1]) for key,p in policies.items()}
        def portfolio_cash(assign):
            # All regimes share one cash ledger. Reject a candidate that merely
            # shifts a windfall into one year at the expense of every other year.
            # Every yearly component is calculated from pre-target training years.
            payouts=[]
            by_year=defaultdict(list)
            for key,ix in chosen_groups.items():
                a,b=assign[key]
                for i in ix:
                    p=int(money[i,a]+money[i,b])
                    payouts.append(p)
                    by_year[int(year[i])].append(p)
            if not payouts:return (-1.0,-1.0,-1)
            robust_total=(sum(payouts)-max(payouts))/(200*len(payouts))
            # Annual minimum is a regularizer, not an individual-cell ROI rule.
            annual=[(sum(v)-max(v))/(200*len(v)) for v in by_year.values() if v]
            return (min(annual),robust_total,sum(payouts))
        best_cash=portfolio_cash(current)
        for _ in range(4):
            changed=False
            for key in sorted(current):
                old=current[key];winner=old;winner_cash=best_cash
                for candidate in pair_options.get(key,[]):
                    if candidate==old:continue
                    current[key]=candidate
                    score=portfolio_cash(current)
                    if score>winner_cash:
                        winner_cash=score;winner=candidate
                current[key]=winner
                if winner!=old:
                    changed=True;best_cash=winner_cash
            if not changed:break
        # Race selection priority must vary by pre-known regime. Previously
        # every key inherited the same portfolio score, reducing the 5R cap
        # to an arbitrary race-ID sort. Estimate a robust regime-specific
        # cash yield exclusively from training years; never use test payouts.
        for key,(a,b) in current.items():
            _,_,_,support=policies[key]
            ix=train_groups.get(key,[])
            if ix:
                payouts=money[np.asarray(ix,dtype=int),a]+money[np.asarray(ix,dtype=int),b]
                robust=(int(payouts.sum())-int(payouts.max()))/(200*len(ix))
                # Shrink sparse cells toward the global training portfolio,
                # preserving coverage while avoiding small-cell jackpots.
                strength=len(ix)/(len(ix)+100)
                priority=strength*robust+(1-strength)*best_cash[1]
            else:
                priority=best_cash[1]
            policies[key]=(a,b,float(priority),support)
        days=defaultdict(list)
        for i in test:
            i=int(i);a,b,priority,support=policies[keys[i]]
            x=dict(raceId=str(races[i]["id"]),day=str(races[i]["day"]),venue=venue[i],
                year=target,quarter=int(quarter[i]),marketA=next(k for k,(lo,hi) in enumerate(BOUNDS) if lo<=a<hi),
                marketB=next(k for k,(lo,hi) in enumerate(BOUNDS) if lo<=b<hi),
                ticketA=a,ticketB=b,stakeYen=200,paidYen=int(money[i,a]+money[i,b]),
                preRacePriority=priority,trainingSupport=support)
            days[(x["day"],x["venue"])].append(x)
        counts=defaultdict(int)
        for key,rows in days.items():
            rows.sort(key=lambda x:(-x["preRacePriority"],x["raceId"]))
            chosen=rows[:5];counts[len(chosen)]+=1;result.extend(chosen)
        coverage[str(target)]=dict(observedVenueDays=len(days),selected3to5=sum(v for k,v in counts.items() if 3<=k<=5),
            selected5=counts[5],lessThan3=sum(v for k,v in counts.items() if k<3),
            unobservedOfficialVenueDays="NOT_VERIFIED",trainingRaces=len(train),testRaces=len(test))
    return result,coverage
def main():
    if "--self-test" in sys.argv:
        assert stats([dict(stakeYen=200,paidYen=500),dict(stakeYen=200,paidYen=100)])["minusMaxRaceRoiPct"]==25
        print("JOINT_CASH_COVER_SELF_TEST_OK");return
    src=ROOT/"scripts/research-nov2026-seasonal-ensemble-cash-first.py"
    spec=importlib.util.spec_from_file_location("cashsrc",src)
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
    races,cash,cat,widths,types,rid,year,quarter,joint=m.obtain_rows()
    if len(cash)!=336*len(races) or np.any(cash<0):raise RuntimeError("INVALID_CASH_DATA")
    fields=cat["fieldSize"].reshape(len(races),336)[:,0].astype(int)
    bets,coverage=select(cash,races,year,quarter,fields)
    if any(b["marketA"]==b["marketB"] for b in bets):raise RuntimeError("SAME_MARKET")
    if len({(b["raceId"],b["day"],b["venue"]) for b in bets})!=len(bets):raise RuntimeError("DUPLICATE_RACE")
    yearly={str(y):stats([b for b in bets if b["year"]==y]) for y in (2023,2024,2025,2026)}
    quarters={str(y):{str(q):stats([b for b in bets if b["year"]==y and b["quarter"]==q]) for q in range(1,5)} for y in (2023,2024,2025,2026)}
    report=dict(researchOnly=True,adoptable=False,officialT15Verified=False,officialJraPayoutReconciled=False,
        historicalCashSource="third_party_unreconciled",knownPriorExposure2025And2026=True,
        candidateRaces=len(races),candidateTickets=len(cash),year=yearly,quarters=quarters,
        combined=stats(bets),coverage=coverage)
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    with gzip.open(BETS,"wt",encoding="utf8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(bets[0]) if bets else ["raceId"]);w.writeheader();w.writerows(bets)
    print("JOINT_CASH_COVER_RESULT",json.dumps(report,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
