#!/usr/bin/env python3
"""Quarterly prequential joint cash-regime research. Third-party settlements; NOT T-15 certified."""
import csv,gzip,importlib.util,json,sys
from pathlib import Path
from collections import defaultdict
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-quarterly-joint-cash.json"
BETS=ROOT/"analysis-results/nov2026-quarterly-joint-cash-bets.csv.gz"
MARKETS=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
def summarize(rows):
    stake=sum(x["stakeYen"] for x in rows);paid=sum(x["paidYen"] for x in rows)
    top=max((x["paidYen"] for x in rows),default=0)
    return dict(races=len(rows),stakeYen=stake,paidYen=paid,hitRaces=sum(x["paidYen"]>0 for x in rows),
                roiPct=round(100*paid/stake,4) if stake else None,
                minusMaxRaceRoiPct=round(100*(paid-top)/stake,4) if stake else None)
def run(races,cash,year,quarter,fields):
    n=len(races);money=cash.reshape(n,336)
    venue=np.array([str(r["venue"]) for r in races])
    day=np.array([str(r["day"]) for r in races])
    program=np.array([int(r["raceNo"]) for r in races])
    if np.any((program<1)|(program>12)):raise RuntimeError("INVALID_PROGRAM")
    band=np.where(fields<=9,0,np.where(fields<=13,1,2))
    # Only pre-race features; no winners, finish positions or test payouts in routing.
    keys=[(venue[i],int(quarter[i]),int(band[i]),int((program[i]-1)//4)) for i in range(n)]
    all_bets=[];coverage={};missing=0
    periods=[(y,q) for y in range(2023,2027) for q in range(1,5)]
    for target,q in periods:
        period=target*4+q
        train=np.flatnonzero((year*4+quarter<period)&(year*4+quarter>=period-24)&(year>=2017))
        test=np.flatnonzero((year==target)&(quarter==q))
        if not len(test):continue
        if not len(train):raise RuntimeError("NO_PAST_TRAINING")
        # Directly discover high-hit and largest-race-excluded cash candidates from past settlements.
        v=money[train]
        candidates=[]
        for lo,hi in MARKETS:
            hits=np.count_nonzero(v[:,lo:hi],axis=0)
            robust=v[:,lo:hi].sum(axis=0)-v[:,lo:hi].max(axis=0)
            a=np.argsort(-hits,kind="stable")[:3]+lo
            b=np.argsort(-robust,kind="stable")[:4]+lo
            candidates.append(list(dict.fromkeys(map(int,list(a)+list(b)))))
        options=[]
        for market_a in range(6):
            for market_b in range(market_a+1,6):
                for a in candidates[market_a]:
                    for b in candidates[market_b]:
                        for sa,sb in ((100,100),(100,200),(200,100)):
                            options.append((a,b,sa,sb))
        # Prior-period regime-specific cash ledger with shrinkage for sparse states.
        groups=defaultdict(list)
        for i in train:groups[keys[int(i)]].append(int(i))
        def score_option(ix,option):
            a,b,sa,sb=option
            p=(money[ix,a]*sa+money[ix,b]*sb)//100
            stake=(sa+sb)*len(ix)
            if not stake:return -1e9
            years=year[ix]
            # Cash return after removing largest race, and worst annual cash ROI.
            robust=(int(p.sum())-int(p.max()))/stake
            annual=[(int(p[years==yy].sum())-int(p[years==yy].max()))/((sa+sb)*int(np.sum(years==yy))) for yy in np.unique(years)]
            return robust+0.1*min(annual)
        # Global pool is a fallback only, never an independently adopted model.
        global_rank=sorted(options,key=lambda x:score_option(train,x),reverse=True)[:16]
        policies={}
        for key,ix in groups.items():
            ix=np.asarray(ix,dtype=int)
            source=ix if len(ix)>=60 else train[venue[train]==key[0]]
            if len(source)<60:source=train
            ranked=sorted(options,key=lambda x:score_option(source,x),reverse=True)
            policies[key]=ranked[:8]
        # Jointly optimize assignments on a complete historical 5R-per-venue-day slate.
        train_days=defaultdict(list)
        for i in train:train_days[(day[i],venue[i])].append(int(i))
        current={key:opts[0] for key,opts in policies.items()}
        fallback=global_rank[0]
        def priority(key,assignment):
            ix=groups.get(key,[])
            if not ix:return -1
            return score_option(np.asarray(ix,dtype=int),assignment)
        def slate(assign):
            priorities={k:priority(k,v) for k,v in assign.items()}
            return [i for indices in train_days.values() for i in sorted(indices,key=lambda j:(-priorities.get(keys[j],-1),int(program[j])))[:5]]
        chosen=slate(current)
        def objective(assign,indices):
            payouts=[];stakes=[];by_year=defaultdict(list)
            for i in indices:
                a,b,sa,sb=assign.get(keys[i],fallback)
                p=int((money[i,a]*sa+money[i,b]*sb)//100)
                payouts.append(p);stakes.append(sa+sb);by_year[int(year[i])].append((p,sa+sb))
            if not stakes:return (-1e9,-1e9)
            robust=(sum(payouts)-max(payouts))/sum(stakes)
            annual=min((sum(p for p,s in rows)-max(p for p,s in rows))/sum(s for p,s in rows) for rows in by_year.values())
            return (robust+0.1*annual,robust)
        for _ in range(3):
            for key in sorted(current):
                best=current[key];bestscore=objective(current,chosen)
                for option in policies[key]:
                    current[key]=option
                    val=objective(current,chosen)
                    if val>bestscore:bestscore=val;best=option
                current[key]=best
            new=slate(current)
            if new==chosen:break
            chosen=new
        priorities={k:priority(k,v) for k,v in current.items()}
        test_days=defaultdict(list)
        for i in test:test_days[(day[i],venue[i])].append(int(i))
        counts=defaultdict(int)
        for _,indices in test_days.items():
            selected=sorted(indices,key=lambda j:(-priorities.get(keys[j],-1),int(program[j])))[:5]
            counts[len(selected)]+=1
            for i in selected:
                a,b,sa,sb=current.get(keys[i],fallback)
                all_bets.append(dict(raceId=str(races[i]["id"]),day=day[i],venue=venue[i],year=target,quarter=q,
                    marketA=next(k for k,(lo,hi) in enumerate(MARKETS) if lo<=a<hi),
                    marketB=next(k for k,(lo,hi) in enumerate(MARKETS) if lo<=b<hi),
                    ticketA=a,ticketB=b,stakeA=sa,stakeB=sb,stakeYen=sa+sb,
                    paidYen=int((money[i,a]*sa+money[i,b]*sb)//100)))
        coverage[f"{target}Q{q}"]=dict(trainRaces=len(train),testRaces=len(test),
            venueDays=len(test_days),selected5=counts[5],selected3to5=sum(v for k,v in counts.items() if 3<=k<=5),
            below3=sum(v for k,v in counts.items() if k<3))
    return all_bets,coverage
def main():
    if "--self-test" in sys.argv:
        assert summarize([dict(stakeYen=200,paidYen=500),dict(stakeYen=200,paidYen=100)])["minusMaxRaceRoiPct"]==25
        assert len(MARKETS)==6 and sum(hi-lo for lo,hi in MARKETS)==336
        print("QUARTERLY_JOINT_CASH_SELF_TEST_OK");return
    src=ROOT/"scripts/research-nov2026-seasonal-ensemble-cash-first.py"
    spec=importlib.util.spec_from_file_location("cashsrc",src)
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
    races,cash,cat,widths,types,rid,year,quarter,joint=mod.obtain_rows()
    if len(cash)!=336*len(races) or np.any(cash<0):raise RuntimeError("INVALID_CASH")
    fields=cat["fieldSize"].reshape(len(races),336)[:,0].astype(int)
    bets,coverage=run(races,cash,year,quarter,fields)
    if any(b["marketA"]==b["marketB"] for b in bets):raise RuntimeError("DUPLICATE_MARKET")
    if len({b["raceId"] for b in bets})!=len(bets):raise RuntimeError("DUPLICATE_RACE")
    report=dict(researchOnly=True,adoptable=False,officialT15Verified=False,officialJraPayoutReconciled=False,
        source="third_party_unreconciled",priorExposure2025And2026=True,
        regimeDimensions=["venue","quarter","fieldSizeBand","programNumberBand"],
        missingOfficialVenueDays="NOT_VERIFIED",candidateRaces=len(races),
        combined=summarize(bets),years={str(y):summarize([b for b in bets if b["year"]==y]) for y in range(2023,2027)},
        quarters={f"{y}Q{q}":summarize([b for b in bets if b["year"]==y and b["quarter"]==q]) for y in range(2023,2027) for q in range(1,5)},
        coverage=coverage)
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    with gzip.open(BETS,"wt",encoding="utf8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(bets[0]) if bets else ["raceId"]);w.writeheader();w.writerows(bets)
    print("QUARTERLY_JOINT_CASH_RESULT",json.dumps(report,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
