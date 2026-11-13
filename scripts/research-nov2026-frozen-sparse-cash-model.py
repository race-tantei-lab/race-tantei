#!/usr/bin/env python3
"""FREE-CONSTRAINTS FROZEN REAL-CASH RULE MODEL.

Actually materializes a selected betting model, per-race executable tickets,
and chronological money ledger. No fixed 3/5 racing-day quota, paired markets,
hit-rate floor, or fixed daily spend; skips any race without a strong signal.

Use only pre-result odds / field / venue / calendar categorical conditions.
Mine exact TICKET TEMPLATE x race condition from 2017-2021 outcomes. 2022
is the ONLY parameter-selection stage, then freeze. Hold out 2023-2026.
No outcomes from the predicted race are ever fed into the betting decision.
Source odds are final historical win odds, not JRA T-15; third-party payout
unreconciled. This is NOT production-ready regardless of retrospective ROI.
"""
from __future__ import annotations
import collections,csv,importlib.util,json,sys,time
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parents[1]
OUT=R/"analysis-results/nov2026-frozen-sparse-cash-model.json"
LED=R/"analysis-results/nov2026-frozen-sparse-cash-bets.csv"
MODEL=R/"analysis-results/nov2026-frozen-sparse-cash-policy.json"
PARAMS=R/"analysis-results/nov2026-frozen-sparse-cash-frozen-scores.npz"
TRAIN=tuple(range(2017,2022))
VALID=2022
EVAL=(2023,2024,2025,2026)
MKT=("単勝","ワイド","馬連","馬単","3連複","3連単")
FIELDS={"favOdds":5,"fieldSize":4,"quarter":4,"venue":10,
        "raceBand":3,"favGap":4}
SCHEMAS=(
 (),("favOdds",),("fieldSize",),("quarter",),("venue",),("raceBand",),
 ("favGap",),("favOdds","fieldSize"),("favOdds","quarter"),
 ("venue","quarter"),("venue","fieldSize"),("venue","favOdds"),
 ("fieldSize","quarter"),("raceBand","favOdds"),("venue","favGap"),
 ("favOdds","favGap"),("quarter","favGap"),("fieldSize","favGap"),
 ("venue","quarter","favOdds"),("venue","quarter","fieldSize"),
 ("venue","fieldSize","favOdds"),("quarter","favOdds","fieldSize"),
 ("venue","favOdds","favGap"),("raceBand","favOdds","fieldSize"),
 ("quarter","favOdds","favGap"))
# The standard JRA pari-mutuel takeout makes this intentionally sparse:
# only leave-max REAL money return >200/100 yen is eligible as a rule.
MIN_TRAINS=(6,12,24,48)
MIN_HITS=(2,3)
MIN_POST_MAX=(200,350)
PICK_PER_DAY=(1,2,4,12)
CONFIDENCE=(.25,)
SEEDS=(101,211,431)
def dep():
    p=R/"scripts/research-nov2026-decade-roi-first-sixmarkets.py"
    q=importlib.util.spec_from_file_location("sparse_fullcash_archive",p)
    m=importlib.util.module_from_spec(q);sys.modules[q.name]=m;q.loader.exec_module(m)
    return m
def dep_parse():
    p=R/"scripts/research-nov2026-sixmarket-real-paid-cash.py"
    q=importlib.util.spec_from_file_location("sparse_fullcash_parser",p)
    m=importlib.util.module_from_spec(q);sys.modules[q.name]=m;q.loader.exec_module(m)
    return m
def money(y):
    v=np.asarray(y,dtype=np.int64);n=len(v);stake=100*n
    paid=int(v.sum());mx=int(v.max()) if n else 0
    return {"bets":n,"stakeYen":stake,"paidYen":paid,
      "roiPct":round(100*paid/stake,4) if n else None,
      "minusLargestPaidRaceRoiPct":round(100*(paid-mx)/stake,4) if n else None,
      "hitPct":round(100*np.count_nonzero(v)/n,4) if n else None,
      "largestRacePaidYen":mx}
def qualified(q,minimum=6):
    return q["bets"]>=minimum and (q["roiPct"] or 0)>=200 and (
      q["minusLargestPaidRaceRoiPct"] or 0)>=200
