#!/usr/bin/env python3
"""Cash-first EXHAUSTIVE bounded conjunction search. No prediction model.

Define the search space BEFORE reading returns:
- ALL 1030 tickets per JRA race with top 10 horses by archived final win odds;
- ALL six market types (WIN, WIDE, QUINELLA, EXACTA, TRIO, TRIFECTA);
- ALL 1-, 2-, 3-, 4-way subsets of 12 specified categorical features;
- extra one- and two-way demographic/draw features and exact-rank pairs.
Report every historical >=200% gross ROI cell with >=20 cash tickets.
For strict cells test max-race-trimmed ROI >=200% and >=100 tickets.
Examine 2023-26 separately; NEVER use test years in initial discovery.

CAVEATS: odds in the input are FINAL win odds, not official T-15; source
is a third-party archived settled-payout mirror. Historical matches do
not prove a profitable ex-ante system; absolutely no production changes.
"""
from __future__ import annotations
from itertools import combinations
from pathlib import Path
from collections import Counter
import csv,gzip,importlib.util,json,sys,time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-direct-exhaustive-cash-roi200.json"
ROWS=ROOT/"analysis-results/nov2026-all-historical-roi200-cash-cells.csv.gz"
BASE=(
    "rankMin","rankMax","rankGap","rankFirst",
    "oddsGeom","oddsSpread","favOdds","favGap",
    "venue","fieldSize","raceBand","quarter"
)
ADDITIONAL=("draw","horseAge","horseWeight","favCount","rankSum","rankSecond")
PERIODS=("train2015To2022","2023","2024","2025","2026JanApr")
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
GROSS_MIN_SAMPLE=20
ROBUST_MIN_SAMPLE=100
TARGET_ROI_PERCENT=200

def load_source():
    path=ROOT/"scripts/research-nov2026-decade-roi-first-sixmarkets.py"
    spec=importlib.util.spec_from_file_location("cash_first_all_combinations_source",path)
    source=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=source
    spec.loader.exec_module(source)
    return source

def patterns():
    # Exactly enumerate EVERY nonempty subset through four attributes
    # of this pre-registered core vocabulary; avoid feature-wise cherry picking.
    yield from (tuple(x) for k in range(1,5) for x in combinations(BASE,k))
    # Separate extra vocabulary: all singletons and core x extra pairs.
    for extra in ADDITIONAL:
        yield (extra,)
        for core in BASE:
            yield (core,extra)
    yield ("rankExact",)
    for core in ("oddsGeom","favOdds","venue","fieldSize","quarter","favGap"):
        yield ("rankExact",core)

