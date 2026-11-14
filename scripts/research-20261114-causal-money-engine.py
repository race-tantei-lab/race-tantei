#!/usr/bin/env python3
"""Causal JRA cash-ROI learning engine, 2015..2026Apr + Aug..Nov audit.

Fundamental difference from the prior retrospective 360%-ROI engine:
each month is predicted from bets and settlements from EARLIER MONTHS ONLY.
The entire 2015-Jan..2026-Apr archive is ONE evaluation, but no month may
access its own result or any future month's payoff when selecting tickets.

Objectives: actual money profit and cash ROI, one-largest-race exclusion,
20% paid-hit minimum, >=3 distinct bought races each eligible venue-day.
Hit rate is NEVER a reward, feature or stake bonus; profitable bets are tracked
separately. No fit on August onward when evaluating August onward.

Only JRA-final historical win odds are present for the old archive;
they are NOT verified pre-start 15-minute snapshots, and third-party payouts
have not been independently certified. This script can discover research
patterns, NOT validate T-15 production model readiness or future guarantees.
"""
from __future__ import annotations
import collections, csv, gzip, importlib.util, json, math, sys, time
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-causal-money-only-full-history.json"
LED=ROOT/"analysis-results/20261114-causal-money-only-prequential-ledger.csv.gz"
SCHEMAS=((),("oddsGeom",),("favOdds",),("fieldSize",),
         ("venue",),("quarter",),("raceBand",),
         ("oddsGeom","fieldSize"),("favOdds","venue"))
CARD={"oddsGeom":8,"favOdds":5,"fieldSize":4,"venue":10,
      "quarter":4,"raceBand":3}
VARIANTS=(
  {"name":"causal_conservative","minN":80,"minHit":5,"shrink":220,"uplift":.8},
  {"name":"causal_strict","minN":180,"minHit":12,"shrink":500,"uplift":.6},
  {"name":"causal_shrunk","minN":35,"minHit":3,"shrink":350,"uplift":.45})
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
MARKET_DEFAULT=(.72,.72,.72,.72,.72,.72)
ALLOWED_RANKS=6
MIN_RACES=3
CAP_ROI=25.0
def imported(path,name):
    p=ROOT/path
    spec=importlib.util.spec_from_file_location(name,p)
    if not spec or not spec.loader:raise RuntimeError("SOURCE_MISSING:"+str(p))
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m
    spec.loader.exec_module(m)
    return m
class PastState:
    def __init__(self,tickets,schema):
        count=tickets
        for k in schema:count*=CARD[k]
        self.schema=schema
        self.n=np.zeros(count,dtype=np.int64)
        self.wins=np.zeros(count,dtype=np.int64)
        self.cash=np.zeros(count,dtype=np.int64)
        self.maxcash=np.zeros(count,dtype=np.int64)
    def code(self,cat,templates):
        x=np.broadcast_to(templates,cat["venue"].shape).astype(np.int32).copy()
        for k in self.schema:
            q=cat[k]
            if np.any(q>=CARD[k]):raise RuntimeError("BAD_CAUSAL_PRERACE_BIN:"+k)
            x=x*CARD[k]+q.astype(np.int32)
        return x
    def update(self,key,money):
        a=key.ravel()
        b=money.ravel().astype(np.int64)
        if len(a)!=len(b):raise RuntimeError("HISTORY_MATRIX_NOT_ALIGNED")
        self.n+=np.bincount(a,minlength=len(self.n)).astype(np.int64)
        self.wins+=np.bincount(a,weights=(b>0),minlength=len(self.n)).astype(np.int64)
        self.cash+=np.bincount(a,weights=b,minlength=len(self.n)).astype(np.int64)
        nonzero=np.flatnonzero(b)
        if len(nonzero):np.maximum.at(self.maxcash,a[nonzero],b[nonzero])