def archive():
    module=dep();parser=dep_parse()
    races=module.read_all_races(parser.parse_payments)
    if not (module.CACHE.exists() and module.RACE_CACHE.exists()):
        module.CACHE.parent.mkdir(parents=True,exist_ok=True)
        module.full_features(races)
    year=np.asarray([int(r["month"][:4]) for r in races],dtype=np.int16)
    ids=np.flatnonzero(year>=2017)
    races=[races[int(i)] for i in ids]
    years=year[ids]
    cat={}
    with np.load(module.CACHE,allow_pickle=False) as z:
        if z["payout"].shape[0]!=len(year):raise RuntimeError("CASH_CACHE_WRONG_ARCHIVE")
        payouts=z["payout"][ids].astype(np.int32)
        for key in FIELDS:cat[key]=np.asarray(z[key][ids],dtype=np.uint8)
    if payouts.shape!=(len(races),module.N) or any(v.shape!=payouts.shape for v in cat.values()):
        raise RuntimeError("SIX_MARKET_CASH_SHAPE_MISMATCH")
    return module,races,years,payouts,cat
def sample_group_code(cat,template,schema):
    # template remains literal bet TYPE + ordered 1..10 popularity ranks.
    # This cannot encode winner, top3 outcome, or payout, by construction.
    code=np.broadcast_to(template,cat["venue"].shape).astype(np.int32).copy()
    size=int(template.max())+1
    for f in schema:
        v=cat[f]
        if np.any(v>=FIELDS[f]):raise RuntimeError("BAD_PRE_RACE_CATEGORY_"+f)
        code=code*FIELDS[f]+v.astype(np.int32)
        size*=FIELDS[f]
    return code,size
def frozen_cash_rules(years,payout,cat):
    train=np.flatnonzero(np.isin(years,TRAIN))
    if len(train)<13000:raise RuntimeError("NOT_ENOUGH_TRAINING")
    template=np.arange(payout.shape[1],dtype=np.int32)[None,:]
    buckets=[]
    for si,schema in enumerate(SCHEMAS):
        # Groups always keyed by EXACT ticket template and categorical
        # race-context schema, no race-result-derived feature.
        groups,nc=sample_group_code({f:cat[f][train] for f in FIELDS},template,schema)
        c=groups.ravel()
        p=payout[train].ravel().astype(np.float64)
        counts=np.bincount(c,minlength=nc)
        return_sum=np.bincount(c,weights=p,minlength=nc)
        hits=np.bincount(c,weights=(p>0),minlength=nc)
        largest=np.zeros(nc,dtype=np.float64)
        w=np.flatnonzero(p>0)
        np.maximum.at(largest,c[w],p[w])
        # Each group has at most one ticket per race, hence max individual
        # winning payout = true largest race payout for this rule.
        robust=(return_sum-largest)/np.maximum(1,counts)
        # count, hits and returns per unit all freeze before 2022.
        buckets.append({"schema":list(schema),"size":nc,
            "count":counts,"cash":return_sum,"hit":hits,"largest":largest,
            "robust":robust})
    return buckets
def score_rules(buckets,cat,minimum,hit_min,robust_min,confidence):
    n,nt=cat["venue"].shape
    template=np.arange(nt,dtype=np.int32)[None,:]
    best=np.zeros((n,nt),dtype=np.float32)
    chosen=np.full((n,nt),-1,dtype=np.int16)
    for si,r in enumerate(buckets):
        count=r["count"]
        ok=(count>=minimum)&(r["hit"]>=hit_min)&(r["robust"]>=robust_min)
        if not np.any(ok):continue
        # Anti-jackpot capped per-ticket train score, scaled by support
        # confidence and number of distinct cash-paying tickets.
        signal=np.where(ok,np.minimum(r["robust"],15000)*
            np.power(np.minimum(count,200)/200,confidence)*
            np.minimum(r["hit"],15)/15,0).astype(np.float32)
        code,_=sample_group_code(cat,template,r["schema"])
        evaluated=signal[code]
        mask=evaluated>best
        best[mask]=evaluated[mask]
        chosen[mask]=si
    return best,chosen
