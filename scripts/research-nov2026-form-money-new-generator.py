#!/usr/bin/env python3
"""New independent six-market chronological-horse-FORM actual-cash generator.

All six bet types/all rank-seven ticket combinations, not old-model bets.
2022 is the only rule search year; 2023+ is evaluated only for a 2022
qualifier. Numerical 200% / minus-largest 200% / hit 20% gates are HARD.
All settlement numbers from a pinned external mirror; final win odds are
not verified JRA T-15 quotes. No promotion to live is allowed.
"""
from __future__ import annotations
import collections,csv,importlib.util,itertools,json,math,sys,time
from pathlib import Path
import numpy as np
from lightgbm import LGBMClassifier,LGBMRegressor
R=Path(__file__).resolve().parents[1]
OUT=R/"analysis-results/nov2026-form-money-context-search.json"
LED=R/"analysis-results/nov2026-form-money-context-forward-bets.csv"
YEARS_TRAIN=(2017,2018,2019,2020,2021)
YEARS_FINAL=tuple(range(2017,2023))
EVAL=(2023,2024,2025,2026)
PAIRS=tuple(itertools.combinations(range(6),2))
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
LIMITS=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
STAKES=((1000,1000),(1500,500),(1900,100),(500,1500),(100,1900))
FORMULAE=((1.,0.),(.5,0.),(1.5,0.),(2.,0.),(.5,.5),(1.,.5),(1.5,.5),(.5,1.),(1.,1.),(1.5,1.),(1.,2.),(.5,2.))
SLATES=(3,4,5)
SEED=20261113

def module(name,path):
    s=importlib.util.spec_from_file_location(name,R/path)
    m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m

def obtain():
    # Do NOT restrict the 3-5R venue/day universe to races with exact horse
    # identity joins: that accidentally makes every portfolio invalid.
    # Carry all original settled races and mark missing historical form
    # explicitly. All payouts remain labels, never generator inputs.
    m=module("form_cash_source","scripts/research-nov2026-seasonal-ensemble-cash-first.py")
    joined,joined_paid,joined_attrs,widths,_,_,_,_,joint=m.obtain_rows()
    if len(joined)<16000 or len(joined_attrs)<30:raise RuntimeError("INCOMPLETE_FORM_ARCHIVE")
    source=module("original_full_cash_source","scripts/research-nov2026-decade-roi-first-sixmarkets.py")
    parser=module("original_full_cash_parser","scripts/research-nov2026-sixmarket-real-paid-cash.py")
    form=module("full_cash_rank7_indices","scripts/research-nov2026-chronological-form-money-conditions.py")
    archive=source.read_all_races(parser.parse_payments)
    ix=np.asarray([j for j,r in enumerate(archive) if r["month"]>="201701"],dtype=np.int32)
    races=[archive[int(j)] for j in ix]
    template=joint.rank7_market_indices(source,form)
    if len(template)!=336 or len(races)<25000:raise RuntimeError("INCOMPLETE_FULL_PROGRAM_TICKETS")
    with np.load(source.CACHE,allow_pickle=False) as z:
        if z["payout"].shape[0]!=len(archive):raise RuntimeError("CASH_ORDER_MISMATCH")
        full_paid=z["payout"][ix[:,None],template[None,:]].astype(np.int32)
        full_attrs={}
        n=len(races)
        for field in joined_attrs:
            if field in z.files:
                full_attrs[field]=z[field][ix[:,None],template[None,:]].astype(np.uint8).reshape(-1)
            elif field=="relativeDraw":
                full_attrs[field]=(
                    z["draw"][ix[:,None],template[None,:]].astype(np.uint16) *
                    source.SINGLE_BINS["fieldSize"]+
                    z["fieldSize"][ix[:,None],template[None,:]].astype(np.uint16)
                ).astype(np.uint8).reshape(-1)
            else:
                full_attrs[field]=np.zeros(n*336,dtype=np.uint8)
    pos={r["id"]:i for i,r in enumerate(races)}
    target=[];original=[]
    for i,r in enumerate(joined):
        j=pos.get(r["id"])
        if j is None:raise RuntimeError("JOINED_RACE_OUTSIDE_FULL_CASH_SOURCE")
        target.append(j);original.append(i)
    target=np.asarray(target,dtype=np.int32)
    original=np.asarray(original,dtype=np.int32)
    if not np.array_equal(full_paid[target],joined_paid.reshape(-1,336)[original]):
        raise RuntimeError("JOINED_VS_UNJOINED_SETTLED_TICKET_PAYOUT_DIFFERENCE")
    for field,values in joined_attrs.items():
        src=values.reshape(len(joined),336)
        dest=full_attrs[field].reshape(len(races),336)
        dest[target]=src[original]
    matched=np.zeros(len(races)*336,dtype=np.uint8)
    matched.reshape(len(races),336)[target]=1
    full_attrs["formIdentityMatched"]=matched
    types=np.tile(np.array([0]*7+[1]*21+[2]*21+[3]*42+[4]*35+[5]*210,
                          dtype=np.uint8),len(races))
    years=np.asarray([int(r["month"][:4]) for r in races],dtype=np.int16)
    if np.any(np.asarray([r["month"] for r in races])[years==2026]>="202605"):
        raise RuntimeError("MONTH_BOUNDARY_INVALID")
    print("FULL_PROGRAM_FORM_COVERAGE",json.dumps({
        "allHistoricalRaces":len(races),"formMatchedRaces":len(joined),
        "formMissingButRetainedRaces":len(races)-len(joined),
        "noSelectionOnAvailableForms":True,
        "moneyLabelsExactJoinReconciled":True,
        "years":dict(collections.Counter(map(int,years)))
    },ensure_ascii=False),flush=True)
    return races,full_paid,full_attrs,types,years,tuple(sorted(full_attrs))