def choose_templates(core):
    slots,mids=core.fixed_template()
    keep=np.asarray([max(r)<ALLOWED_RANKS for r in slots],dtype=bool)
    chosen=np.flatnonzero(keep).astype(np.int32)
    markets=mids[chosen]
    if len(chosen)<150 or len(set(markets.tolist()))!=6:
        raise RuntimeError("CAUSAL_SIX_MARKET_TEMPLATE_COVERAGE_FAIL")
    return chosen,markets
def load_historical():
    core=imported("scripts/research-nov2026-decade-roi-first-sixmarkets.py","causal_cash_core")
    parse=imported("scripts/research-nov2026-sixmarket-real-paid-cash.py","causal_cash_payout_parser")
    races=core.read_all_races(parse.parse_payments)
    if not core.CACHE.exists() or not core.RACE_CACHE.exists():
        core.CACHE.parent.mkdir(parents=True,exist_ok=True)
        core.full_features(races)
    selected,market=choose_templates(core)
    with np.load(core.CACHE,allow_pickle=False) as npz:
        if npz["payout"].shape!=(len(races),1030):
            raise RuntimeError("BAD_HISTORICAL_SIX_MARKET_CACHE")
        payout=np.asarray(npz["payout"][:,selected],dtype=np.int32)
        cat={k:np.asarray(npz[k][:,selected],dtype=np.uint8) for k in CARD}
    return core,races,payout,cat,selected,market
def calculate_month_scores(states,cat,template,market,variants):
    m=len(cat["venue"]);t=template.shape[1]  # template is [1, ticketCount]
    if any(x.shape!=(m,t) for x in cat.values()):
        raise RuntimeError("CASH_CONTEXT_SHAPE_MISMATCH")
    key0=states[0].code(cat,template)
    cnt=states[0].n[key0]
    wins=states[0].wins[key0]
    # Remove the single biggest historic payout in each previous-month
    # bucket. This deliberately suppresses one-hit jackpot mining.
    gross=np.maximum(0,states[0].cash[key0]-states[0].maxcash[key0])
    mean=gross/np.maximum(1,cnt)/100.
    prior=np.broadcast_to(np.asarray(MARKET_DEFAULT)[market],(m,t))
    weight=np.minimum(1.,cnt/400.)*np.minimum(1.,wins/12.)
    basic=(1-weight)*prior+weight*np.minimum(mean,CAP_ROI)
    # No outcome labels from current month enter this prediction.
    scores=[]
    for var in variants:
        best=basic.copy()
        for st in states[1:]:
            codes=st.code(cat,template)
            n=st.n[codes];h=st.wins[codes]
            eligible=(n>=var["minN"])&(h>=var["minHit"])
            amt=np.maximum(0,st.cash[codes]-st.maxcash[codes])
            v=np.minimum(CAP_ROI,amt/np.maximum(1,n)/100.)
            shrink=n/(n+var["shrink"])
            confidence=np.minimum(1.,h/12.)
            estimate=(1-shrink*confidence)*basic+(shrink*confidence)*v
            adjusted=basic+var["uplift"]*(estimate-basic)
            best=np.where(eligible,np.maximum(best,adjusted),best)
        scores.append(np.maximum(.0,np.minimum(best,CAP_ROI)))
    return np.stack(scores,axis=1)
def choose_markets(scores,market,tpl_ids):
    # scores: [races, models, tickets]; choose strongest cash return ticket
    # inside every market, then order by gross expected return / yen.
    nr,nvar,nt=scores.shape
    picked=np.empty((nr,nvar,6),dtype=np.int32)
    value=np.empty((nr,nvar,6),dtype=np.float32)
    for mk in range(6):
        subset=np.flatnonzero(market==mk)
        if not len(subset):raise RuntimeError("MARKET_WITHOUT_OPTIONS")
        k=np.argmax(scores[:,:,subset],axis=2)
        # Score matrix order: [race, variant, selected template]
        picked[:,:,mk]=tpl_ids[subset[k]]
        value[:,:,mk]=np.take_along_axis(scores[:,:,subset],k[:,:,None],axis=2)[:,:,0]
    return picked,value
