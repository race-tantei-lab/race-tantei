#!/usr/bin/env python3
"""Bayesian CASH-return expert ensemble for two-market JRA tickets.

Model architecture is not a horse win predictor, old LightGBM bet allocator,
or an in-sample high-ROI cell list. Per ticket empirical money and paid-event
posteriors are learned across exchangeable context panels: market/template,
venue, quarter, field size, favorite odds, odds geometry, rank geometry, and
interactions. Exponentially shrunk posterior payout drives race and two-type
choices under fixed 2,000 JPY, strictly before settlement. Train 2017-2021,
select 2022 policy, then independent nested walk-forward 2023-2026.
Actual cash paid only: no logloss. Never promote without T15 odds proof.
"""
from __future__ import annotations
import collections,csv,importlib.util,itertools,json,math,sys,time
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parents[1]
OUT=R/"analysis-results/nov2026-bayesian-market-cash-bandit.json"
LED=R/"analysis-results/nov2026-bayesian-market-cash-bandit-bets.csv"
B=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
TYPE=("単勝","ワイド","馬連","馬単","3連複","3連単")
PROB_PRIORS=(10.,40.,150.,500.)
TRIM=(0.,1.)
TEMPLATE_WEIGHTS=(.2,.45,.7)
REGIME_WEIGHTS=(.1,.35,.65)
HIT_POWER=(0.,.25,.7,1.25)
RACES=(3,4,5)
SPLITS=((1000,1000),(1500,500),(1900,100),(500,1500),(100,1900))
TRAIN=tuple(range(2017,2022))
EVAL=(2023,2024,2025,2026)
SOURCE_PATH="scripts/research-nov2026-form-money-new-generator.py"
def imported():
  spec=importlib.util.spec_from_file_location("bayesian_money_data",R/SOURCE_PATH)
  m=importlib.util.module_from_spec(spec)
  sys.modules[spec.name]=m;spec.loader.exec_module(m)
  return m
def metrics(rows):
  arr=np.asarray(rows,dtype=np.int64);n=len(arr);s=n*2000
  total=int(arr.sum());mx=int(arr.max()) if n else 0
  return {"races":n,"stakeYen":s,"paidYen":total,
   "roiPct":round(total*100/s,5) if n else None,
   "minusMaxRaceRoiPct":round((total-mx)*100/s,5) if n else None,
   "hitRacePct":round(100*np.count_nonzero(arr)/n,5) if n else None,
   "biggestPaidRaceYen":mx}
def qualifies(m,minn):
  return m["races"]>=minn and (m["roiPct"] or 0)>=200 and (
    m["minusMaxRaceRoiPct"] or 0)>=200 and (m["hitRacePct"] or 0)>=20
def panels(attrs,markets,n):
  # Entire panel construction uses only available BEFORE-RACE category
  # features. Historical win odds are post-race final and therefore a
  # research proxy ONLY, not a deployable JRA T15 market feed.
  defs=("venue","quarter","fieldSize","favOdds","oddsGeom","rankGap")
  fields={key:np.asarray(attrs[key],dtype=np.int32) for key in defs}
  t=markets.astype(np.int32)
  unique=np.tile(np.arange(336,dtype=np.int32),n)
  feats={"template":unique}
  def encode(name,*f):
    keys=[np.array(t,dtype=np.int32)]
    for v in f:keys.append(fields[v])
    out=keys[0]
    for c in keys[1:]:
      out=out*(int(c.max())+1)+c
    feats[name]=out
  for x in defs:encode(x,x)
  for x,y in (("venue","quarter"),("fieldSize","favOdds"),
              ("oddsGeom","rankGap"),("venue","fieldSize"),
              ("quarter","oddsGeom"),("favOdds","rankGap")):
    encode(x+"_"+y,x,y)
  return feats
