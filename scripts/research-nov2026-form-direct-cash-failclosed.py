#!/usr/bin/env python3
"""Direct, all-cells monetary ROI search on historical pre-race HORSE FORM.

No horse prediction model is fitted. Enumerate 20 pre-race form attributes:
single forms, ALL 190 pairs of forms, ALL 200 form + market-context
pairs, plus 68 predetermined 2-form + context triples. Each market/ticket
category combination is evaluated using exactly actual settled 100-yen returns.

FAIL CLOSED: no form-less ticket may enter the cash totals, no 0 bucket for
missing race joins. The archive feature join must match YEAR-MONTH, venue,
race number, and names/numbers of all top-seven runners, uniquely.
Split: 2024 mining, 2025H1 and 2025H2 independently, 2026 Jan-Mar
chronological check (2025 and 2026 were previously examined by research).
Payouts are third-party; official JRA T-15 odds are NOT available.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from itertools import combinations
from pathlib import Path
import csv,gzip,importlib.util,json,sys,time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-form-direct-exhaustive-roi200.json"
ALL=ROOT/"analysis-results/nov2026-form-direct-roi200-cells.csv.gz"
PERIODS=("train2024","2025H1","2025H2","2026JanMar")
MIN_TRAIN=100
MIN_LATER=10

def mod(file,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/file)
    if spec is None or spec.loader is None:raise RuntimeError("DEPENDENCY_MISSING:"+file)
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj

def schemas(form):
    names=tuple(form.NEW_NAMES)
    ctx=tuple(form.CASH_CONTEXT)
    if len(names)!=20 or len(ctx)!=10:raise RuntimeError("FORM_SCHEMA_CHANGED")
    seen=set()
    for one in names:
        seen.add((one,))
        for context in ctx:seen.add((one,context))
    for a,b in combinations(names,2):seen.add((a,b))
    for a,b in form.FORM_COMBOS:
        for context in ("oddGeom","rankMax","venue","fieldBand"):
            seen.add((a,b,context))
    found=tuple(sorted(seen))
    if len(found)!=478:raise RuntimeError("FORM_SCHEMA_EXPECTED_478:"+str(len(found)))
    return found

def joined_full_names(races,metadata,history_names,settled_names,form):
    # Only horse identity and month/venue/race number are used; NO finish,
    # winner, payouts, post-race prices or other target data enter the join.
    available=defaultdict(list)
    for idx,m in enumerate(metadata):
        venue=next((num for name,num in form.VENUES.items()
                    if name in m["venue"]),None)
        month=str(m["date"])[:7].replace("-","")
        if venue and len(month)==6:
            available[(month,venue,int(m["raceNo"]))].append(idx)
    ok={};audit=Counter()
    used=set()
    for race in races:
        pool=[int(h[0]) for h in race["horses"][:7]]
        source=settled_names.get(race["id"],{})
        if len(pool)!=7 or len(set(pool))!=7 or any(p not in source for p in pool):
            audit["missingSettledRunnerIdentity"]+=1
            continue
        key=(race["month"],str(race["venue"]),int(race["no"]))
        matching=[]
        for idx in available.get(key,[]):
            m=metadata[idx]
            hnames=history_names.get(m["raceId"],{})
            if all(num in m["horseNos"] and
                   form.normalize_horse(hnames.get(num,""))==source[num] and
                   bool(source[num]) for num in pool):
                matching.append(idx)
        if len(matching)!=1:
            audit["noUnambiguousSevenHorseMonthVenueRaceJoin"]+=1
            continue
        idx=matching[0]
        if idx in used:raise RuntimeError("DUPLICATE_HISTORICAL_RACE_JOIN")
        used.add(idx)
        ok[race["id"]]=idx
        audit["uniqueSevenHorseJoined"]+=1
        audit["joinedYear"+race["month"][:4]]+=1
    return ok,dict(audit)

def max_race_return(codes,race_ids,returns,candidate_ids,ngroups,n_races):
    """Exact maximum payout SUM within one race for each selected cell."""
    max_paid=np.zeros(ngroups,dtype=np.float64)
    if not len(candidate_ids):return max_paid
    keep=np.zeros(ngroups,dtype=bool)
    keep[candidate_ids]=True
    ix=np.flatnonzero((returns>0)&keep[codes])
    if not len(ix):return max_paid
    packed=(codes[ix].astype(np.int64)*int(n_races)+race_ids[ix].astype(np.int64))
    uniq,rev=np.unique(packed,return_inverse=True)
    sums=np.bincount(rev,weights=returns[ix])
    np.maximum.at(max_paid,uniq//int(n_races),sums)
    return max_paid

def measure(codes,returns,race_ids,mask,ids,ngroups,n_races):
    a=codes[mask];y=returns[mask];rid=race_ids[mask]
    n=np.bincount(a,minlength=ngroups)
    paid=np.bincount(a,weights=y,minlength=ngroups)
    pos=y>0
    win=np.bincount(a[pos],minlength=ngroups)
    worst=max_race_return(a,rid,y,ids,ngroups,n_races)
    return n,paid,win,worst

def percentage(paid,n):
    return round(float(paid)/int(n),4) if n>0 else None

def main():
    if "--self-test" in sys.argv:
        X=np.array([300,200,400,0,100,0],dtype=np.int32)
        codes=np.array([0,0,0,0,1,1],dtype=np.int32)
        races=np.array([0,0,1,1,2,2],dtype=np.int32)
        maxy=max_race_return(codes,races,X,np.array([0,1]),2,3)
        assert maxy.tolist()==[500.,100.]
        assert percentage(600,3)==200.
        f=mod("scripts/research-nov2026-chronological-form-money-conditions.py","form_categories_source")
        assert len(schemas(f))==478
        print("FORM_DIRECT_PAID_CASH_FAIL_CLOSED_SELFTEST_OK",flush=True)
        return

    begin=time.monotonic()
    form=mod("scripts/research-nov2026-chronological-form-money-conditions.py","form_cat")
    hist=mod("scripts/research-nov2026-56feature-sixmarket-pl-money.py","pre_result_chronology")
    pub=mod("scripts/research-nov2026-sixmarket-real-paid-cash.py","paid_sixmarket")
    past=mod("scripts/research-nov2026-roi200-first-pattern-search.py","category_source")
    cache=mod("scripts/research-nov2026-profitable-individual-rule-subsets.py","real_money_cached_categories")
    pub.TOP_HORSES=7
    raw_races,source_audit=pub.read_pinned_csv()
    names=hist.read_source_horse_names()
    X,won,off,meta,arch_names,drop=hist.historical_horse_features()
    joined,join_audit=joined_full_names(raw_races,meta,arch_names,names,hist)
    race_cached,y_full,idx_full,type_full,cat_full=cache.history_and_categories(past)
    if len(raw_races)!=len(race_cached) or [r["id"] for r in raw_races]!=[r["id"] for r in race_cached]:
        raise RuntimeError("PAYOUT_CACHE_RACE_ORDER_NOT_IDENTICAL_TO_RAW_PAYOUTS")
    # Never call form_categories on unmatched races: it would assign zero
    # form categories, which are valid and create artificial profit patterns.
    keep_race=np.asarray([i for i,r in enumerate(raw_races) if r["id"] in joined],dtype=np.int32)
    selected=[raw_races[int(i)] for i in keep_race]
    for year in (2024,2025,2026):
        actual=sum(r["month"].startswith(str(year)) for r in selected)
        total=sum(r["month"].startswith(str(year)) for r in raw_races)
        if actual<500 or actual/max(total,1)<.55:
            raise RuntimeError("INSUFFICIENT_PRE_RACE_FORM_COVERAGE_YEAR_"+str(year)+":"+str(actual)+"/"+str(total))
    formcats=form.form_categories(selected,joined,meta,off,X)
    if any(len(v)!=len(selected)*336 for v in formcats.values()):
        raise RuntimeError("FORM_ROWS_NOT_ALIGNED_WITH_PAID_TICKETS")
    rows=(keep_race[:,None]*336+np.arange(336)).ravel()
    if np.any(idx_full[rows]!=np.repeat(keep_race,336)):
        raise RuntimeError("CACHED_PAID_TICKET_RACE_INDEX_MISALIGNED")
    y=y_full[rows].astype(np.int32)
    typ=type_full[rows].astype(np.int8)
    race_id=np.repeat(np.arange(len(selected),dtype=np.int32),336)
    cats={k:v[rows] for k,v in cat_full.items()}
    cats.update(formcats)
    if np.any(y<0) or len(y)!=336*len(selected):
        raise RuntimeError("NOT_ALL_336_TRUE_SETTLED_TICKETS_PER_JOINED_RACE")
    if any(np.any(arr>3) for arr in formcats.values()):
        raise RuntimeError("MISSING_OR_OUT_OF_RANGE_FORM_BUCKET")
    past.BASE_FEATURES.update({name:4 for name in form.NEW_NAMES})
    spans=np.asarray([r["month"] for r in selected])
    period={
      "train2024":(spans>="202401")&(spans<"202501"),
      "2025H1":(spans>="202501")&(spans<"202507"),
      "2025H2":(spans>="202507")&(spans<"202601"),
      "2026JanMar":(spans>="202601")&(spans<"202604")}
    periods={k:np.repeat(v,336) for k,v in period.items()}
    scans=schemas(form)
    print("FORM_DIRECT_CASH_UNIVERSE",json.dumps({
       "rawPayoutRaces":len(raw_races),"validSevenNameJoinedRaces":len(selected),
       "validTicketCount":len(y),"schemas":len(scans),
       "trainingRaces":int(sum(period["train2024"])),
       "validationRaces":{k:int(sum(v)) for k,v in period.items()},
       "joinAudit":join_audit,"sourceAudit":source_audit,
       "chronologicalFeatureDropped":drop,
       "historicalOddsOnlyFinal":True},ensure_ascii=False,default=str),flush=True)

    fields=["market","fields","conditionCode","2024Tickets",
       "2024WinningTickets","2024StakeYen","2024PayoutYen",
       "2024RoiPct","2024LargestRaceYen","2024MinusMaxRaceRoiPct",
       "2025H1Tickets","2025H1PayoutYen","2025H1MinusMaxRaceRoiPct",
       "2025H2Tickets","2025H2PayoutYen","2025H2MinusMaxRaceRoiPct",
       "2026JanMarTickets","2026JanMarPayoutYen",
       "2026JanMarMinusMaxRaceRoiPct"]
    totals=Counter()
    top=[]
    ALL.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(ALL,"wt",newline="",encoding="utf-8") as fh:
      writer=csv.DictWriter(fh,fieldnames=fields);writer.writeheader()
      for it,pat in enumerate(scans,1):
        fieldsig=("market",)+pat
        code,ngroups=past.mixed_code(fieldsig,typ,cats)
        train=periods["train2024"]
        n=np.bincount(code[train],minlength=ngroups)
        cash=np.bincount(code[train],weights=y[train],minlength=ngroups)
        wins=np.bincount(code[train & (y>0)],minlength=ngroups)
        gross=np.flatnonzero((n>=MIN_TRAIN)&(wins>=3)&(cash>=200*n))
        totals["historicalGross200Support100"]+=len(gross)
        if not len(gross):continue
        maxrace=max_race_return(code[train],race_id[train],y[train],
                  gross,ngroups,len(selected))
        robust=gross[(cash[gross]-maxrace[gross])>=200*n[gross]]
        totals["historicalRobust200Support100"]+=len(robust)
        if not len(robust):continue
        future={}
        for per in PERIODS[1:]:
            future[per]=measure(code,y,race_id,periods[per],
                              robust,ngroups,len(selected))
        for group in robust:
            group=int(group)
            row={"market":form.SIX[group//(ngroups//6)] if ngroups%6==0 else "unknown",
             "fields":"+".join(pat),"conditionCode":group,
             "2024Tickets":int(n[group]),
             "2024WinningTickets":int(wins[group]),
             "2024StakeYen":int(n[group]*100),
             "2024PayoutYen":int(round(cash[group])),
             "2024RoiPct":percentage(cash[group],n[group]),
             "2024LargestRaceYen":int(round(maxrace[group])),
             "2024MinusMaxRaceRoiPct":percentage(cash[group]-maxrace[group],n[group])}
            survive=True
            for per in PERIODS[1:]:
                nn,pp,ww,bb=future[per]
                row[per+"Tickets"]=int(nn[group])
                row[per+"PayoutYen"]=int(round(pp[group]))
                row[per+"MinusMaxRaceRoiPct"]=percentage(pp[group]-bb[group],nn[group])
                is200=(nn[group]>=MIN_LATER and pp[group]-bb[group]>=200*nn[group])
                totals[per+"Robust200"]+=int(is200)
                survive=survive and is200
            totals["allFuturePeriodsRobust200"]+=int(survive)
            writer.writerow(row)
            top.append(row)
        if it%25==0:
          print("FORM_DIRECT_CASH_PROGRESS",json.dumps({
            "schemas":it,"total":len(scans),"cash200cells":int(totals["historicalGross200Support100"]),
            "historicallyRobust":int(totals["historicalRobust200Support100"]),
            "repeatedThrough2026":int(totals["allFuturePeriodsRobust200"]),
            "elapsedSeconds":round(time.monotonic()-begin,2)}),flush=True)
    top.sort(key=lambda x:(-x["2024Tickets"],-x["2024MinusMaxRaceRoiPct"]))
    result={"status":"RESEARCH_NOT_PRODUCTION","method":"direct all preset 478 form-context cash conjunctions, no model fitted",
      "dataProvenance":"third-party JRA settled payouts, per ticket ¥100 cash",
      "preRaceFormSource":"chronological same-day-safe 56 features reconstructed from archived runners",
      "strictMonthVenueRaceAndSevenHorseNameJoin":True,
      "training":"2024 only; data form source too sparse for requested 2015-22 history",
      "holdoutChecks":["2025H1","2025H2","2026JanMar"],
      "2025And2026PreviouslyInspected":True,
      "officialT15SixMarketOdds":False,"officialPayoutReconciliation":False,
      "matchedRaces":len(selected),"ticketCount":len(y),
      "schemas":len(scans),"stats":dict(totals),"bestSupported2024CashCells":top[:50],
      "allHistoricallyRobustCells":str(ALL.relative_to(ROOT)),
      "productionChanged":False,"seconds":round(time.monotonic()-begin,2)}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("FORM_DIRECT_CASH_FINAL",json.dumps({
       "stats":dict(totals),"schemas":len(scans),"races":len(selected),
       "elapsedSeconds":result["seconds"],"json":str(OUT),"csv":str(ALL)},
       ensure_ascii=False),flush=True)

if __name__=="__main__": main()
