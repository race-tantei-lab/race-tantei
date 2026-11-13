#!/usr/bin/env python3
"""DIRECT CASH >=200% CANDIDATE MINING: no negative-ROI candidate ever emitted.

This is NOT 'fit model and accept/reject'. Instead iterate pre-race condition
conjunctions and exact purchasable top-ten ticket templates; return ONLY money
rules whose actual 2017-22 realized yen payout minus the single largest
race payout is >=200% of all original invested yen. Nothing else can enter
the candidate list. Independently describe 2023 and 2024-2026 cash. Do not
use those years to CREATE or modify candidates.

Important: all source CSV WIN odds are FINAL, not official JRA T-15; payouts
are a pinned third-party mirror; a qualifying historical money pattern
is NOT a guaranteed future 200% system. No production writes/Cloudflare.
"""
from __future__ import annotations
import collections,csv,gzip,importlib.util,json,math,sys,time
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parents[1]
OUTPUT=R/"analysis-results/nov2026-top10-only-actual-cash200.json"
ROWS=R/"analysis-results/nov2026-top10-only-cash200-conditions.csv.gz"
LEDGER=R/"analysis-results/nov2026-top10-2023-24-repeat-positive-rules.csv"
TRAIN=(2017,2018,2019,2020,2021,2022)
LATER=(2023,2024,2025,2026)
MIN_COUNT=(6,10,20,40,80)
MIN_HITS=2
TEMPLATE_COUNT=1030
COLS=("favOdds","fieldSize","quarter","venue","raceBand",
      "favGap","rankMin","rankMax","rankGap","oddsGeom","draw",
      "horseAge","horseWeight","oddsSpread")
BIN={"favOdds":5,"fieldSize":4,"quarter":4,"venue":10,
     "raceBand":3,"favGap":4,"rankMin":10,"rankMax":10,
     "rankGap":10,"oddsGeom":8,"draw":5,"horseAge":5,
     "horseWeight":5,"oddsSpread":5}
# Betting rule = exact action template and any one pre-bet condition.
# Includes cross products across court/season/horse physical card.
SCHEMA=(
 (),("favOdds",),("fieldSize",),("quarter",),("venue",),
 ("raceBand",),("favGap",),("rankMin",),("rankMax",),("rankGap",),
 ("oddsGeom",),("draw",),("horseAge",),("horseWeight",),
 ("oddsSpread",),("venue","quarter"),("venue","fieldSize"),
 ("venue","favOdds"),("quarter","favOdds"),("fieldSize","favOdds"),
 ("favOdds","favGap"),("fieldSize","quarter"),("rankMin","venue"),
 ("rankMax","venue"),("rankMin","quarter"),("rankMax","quarter"),
 ("rankGap","favOdds"),("rankMin","favOdds"),("rankMax","favOdds"),
 ("oddsGeom","favOdds"),("oddsGeom","fieldSize"),("draw","venue"),
 ("draw","quarter"),("horseAge","venue"),("horseWeight","venue"),
 ("venue","quarter","fieldSize"),("venue","quarter","favOdds"),
 ("venue","favOdds","fieldSize"),("venue","favGap","favOdds"),
 ("quarter","fieldSize","favOdds"),("rankMax","favOdds","quarter"),
 ("rankGap","venue","quarter"),("rankMin","venue","quarter"),
 ("rankMax","venue","fieldSize"),("draw","venue","quarter"),
 ("horseAge","venue","quarter"),("oddsGeom","venue","quarter"),
 ("favGap","venue","quarter"),("rankMax","favOdds","fieldSize"),
 ("rankMin","favOdds","fieldSize"),("oddsSpread","quarter","venue"),
 ("rankMin","rankMax","favOdds"),("rankMin","rankMax","fieldSize"),
 ("rankMin","rankMax","quarter"),("rankMin","rankMax","venue"))
def module(path,modname):
    spec=importlib.util.spec_from_file_location(modname,R/path)
    v=importlib.util.module_from_spec(spec)
    sys.modules[modname]=v;spec.loader.exec_module(v);return v