def build_panel(cash,years,panels,train_years,prior,trim):
  all_idx=np.flatnonzero(np.isin(years,train_years))
  if len(all_idx)<8500:raise RuntimeError("TRAINING_PROGRAM_TOO_SMALL")
  n=cash.shape[1];flat=(all_idx[:,None]*n+np.arange(n)[None,:]).ravel()
  paid=cash.ravel()[flat].astype(np.float64)
  hits=(paid>0).astype(np.float64)
  group=np.repeat(np.arange(6),[7,21,21,42,35,210])
  # Cash base rate of the full all-combination market, NOT a future
  # outcome feature, with a family-wide 2% shrinkage toward 70 yen/100.
  priors=[]
  for m,(lo,hi) in enumerate(B):
    p=cash[np.ix_(all_idx,np.arange(lo,hi))].astype(np.float64)
    rate=float(p.mean());chance=float(np.mean(p>0))
    priors.append((.98*rate+.02*70.,chance))
  base=np.asarray(priors,dtype=np.float64)[group]
  estimates={};raw={};support={}
  for name,codes in panels.items():
    tt=codes[flat]
    nb=int(codes.max())+1
    count=np.bincount(tt,minlength=nb).astype(np.float64)
    total=np.bincount(tt,weights=paid,minlength=nb)
    wins=np.bincount(tt,weights=hits,minlength=nb)
    maximum=np.zeros(nb,dtype=np.float64)
    np.maximum.at(maximum,tt,paid)
    numerator=total-trim*maximum
    parent=np.full(nb,np.mean(base[:,0]),dtype=np.float64)
    parenthit=np.full(nb,np.mean(base[:,1]),dtype=np.float64)
    if name!="template":
      # Every category contains a market ID as the outermost digit.
      # Recover that explicit market id safely by taking the first
      # observed candidate of each code rather than dividing by arbitrary
      # feature widths.
      unique=np.full(nb,-1,dtype=np.int16)
      for m,(lo,hi) in enumerate(B):
        idxm=flat[np.isin(flat%n,np.arange(lo,hi))]
        unique[codes[idxm]]=m
      ok=unique>=0
      parent[ok]=[priors[k][0] for k in unique[ok]]
      parenthit[ok]=[priors[k][1] for k in unique[ok]]
    else:
      parent=np.asarray(base[:,0],dtype=np.float64)
      parenthit=np.asarray(base[:,1],dtype=np.float64)
    expected=(numerator+prior*parent)/(count+prior)
    chance=(wins+prior*parenthit)/(count+prior)
    estimates[name]=(expected, chance)
    support[name]=int(np.count_nonzero(count))
  return estimates,support
def project(estimates,panels,positions,regime,templateweight):
  # Relatively hierarchical: template, all single contexts and 2-way
  # interactions. Every posterior is money paid per 100-yen ticket.
  singles=("venue","quarter","fieldSize","favOdds","oddsGeom","rankGap")
  doubles=("venue_quarter","fieldSize_favOdds","oddsGeom_rankGap",
      "venue_fieldSize","quarter_oddsGeom","favOdds_rankGap")
  g=np.zeros(len(positions),dtype=np.float64)
  h=np.zeros(len(positions),dtype=np.float64)
  wtot=0.
  def add(k,w):
    nonlocal g,h,wtot
    out,p=estimates[k];idx=panels[k][positions]
    g+=w*out[idx];h+=w*p[idx];wtot+=w
  add("template",templateweight)
  for name in singles:add(name,(1-templateweight)*(1-regime)/len(singles))
  for name in doubles:add(name,(1-templateweight)*regime/len(doubles))
  if wtot<.99 or wtot>1.01:raise RuntimeError("BAD_EXPERT_WEIGHTS")
  return np.maximum(g,1e-7),np.maximum(h,1e-7)