def features(attrs,markets,keys,positions):
    x=np.empty((len(positions),len(keys)+1),dtype=np.float32)
    x[:,0]=markets[positions]
    for j,key in enumerate(keys):x[:,j+1]=attrs[key][positions]
    return x

def train(cash,attrs,markets,years,keys,train_years):
    ids=np.flatnonzero(np.isin(years,train_years))
    if len(ids)<7000:raise RuntimeError("INSUFFICIENT_CASH_TRAIN_DAYS")
    flat=(ids[:,None]*336+np.arange(336)[None,:]).ravel()
    labels=cash.ravel()[flat]
    positive=labels>0
    rng=np.random.default_rng(SEED)
    keep=positive|(rng.random(len(flat))<.05)
    selected=flat[keep]
    x=features(attrs,markets,keys,selected)
    w=np.where(positive[keep],1.,20.).astype(np.float32)
    base=dict(n_estimators=140,learning_rate=.047,num_leaves=15,max_depth=6,
        min_child_samples=330,colsample_bytree=.85,reg_lambda=28.,
        reg_alpha=.6,random_state=SEED,n_jobs=3,verbosity=-1)
    event=LGBMClassifier(objective="binary",**base)
    event.fit(x,positive[keep].astype(np.int8),sample_weight=w)
    pos=flat[positive]
    yp=cash.ravel()[pos].astype(np.float32)
    mt=markets[pos].astype(int)
    caps=np.asarray([np.quantile(yp[mt==k],.95) for k in range(6)],dtype=np.float32)
    if np.any(caps<100):raise RuntimeError("MISSING_MARKET_PAYOUT_SUPPORT")
    sev=LGBMRegressor(objective="poisson",**{**base,"min_child_samples":160})
    counts=np.bincount(mt,minlength=6)
    sev.fit(features(attrs,markets,keys,pos),
      np.minimum(yp,caps[mt])/100,
      sample_weight=1./np.sqrt(counts[mt].astype(np.float32)))
    direct=LGBMRegressor(objective="tweedie",tweedie_variance_power=1.35,**base)
    direct.fit(x,
       np.minimum(cash.ravel()[selected],caps[markets[selected].astype(int)])/100,
       sample_weight=w)
    return (event,sev,direct)

def infer(models,attrs,markets,keys,year,yr):
    idx=np.flatnonzero(year==yr)
    flat=(idx[:,None]*336+np.arange(336)[None,:]).ravel()
    arr=[]
    event,sev,direct=models
    for st in range(0,len(flat),250000):
        x=features(attrs,markets,keys,flat[st:st+250000])
        p=np.clip(event.predict_proba(x)[:,1],1e-7,1)
        c=np.maximum(sev.predict(x),1e-7)
        d=np.maximum(direct.predict(x),1e-7)
        arr.append(np.stack([p*c,d,p],axis=-1))
    return idx,np.concatenate(arr).reshape(len(idx),336,3)

def proposals(cash,idx,signal,source,expo):
    beta,gamma=expo
    strength=(np.maximum(signal[:,:,source],1e-9)**beta)*(
        np.maximum(signal[:,:,2],1e-9)**gamma)
    n=len(idx)
    raw=np.empty((n,6),np.int16)
    val=np.empty((n,6),np.float64)
    paid=np.empty((n,6),np.int32)
    for market,(lo,hi) in enumerate(LIMITS):
        ids=np.argmax(strength[:,lo:hi],axis=1).astype(np.int16)+lo
        raw[:,market]=ids
        val[:,market]=strength[np.arange(n),ids]
        paid[:,market]=cash[idx,ids]
    return raw,val,paid