def source_data():
    source=module("scripts/research-nov2026-decade-roi-first-sixmarkets.py","direct200_source")
    parser=module("scripts/research-nov2026-sixmarket-real-paid-cash.py","direct200_parser")
    records=source.read_all_races(parser.parse_payments)
    if not source.CACHE.exists() or not source.RACE_CACHE.exists():
        source.CACHE.parent.mkdir(parents=True,exist_ok=True)
        source.full_features(records)
    recorded=json.loads(source.RACE_CACHE.read_text())["races"]
    if len(records)!=len(recorded) or any(r["id"]!=z["id"] for r,z in zip(records,recorded)):
        raise RuntimeError("STALE_PAYOUT_SOURCE_OR_RACE_ORDER")
    ids=np.asarray([j for j,r in enumerate(records) if int(r["month"][:4])>=2017],dtype=np.int32)
    races=[records[int(i)] for i in ids]
    year=np.asarray([int(r["month"][:4]) for r in races],dtype=np.int16)
    with np.load(source.CACHE,allow_pickle=False) as b:
       pay=b["payout"][ids].astype(np.int32)
       cat={f:b[f][ids].astype(np.uint8) for f in COLS}
    if pay.shape!=(len(races),1030):
       raise RuntimeError("MISSING_1030_CASH_TICKETS")
    if any(cat[k].shape!=pay.shape for k in COLS):
       raise RuntimeError("FEATURES_MONEY_ALIGNMENT")
    return source,races,year,pay,cat
def group_index(cat,fields):
    n,nt=cat["venue"].shape
    result=np.broadcast_to(np.arange(nt,dtype=np.int32),(n,nt)).copy()
    maxgroup=nt
    for f in fields:
       arr=cat[f]
       if np.any(arr>=BIN[f]):raise RuntimeError("INVALID_"+f+"_BIN")
       result=result*BIN[f]+arr.astype(np.int32)
       maxgroup*=BIN[f]
    return result.ravel(),maxgroup
def month_metrics(cash,n,big,hit):
    n=int(n);cash=float(cash);big=float(big);hit=int(hit)
    return {"tickets":n,"stakeYen":n*100,"paidYen":int(round(cash)),
      "cashRoiPct":round(cash/n,5) if n else None,
      "minusMaxRaceRoiPct":round((cash-big)/n,5) if n else None,
      "paidTickets":hit,"hitPct":round(100*hit/n,3) if n else None,
      "largestPaidRaceYen":int(round(big))}
def validate_exact_max(codes,outcome,good,count):
    biggest=np.zeros(count,dtype=np.float64)
    pos=np.flatnonzero(outcome>0)
    if len(pos):
       chosen=np.zeros(count,dtype=bool);chosen[good]=True
       needed=chosen[codes[pos]]
       np.maximum.at(biggest,codes[pos[needed]],outcome[pos[needed]])
    return biggest
def cash_groups(index,paid,count,only=None):
    tickets=np.bincount(index,minlength=count)
    money=np.bincount(index,weights=paid,minlength=count)
    winning=np.flatnonzero(paid>0)
    positive=np.bincount(index[winning],minlength=count)
    if only is None:only=np.flatnonzero((tickets>=min(MIN_COUNT))&(positive>=MIN_HITS))
    biggest=validate_exact_max(index,paid,only,count)
    return tickets,money,positive,biggest
def decode(code,schema):
    categories={}
    for f in reversed(schema):
        categories[f]=int(code%BIN[f]);code//=BIN[f]
    if code>=TEMPLATE_COUNT:raise RuntimeError("CANNOT_DECODE_TICKET_TEMPLATE")
    return int(code),categories