def decisions(races,cash,idx,gain,prob,hitpower,slate,split):
  n=len(idx)
  signal=gain.reshape(n,336)*np.maximum(prob.reshape(n,336),1e-7)**hitpower
  idxc=np.zeros((n,6),np.int16);raw=np.zeros((n,6),np.float64)
  paid=np.zeros((n,6),np.int32)
  for m,(lo,hi) in enumerate(B):
    j=np.argmax(signal[:,lo:hi],axis=1)+lo
    idxc[:,m]=j
    raw[:,m]=signal[np.arange(n),j]
    paid[:,m]=cash[idx,j]
  rgroup=collections.defaultdict(list)
  for k,i in enumerate(idx):
    r=races[int(i)]
    rgroup[(r["day"],str(r["venue"]))].append(k)
  if any(len(x)<slate for x in rgroup.values()):raise RuntimeError("DAY_SLATE_INCOMPLETE")
  # Pick the strongest TWO DISTINCT market signals in the race;
  # no late result determines race selection/amount.
  ordered=np.argsort(-raw,axis=1,kind="stable")
  a=ordered[:,0];b=ordered[:,1]
  if np.any(a==b):raise RuntimeError("DUPLICATE_MARKET")
  x,y=split
  perrace=paid[np.arange(n),a]*(x//100)+paid[np.arange(n),b]*(y//100)
  sc=raw[np.arange(n),a]+raw[np.arange(n),b]
  selected=np.array([k for g in rgroup.values() for k in sorted(
        g,key=lambda i:(-sc[i],i))[:slate]],dtype=np.int32)
  return selected,perrace[selected],a[selected],b[selected],idxc[selected]
def score_year(races,cash,attrs,markets,years,panels,trainyears,testyear,prior,trim,regime,templateweight,hitpower,slate,split,with_ledger=False):
  stats,support=build_panel(cash,years,panels,trainyears,prior,trim)
  idx=np.flatnonzero(years==testyear)
  positions=(idx[:,None]*336+np.arange(336)[None,:]).ravel()
  gain,prob=project(stats,panels,positions,regime,templateweight)
  chosen,pays,a,b,ticket=decisions(races,cash,idx,gain,prob,hitpower,slate,split)
  summary=metrics(pays)
  if not with_ledger:return summary,None
  rows=[]
  for j,k in enumerate(chosen):
    r=races[int(idx[k])]
    rows.append({"raceId":r["id"],"year":testyear,"raceDate":r["day"],
       "venue":r["venue"],"raceNo":r["raceNo"],
       "marketA":TYPE[int(a[j])],"marketB":TYPE[int(b[j])],
       "rank7TicketA":int(ticket[j,a[j]]),"rank7TicketB":int(ticket[j,b[j]]),
       "stake1Yen":split[0],"stake2Yen":split[1],"paidYen":int(pays[j])})
  return summary,rows
def main():
  if "--self-test" in sys.argv:
    assert sum(b-a for a,b in B)==336
    assert not qualifies({"races":300,"roiPct":400,"minusMaxRaceRoiPct":199,
                          "hitRacePct":60},300)
    assert qualifies({"races":300,"roiPct":250,"minusMaxRaceRoiPct":201,
                       "hitRacePct":20},300)
    print("BAYESIAN_CASH_HIERARCHY_GATE_SELFTEST_OK");return
  start=time.monotonic()
  base=imported()
  races,cash,attrs,markets,years,keys=base.obtain()
  p=panels(attrs,markets,len(races))
  # Every 2022 candidate uses SAME 2017-21 historical pre-data-only
  # posterior; later outcomes never used to select hyperparameters.
  ix=np.flatnonzero(years==2022)
  if len(ix)<2500:raise RuntimeError("MISSING_VALIDATION_RACES")
  positions=(ix[:,None]*336+np.arange(336)[None,:]).ravel()
  examined=0;accepted=0;best=None
  # 4 shrink strengths x 2 trim x 3 template x 3 regime x
  # 4 hit powers x 3 slates x 5 splits = 4320 unique CASH policies.
  for prior in PROB_PRIORS:
   for trim in TRIM:
    post,support=build_panel(cash,years,p,TRAIN,prior,trim)
    for template in TEMPLATE_WEIGHTS:
     for regime in REGIME_WEIGHTS:
      expected,chance=project(post,p,positions,regime,template)
      for power in HIT_POWER:
       for slate in RACES:
        for split in SPLITS:
         selected,paid,_,_,_=decisions(races,cash,ix,expected,chance,power,slate,split)
         result=metrics(paid);examined+=1
         if qualifies(result,600):
          accepted+=1
          policy={"prior":prior,"trim":trim,"regime":regime,
                  "templateWeight":template,"hitPower":power,
                  "racesPerVenueDay":slate,"split":list(split),
                  "qualification2022":result}
          if best is None or result["minusMaxRaceRoiPct"]>best["qualification2022"]["minusMaxRaceRoiPct"]:
            best=policy
  if examined!=4320:raise RuntimeError("INCOMPLETE_CONTEXTUAL_SEARCH")
  report={"status":"SEARCH_FAMILY_REJECTED_NOT_A_MODEL","adoptedModel":False,
      "productionChanged":False,"chronologicalTrainingOnly":True,
      "researchOnly":True,"exactJraT15OddsVerified":False,
      "thirdPartyPayoutsReconciledJra":False,
      "sourceCandidateTickets":int(cash.size),"marketContexts":list(p),
      "searchedCashPolicies":examined,"qualified2022Policies":accepted,
      "qualifiedPolicy":best,
      "2026AugustNovemberForwardCovered":False}
  if best is not None:
    byyear={};allrows=[]
    for y in EVAL:
      # True chronological cumulative expansion: 2023 results CAN help
      # decide 2024 races, but neither same-day nor future results can.
      training=tuple(range(2017,y))
      m,rows=score_year(races,cash,attrs,markets,years,p,training,y,
        best["prior"],best["trim"],best["regime"],best["templateWeight"],
        best["hitPower"],best["racesPerVenueDay"],tuple(best["split"]),True)
      byyear[str(y)]=m
      allrows.extend(rows)
      print("BAYESIAN_RETURN_CASH_HOLDOUT",json.dumps({"year":y,"cash":m}),flush=True)
    combined=metrics([x["paidYen"] for x in allrows])
    ok=qualifies(combined,1200) and all(
      qualifies({**v,"races":max(30,v["races"])},30) for v in byyear.values())
    report.update(status="NUMERIC_200_NOT_T15_CERTIFIED" if ok
       else "SEARCH_FAMILY_REJECTED_NOT_A_MODEL",
       independentCash=combined,forwardYearMoney=byyear,independentPass=bool(ok))
    if allrows:
      LED.parent.mkdir(parents=True,exist_ok=True)
      with LED.open("w",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=list(allrows[0]));w.writeheader();w.writerows(allrows)
  report["seconds"]=round(time.monotonic()-start,3)
  OUT.parent.mkdir(parents=True,exist_ok=True)
  OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
  print("BAYESIAN_RETURN_CASH_RESULT",json.dumps({"status":report["status"],
      "qualifiedRule":bool(best),"cashPolicies":examined,"accepted":accepted,
      "productionChanged":False,"durationSec":report["seconds"]},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