def predict_past_months(races,payout,cat,tpl_ids,market):
    n=len(races);v=len(VARIANTS)
    predictions=np.empty((n,v,6),dtype=np.int32)
    value=np.empty((n,v,6),dtype=np.float32)
    states=[PastState(len(tpl_ids),sc) for sc in SCHEMAS]
    template=np.arange(len(tpl_ids),dtype=np.int32)[None,:]
    counter=collections.Counter()
    months=sorted({r["month"] for r in races})
    if len(months)!=136:raise RuntimeError("FULL_136_MONTH_PREQUENTIAL_WINDOW_MISSING")
    for num,month in enumerate(months):
        ids=np.asarray([j for j,r in enumerate(races) if r["month"]==month],dtype=np.int32)
        # All records of SAME month processed BEFORE any payout from that
        # month updates the learning state, including other JRA race days.
        slice_cat={k:cat[k][ids] for k in CARD}
        s=calculate_month_scores(states,slice_cat,template,market,VARIANTS)
        bet,pred=choose_markets(s,market,tpl_ids)
        predictions[ids]=bet
        value[ids]=pred
        # Retroactive training AFTER all this month's bets were generated.
        pay=payout[ids]
        for st in states:st.update(st.code(slice_cat,template),pay)
        counter[month]=len(ids)
        if (num+1)%12==0 or num+1==len(months):
            print("CAUSAL_MONTHLY_CASH_TRAINING_PROGRESS",json.dumps({
                "month":month,"monthsProcessed":num+1,
                "noSameOrFutureMonthPayoutForPredictions":True,
                "raceCount":sum(counter.values())}),flush=True)
    return predictions,value,states,dict(counter)
def stake_units(roi,mode):
    # Keep spending modest when the past predicts a loss. More money
    # can be spent ONLY when cash-return forecast is greater than cost.
    edge=max(0.,float(roi)-1.)
    if mode=="flat_100":return 1
    if mode=="cash_edge":return 1+min(9,int(edge/.45))
    if mode=="cash_scaled":return 1+min(19,int(edge/.25))
    raise RuntimeError("UNKNOWN_CAUSAL_STAKE_METHOD")
def strategies():
    return [{"variant":iv,"slate":slate,"markets":allowed,
             "stake":stake,"paired":paired}
      for iv in range(len(VARIANTS))
      for slate in (3,5,8,12)
      for allowed in ("all6","no_trifecta","winwide")
      for stake in ("flat_100","cash_edge","cash_scaled")
      for paired in (False,True)]
