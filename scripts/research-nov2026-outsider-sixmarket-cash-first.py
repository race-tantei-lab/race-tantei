#!/usr/bin/env python3
"""DIRECT actual-cash ROI200 extraction: outsider tickets in all SIX JRA markets.

This is NOT a model training pipeline. It enumerates every bet containing at
least one outsider among archived final-odds ranks 11-18 in races with >=11
runners; one-, two-attribute full conjunction sets and eight predeclared
three-way schema families; every categorical value cell. First discover on
2015-22 payouts, then check 2023, 24, 25, 2026 Jan-Apr separately.
Only 100-yen ticket stakes and actual 100-yen payout integers are used.

Historical final win odds are NOT T-15 JRA odds. Third-party payouts are not
independently JRA-reconciled. Research-only, no live betting/deployment.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from itertools import combinations,permutations
from pathlib import Path
import csv,gzip,importlib.util,json,sys,time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-outsider-sixmarket-roi200-direct.json"
CSV=ROOT/"analysis-results/nov2026-outsider-gross200-conditions.csv.gz"
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
UNORDERED={1,2,4}
FEATURES=(
    "outsiderCount","outsiderRank","strongRank","rankSpread",
    "oddsGeom","outsiderOdds","favOdds","venue","fieldSize",
    "raceBand","quarter","drawMin","ageMax"
)
BINS={
    "outsiderCount":3,"outsiderRank":4,"strongRank":5,"rankSpread":5,
    "oddsGeom":9,"outsiderOdds":8,"favOdds":7,"venue":10,"fieldSize":4,
    "raceBand":3,"quarter":4,"drawMin":6,"ageMax":5
}
TRIPLES=(
  ("outsiderRank","oddsGeom","venue"),
  ("outsiderRank","outsiderOdds","favOdds"),
  ("outsiderCount","strongRank","oddsGeom"),
  ("outsiderCount","outsiderOdds","venue"),
  ("outsiderRank","rankSpread","fieldSize"),
  ("strongRank","oddsGeom","raceBand"),
  ("oddsGeom","venue","quarter"),
  ("outsiderOdds","drawMin","ageMax"),
)
PATTERNS=tuple((x,) for x in FEATURES)+tuple(combinations(FEATURES,2))+TRIPLES
PERIODS=("2015-2022","2023","2024","2025","2026JanApr")
CUTOFF=10
TEMPLATES={}

def source():
  name="outsider_six_market_public_cash_source"
  spec=importlib.util.spec_from_file_location(name,ROOT/"scripts/research-nov2026-decade-roi-first-sixmarkets.py")
  x=importlib.util.module_from_spec(spec);sys.modules[name]=x;spec.loader.exec_module(x)
  return x

def templates(n,market):
  key=n,market
  if key in TEMPLATES:return TEMPLATES[key]
  if market==0:combos=((i,) for i in range(n))
  elif market in (1,2):combos=combinations(range(n),2)
  elif market==3:combos=permutations(range(n),2)
  elif market==4:combos=combinations(range(n),3)
  else:combos=permutations(range(n),3)
  arr=np.asarray([z for z in combos if max(z)>=CUTOFF],dtype=np.int16)
  assert arr.ndim==2 and arr.shape[1]==(1 if market==0 else 3 if market in (4,5) else 2)
  ranks_idx={tuple(row):i for i,row in enumerate(arr.tolist())}
  mx=arr.max(axis=1)
  mn=arr.min(axis=1)
  lo=np.where(arr>=10,arr,99).min(axis=1)
  fixed={
    "outsiderCount":(arr>=10).sum(axis=1)-1,
    "outsiderRank":(mx-10)//2,
    "strongRank":np.searchsorted([3,6,10,14],mn,side="right"),
    "rankSpread":np.searchsorted([3,7,11,15],mx-mn,side="right")
  }
  TEMPLATES[key]=(arr,ranks_idx,{k:np.asarray(v,dtype=np.uint8) for k,v in fixed.items()})
  return TEMPLATES[key]

def get_features_and_payout(race,market):
  horses=race["horses"]
  n=len(horses)
  if n<=10:return None
  if n>18:raise RuntimeError("MORE_THAN_18_JRA_RUNNERS")
  arr,idx,fixed=templates(n,market)
  count=len(arr)
  nums=np.array([int(h[0]) for h in horses],dtype=np.int16)
  odds=np.array([float(h[1]) for h in horses],dtype=np.float64)
  ages=np.array([int(h[2]) for h in horses],dtype=np.int16)
  basket=odds[arr]
  outsider_odds=np.where(arr>=10,basket,np.inf).min(axis=1)
  x={
    **fixed,
    "oddsGeom":np.searchsorted(
       [5,10,20,40,80,160,320,640],
       np.exp(np.log(np.maximum(basket,1)).mean(axis=1)),side="right"),
    "outsiderOdds":np.searchsorted(
       [10,20,40,80,160,320,640],outsider_odds,side="right"),
    "favOdds":np.full(count,np.searchsorted(
       [1.5,2,3,4,6,10],odds[0],side="right"),dtype=np.uint8),
    "venue":np.full(count,int(race["venue"])-1,dtype=np.uint8),
    "fieldSize":np.full(count,(n-11)//2,dtype=np.uint8),
    "raceBand":np.full(count,(int(race["raceNo"])-1)//4,dtype=np.uint8),
    "quarter":np.full(count,(int(race["month"][4:])-1)//3,dtype=np.uint8),
    "drawMin":np.searchsorted([3,6,9,12,15],nums[arr].min(axis=1),side="right"),
    "ageMax":np.searchsorted([3,4,5,6],ages[arr].max(axis=1),side="right")
  }
  for k in FEATURES:
    if not np.all((x[k]>=0)&(x[k]<BINS[k])):
      raise RuntimeError("FEATURE_OUTSIDE_BINS:"+k+":"+str(np.max(x[k])))
  payouts=np.zeros(count,dtype=np.int32)
  rank_of_num={int(h[0]):j for j,h in enumerate(horses)}
  for combo,yen in race["payout"][market].items():
    try:k=tuple(rank_of_num[int(num)] for num in combo)
    except KeyError:continue
    if max(k)<10:continue
    if market in UNORDERED:k=tuple(sorted(k))
    dest=idx.get(k)
    if dest is not None:payouts[dest]=int(yen)
  return {k:np.asarray(x[k],dtype=np.uint8) for k in FEATURES},payouts

def group_code(data,pattern):
  code=data[pattern[0]].astype(np.int32).copy()
  size=BINS[pattern[0]]
  for name in pattern[1:]:
    code=code*BINS[name]+data[name].astype(np.int32)
    size*=BINS[name]
  return code,size

def cash_stat_array(market_races,market,schemas):
  sums={}
  for pat in schemas:
    size=np.prod([BINS[z] for z in pat]).item()
    sums[pat]={
       "n":np.zeros(size,dtype=np.int64),
       "paid":np.zeros(size,dtype=np.float64),
       "hits":np.zeros(size,dtype=np.int64),
       "maxrace":np.zeros(size,dtype=np.float64)}
  count_hyp=0;selected_races=0
  for start in range(0,len(market_races),100):
    group=market_races[start:start+100]
    data={k:[] for k in FEATURES};paybuf=[];rowids=[]
    for row,race in enumerate(group):
      pair=get_features_and_payout(race,market)
      if pair is None:continue
      features,payout=pair
      for name in FEATURES:data[name].append(features[name])
      paybuf.append(payout)
      rowids.append(np.full(len(payout),row,dtype=np.int16))
      selected_races+=1
      count_hyp+=len(payout)
    if not paybuf:continue
    data={k:np.concatenate(arr) for k,arr in data.items()}
    paid=np.concatenate(paybuf)
    rows=np.concatenate(rowids)
    good=np.flatnonzero(paid>0)
    for pat in schemas:
      code,size=group_code(data,pat)
      dst=sums[pat]
      dst["n"]+=np.bincount(code,minlength=size)
      dst["paid"]+=np.bincount(code,weights=paid,minlength=size)
      dst["hits"]+=np.bincount(code[good],minlength=size)
      if len(good):
        packed=code[good].astype(np.int64)*len(group)+rows[good]
        uniq,reverse=np.unique(packed,return_inverse=True)
        cash_race=np.bincount(reverse,weights=paid[good])
        np.maximum.at(dst["maxrace"],uniq//len(group),cash_race)
    if start and start%800==0:
      print("OUTSIDER_CASH_BATCH",json.dumps({
       "market":MARKETS[market],"racesProcessed":start,
       "racesTotal":len(market_races),"ticketCandidates":count_hyp,
       "schemas":len(schemas)}),flush=True)
  return sums,count_hyp,selected_races

def decode(pat,code):
  z=int(code); out={}
  for key in reversed(pat):
    out[key]=z%BINS[key]
    z//=BINS[key]
  return {key:out[key] for key in pat}

def roi(cash,n):
  return round(float(cash)/int(n),4) if n>0 else None

def main():
  if "--self-test" in sys.argv:
    assert len(PATTERNS)==len(FEATURES)+len(FEATURES)*(len(FEATURES)-1)//2+len(TRIPLES)
    arr,idx,f=templates(18,5)
    assert len(arr)==len(tuple(permutations(range(18),3)))-len(tuple(permutations(range(10),3)))
    assert all(np.max(v)<BINS[k] for k,v in f.items())
    code,n=group_code({"outsiderRank":np.array([1,2],dtype=np.uint8),
      "venue":np.array([2,3],dtype=np.uint8)},("outsiderRank","venue"))
    assert code.tolist()==[12,23] and n==40
    print("OUTSIDER_CASH_ALL_MARKET_SELFTEST_OK",flush=True)
    return
  tic=time.monotonic()
  parser=source()
  public_parser=parser.mod("scripts/research-nov2026-sixmarket-real-paid-cash.py","outsider_cash_parser")
  races=parser.read_all_races(public_parser.parse_payments)
  by_period={k:[] for k in PERIODS}
  for r in races:
    yr=int(r["month"][:4])
    if len(r["horses"])<=10:continue
    p=("2015-2022" if yr<=2022 else
       "2026JanApr" if yr==2026 else str(yr))
    by_period[p].append(r)
  print("OUTSIDER_CASH_UNIVERSE",json.dumps({
    "racesWith11PlusRunners":sum(len(v) for v in by_period.values()),
    "racesByPeriod":{k:len(v) for k,v in by_period.items()},
    "markets":list(MARKETS),
    "allSingleAndPairSchemas":len(FEATURES)+len(FEATURES)*(len(FEATURES)-1)//2,
    "fixedAdditionalTriples":len(TRIPLES),
    "schemaCountPerMarket":len(PATTERNS),
    "rank11Through18Allowed":True,"allOutsiderContainingTicketCombinations":True,
    "historicalOddsAreFinalNotT15":True},ensure_ascii=False),flush=True)
  report={"scope":"all 6 markets, all candidate tickets containing odds-rank 11-18 runners",
    "historicalOddsNotT15":True,
    "payoutSource":"pinned third-party settled JRA CSV, 100-yen tickets",
    "officialReconciliationIncomplete":True,
    "notADeployedModel":True,
    "schemasPerMarket":len(PATTERNS),
    "racesByPeriod":{k:len(v) for k,v in by_period.items()},
    "markets":{}, "allStrictHistoricalCells":[]}
  cols=("market","schema","categories","historicalTickets","historicalWinningTickets",
   "historicalStakeYen","historicalPaidYen","historicalGrossRoiPct",
   "historicalMaxRacePaidYen","historicalMinusMaxRaceRoiPct","strictHistorical200")
  totals=Counter()
  with gzip.open(CSV,"wt",newline="",encoding="utf8") as fp:
    writer=csv.DictWriter(fp,fieldnames=cols);writer.writeheader()
    for market in range(6):
      tr,trial_count,race_count=cash_stat_array(by_period["2015-2022"],market,PATTERNS)
      strict=[]
      gross_market=0
      for pat,d in tr.items():
        n,p,h,b=(d[x] for x in ("n","paid","hits","maxrace"))
        historical=np.flatnonzero((n>=20)&(h>=2)&(p>=200*n))
        good=(n>=100)&(h>=5)&(p-b>=200*n)
        totals["historicalGross200"]+=len(historical)
        gross_market+=len(historical)
        for j in historical:
          row={
            "market":MARKETS[market],"schema":"+ ".join(pat),
            "categories":json.dumps(decode(pat,j),separators=(",",":")),
            "historicalTickets":int(n[j]),"historicalWinningTickets":int(h[j]),
            "historicalStakeYen":int(n[j]*100),"historicalPaidYen":int(round(p[j])),
            "historicalGrossRoiPct":roi(p[j],n[j]),
            "historicalMaxRacePaidYen":int(round(b[j])),
            "historicalMinusMaxRaceRoiPct":roi(p[j]-b[j],n[j]),
            "strictHistorical200":int(bool(good[j]))}
          writer.writerow(row)
          if good[j]:
            strict.append((pat,int(j),row))
      totals["strictHistorical200"]+=len(strict)
      active=tuple(dict.fromkeys(pat for pat,_,_ in strict))
      later={}
      for year in PERIODS[1:]:
        if active:
          info,tickets,races_count=cash_stat_array(by_period[year],market,active)
          later[year]=info
        else:
          later[year]={}
      examples=[]
      for pat,idx,row in strict:
        out={**row,"future":{}}
        survive=True
        for year in PERIODS[1:]:
          d=later[year][pat]
          nn=int(d["n"][idx]);pp=int(round(d["paid"][idx]))
          mb=int(round(d["maxrace"][idx]))
          netroi=roi(pp-mb,nn)
          out["future"][year]={
            "tickets":nn,"stakeYen":100*nn,"paidYen":pp,
            "grossRoiPct":roi(pp,nn),"maxRacePaidYen":mb,
            "minusMaxRaceRoiPct":netroi}
          if year=="2023" and nn>=10 and netroi>=200:
            totals["repeat2023Robust200"]+=1
          if year=="2024" and nn>=10 and netroi>=200:
            totals["repeat2024Robust200"]+=1
          if not(nn>=10 and netroi>=200):
            survive=False
        if survive:totals["allFuturePeriodsRobust200"]+=1
        examples.append(out)
      examples.sort(key=lambda x:(-x["historicalTickets"],-x["historicalMinusMaxRaceRoiPct"]))
      report["allStrictHistoricalCells"].extend(examples)
      report["markets"][MARKETS[market]]={
        "historicalOutsiderTickets":trial_count,
        "historicalRaces":race_count,"historicalGross200Cells":gross_market
        "strictHistoricalCells":len(strict),
        "schemasWithStrictCells":len(active)}
      # Snapshot count of gross conditions per market is reconstructed from CSV
      print("OUTSIDER_CASH_MARKET_DONE",json.dumps({
        "market":MARKETS[market],"historicalTickets":trial_count,
        "historicalGross200":gross_market,"historicallyRobust200":len(strict),
        "testedSchemasForFuture":len(active),
        "secondsElapsed":round(time.monotonic()-tic,1)
      },ensure_ascii=False),flush=True)
  report["stats"]=dict(totals)
  report["allStrictHistoricalCells"].sort(key=lambda x:
      (-x["historicalTickets"],-x["historicalMinusMaxRaceRoiPct"]))
  report["topStrictCells"]=report["allStrictHistoricalCells"][:50]
  report["strictCellsTotal"]=len(report["allStrictHistoricalCells"])
  report.pop("allStrictHistoricalCells")
  report["grossHistorical200AllCellsGzipCsv"]=str(CSV.relative_to(ROOT))
  report["seconds"]=round(time.monotonic()-tic,2)
  OUT.parent.mkdir(parents=True,exist_ok=True)
  OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
  print("OUTSIDER_CASH_FINAL",json.dumps({
    "stats":dict(totals),"seconds":report["seconds"],
    "json":str(OUT),"csv":str(CSV)},ensure_ascii=False),flush=True)

if __name__=="__main__":
  main()
