#!/usr/bin/env python3
"""Form x three pre-race race-context dimensions: new finite cash-first search.

This extends the first valid 2024-only horse-form experiment to 2017-22
discovery, 2023/24 independent repetition checks, 2025 and 2026JanApr
previously-inspected chronological checks. SIX cash markets, TOP SEVEN
runner tickets, 76 form-pair venue-quarter condition schemas: 19 non-odds horse-form x 10 triples of five pre-race context columns.

NO horse win model trained. Actual third-party payout yen per 100-yen
ticket; not official independent reconciliation. Historical odds are
final WIN odds, NOT official JRA T-15.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from itertools import combinations
from pathlib import Path
import csv,gzip,importlib.util,json,sys,time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-form-pair-venue-quarter-roi200.json"
ROWS=ROOT/"analysis-results/nov2026-form-pair-venue-quarter-robust-cells.csv.gz"
TRAIN="2017To2022"
YEARS=(TRAIN,"2023","2024","2025","2026JanApr")
CONTEXT=("rankMin","rankMax","rankGap","oddsGeom","favOdds",
         "venue","fieldSize","quarter","draw","horseAge")
GROUP_MIN_TRAIN=100

def mod(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if spec is None or spec.loader is None:raise RuntimeError("SOURCE_NOT_FOUND:"+path)
    x=importlib.util.module_from_spec(spec)
    sys.modules[name]=x
    spec.loader.exec_module(x)
    return x

def rank7_market_indices(source,form):
    positions=form.positional_tickets()
    slots,market=source.fixed_template()
    mapping={(int(market[i]),tuple(slots[i])):i for i in range(len(slots))}
    boundaries=np.cumsum((0,7,21,21,42,35,210))
    result=[]
    for typ in range(6):
        for row in positions[boundaries[typ]:boundaries[typ+1]]:
            parts=tuple(int(x) for x in row if x>=0)
            result.append(mapping[(typ,parts)])
    if len(result)!=336 or len(set(result))!=336:raise RuntimeError("TOP7_TICKETS_NOT_336")
    return np.asarray(result,dtype=np.int32)

def names_from_monthly_data(files,form):
    out=defaultdict(dict)
    for file in files:
        with file.open(encoding="utf-8-sig",newline="") as fh:
            for rec in csv.DictReader(fh):
                rid=str(rec.get("race_id",""))
                name=rec.get("馬名") or rec.get("馬名(漢字)") or rec.get("horse_name")
                try:num=int(rec.get("馬番",""))
                except (TypeError,ValueError):continue
                if len(rid)==12 and name:
                    out[rid][num]=form.normalize_horse(name)
    return out

def attrs(form):
    # Two distinct time-ordered horse-form categories crossed with two
    # genuinely pre-race context dimensions. No historical final odds.
    safe=tuple(x for x in form.NEW_NAMES if x!="rankFormMismatch")
    choices=[(a,b,"venue","quarter") for a,b in combinations(safe,2)]
    if len(choices)!=171:raise RuntimeError("EXPECTED_171_FORM_PAIR_SCHEMAS")
    return choices

def mixed(types,feature,widths,cols):
    a=types.astype(np.int32).copy()
    groups=6
    for key in cols:
        w=int(widths[key])
        v=feature[key]
        if np.any(v>=w):raise RuntimeError("CATEGORY_INVALID_"+key)
        a=a*w+v.astype(np.int32)
        groups*=w
    if groups>2000000:raise RuntimeError("GROUP_CAP_EXCEEDED")
    return a,groups

def max_race(group,payout,rid,candidates,n,grouplen):
    maxpaid=np.zeros(grouplen,dtype=np.float64)
    if not len(candidates):return maxpaid
    good=np.zeros(grouplen,dtype=np.bool_)
    good[candidates]=True
    idx=np.flatnonzero((payout>0)&good[group])
    if not len(idx):return maxpaid
    combined=(group[idx].astype(np.int64)*n+rid[idx].astype(np.int64))
    uq,inverse=np.unique(combined,return_inverse=True)
    paid_per_race=np.bincount(inverse,weights=payout[idx])
    np.maximum.at(maxpaid,uq//n,paid_per_race)
    return maxpaid

def money(group,spent,paid,ids,mask,needed,grpcount,race_count):
    g=group[mask];y=paid[mask];r=ids[mask]
    n=np.bincount(g,minlength=grpcount)
    total=np.bincount(g,weights=y,minlength=grpcount)
    largest=max_race(g,y,r,needed,race_count,grpcount)
    return n,total,largest

def roi(paid,n):
    # Stakes are fixed at 100 JPY per ticket. E.g. 200 yen returned on
    # one 100 yen ticket is 200%, not 20,000%.
    return round(float(paid)/float(n),4) if n>0 else None

def main():
    if "--self-test" in sys.argv:
        form=mod("scripts/research-nov2026-chronological-form-money-conditions.py","decade_form_test")
        source=mod("scripts/research-nov2026-decade-roi-first-sixmarkets.py","decade_cash_test")
        assert rank7_market_indices(source,form).size==336
        assert len(attrs(form))==171
        g=np.array([0,0,0,1,1,1],np.int32)
        p=np.array([300,200,400,100,100,0],np.int32)
        r=np.array([0,0,1,0,2,2],np.int32)
        assert max_race(g,p,r,np.array([0,1]),3,2).tolist()==[500,100]
        assert roi(200,1)==200.0
        assert roi(500,5)==100.0
        print("FORM_PAIR_VENUE_QUARTER_DIRECT_ROI200_SELFTEST_OK",flush=True)
        return
    tic=time.monotonic()
    source=mod("scripts/research-nov2026-decade-roi-first-sixmarkets.py","all_six_actual_paid")
    parser=mod("scripts/research-nov2026-sixmarket-real-paid-cash.py","all_six_payments")
    form=mod("scripts/research-nov2026-chronological-form-money-conditions.py","time_safe_form")
    hist=mod("scripts/research-nov2026-56feature-sixmarket-pl-money.py","horse_form_source")
    numeric=mod("scripts/research-nov2026-form-direct-cash-failclosed.py","strict_form_join")
    archive=source.read_all_races(parser.parse_payments)
    if not(source.CACHE.exists() and source.RACE_CACHE.exists()):
        source.CACHE.parent.mkdir(parents=True,exist_ok=True)
        source.full_features(archive)
    recorded=json.loads(source.RACE_CACHE.read_text(encoding="utf-8"))["races"]
    if len(archive)!=len(recorded) or any(r["id"]!=z["id"] for r,z in zip(archive,recorded)):
        raise RuntimeError("PAID_CASH_ARCHIVE_ORDER_CHANGED")
    for r in archive:
        r["no"]=r["raceNo"]
        r["venue"]=f"{int(r['venue']):02d}"
    source_names=names_from_monthly_data(
        sorted(source.FILES.glob("raceresults_*.csv")),hist)
    X,won,off,meta,archive_names,dropped=hist.historical_horse_features()
    eligible=[r for r in archive if r["month"]>="201701"]
    joined,join_audit=numeric.joined_full_names(
        eligible,meta,archive_names,source_names,hist)
    row_number=np.asarray([i for i,r in enumerate(archive)
                           if r["month"]>="201701" and r["id"] in joined],
                          dtype=np.int32)
    selected=[archive[int(i)] for i in row_number]
    groups=Counter(r["month"][:4] for r in selected)
    allyears=Counter(r["month"][:4] for r in eligible)
    for year in range(2017,2027):
        if groups[str(year)]<100 or groups[str(year)]/max(1,allyears[str(year)])<.40:
            raise RuntimeError("FORM_PAIR_VENUE_QUARTER_MATCHED_COVERAGE_TOO_SMALL_"+
                               str(year)+":"+str(groups[str(year)])+"/"+
                               str(allyears[str(year)]))
    formcats=form.form_categories(selected,joined,meta,off,X)
    mapping=rank7_market_indices(source,form)
    with np.load(source.CACHE,allow_pickle=False) as data:
        old=data["payout"]
        if old.shape!=(len(archive),1030):raise RuntimeError("DECADE_SOURCE_SHAPE")
        payments=old[row_number[:,None],mapping[None,:]].astype(np.int32).ravel()
        cat={k:data[k][row_number[:,None],mapping[None,:]].astype(np.uint8).ravel()
             for k in CONTEXT}
    del old
    widths={**{name:4 for name in form.NEW_NAMES},
            **{key:source.SINGLE_BINS[key] for key in CONTEXT}}
    for k,v in formcats.items():cat[k]=v
    if len(payments)!=len(selected)*336 or any(len(x)!=len(payments) for x in cat.values()):
        raise RuntimeError("FORM_PRE_RACE_AND_PAID_TICKET_MISALIGN")
    markets=np.repeat(np.array([0]*7+[1]*21+[2]*21+[3]*42+[4]*35+[5]*210,
                   dtype=np.uint8)[None,:],len(selected),axis=0).ravel()
    rid=np.repeat(np.arange(len(selected),dtype=np.int32),336)
    periods={
      TRAIN:np.repeat(np.array(["201701"<=r["month"]<"202301" for r in selected]),336),
      "2023":np.repeat(np.array([r["month"][:4]=="2023" for r in selected]),336),
      "2024":np.repeat(np.array([r["month"][:4]=="2024" for r in selected]),336),
      "2025":np.repeat(np.array([r["month"][:4]=="2025" for r in selected]),336),
      "2026JanApr":np.repeat(np.array([r["month"][:4]=="2026" for r in selected]),336)}
    schemas=attrs(form)
    print("FORM_PAIR_VENUE_QUARTER_CASH_UNIVERSE",json.dumps({
      "archivedAllJraRaces":len(archive),"strictMatched2017PlusRaces":len(selected),
      "strictJoinedYearCounts":dict(groups),
      "cashTicketCandidates":len(payments),
      "conditionSchemas":len(schemas),
      "moneySource":"third-party payout yen per 100 yen ticket",
      "historicalFinalWinOddsNotT15":True},ensure_ascii=False),flush=True)
    stats=Counter();rows=[]
    ROWS.parent.mkdir(parents=True,exist_ok=True)
    keys=("schema","market","conditionCode","trainTickets","trainSpentYen","trainPaidYen",
          "trainRoiPct","trainBiggestRaceYen","trainMinusMaxRaceRoiPct",
          "2023Tickets","2023SpentYen","2023PayoutYen","2023MinusMaxRaceRoiPct",
          "2024Tickets","2024SpentYen","2024PayoutYen","2024MinusMaxRaceRoiPct",
          "2025Tickets","2025SpentYen","2025PayoutYen","2025MinusMaxRaceRoiPct",
          "2026JanAprTickets","2026JanAprSpentYen","2026JanAprPayoutYen",
          "2026JanAprMinusMaxRaceRoiPct")
    with gzip.open(ROWS,"wt",encoding="utf-8",newline="") as f:
      writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
      for i,cols in enumerate(schemas,1):
        code,num=mixed(markets,cat,widths,cols)
        train=periods[TRAIN]
        n=np.bincount(code[train],minlength=num)
        paid=np.bincount(code[train],weights=payments[train],minlength=num)
        wins=np.bincount(code[train&(payments>0)],minlength=num)
        found=np.flatnonzero((n>=100)&(wins>=5)&(paid>=200*n))
        stats["trainingGross200Support100"]+=len(found)
        if not len(found):continue
        big=max_race(code[train],payments[train],rid[train],
                    found,len(selected),num)
        strict=found[(paid[found]-big[found])>=200*n[found]]
        stats["trainingRobust200Support100"]+=len(strict)
        if not len(strict):continue
        nextyears={}
        for period in YEARS[1:]:
            nextyears[period]=money(code,100,payments,rid,
                           periods[period],strict,num,len(selected))
        for cell in strict:
            cell=int(cell)
            block=int(num//6)
            row={
              "schema":"+".join(cols),"market":form.SIX[cell//block],
              "conditionCode":cell,
              "trainTickets":int(n[cell]),"trainSpentYen":int(n[cell])*100,"trainPaidYen":int(round(paid[cell])),
              "trainRoiPct":roi(paid[cell],n[cell]),
              "trainBiggestRaceYen":int(round(big[cell])),
              "trainMinusMaxRaceRoiPct":roi(paid[cell]-big[cell],n[cell])}
            valid=True
            for per in YEARS[1:]:
                nn,pp,b=nextyears[per]
                row[per+"Tickets"]=int(nn[cell])
                row[per+"SpentYen"]=int(nn[cell])*100
                row[per+"PayoutYen"]=int(round(pp[cell]))
                row[per+"MinusMaxRaceRoiPct"]=roi(pp[cell]-b[cell],nn[cell])
                qualified=bool(nn[cell]>=10 and pp[cell]-b[cell]>=200*nn[cell])
                stats[per+"Robust200"]+=int(qualified)
                valid=valid and qualified
            stats["allPeriodsRobust200"]+=int(valid)
            writer.writerow(row);rows.append(row)
        if i%25==0:
            print("FORM_PAIR_VENUE_QUARTER_CASH_PROGRESS",json.dumps({
              "schemas":i,"total":len(schemas),
              "trainGross200":int(stats["trainingGross200Support100"]),
              "trainRobust200":int(stats["trainingRobust200Support100"]),
              "replicated2023":int(stats["2023Robust200"]),
              "replicated2024":int(stats["2024Robust200"]),
              "seconds":round(time.monotonic()-tic,2)}),flush=True)
    rows.sort(key=lambda x:(-x["trainTickets"],-x["trainMinusMaxRaceRoiPct"]))
    result={
      "method":"direct 2017-22 form x form-pair venue-quarter cash ROI200 discovery, no model fit",
      "source":"pinned third-party settled payout CSV + time-ordered archive of 56 pre-race features",
      "matchedYearCoverage":dict(groups),"rawJraRaces":len(archive),
      "matchedRaces":len(selected),"ticketCount":len(payments),
      "schemaCount":len(schemas),
      "trainingYears":"2017-2022",
      "confirmationYears":["2023","2024","2025","2026JanApr"],
      "2025And2026PreviouslyInspected":True,
      "finalWinOddsNotT15":True,"officialPayoutReconciled":False,
      "stats":dict(stats),"largestSupportedCells":rows[:50],
      "historicalRobustConditionsFile":str(ROWS.relative_to(ROOT)),
      "productionChanged":False,"seconds":round(time.monotonic()-tic,2)}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FORM_PAIR_VENUE_QUARTER_DIRECT_CASH_FINAL",json.dumps({
      "stats":dict(stats),"seconds":result["seconds"],"rows":len(rows),
      "json":str(OUT),"csv":str(ROWS)},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