def grouped(races,idx):
    groups=collections.defaultdict(list)
    for j,i in enumerate(idx):
        r=races[int(i)]
        groups[(r["day"],r["venue"])].append(j)
    return [np.asarray(v,np.int32) for _,v in sorted(groups.items())]

def metrics(rows):
    n=len(rows);return_sum=sum(int(v) for v in rows);stake=n*2000
    maximum=max((int(v) for v in rows),default=0);hit=sum(int(v>0) for v in rows)
    return dict(races=n,stakeYen=stake,paidYen=return_sum,
      roiPct=round(100*return_sum/stake,4) if stake else None,
      minusMaxRaceRoiPct=round(100*(return_sum-maximum)/stake,4) if stake else None,
      hitRacePct=round(100*hit/n,4) if n else None,
      biggestRacePaidYen=maximum)

def qualifies(m):
    return m["races"]>=300 and (m["roiPct"] or 0)>=200 and (
        m["minusMaxRaceRoiPct"] or 0)>=200 and (m["hitRacePct"] or 0)>=20

def optimize(races,cash,idx,pred):
    grouping=grouped(races,idx)
    quarters=np.asarray([(int(races[int(i)]["month"][4:])-1)//3 for i in idx],
                        dtype=np.int8)
    if len(grouping)<120:raise RuntimeError("VAL_DAYS_TOO_FEW")
    best=None;processed=0;seasons=0
    # Optimize disjoint seasonal market PAIR switches. 15^4 pair
    # allocations per signal/power/slate/stake are represented EXACTLY
    # by independent-quarter maxima, not tested by opening 2023 labels.
    for source in (0,1):
      for expo in FORMULAE:
        ranks,score,pays=proposals(cash,idx,pred,source,expo)
        for slate in SLATES:
          if any(len(v)<slate for v in grouping):
             continue  # cannot silently drop any venue-day
          for stake in STAKES:
            summaries=[]
            for a,b in PAIRS:
              edge=score[:,a]+score[:,b]
              positions=[]
              for group in grouping:
                positions+=sorted(group.tolist(),
                     key=lambda i:(-edge[i],i))[:slate]
              take=np.asarray(positions,dtype=np.int32)
              ret=(pays[take,a]*(stake[0]//100)+pays[take,b]*(stake[1]//100))
              q=quarters[take]
              summaries.append((a,b,take,ret,q))
              processed+=1
            # choose best pair per quarter on 2022 validation cash,
            # then freeze that four-season vector before test years.
            chosen=[]
            for q in range(4):
              best_q=max(summaries,key=lambda r:(
                int(r[3][r[4]==q].sum())-
                (int(r[3][r[4]==q].max()) if np.any(r[4]==q) else 0),
                int(np.count_nonzero(r[3][r[4]==q]))))
              chosen.append(best_q)
            season_ret=[]
            for q,r in enumerate(chosen):season_ret.extend(r[3][r[4]==q].tolist())
            seasons+=1
            m=metrics(season_ret)
            if qualifies(m):
              candidate=dict(signal=source,expo=expo,slate=slate,
                 splitYen=list(stake),pairsByQuarter=[list(z[:2]) for z in chosen],
                 validation=m,marketAllocationDesigns=15**4)
              if best is None or m["minusMaxRaceRoiPct"]>best["validation"]["minusMaxRaceRoiPct"]:
                 best=candidate
    return best,dict(materializedMarketPairStrategies=processed,
      equivalentCombinatorialSeasonalPortfolios=seasons*15**4,
      noEvaluationYearLabelsUsedForSelection=True,
      fullVenueDayCount=len(grouping),
      allVenueDaysMinThree=all(len(v)>=3 for v in grouping),
      usableSeasonalConfigurations=seasons)

def apply(races,cash,idx,pred,rule):
    s=rule["signal"];expo=tuple(rule["expo"]);slate=rule["slate"]
    raw,score,pays=proposals(cash,idx,pred,s,expo)
    rows=[]
    for group in grouped(races,idx):
      if len(group)<slate:raise RuntimeError("FORWARD_COVERAGE_MISSING")
      q=(int(races[int(idx[group[0]])]["month"][4:])-1)//3
      a,b=rule["pairsByQuarter"][q]
      s1,s2=rule["splitYen"]
      edge=score[:,a]+score[:,b]
      for k in sorted(group.tolist(),key=lambda i:(-edge[i],i))[:slate]:
         race=races[int(idx[k])]
         rows.append(dict(raceId=race["id"],year=int(race["month"][:4]),
            venue=race["venue"],day=race["day"],raceNo=race["raceNo"],
            market1=MARKETS[a],market2=MARKETS[b],
            ticket1=int(raw[k,a]),ticket2=int(raw[k,b]),
            stake1Yen=s1,stake2Yen=s2,
            paidYen=int(pays[k,a]*(s1//100)+pays[k,b]*(s2//100))))
    return rows

def main():
  if "--self-test" in sys.argv:
     assert len(PAIRS)==15 and sum(b-a for a,b in LIMITS)==336
     assert all(sum(x)==2000 for x in STAKES)
     assert not qualifies(dict(races=400,roiPct=199.99,minusMaxRaceRoiPct=250,hitRacePct=35))
     assert qualifies(dict(races=400,roiPct=220,minusMaxRaceRoiPct=200,hitRacePct=20))
     print("CHRONOLOGICAL_FORM_CONTEXT_CASH_SELFTEST_OK",flush=True);return
  start=time.monotonic()
  races,cash,attrs,markets,year,keys=obtain()
  print("NEW_FORM_FINANCIAL_GENERATOR_SOURCE",json.dumps({
    "sourceRaces":len(races),"allTicketCandidates":int(cash.size),
    "chronologicalFormAndRaceContextFeatures":len(keys),
    "sourceHasExactJraT15Odds":False,
    "sourceThirdPartyPayoutNotIndependentlyAuthenticated":True},
    ensure_ascii=False),flush=True)
  model=train(cash,attrs,markets,year,keys,YEARS_TRAIN)
  idx,score=infer(model,attrs,markets,keys,year,2022)
  winner,search=optimize(races,cash,idx,score)
  result={"researchOnly":True,"adoptedModel":False,
      "status":"SEARCH_FAMILY_REJECTED_NOT_A_MODEL",
      "source":"chronological horse form + odds rank cash generation",
      "trainingYears":list(YEARS_TRAIN),"validationYear":2022,
      "searched":search,"numericalRuleQualifiedBeforeOOS":bool(winner),
      "productionChanged":False,"noFutureResultsInSelection":True,
      "jraT15OddsVerified":False,"payoutSourceOfficiallyReconciled":False,
      "2026AugNovIndependentTicketsCovered":False}
  if winner is not None:
      result["qualifiedOn2022"]=winner
      frozen=train(cash,attrs,markets,year,keys,YEARS_FINAL)
      allrows=[];yr={}
      for y in EVAL:
          ix,pred=infer(frozen,attrs,markets,keys,year,y)
          bought=apply(races,cash,ix,pred,winner)
          yr[str(y)]=metrics([z["paidYen"] for z in bought])
          allrows+=bought
      aggregate=metrics([z["paidYen"] for z in allrows])
      passed=qualifies(aggregate) and all(
        (yr[str(y)]["races"]>=30 and
         (yr[str(y)]["roiPct"] or 0)>=200 and
         (yr[str(y)]["minusMaxRaceRoiPct"] or 0)>=200 and
         (yr[str(y)]["hitRacePct"] or 0)>=20)
        for y in EVAL)
      result.update({"forwardCash":aggregate,"forwardYear":yr,
          "status":"NUMERIC_PASS_BUT_NOT_JRA_T15_VERIFIED" if passed
                 else "SEARCH_FAMILY_REJECTED_NOT_A_MODEL",
          "forwardPassAllYears":bool(passed)})
      if allrows:
          LED.parent.mkdir(parents=True,exist_ok=True)
          with LED.open("w",newline="",encoding="utf8") as f:
              w=csv.DictWriter(f,fieldnames=list(allrows[0]));w.writeheader();w.writerows(allrows)
  result["seconds"]=round(time.monotonic()-start,2)
  OUT.parent.mkdir(parents=True,exist_ok=True)
  OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
  print("NEW_FORM_CASH_ACCEPTANCE_RESULT",json.dumps({
      "status":result["status"],"numericalQualified":result["numericalRuleQualifiedBeforeOOS"],
      "testedEquivalentPortfolioArchitectures":search["equivalentCombinatorialSeasonalPortfolios"],
      "durationSeconds":result["seconds"],"productionUnchanged":True
  },ensure_ascii=False),flush=True)
if __name__=="__main__":main()