def digest_policy(races,output,values,payout,templates,market,conf,ledger=False):
    # NO CURRENT OR FUTURE CASH is consulted in any decision.
    allowed=({"all6":set(range(6)),
              "no_trifecta":set(range(5)),
              "winwide":{0,1}}[conf["markets"]])
    slotmap={int(k):i for i,k in enumerate(templates)}
    rows=[]
    groups=collections.defaultdict(list)
    for i,r in enumerate(races):groups[(r["day"],int(r["venue"]))].append(i)
    short=[(k,len(v)) for k,v in groups.items() if len(v)<3]
    if short:raise RuntimeError("LESS_THAN_3_RACE_JRA_VENUE_DATE:"+str(short[:2]))
    for day,idx in sorted(groups.items()):
        possibilities=[]
        for i in idx:
            v=conf["variant"]
            scores=values[i,v]
            sorted_m=sorted(allowed,key=lambda m:(-float(scores[m]),m))
            first=sorted_m[0]
            second=sorted_m[1] if len(sorted_m)>1 else None
            ps=float(scores[first])
            s1=stake_units(ps,conf["stake"])
            s2=0
            if conf["paired"] and second is not None and float(scores[second])>=1.1:
                s2=stake_units(float(scores[second]),conf["stake"])
            strength=(ps-1)*s1
            if s2:strength+=(float(scores[second])-1)*s2
            possibilities.append((strength,str(races[i]["id"]),i,first,second,s1,s2))
        # Minimum 3 regardless of current market conditions. Extra tickets
        # selected only if they are forecast cash-positive; no hit bonus.
        possibilities.sort(key=lambda r:(-r[0],r[1]))
        picked=possibilities[:3]
        for z in possibilities[3:conf["slate"]]:
            if z[0]>0:picked.append(z)
        for strength,rid,i,first,second,s1,s2 in picked:
            id1=int(output[i,conf["variant"],first])
            id2=int(output[i,conf["variant"],second]) if s2 else -1
            a=int(payout[i,slotmap[id1]])*s1
            b=int(payout[i,slotmap[id2]])*s2 if s2 else 0
            stake=100*(s1+s2);paid=a+b
            rows.append({"raceId":rid,"group":day,"ticket1":id1,
                "ticket2":id2 if s2 else None,"stake1":100*s1,
                "stake2":100*s2,"stakeYen":stake,"paidYen":paid,
                "profitYen":paid-stake,"hit":int(paid>0),
                "profitableRace":int(paid>stake),
                "predictedNetYen":round(strength*100,2)})
    if len({z["raceId"] for z in rows})!=len(rows):
        raise RuntimeError("DUPLICATE_BET_RACE")
    byday=collections.Counter(z["group"] for z in rows)
    if set(byday)!=set(groups) or any(v<3 for v in byday.values()):
        raise RuntimeError("VENUE_DAY_THREE_DISTINCT_BET_GAP")
    cost=sum(z["stakeYen"] for z in rows)
    cash=sum(z["paidYen"] for z in rows)
    maxp=max(z["paidYen"] for z in rows)
    nr=len(rows);hits=sum(z["hit"] for z in rows)
    profitable=sum(z["profitableRace"] for z in rows)
    if cost<100*nr:raise RuntimeError("BET_NOT_IN_100_YEN_UNITS")
    metric={"purchaseRaces":nr,"venueDays":len(groups),
        "stakeYen":cost,"paidYen":cash,"profitYen":cash-cost,
        "cashRoiPct":round(100*cash/cost,4),
        "largestRacePayoutYen":maxp,
        "minusLargestRaceCashRoiPct":round(100*(cash-maxp)/cost,4),
        "hitRaces":hits,"hitRacePct":round(100*hits/nr,4),
        "profitableRaces":profitable,"profitableRacePct":round(100*profitable/nr,4)}
    if not ledger:return metric,None
    return metric,rows
def qualifies(m):
    return (m["paidYen"]>=2*m["stakeYen"] and
            m["paidYen"]-m["largestRacePayoutYen"]>=2*m["stakeYen"] and
            m["hitRaces"]*5>=m["purchaseRaces"] and
            m["purchaseRaces"]>=3*m["venueDays"])
