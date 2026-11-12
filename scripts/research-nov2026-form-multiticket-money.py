#!/usr/bin/env python3
"""Research a genuinely NEW 2-MARKET MULTI-TICKET CASH PORTFOLIO generator.

Old 2 ticket one-combo-per-market constraint is removed. Enumerate cash tickets
from entire race (6 types x 7 odds-ranked horses) and form 2 distinct-market
wheels (1/2/3/5/8 actual combos per market), split 2000 yen in 100-yen units.
Exactly 3/4/5 races/venue/day; model gets no outcome/payout in features.
Fit 2017-21, screen validation 2022, only if >200 after biggest payout and
hit>=20% evaluate 2023-26 Apr. No below-200 model reported.
Research only: historical odds are NOT proven JRA official T-15.
"""
from __future__ import annotations
import collections,csv,importlib.util,itertools,json,math,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-form-formation-money.json"
BETS=ROOT/"analysis-results/nov2026-form-formation-money-bets.csv"
PAIRS=tuple(itertools.combinations(range(6),2))
MKT=("単勝","ワイド","馬連","馬単","3連複","3連単")
LIMITS=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
K=(1,2,3,5,8)
BUDGET=((1000,1000),(1500,500),(1900,100),(500,1500),(100,1900))
EXP=((.5,0.),(1.,0.),(1.5,0.),(1.,.5),(.5,1.),(1.,1.))
SLATE=(3,4,5)
ALLOC=("equal","head")
def module():
    p=ROOT/"scripts/research-nov2026-form-money-new-generator.py"
    spec=importlib.util.spec_from_file_location("form_paid_wheel_source",p)
    a=importlib.util.module_from_spec(spec);sys.modules[spec.name]=a;spec.loader.exec_module(a)
    return a
def metrics(v):
    n=len(v)
    if not n:return {"races":0,"roiPct":None}
    arr=np.asarray(v,dtype=np.int64);paid=int(arr.sum());stake=n*2000
    return dict(races=n,stakeYen=stake,paidYen=paid,
       roiPct=round(100*paid/stake,5),
       minusMaxRaceRoiPct=round(100*(paid-int(arr.max()))/stake,5),
       hitRacePct=round(100*np.count_nonzero(arr)/n,5),
       maxRacePaidYen=int(arr.max()))
def passes(s,minimum=300):
    return s["races"]>=minimum and s["roiPct"]>=200 and \
           s["minusMaxRaceRoiPct"]>=200 and s["hitRacePct"]>=20