def main():
    if "--self-test" in sys.argv:
       assert len(SCHEMA)>=50
       assert len({a for a in SCHEMA})==len(SCHEMA)
       assert month_metrics(1050,5,200,3)["minusMaxRaceRoiPct"]==170.
       assert month_metrics(1050,5,0,3)["cashRoiPct"]==210.
       assert not (month_metrics(1050,5,200,3)["minusMaxRaceRoiPct"]>=200)
       print("ONLY_ROI200_MONEY_EXACT_TICKET_TEST_OK",flush=True);return
    clock=time.monotonic()
    source,races,years,payout,cat=source_data()
    slots,market=source.fixed_template()
    market_names=("単勝","ワイド","馬連","馬単","3連複","3連単")
    train=np.isin(years,TRAIN)
    checks={str(y):years==y for y in LATER}
    train_money=payout[train].ravel()
    candidates=[]
    hit_counts=collections.Counter()
    survivors=collections.Counter()
    confirm=collections.Counter()
    for si,schema in enumerate(SCHEMA):
        c,n=group_index({f:cat[f][train] for f in COLS},schema)
        count,pay,hit,big=cash_groups(c,train_money,n)
        q=(count>=min(MIN_COUNT))&(hit>=MIN_HITS)&(
            (pay-big)>=2*100*count)
        qualifiers=np.flatnonzero(q)
        hit_counts["schemas"]+=1
        hit_counts["actualRoi200Cells"]+=int(len(qualifiers))
        # Retain ONLY the 200%-above-after-max historical conditions.
        if not len(qualifiers):continue
        later={}
        for year,mask in checks.items():
            cid,_=group_index({f:cat[f][mask] for f in COLS},schema)
            obs=payout[mask].ravel()
            gc,gy,gh,gb=cash_groups(cid,obs,n,qualifiers)
            later[year]=(gc,gy,gh,gb)
        # Produce a financial candidate row ONLY if 2017-22 ROI
        # >=200 excluding largest winning race, no exceptions.
        for raw in qualifiers:
           k=int(raw)
           tpl,conditions=decode(k,schema)
           rule={"schemaIndex":si,"schema":"+".join(schema) or "ALL",
             "templateId":tpl,"market":market_names[int(market[tpl])],
             "positionRank1based":[p+1 for p in slots[tpl]],
             "conditions":conditions,"groupCode":k,
             "train":month_metrics(pay[k],count[k],big[k],hit[k])}
           if rule["train"]["minusMaxRaceRoiPct"]<200:
                raise RuntimeError("CANDIDATE_ROI200_INVARIANT_BROKEN")
           rule["forward"]={}
           for year in later:
              nc,py,ht,bg=later[year]
              rule["forward"][year]=month_metrics(py[k],nc[k],bg[k],ht[k])
           candidates.append(rule)
           if count[k]>=20 and hit[k]>=3:survivors["trainSupport20And3Wins"]+=1
           yr=rule["forward"]["2023"]
           if yr["tickets"]>=6 and yr["paidTickets"]>=2 and (
                  yr["minusMaxRaceRoiPct"] or 0)>=200:
                confirm["train200And2023Independent200"]+=1
           y24=rule["forward"]["2024"]
           if yr["tickets"]>=6 and yr["paidTickets"]>=2 and (
                 yr["minusMaxRaceRoiPct"] or 0)>=200 and (
                 y24["tickets"]>=6 and y24["paidTickets"]>=2 and
                 (y24["minusMaxRaceRoiPct"] or 0)>=200):
                confirm["train200And2023And2024Independent200"]+=1
        if (si+1)%10==0 or si==len(SCHEMA)-1:
            print("ONLY_ROI200_CONDITIONS_PROGRESS",json.dumps({
              "checkedSchemas":si+1,"totalSchemas":len(SCHEMA),
              "qualifyingROI200Cells":len(candidates),
              "repeated2023":confirm["train200And2023Independent200"],
              "elapsed":round(time.monotonic()-clock,1)}),flush=True)
    # All emitted candidates, without condition that depends on 2023+ labels.
    # The 2023 repeated list is reported separately, not 'retuned' on 2023.
    candidates.sort(key=lambda r:(
       -r["train"]["tickets"],-r["train"]["minusMaxRaceRoiPct"]))
    supported=[r for r in candidates if
       r["train"]["tickets"]>=20 and r["train"]["paidTickets"]>=3]
    top2023=[r for r in candidates if
       r["forward"]["2023"]["tickets"]>=6 and
       r["forward"]["2023"]["paidTickets"]>=2 and
       (r["forward"]["2023"]["minusMaxRaceRoiPct"] or 0)>=200]
    top2023.sort(key=lambda r:(-r["forward"]["2023"]["tickets"],
      -r["forward"]["2023"]["minusMaxRaceRoiPct"]))
    # True cash aggregate, never replacing the hard training 200%
    # candidate criterion. 2024+ is a temporal audit, not a rule source.
    forward_strict=[]
    forward_audit=[]
    for r in top2023:
        series=[r["forward"][str(y)] for y in LATER]
        amount=sum(z["paidYen"] for z in series)
        spent=sum(z["stakeYen"] for z in series)
        biggest=max(z["largestPaidRaceYen"] for z in series)
        robust=round(100*(amount-biggest)/spent,4) if spent else None
        later=series[1:]
        hspent=sum(z["stakeYen"] for z in later)
        hpaid=sum(z["paidYen"] for z in later)
        hbiggest=max(z["largestPaidRaceYen"] for z in later)
        hrobust=round(100*(hpaid-hbiggest)/hspent,4) if hspent else None
        info={"market":r["market"],"rank":r["positionRank1based"],
          "schema":r["schema"],"conditions":r["conditions"],
          "trainTickets":r["train"]["tickets"],
          "trainMinusMaxRoi":r["train"]["minusMaxRaceRoiPct"],
          "2023":r["forward"]["2023"],
          "2024":r["forward"]["2024"],
          "2025":r["forward"]["2025"],
          "2026":r["forward"]["2026"],
          "forwardTotalStakeYen":spent,"forwardTotalPaidYen":amount,
          "forwardTotalMinusMaxRoiPct":robust,
          "untouched2024To2026MinusMaxRoiPct":hrobust}
        forward_audit.append(info)
        if robust is not None and robust>=200:
            forward_strict.append(info)
    print("ROI200_2023_CANDIDATE_EXAMPLES",json.dumps(
      forward_audit[:8],ensure_ascii=False),flush=True)
    print("ROI200_REPEATED_TOTAL_ACTUAL_YEN",json.dumps({
      "2023RepeatedCandidateCount":len(top2023),
      "2023To2026Robust200Candidates":len(forward_strict),
      "2024To2026Robust200Candidates":sum(
         (v["untouched2024To2026MinusMaxRoiPct"] or 0)>=200
         for v in forward_audit),
      "examples":forward_strict[:5]},ensure_ascii=False),flush=True)
    # For all historical candidates store a CSV artifact.
    ROWS.parent.mkdir(exist_ok=True,parents=True)
    with gzip.open(ROWS,"wt",encoding="utf-8",newline="") as f:
       names=["schema","templateId","market","positionRank1based",
         "conditions","trainTickets","trainCashRoiPct",
         "trainMinusMaxRoiPct","trainHits","2023Tickets",
         "2023MinusMaxRoiPct","2024Tickets","2024MinusMaxRoiPct",
         "2025Tickets","2025MinusMaxRoiPct","2026Tickets",
         "2026MinusMaxRoiPct"]
       w=csv.DictWriter(f,fieldnames=names);w.writeheader()
       for r in candidates:
         row={"schema":r["schema"],"templateId":r["templateId"],
          "market":r["market"],"positionRank1based":"-".join(map(str,r["positionRank1based"])),
          "conditions":json.dumps(r["conditions"],separators=(",",":")),
          "trainTickets":r["train"]["tickets"],
          "trainCashRoiPct":r["train"]["cashRoiPct"],
          "trainMinusMaxRoiPct":r["train"]["minusMaxRaceRoiPct"],
          "trainHits":r["train"]["paidTickets"]}
         for y in LATER:
            m=r["forward"][str(y)]
            row[str(y)+"Tickets"]=m["tickets"]
            row[str(y)+"MinusMaxRoiPct"]=m["minusMaxRaceRoiPct"]
         w.writerow(row)
    report={
        "status":"HISTORICAL_CASH_ROI200_CANDIDATES_EXTRACTED" if candidates
            else "NO_DISCOVERED_CASH200_PATTERN",
        "notAPretrainedHorseWinModel":True,
        "candidateDefinition":"real paid cash ROI >=200% after removing largest race payout, original spend retained; 2017-2022; >=6 tickets and >=2 winning ticket events",
        "candidateOnlyBelow200NeverExists":True,
        "historicalFinalOddsNotOfficialJraT15":True,
        "notIndependentlyJraPayoutReconciled":True,
        "productionUnchanged":True,
        "fullTop10SixMarkets":True,
        "sourceRaces":len(races),
        "historicalTicketTemplates":TEMPLATE_COUNT,
        "searchSchemas":len(SCHEMA),
        "totalHistoricalBetableTicketEvents":int(payout.size),
        "totalFinancialCandidates":len(candidates),
        "candidatesWithSupport20AndThreeHits":len(supported),
        "countRepeated200In2023":len(top2023),
        "countRepeated200In2023And2024":confirm["train200And2023And2024Independent200"],
        "repeated2023CandidateCrossYearMoneyAudits":forward_audit[:35],
        "2023To2026ConfirmedRobust200Count":len(forward_strict),
        "mostSupportedStrictlyRO200Candidates":supported[:35],
        "topRepeated2023Only200Candidates":top2023[:35],
        "allCandidateCsv":str(ROWS.relative_to(R)),
        "elapsedSec":round(time.monotonic()-clock,2)}
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("ROI200_ONLY_CANDIDATE_SEARCH_RESULT",json.dumps({
      "status":report["status"],"cash200Train":len(candidates),
      "cash200TrainWithSupport20":len(supported),
      "cash200RepeatedOn2023":len(top2023),
      "cash200RepeatedOn2023And2024":report["countRepeated200In2023And2024"],
      "ticketUniverse":int(payout.size),
      "ruleSpaces":len(SCHEMA),
      "elapsedSec":report["elapsedSec"],
      "prodChanged":False
    },ensure_ascii=False),flush=True)
if __name__=="__main__":main()