def run_all(races,payout,cat,tpl,market):
    start=time.monotonic()
    pred,values,states,month_count=predict_past_months(races,payout,cat,tpl,market)
    allpol=strategies()
    results=[]
    best_diagnostic=None
    for ci,conf in enumerate(allpol):
        m,_=digest_policy(races,pred,values,payout,tpl,market,conf)
        if best_diagnostic is None or m["profitYen"]>best_diagnostic["money"]["profitYen"]:
            best_diagnostic={"configuration":conf,"money":m}
        if qualifies(m):
            results.append({"configuration":conf,"money":m})
        if (ci+1)%36==0:
            print("CAUSAL_FROZEN_HISTORY_POLICIES_EVALUATED",
                json.dumps({"evaluated":ci+1,"total":len(allpol),
                  "cash200OnlyQualifyingCount":len(results),
                  "bestDiagnosticProfitYen":best_diagnostic["money"]["profitYen"]}),flush=True)
    results.sort(key=lambda x:x["money"]["profitYen"],reverse=True)
    winner=results[0] if results else None
    if winner:
        metric,led=digest_policy(races,pred,values,payout,tpl,market,
                                 winner["configuration"],True)
        if metric!=winner["money"]:
            raise RuntimeError("LEDGER_VS_PORTFOLIO_CASH_MISMATCH")
        LED.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(LED,"wt",encoding="utf8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(led[0]));w.writeheader()
            w.writerows(sorted(led,key=lambda x:x["raceId"]))
    report={"status":"CAUSAL_PREQUENTIAL_CASH200_HIT20_FOUND" if winner else
                   "NO_CAUSALLY_BACKTESTED_CASH200_HIT20_FOUND",
         "period":"2015-01 through 2026-04",
         "months":len(month_count),
         "historicalRaces":len(races),
         "sameOrFutureMonthSettlementsAvailableDuringPrediction":False,
         "all136MonthsIncludedInSingleTotal":True,
         "finalWinOddsNotVerifiedT15":True,
         "source":"third-party 136 month settled race CSV, not official certified",
         "retrospectivePolicySelectionMayOverfit":True,
         "productionChanged":False,
         "betTypes":list(MARKETS),
         "candidateCount":len(results),
         "realMoneyQualifyingCandidates":results[:15],
         "bestCashDiagnosticOnly":best_diagnostic,
         "policiesAudited":len(allpol),
         "parameters":{"variants":VARIANTS,"minRaces":MIN_RACES},
         "elapsedSeconds":round(time.monotonic()-start,1)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("CAUSAL_CASH_ENGINE_FINAL",json.dumps({
      "status":report["status"],"period":report["period"],
      "prequential":True,"policyCount":len(allpol),"trueCashCandidates":len(results),
      "winner":winner,"bestDiagnostic":best_diagnostic,
      "elapsedSeconds":report["elapsedSeconds"]},ensure_ascii=False),flush=True)
    return report
def selftest():
    s=PastState(2,())
    code=np.asarray([[0,1],[0,1]],np.int32)
    money=np.asarray([[0,1000],[120,0]],np.int32)
    assert s.n.sum()==0
    s.update(code,money)
    assert s.n.tolist()==[2,2]
    assert s.cash.tolist()==[120,1000] and s.maxcash.tolist()==[120,1000]
    assert s.wins.tolist()==[1,1]
    assert not qualifies({"paidYen":4000,"stakeYen":1000,
        "largestRacePayoutYen":2500,"hitRaces":2,"purchaseRaces":10,"venueDays":3})
    assert qualifies({"paidYen":5000,"stakeYen":1000,
        "largestRacePayoutYen":2000,"hitRaces":2,"purchaseRaces":10,"venueDays":3})
    assert stake_units(.5,"cash_scaled")==1
    assert stake_units(2.5,"cash_scaled")>stake_units(.5,"cash_scaled")
    # Deliberate chronology test: current-month score cannot incorporate
    # hypothetical current-month money until update() is called.
    cat={"venue":np.zeros((1,2),np.uint8)}
    for k in CARD:
        if k not in cat:cat[k]=np.zeros((1,2),np.uint8)
    pred1=calculate_month_scores([PastState(2,z) for z in SCHEMAS],
         cat,np.arange(2,dtype=np.int32)[None,:],np.asarray([0,1]),VARIANTS)
    assert np.allclose(pred1[0,:,0],.72)
    print("CAUSAL_MONEY_PREQUENTIAL_SELFTEST_OK",flush=True)
def main():
    if "--self-test" in sys.argv:
        selftest();return
    core,races,payout,cat,templates,market=load_historical()
    run_all(races,payout,cat,templates,market)
if __name__=="__main__":main()