def unit_weights(scores,units,k,alloc):
    if units<k:return None
    if alloc=="equal":
        u=np.full((len(scores),k),units//k,dtype=np.int32)
        rem=units%k
        if rem:u[:,:rem]+=1
    else:
        u=np.ones((len(scores),k),dtype=np.int32)
        u[:,0]+=units-k
    if np.any(u<1) or not np.all(u.sum(axis=1)==units):
        raise RuntimeError("100YEN_STAKE_ALLOCATION_FAILED")
    return u
def top_arrays(src,raw,idx,pred,kind,expo):
    beta,gamma=expo
    sig=np.maximum(pred[:,:,kind],1e-8)**beta*(
        np.maximum(pred[:,:,2],1e-8)**gamma)
    n=len(idx)
    top_idx=np.zeros((n,6,8),dtype=np.int16)
    top_sig=np.zeros((n,6,8),dtype=np.float64)
    top_paid=np.zeros((n,6,8),dtype=np.int32)
    for market,(lo,hi) in enumerate(LIMITS):
       x=np.argsort(-sig[:,lo:hi],axis=1,kind="stable")[:,:8]
       take=x+lo
       top_idx[:,market,:]=take
       top_sig[:,market,:]=np.take_along_axis(sig,take,axis=1)
       top_paid[:,market,:]=src[idx[:,None],take]
    return top_idx,top_sig,top_paid
def payout_tables(sig,paid):
    # Cache at most 6 x 5 budgets x 5 wheel sizes x 2 allocations
    # cash outcome and predicted cash before opening 2022 settlement labels.
    tables={}
    for market in range(6):
      for budget in sorted({x for pair in BUDGET for x in pair}):
        for k in K:
          if k*100>budget:continue
          for alloc in ALLOC:
            weights=unit_weights(sig[:,market,:k],budget//100,k,alloc)
            tables[(market,budget,k,alloc)]=(
              np.sum(paid[:,market,:k]*weights,axis=1,dtype=np.int64),
              np.sum(sig[:,market,:k]*weights,axis=1,dtype=np.float64),
            )
    return tables
def groups(races,idx):
    by=collections.defaultdict(list)
    for j,i in enumerate(idx):
      r=races[int(i)]
      by[(r["day"],str(r["venue"]))].append(j)
    return [np.asarray(x,dtype=np.int32) for _,x in sorted(by.items())]
def options(races,idx,table,slate):
    return np.concatenate([np.asarray(sorted(g.tolist(),key=lambda i:(-table[i],i))[:slate],
                          dtype=np.int32) for g in groups(races,idx)])
def search(races,src,idx,pred):
    groupset=groups(races,idx)
    if len(groupset)<100 or any(len(g)<3 for g in groupset):
        raise RuntimeError("INVALID_OR_INCOMPLETE_ORIGINAL_JRA_SLATES")
    quarters=np.asarray([(int(races[int(i)]["month"][4:])-1)//3 for i in idx],
                        dtype=np.int8)
    count=0;possible=0;passing=0;best=None
    # Per season, choose best pair; no 2023+ label is read to rank.
    for kind in (0,1):
      for ex in EXP:
        topindex,topsig,topcash=top_arrays(src,src,idx,pred,kind,ex)
        tables=payout_tables(topsig,topcash)
        for slate in SLATE:
          if any(len(g)<slate for g in groupset):continue
          for budget in BUDGET:
            for wheel1 in K:
              if wheel1*100>budget[0]:continue
              for wheel2 in K:
                if wheel2*100>budget[1]:continue
                for alloc in ALLOC:
                  pay_per_pair=[]
                  for a,b in PAIRS:
                    v1,score1=tables[(a,budget[0],wheel1,alloc)]
                    v2,score2=tables[(b,budget[1],wheel2,alloc)]
                    selected=options(races,idx,score1+score2,slate)
                    pay=v1[selected]+v2[selected]
                    pay_per_pair.append((a,b,selected,pay,quarters[selected]))
                    count+=1
                  chosen=[]
                  for q in range(4):
                    z=max(pay_per_pair,key=lambda x:(
                          int(x[3][x[4]==q].sum())-(
                             int(x[3][x[4]==q].max()) if np.any(x[4]==q) else 0),
                          int(np.count_nonzero(x[3][x[4]==q]))))
                    chosen.append(z)
                  returns=np.concatenate([z[3][z[4]==q] for q,z in enumerate(chosen)])
                  possible+=1
                  cash=metrics(returns)
                  if passes(cash):
                    passing+=1
                    candidate=dict(kind=kind,expo=ex,slate=slate,
                      budget=budget,perMarketTickets=[wheel1,wheel2],allocation=alloc,
                      pairsByQuarter=[list(z[:2]) for z in chosen],
                      cash2022=cash)
                    if best is None or cash["minusMaxRaceRoiPct"]>best["cash2022"]["minusMaxRaceRoiPct"]:
                        best=candidate
    return best,dict(materializedIndividualMarketPairPolicies=count,
      quarterSwitchConfigsEvaluated=possible,
      quarterPairAssignmentsPerConfig=15**4,
      mathematicallyPossibleQuarterPairPolicies=possible*15**4,
      qualifyingValidationConfigs=passing,
      2022Groups=len(groupset))
def apply(races,cash,idx,pred,recipe):
    kind=recipe["kind"];ex=tuple(recipe["expo"])
    _,scores,payout=top_arrays(cash,cash,idx,pred,kind,ex)
    tables=payout_tables(scores,payout)
    slate=int(recipe["slate"]);weights=tuple(recipe["budget"])
    k1,k2=recipe["perMarketTickets"];alloc=recipe["allocation"]
    ret=[];ledger=[]
    for group in groups(races,idx):
      if len(group)<slate:raise RuntimeError("FINAL_DAY_COVERAGE_MISSING")
      q=(int(races[int(idx[group[0]])]["month"][4:])-1)//3
      a,b=recipe["pairsByQuarter"][q]
      av,ap=tables[(a,weights[0],k1,alloc)]
      bv,bp=tables[(b,weights[1],k2,alloc)]
      ranked=sorted(group.tolist(),key=lambda i:(-ap[i]-bp[i],i))[:slate]
      for i in ranked:
        r=races[int(idx[i])]
        paid=int(av[i]+bv[i]);ret.append(paid)
        ledger.append(dict(year=int(r["month"][:4]),raceId=r["id"],
          day=r["day"],venue=r["venue"],raceNo=r["raceNo"],
          market1=MKT[a],market2=MKT[b],ticketCount1=k1,ticketCount2=k2,
          allocation=alloc,stake1Yen=weights[0],stake2Yen=weights[1],
          paidYen=paid))
    return ret,ledger
def main():
    if "--self-test" in sys.argv:
       assert len(PAIRS)==15 and sum(b-a for a,b in LIMITS)==336
       assert all(a+b==2000 for a,b in BUDGET)
       assert len(ALLOC)==2 and len(K)==5
       assert not passes(dict(races=700,roiPct=250,minusMaxRaceRoiPct=199,hitRacePct=30))
       assert passes(dict(races=700,roiPct=220,minusMaxRaceRoiPct=200,hitRacePct=20))
       assert np.array_equal(unit_weights(np.ones((2,3)),8,3,"head")[0],np.array([6,1,1]))
       print("MULTI_TICKET_TWO_MARKET_FINANCIAL_TESTS_OK",flush=True);return
    began=time.monotonic()
    base=module()
    races,cash,attrs,types,year,keys=base.obtain()
    print("FORMATION_MONEY_DATASET",json.dumps({"races":len(races),
      "allSingleTickets":int(cash.size),"wheelSizes":K,
      "actualPaidYenTargetsOnly":True,
      "officialT15QuoteProven":False},ensure_ascii=False),flush=True)
    mods=base.train(cash,attrs,types,year,keys,base.YEARS_TRAIN)
    ix,signal=base.infer(mods,attrs,types,keys,year,2022)
    winner,coverage=search(races,cash,ix,signal)
    outcome=dict(status="REJECTED_NOT_A_MODEL",
       adoptedModel=False,productionChanged=False,
       generator="cash-first historical horse form box/formation ticket allocation",
       independentTwoMarketsPerRace=True,
       raceCountPerVenueDay=[3,4,5],allTicketCandidates=cash.size,
       trainingYears=list(base.YEARS_TRAIN),validationYear=2022,
       amountPerRaceYen=2000,
       exactJraT15OddsVerified=False,
       thirdPartyPayoutsIndependentlyVerified=False,
       previouslyInspectedLaterOutcomes=True,
       2026AugNovNotCovered=True,search=coverage)
    if winner:
       outcome["passed2022Gate"]=winner
       mod2=base.train(cash,attrs,types,year,keys,base.YEARS_FINAL)
       years={};rows=[];allret=[]
       for y in EVAL:
          ids,pred=base.infer(mod2,attrs,types,keys,year,y)
          returned,ledger=apply(races,cash,ids,pred,winner)
          years[str(y)]=metrics(returned);rows+=ledger;allret+=returned
       agg=metrics(allret)
       success=passes(agg) and all(
           (years[str(y)]["races"]>=30 and
             years[str(y)]["roiPct"]>=200 and
             years[str(y)]["minusMaxRaceRoiPct"]>=200 and
             years[str(y)]["hitRacePct"]>=20)
             for y in EVAL)
       outcome.update(status="HISTORICAL_NUMERIC_200_REQUIRES_T15" if success
                      else "REJECTED_NOT_A_MODEL",
         frozenForwardCash=agg,frozenYearCash=years,heldoutPass=success)
       if rows:
          BETS.parent.mkdir(parents=True,exist_ok=True)
          with BETS.open("w",newline="",encoding="utf-8") as f:
            wr=csv.DictWriter(f,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)
    outcome["executionSeconds"]=round(time.monotonic()-began,3)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(outcome,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FORMATION_MONEY_ACCEPTANCE_FINAL",json.dumps({
        "status":outcome["status"],
        "2022Qualified":bool(winner),
        "quarterSwitchConfigurationsTested":coverage["quarterSwitchConfigsEvaluated"],
        "distinctPairsAndStakesTested":coverage["materializedIndividualMarketPairPolicies"],
        "elapsedSeconds":outcome["executionSeconds"],
        "productionUnchanged":True
    },ensure_ascii=False),flush=True)
if __name__=="__main__":main()