def select(races,idx,score,ruleidx,spent_per_day,random_seed):
    n=len(idx)
    # Deterministic sparse model: max money signal per race, then at most
    # n events per venue-day. Deterministic raceID tie break before payment.
    valid=np.max(score,axis=1)>0
    best_ticket=np.argmax(score,axis=1).astype(np.int32)
    strength=score[np.arange(n),best_ticket]
    policy=ruleidx[np.arange(n),best_ticket]
    grouped=collections.defaultdict(list)
    for k,i in enumerate(idx):
        if not valid[k]:continue
        r=races[int(i)]
        grouped[(r["day"],r["venue"])].append(k)
    selected=[]
    for key,indices in sorted(grouped.items()):
        # The seed controls deterministic tie ordering only, NOT paid labels.
        def keyfn(k):
            z=(int(races[int(idx[k])]["id"][-6:])*1103515245+random_seed)%2147483647
            return (-float(strength[k]),int(z),int(idx[k]))
        selected.extend(sorted(indices,key=keyfn)[:spent_per_day])
    return np.asarray(selected,dtype=np.int32),best_ticket,policy,strength
def tickets_for(races,idx,cash,pre,chosen,perday,seed,slots,market):
    indices,tickets,policies,strength=select(races,idx,pre,chosen,perday,seed)
    settlement=cash[idx[indices],tickets[indices]].astype(np.int64)
    ledger=[]
    for z,j in enumerate(indices):
        r=races[int(idx[j])]
        tpl=int(tickets[j]);kind=int(market[tpl])
        slot=slots[tpl]
        horses=[int(r["horses"][rank][0]) for rank in slot]
        # This mapping to horse number uses the same historical source
        # ranking; not result positions (the research source has final odds).
        ledger.append({"raceId":r["id"],"year":int(r["month"][:4]),
          "raceDay":r["day"],"venue":r["venue"],"raceNo":r["raceNo"],
          "market":MKT[kind],"ticketTemplate":tpl,
          "horseNumbers":"-".join(map(str,horses)),
          "stakeYen":100,"paidYen":int(settlement[z]),
          "trainingRuleSchema":int(policies[j]),"frozenTrainScore":round(float(strength[j]),3)})
    return ledger,money(settlement)