def max_race_by_group(codes,winning_idx,winning_payout,n_races,size,eligible):
    """Exact maximum same-race payout within EACH cash condition, not max ticket."""
    result=np.zeros(size,dtype=np.float64)
    if not len(eligible) or not len(winning_idx):
        return result
    admissible=np.zeros(size,dtype=np.bool_)
    admissible[eligible]=True
    g=codes[winning_idx]
    ok=admissible[g]
    if not np.any(ok):return result
    g=g[ok].astype(np.int64)
    row=(winning_idx[ok]//1030).astype(np.int64)
    compound=g*int(n_races)+row
    unique,inv=np.unique(compound,return_inverse=True)
    per_race=np.bincount(inv,weights=winning_payout[ok])
    np.maximum.at(result,unique//n_races,per_race)
    return result

def precompute():
    source=load_source()
    if not source.CACHE.exists() or not source.RACE_CACHE.exists():
        raise RuntimeError("CASH_CACHE_MISSING_USE_PINNED_ARCHIVE_ACTION")
    races=json.loads(source.RACE_CACHE.read_text(encoding="utf8"))["races"]
    years=np.array([int(x["month"][:4]) for x in races],dtype=np.int16)
    periods={
       "train2015To2022":(years>=2015)&(years<=2022),
       "2023":years==2023,"2024":years==2024,
       "2025":years==2025,"2026JanApr":years==2026
    }
    with np.load(source.CACHE,allow_pickle=False) as blob:
        full_paid=blob["payout"]
        if full_paid.shape!=(len(races),1030) or not np.issubdtype(full_paid.dtype,np.integer):
            raise RuntimeError("CASH_SETTLEMENT_MATRIX_ALIGNMENT_FAILED")
        prices={}
        pp={}
        for tag,mask in periods.items():
            a=full_paid[mask].ravel()
            if len(a)==0:raise RuntimeError("EMPTY_PERIOD_"+tag)
            pp[tag]={
               "cash":a,
               "winningIndex":np.flatnonzero(a>0),
               "races":int(np.sum(mask)),
               "positive":a[a>0].astype(np.float64)
            }
            prices[tag]={}
        keys=set(BASE)|set(ADDITIONAL)|{"rankExact","market"}
        for k in keys:
            z=blob[k]
            if z.shape!=full_paid.shape:
                raise RuntimeError("TICKET_FEATURE_SHAPE_BAD_"+k)
            for tag,mask in periods.items():prices[tag][k]=z[mask]
    print("DIRECT_ALL_CASH_SOURCE",json.dumps({
       "races":len(races),"allSixMarketTicketCandidates":len(races)*1030,
       "preRegisteredCoreAttributes":list(BASE),
       "allCoreOneToFourWaySubsets":sum(1 for _ in (
           q for z in range(1,5) for q in combinations(BASE,z))),
       "extendedSchemas":len(ADDITIONAL)*(len(BASE)+1)+7,
       "racesByPeriod":{k:v["races"] for k,v in pp.items()},
       "priorFinalWinOddsNotT15":True
    }),flush=True)
    return source,prices,pp,races

def evaluate_group(source,features,info,pattern,target_codes):
    code,size=source.mixed_code(features,pattern)
    code=code.ravel()
    y=info["cash"]
    if len(code)!=len(y):raise RuntimeError("GROUP_CASH_MISALIGN")
    count=np.bincount(code,minlength=size)
    payout=np.bincount(code,weights=y,minlength=size)
    pos_idx=info["winningIndex"]
    biggest=max_race_by_group(
        code,pos_idx,info["positive"],info["races"],size,target_codes)
    return count,payout,biggest

def decode_condition(source,pat,idx):
    rest=int(idx)
    categoricals={}
    for key in reversed(pat):
        base=source.SINGLE_BINS[key]
        categoricals[key]=rest%base
        rest//=base
    if not 0<=rest<6:raise RuntimeError("BAD_MARKET_ENCODING")
    return MARKETS[rest],{key:int(categoricals[key]) for key in pat}

def roi(yen,tickets):
    return round(100.0*float(yen)/(100.0*int(tickets)),4) if tickets else None

def main():
    if "--self-test" in sys.argv:
        toy=np.array([300,100,0,0,100,0],dtype=np.int32)
        idx=np.flatnonzero(toy>0)
        c=np.array([0,0,1,1,0,0],dtype=np.int32)
        out=max_race_by_group(c,idx,toy[idx],3,2,np.array([0]))
        # rows 0: 300+100, rows 1: 100+0
        assert out[0]==400.0 and out[1]==0.0
        assert len(tuple(patterns()))==sum(
          __import__("math").comb(12,k) for k in range(1,5))+6*13+7
        print("DIRECT_ALL_CASH_MONEY_ARITHMETIC_SELFTEST_OK",flush=True)
        return
    start=time.monotonic()
    source,feature,period,races=precompute()
    all_pat=tuple(patterns())
    stats=Counter()
    strict=[]
    forward=[]
    fields=["schema","cashMarket","categoricalValues","groupCode",
            "trainTickets","trainWinningTickets","trainStakeYen",
            "trainPaidYen","trainGrossRoiPct",
            "trainMaxRacePayoutYen","trainMinusMaxRaceRoiPct",
            "strictHistorical200",
            "2023Tickets","2023PaidYen","2023MinusMaxRaceRoiPct",
            "2024Tickets","2024PaidYen","2024MinusMaxRaceRoiPct",
            "2025Tickets","2025PaidYen","2025MinusMaxRaceRoiPct",
            "2026JanAprTickets","2026JanAprPaidYen",
            "2026JanAprMinusMaxRaceRoiPct"]
    ROWS.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(ROWS,"wt",encoding="utf-8",newline="") as fh:
      writer=csv.DictWriter(fh,fieldnames=fields)
      writer.writeheader()
      for count_pat,pat in enumerate(all_pat,1):
        tr=period["train2015To2022"]
        group,size=source.mixed_code(feature["train2015To2022"],pat)
        flat=group.ravel()
        n=np.bincount(flat,minlength=size)
        paid=np.bincount(flat,weights=tr["cash"],minlength=size)
        nwin=np.bincount(flat[tr["winningIndex"]],minlength=size)
        historical=np.flatnonzero((n>=GROSS_MIN_SAMPLE)&
                    (paid>=2*100*n)&(nwin>=2))
        stats["historicalGross200CellsSupport20"]+=len(historical)
        stats["schemasAudited"]+=1
        if not len(historical):
            if count_pat%75==0:
                print("DIRECT_ALL_CASH_PROGRESS",json.dumps({
                 "schemas":count_pat,"total":len(all_pat),
                 "gross200Cells":int(stats["historicalGross200CellsSupport20"]),
                 "robustHistorical":int(stats["strictHistoricalRobust200CellsSupport100"]),
                 "seconds":round(time.monotonic()-start,1)}),flush=True)
            continue
        maxrace=max_race_by_group(
            flat,tr["winningIndex"],tr["positive"],tr["races"],size,historical)
        strict_mask=((n>=ROBUST_MIN_SAMPLE)&(nwin>=5)&
                     ((paid-maxrace)>=2*100*n))
        good=historical[strict_mask[historical]]
        stats["strictHistoricalRobust200CellsSupport100"]+=len(good)
        stats["strictHistoricalSchemas"]+=int(bool(len(good)))
        # Subsequent years do not affect DISCOVERY or cash thresholds.
        evaluated={}
        for year in PERIODS[1:]:
            if len(good):
                vc,vp,vmax=evaluate_group(
                    source,feature[year],period[year],pat,good)
                evaluated[year]=(vc,vp,vmax)
        # Preserve ALL historical 200% cells in compressed CSV:
        for idx in historical:
            idx=int(idx)
            market,values=decode_condition(source,pat,idx)
            robust=(idx in strict_mask.nonzero()[0]) if False else bool(strict_mask[idx])
            row={
              "schema":"+".join(pat),"cashMarket":market,
              "categoricalValues":json.dumps(values,ensure_ascii=False,separators=(",",":")),
              "groupCode":idx,
              "trainTickets":int(n[idx]),
              "trainWinningTickets":int(nwin[idx]),
              "trainStakeYen":int(n[idx]*100),
              "trainPaidYen":int(round(paid[idx])),
              "trainGrossRoiPct":roi(paid[idx],n[idx]),
              "trainMaxRacePayoutYen":int(round(maxrace[idx])),
              "trainMinusMaxRaceRoiPct":roi(paid[idx]-maxrace[idx],n[idx]),
              "strictHistorical200":int(robust)
            }
            if robust:
                item=dict(row)
                passed=True
                for year in PERIODS[1:]:
                    vc,vp,vmax=evaluated[year]
                    cnt=int(vc[idx])
                    net=float(vp[idx]-vmax[idx])
                    row[year+"Tickets"]=cnt
                    row[year+"PaidYen"]=int(round(vp[idx]))
                    row[year+"MinusMaxRaceRoiPct"]=roi(net,cnt)
                    item[year]={
                       "tickets":cnt,"stakeYen":100*cnt,
                       "paidYen":int(round(vp[idx])),
                       "roiPct":roi(vp[idx],cnt),
                       "maxRacePaidYen":int(round(vmax[idx])),
                       "minusMaxRaceRoiPct":roi(net,cnt)}
                    if year=="2023":
                        passed=bool(cnt>=10 and net>=200*cnt)
                    if year=="2024" and passed:
                        passed=bool(cnt>=10 and net>=200*cnt)
                strict.append(item)
                if item["2023"]["tickets"]>=10 and item["2023"]["minusMaxRaceRoiPct"]>=200:
                    stats["historical200Then2023Robust200"]+=1
                    if item["2024"]["tickets"]>=10 and item["2024"]["minusMaxRaceRoiPct"]>=200:
                        stats["historical200Then2023And2024Robust200"]+=1
                        if item["2025"]["tickets"]>=10 and item["2025"]["minusMaxRaceRoiPct"]>=200:
                            stats["historical200Then2023To2025Robust200"]+=1
                            if item["2026JanApr"]["tickets"]>=10 and item["2026JanApr"]["minusMaxRaceRoiPct"]>=200:
                                stats["historical200Then2023To2026Robust200"]+=1
            writer.writerow(row)
        if count_pat%25==0 or count_pat==len(all_pat):
            print("DIRECT_ALL_CASH_PROGRESS",json.dumps({
              "schemas":count_pat,"total":len(all_pat),
              "gross200Cells":int(stats["historicalGross200CellsSupport20"]),
              "robustHistorical":int(stats["strictHistoricalRobust200CellsSupport100"]),
              "repeat2023Robust":int(stats["historical200Then2023Robust200"]),
              "seconds":round(time.monotonic()-start,1)}),flush=True)
    # Ranking below is only a descriptive report, NOT a deployed model.
    strict.sort(key=lambda q:(-int(q["trainTickets"]),
               -float(q["trainMinusMaxRaceRoiPct"])))
    top2023=sorted((q for q in strict if q["2023"]["tickets"]>=10),
          key=lambda q:(-float(q["2023"]["minusMaxRaceRoiPct"]),
                        -int(q["2023"]["tickets"])))
    report={
      "method":"Direct exhaustive historical settled cash ROI200 condition extraction; NO new model fitted",
      "preRegisteredUniverse":{
        "ticketCandidates":len(races)*1030,
        "perRaceCandidates":1030,
        "raceCount":len(races),
        "markets":list(MARKETS),
        "coreFeatureVocabulary":list(BASE),
        "allCoreSubsetsSizes":[1,2,3,4],
        "additionalFeatures":list(ADDITIONAL),
        "numberOfGroupSchemas":len(all_pat),
        "searchNotEntire18HorseField":True,
        "searchCannotLiterallyEnumerateEveryPossibleContinuousCondition":True},
      "discovery":"2015-2022, >=20 tickets and gross ROI>=200%; strict >=100 and max same-race payout removed ROI>=200%",
      "noOutcomesUsedForFeatureSelection":True,
      "validationYears":[2023,2024,2025,"2026JanApr"],
      "previouslyInspected2025And2026":True,
      "source":"Kenseimk/keiba-agent pinned third-party monthly results",
      "finalOddsNotJraT15":True,
      "officialPayoutReconciliationIncomplete":True,
      "noProductionModification":True,
      "stats":dict(stats),
      "strictHistoricalTotal":len(strict),
      "strictHistoricalMostSupported":strict[:40],
      "strictHistoricalHighest2023RobustRoi":top2023[:40],
      "allHistoricallyGrossRoi200CellsGzipCsv":str(ROWS.relative_to(ROOT)),
      "seconds":round(time.monotonic()-start,2)
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("DIRECT_ALL_CASH_FINAL",json.dumps({
      "sampleTickets":len(races)*1030,"schemas":len(all_pat),
      "strictHistoricalCells":len(strict),
      "stats":dict(stats),
      "seconds":report["seconds"],
      "csv":str(ROWS),"json":str(OUT)},ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