def main():
    if "--self-test" in sys.argv:
        assert len(SCHEMAS)==25
        assert abs(money([1000,2000,0])["minusLargestPaidRaceRoiPct"]-1000/3)<0.001
        assert not qualified(money([1000,0]))
        assert qualified(money([1000]*6))
        print("FROZEN_SPARSE_MODEL_UNIT_CASH_TEST_OK");return
    start=time.monotonic()
    core,races,years,cash,cat=archive()
    templates,market=core.fixed_template()
    buckets=frozen_cash_rules(years,cash,cat)
    index2022=np.flatnonzero(years==VALID)
    validations=[]
    live_candidates=[]
    for minimum in MIN_TRAINS:
     for hits in MIN_HITS:
      for threshold in MIN_POST_MAX:
       for confidence in CONFIDENCE:
        best,chosen=score_rules(buckets,{f:cat[f][index2022] for f in FIELDS},
            minimum,hits,threshold,confidence)
        for perday in PICK_PER_DAY:
         ledger,result=tickets_for(races,index2022,cash,best,chosen,
            perday,SEEDS[0],templates,market)
         policy=dict(minTrainTickets=minimum,minTrainCashHits=hits,
            minTrainingMinusMaxRoiPct=threshold,
            shrinkExponent=confidence,
            maxBetsPerVenueDay=perday,tieSeed=SEEDS[0],
            candidateTemplates=core.N,
            policyFrozenBeforeValidation=True,
            validation2022=result)
         validations.append(policy)
         if qualified(result,6):
            live_candidates.append(policy)
        # Deliberately do not use 2023+ labels for hyperparameter selection.
    pick=max(live_candidates,key=lambda p:(
        p["validation2022"]["minusLargestPaidRaceRoiPct"],
        p["validation2022"]["bets"])) if live_candidates else None
    # A genuine OUTPUT MODEL is emitted even if its numeric gate is
    # rejected: it is then a research model, NOT a 200% adopted model.
    fallback=max(validations,key=lambda p:(
      p["validation2022"]["minusLargestPaidRaceRoiPct"] or -1,
      p["validation2022"]["bets"])) if validations else None
    recipe=pick or fallback
    if recipe is None:raise RuntimeError("NO_TRAINED_POLICY")
    # Actual trained model parameters, not just the experiment algorithm:
    # serialized frozen score vector by ticket+context cell, generated
    # using 2017-2021 ONLY. The policy JSON specifies feature encoding.
    params={}
    for j,r in enumerate(buckets):
        n=r["count"]
        ok=(n>=recipe["minTrainTickets"])&(
            r["hit"]>=recipe["minTrainCashHits"])&(
            r["robust"]>=recipe["minTrainingMinusMaxRoiPct"])
        params["schema"+str(j)]=np.where(ok,
            np.minimum(r["robust"],15000)*
            np.power(np.minimum(n,200)/200,recipe["shrinkExponent"])*
            np.minimum(r["hit"],15)/15,0).astype(np.float32)
    np.savez_compressed(PARAMS,**params)
    with MODEL.open("w",encoding="utf8") as f:
        json.dump({**recipe,"frozenWeightsFile":str(PARAMS.relative_to(R)),
          "features":list(FIELDS),"schemas":[list(z) for z in SCHEMAS],
          "templateOrder":"source.fixed_template top-ten ranks 1030",
          "purpose":"actual-money direct sparse betting",
          "source":"third-party payout with final WIN odds",
          "acceptance":"ONLY with independent 200pct cash ROI, minus-max, official T15",
          "qualification2022":bool(pick),
          "productionAllowed":False},f,ensure_ascii=False,indent=2)
    testyears=(VALID,*EVAL)
    allrows=[];periods={}
    for y in testyears:
        index=np.flatnonzero(years==y)
        score,chosen=score_rules(buckets,{f:cat[f][index] for f in FIELDS},
           recipe["minTrainTickets"],recipe["minTrainCashHits"],
           recipe["minTrainingMinusMaxRoiPct"],recipe["shrinkExponent"])
        rows,report=tickets_for(races,index,cash,score,chosen,
             recipe["maxBetsPerVenueDay"],recipe["tieSeed"],
             templates,market)
        periods[str(y)]=report;allrows.extend(rows)
        print("FROZEN_SPARSE_ACTUAL_JPY",json.dumps({"year":y,"cash":report}),flush=True)
    forward=[r for r in allrows if r["year"]>=2023]
    aggregate=money([r["paidYen"] for r in forward])
    successful=bool(pick) and qualified(aggregate,30) and all(
        qualified(periods[str(y)],4) for y in EVAL)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with LED.open("w",encoding="utf8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(allrows[0]));w.writeheader();w.writerows(allrows)
    report={"status":"RETROSPECTIVE_ONLY_200_NOT_T15_PROVEN" if successful
         else "REJECTED_NOT_ADOPTABLE_MODEL",
       "researchPolicyArtifact":str(MODEL.relative_to(R)),
       "frozenModelWeights":str(PARAMS.relative_to(R)),
       "actualTicketsLedger":str(LED.relative_to(R)),
       "sourceRaces":len(races),"marketTicketTemplates":core.N,
       "trainingYears":TRAIN,"2022ParametersTested":len(validations),
       "2022QualifyingPolicies":len(live_candidates),
       "policyChosenUsingLaterPayouts":False,"frozenModel":recipe,
       "yearlyActualCash":periods,"combined2023To2026ActualCash":aggregate,
       "numericAllYearsPassed":successful,
       "officialT15OddsVerified":False,
       "thirdPartyPayoutIndependentlyVerified":False,
       "2026AugNovNotAvailable":True,
       "productionChanged":False,
       "elapsedSeconds":round(time.monotonic()-start,2)}
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("FROZEN_SPARSE_MODEL_FINAL",json.dumps({"status":report["status"],
         "year2022Qualifiers":len(live_candidates),
         "actualCash2023To2026":aggregate,
         "modelArtifactWritten":True,"actualLedgerRows":len(allrows),
         "elapsedSeconds":report["elapsedSeconds"],
         "productionChanged":False},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
