#!/usr/bin/env python3
"""Research-only exhaustive *bounded* multi-valued cash rule discovery.

Enumerates EVERY subset of 1,2,3,4 from 18 archived pre-result categorical
dimensions and EVERY OBSERVED VALUE assignment per subset / all six JRA
markets. Builds ONE complementary two-ticket portfolio only from conditions
found in 2015-2022 cash settlement. 2023-2026 Apr labels cannot select it.
Includes ALL 1030 top-ten ranked ticket candidates per race, not just top7.
No T-15 odds, no independently reconciled JRA payments; no production writes.
This is not exhaustive over arbitrary depth, every possible horse, or 56 form.
"""
from __future__ import annotations
import csv,gzip,importlib.util,itertools,json,math,sys,time
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-allform-context-multivalue-cash.json"
BETS=ROOT/"analysis-results/nov2026-allform-context-multivalue-bets.csv.gz"
RULES=ROOT/"analysis-results/nov2026-allform-context-multivalue-rules.csv.gz"
FORM_FEATURES=("horseWinAvg","horseTop3Avg","lastFinishAvg","recentFinishAvg","recentSpeedAvg","recentSpeedMax","lastSpeedAvg","speedChangeAvg","jockeyWinAvg","jockeyWinMax","trainerWinAvg","horseExperienceAvg","layoffAvg","distanceFamiliarAvg","surfaceWinAvg","rankFormMismatch","speedRelativeField","jockeyRelativeField","fieldSpeedSpread","comboHorseWinMax")
CONTEXT_FEATURES=("rankMin","rankMax","rankGap","oddsGeom","favOdds","venue","fieldSize","quarter","draw","horseAge","relativeDraw")
FEATURES=FORM_FEATURES+CONTEXT_FEATURES
YEARS=(2023,2024,2025,2026)
MAX_DEPTH=3
TRAIN_FIRST,TRAIN_LAST=2017,2020
VALID=(2021,2022)
MIN_TRAIN=125
MIN_VALID=35
MAX_RETAIN_PER_MARKET=350
CANDIDATES_PER_SCHEMA=6
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
POOL_CHOICES=((0,1,2,3,4,5),(1,2,3,4,5),(2,3,4,5),(3,4,5))
SCALES=(100,200,400,800,1600,3200,6400)
BLENDS=(0.,0.25,0.5,1.,2.)
KEEP=(35,90,200,350)
RACE_COUNTS=(3,4,5)
SOURCE="scripts/research-nov2026-decade-roi-first-sixmarkets.py"

def source():
    sp=importlib.util.spec_from_file_location("multi_cat_paid_source",ROOT/SOURCE)
    v=importlib.util.module_from_spec(sp);sys.modules[sp.name]=v;sp.loader.exec_module(v)
    return v

def pattern_count():
    return sum(math.comb(len(FEATURES),k) for k in range(1,MAX_DEPTH+1)) + math.comb(len(FORM_FEATURES),2)*math.comb(len(CONTEXT_FEATURES),2)

def group_code(cols,market,feat,bins):
    arr=market.astype(np.int32).copy()
    size=6
    for col in cols:
        w=int(bins[col])
        values=feat[col]
        if values.min()<0 or values.max()>=w:raise RuntimeError("INVALID_CATEGORY_"+col)
        arr=arr*w+values.astype(np.int32)
        size*=w
    if size>1_500_000:raise RuntimeError("CATEGORY_COMPOSITION_MEMORY_OVERFLOW")
    return arr,size

def calc_metrics(rows):
    stake=sum(int(x["stakeYen"]) for x in rows)
    paid=sum(int(x["paidYen"]) for x in rows)
    biggest=max((int(x["paidYen"]) for x in rows),default=0)
    return dict(races=len(rows),tickets=2*len(rows),stakeYen=stake,
        paidYen=paid,roiPct=round(100*paid/stake,5) if stake else None,
        minusMaxRaceRoiPct=round(100*(paid-biggest)/stake,5) if stake else None,
        hitRacePct=round(100*sum(x["paidYen"]>0 for x in rows)/len(rows),5)
          if rows else None,biggestRacePayoutYen=biggest)

def load():
    p=ROOT/"scripts/research-nov2026-seasonal-ensemble-cash-first.py"
    spec=importlib.util.spec_from_file_location("all_form_cash_source",p)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    races,paid,features,widths,types,_,year,quarter,_=module.obtain_rows()
    n=len(races)
    if n<16000 or len(paid)!=n*336:
        raise RuntimeError("NOT_ALL_PRE_RACE_56_FORM_CASH_JOINS_AVAILABLE")
    needed=set(FEATURES)
    if not needed.issubset(features):raise RuntimeError("MISSING_REQUIRED_FORM_ATTRIBUTES")
    lookup={k:features[k].reshape(n,336).astype(np.uint8) for k in FEATURES}
    class CashSource:
        SINGLE_BINS={k:int(widths[k]) for k in FEATURES}
    cash=paid.reshape(n,336).astype(np.int32)
    market=types.reshape(n,336).astype(np.uint8)
    return CashSource(),races,cash,lookup,market,year

def mine(src,paid,features,market,year):
    train=np.flatnonzero((year>=TRAIN_FIRST)&(year<=TRAIN_LAST))
    valid=np.flatnonzero(np.isin(year,VALID))
    # limit the physical work to prior years; 2023+ never participates in
    # the construction of train/valid features or market selection.
    ft={k:features[k][train].ravel() for k in FEATURES}
    fv={k:features[k][valid].ravel() for k in FEATURES}
    mt=market[train].ravel();mv=market[valid].ravel()
    yt=paid[train].ravel();yv=paid[valid].ravel()
    pos_t=yt>0;pos_v=yv>0
    candidates=[];stats=Counter()
    begins=time.monotonic()
    for fields in itertools.chain(
       itertools.chain.from_iterable(itertools.combinations(FEATURES,k)
          for k in range(1,MAX_DEPTH+1)),
       (a+b for a in itertools.combinations(FORM_FEATURES,2)
         for b in itertools.combinations(CONTEXT_FEATURES,2))):
        ct,num=group_code(fields,mt,ft,src.SINGLE_BINS)
        cv,_=group_code(fields,mv,fv,src.SINGLE_BINS)
        nt=np.bincount(ct,minlength=num)
        nv=np.bincount(cv,minlength=num)
        pt=np.bincount(ct,weights=yt,minlength=num)
        pv=np.bincount(cv,weights=yv,minlength=num)
        ht=np.bincount(ct[pos_t],minlength=num)
        hv=np.bincount(cv[pos_v],minlength=num)
        stats["schemasScanned"]+=1
        stats["observedValueMarketCells"]+=int(np.count_nonzero(nt))
        ok=(nt>=MIN_TRAIN)&(nv>=MIN_VALID)&(ht>=3)&(hv>=1)
        stats["supportedHistoryCells"]+=int(np.count_nonzero(ok))
        if np.any(ok):
            indexes=np.flatnonzero(ok)
            rt=pt[indexes]/(100*nt[indexes])
            rv=pv[indexes]/(100*nv[indexes])
            # bounded money return + complementary hit cohorts; no condition
            # is excluded merely because it is below ROI200 individually.
            robust0=(np.minimum(rt,12)*.5+np.minimum(rv,12)*.5)
            support=np.sqrt(nt[indexes]/(nt[indexes]+1000.))*np.sqrt(
                  nv[indexes]/(nv[indexes]+150.))
            score=robust0*support
            hr=ht[indexes]/nt[indexes]
            hvp=hv[indexes]/nv[indexes]
            hit=(hr+hvp)*.5*support
            take=set()
            for s in (score,hit):
                amount=min(CANDIDATES_PER_SCHEMA//2,len(indexes))
                if amount:
                    take.update(int(x) for x in np.argpartition(s,-amount)[-amount:])
            chunk=6
            for offset in take:
                idx=int(indexes[offset]);m=int(idx//(num//6))
                if m<0 or m>5:raise RuntimeError("MARKET_GROUP_BAD")
                candidates.append(dict(schema="+".join(fields),fields=fields,
                  conditionCode=idx,market=m,trainCount=int(nt[idx]),
                  validCount=int(nv[idx]),trainCashYen=int(pt[idx]),
                  validCashYen=int(pv[idx]),trainHits=int(ht[idx]),validHits=int(hv[idx]),
                  trainRoiPct=round(100*float(rt[offset]),5),
                  validRoiPct=round(100*float(rv[offset]),5),
                  scoreCash=float(score[offset]),scoreHits=float(hit[offset])))
        if stats["schemasScanned"]%200==0:
            print("ALL_FORM_CONTEXT_MULTI_VALUE_PROGRESS",json.dumps({
             "scanned":int(stats["schemasScanned"]),"total":pattern_count(),
             "observedCells":int(stats["observedValueMarketCells"]),
             "supported":int(stats["supportedHistoryCells"]),
             "retained":len(candidates),"elapsedSeconds":round(time.monotonic()-begins,1)}),
              flush=True)
    # Balance all six wagering markets and cash / hit cohorts, rather than
    # choosing only high-return outliers and losing race coverage.
    retain=[]
    for m in range(6):
        c=[x for x in candidates if x["market"]==m]
        for key in ("scoreCash","scoreHits"):
            c.sort(key=lambda x:(-x[key],-x["trainCount"],x["schema"]))
            retain.extend(c[:MAX_RETAIN_PER_MARKET//2])
    unique={(x["schema"],x["conditionCode"]):x for x in retain}
    retained=list(unique.values())
    stats["retainedDistinctRuleCells"]=len(retained)
    stats["rawTopConditionCells"]=len(candidates)
    stats["trainRaces"]=len(train);stats["validationRaces"]=len(valid)
    stats["seconds"]=round(time.monotonic()-begins,1)
    return retained,dict(stats)

def make_vote_rules(retained,features,market,bins,selected):
    n=len(selected)
    money=np.zeros((n,336),dtype=np.float32)
    hits=np.zeros((n,336),dtype=np.float32)
    # Each candidate has exactly one pre-selected market and an observed
    # conjunction code, with scores from 2015-2022 ONLY.
    families=defaultdict(list)
    for r in retained:
        families[tuple(r["fields"])].append(r)
    feat={k:features[k][selected].ravel() for k in FEATURES}
    mk=market[selected].ravel()
    for fields,arr in families.items():
        codes,_=group_code(fields,mk,feat,bins)
        for r in arr:
            mask=(codes==r["conditionCode"])
            money.ravel()[mask]+=min(4.,r["scoreCash"])
            hits.ravel()[mask]+=min(1.,r["scoreHits"])*5.
    return money,hits

def buy(races,payout,year,index,money,hits,k,blend,second,pool,race_count):
    byday=defaultdict(list)
    spans=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
    for ri,global_i in enumerate(index):
        i=int(global_i)
        s=money[ri]+blend*hits[ri]
        # Multiple rule-votes per ticket, with no payment used in choosing it.
        market_picks=[]
        for mid,(lo,hi) in enumerate(spans):
            j=int(np.argmax(s[lo:hi]))+lo
            market_picks.append((float(s[j]),mid,j))
        base=max(market_picks[:3],key=lambda z:(z[0],-z[1]))
        overlays=[p for p in market_picks if p[1]!=base[1] and p[1] in pool]
        if not overlays:continue
        alt=max(overlays,key=lambda z:(z[0],-z[1]))
        if base[1]==alt[1]:raise RuntimeError("SAME_MARKET")
        payment=int(payout[i,base[2]]+(second//100)*payout[i,alt[2]])
        rid=str(races[i]["id"])
        byday[(str(races[i]["day"]),rid[4:6])].append(dict(
          raceId=rid,day=str(races[i]["day"]),venue=rid[4:6],
          year=int(year[i]),marketA=base[1],ticketA=base[2],
          marketB=alt[1],ticketB=alt[2],baseYen=100,overlayYen=second,
          stakeYen=100+second,paidYen=payment,
          preRaceScore=base[0]+alt[0]))
    result=[]
    for rows in byday.values():
        result+=sorted(rows,key=lambda x:(-x["preRaceScore"],x["raceId"]))[:race_count]
    return result

def evaluate_policies(src,races,paid,features,market,year,retained):
    pre=np.flatnonzero(np.isin(year,VALID))
    baseline=defaultdict(dict)
    # Candidate participation is immutable and independent of 2023+ outcomes.
    choices={}
    for k in KEEP:
        topcash=sorted(retained,key=lambda r:(-r["scoreCash"],r["schema"]))[:k]
        tophit=sorted(retained,key=lambda r:(-r["scoreHits"],r["schema"]))[:k]
        rr={ (r["schema"],r["conditionCode"]):r for r in topcash+tophit}
        choices[k]=list(rr.values())
    frozen_votes={}
    for k,rules in choices.items():
        frozen_votes[k]=make_vote_rules(rules,features,market,src.SINGLE_BINS,pre)
    all_recipes=[]
    for k in KEEP:
      cash,hit=frozen_votes[k]
      for blend in BLENDS:
       for pool in POOL_CHOICES:
        # Race slates are pre-selected ONCE and all stakes are separately
        # settled. This loop searches thousands of strategies cheaply.
        for count in RACE_COUNTS:
         for s in SCALES:
          bets=buy(races,paid,year,pre,cash,hit,k,blend,s,pool,count)
          met=calc_metrics(bets)
          if met["races"]<300:continue
          # Cash ROI dominates. Good hit frequency is a safety gate, not
          # a horse-classification metric or an objective.
          rank=(met["minusMaxRaceRoiPct"] if met["hitRacePct"]>=20
                else met["minusMaxRaceRoiPct"]-100,
                met["roiPct"],met["races"])
          all_recipes.append((rank,(k,blend,pool,count,s),met))
    all_recipes.sort(key=lambda x:x[0],reverse=True)
    winner=all_recipes[0]
    cfg=winner[1]
    print("ALL18_FROZEN_BEFORE2023",json.dumps({
      "testedPortfolioConfigs":len(all_recipes),
      "selected":{"keepRulesPerCohort":cfg[0],"hitWeight":cfg[1],
      "marketPool":cfg[2],"racesPerVenueDay":cfg[3],"overlayStakeYen":cfg[4]},
      "validationCash":winner[2]},ensure_ascii=False),flush=True)
    test=np.flatnonzero(year>=2023)
    cash,hit=make_vote_rules(choices[cfg[0]],features,market,src.SINGLE_BINS,test)
    final=buy(races,paid,year,test,cash,hit,cfg[0],cfg[1],cfg[4],cfg[2],cfg[3])
    yearly={str(y):calc_metrics([b for b in final if b["year"]==y]) for y in YEARS}
    combined=calc_metrics(final)
    count=Counter((b["day"],b["venue"]) for b in final)
    observed=set((str(races[i]["day"]),str(races[i]["id"])[4:6]) for i in test)
    coverage={"observedVenueDays":len(observed),"selectedVenueDays":len(count),
      "daysWith3to5":sum(3<=v<=5 for v in count.values()),
      "daysWith5":sum(v==5 for v in count.values()),
      "venueDaysBelow3":sum(1 for d in observed if count[d]<3)}
    passes=(combined["minusMaxRaceRoiPct"] is not None
      and combined["minusMaxRaceRoiPct"]>=200
      and combined["hitRacePct"] is not None and combined["hitRacePct"]>=20
      and all(yearly[str(y)]["minusMaxRaceRoiPct"] is not None
              and yearly[str(y)]["minusMaxRaceRoiPct"]>=200 for y in YEARS)
      and coverage["venueDaysBelow3"]==0)
    return dict(frozenRecipe=dict(keep=cfg[0],hitWeight=cfg[1],
         marketPool=list(cfg[2]),raceCount=cfg[3],overlayStake=cfg[4]),
      pre2023Validation=winner[2],pre2023PortfolioConfigs=len(all_recipes),
      cashPass=bool(passes),yearly=yearly,combined=combined,coverage=coverage),final

def main():
    if "--self-test" in sys.argv:
        assert len(FEATURES)==31 and len(FORM_FEATURES)==20 and len(CONTEXT_FEATURES)==11 and pattern_count()==15441
        assert all(SCALES[i]%100==0 for i in range(len(SCALES)))
        r=[dict(stakeYen=200,paidYen=500),dict(stakeYen=200,paidYen=100)]
        assert calc_metrics(r)["minusMaxRaceRoiPct"]==25
        x=np.zeros(12,dtype=np.uint8)
        f={"a":x,"b":x}
        c,n=group_code(("a","b"),x,f,{"a":2,"b":3})
        assert n==36 and np.all(c==0)
        print("ALL_FORM_CONTEXT_MULTI_VALUE_CASH_SELFTEST_OK",flush=True);return
    started=time.monotonic()
    src,races,paid,features,market,year=load()
    candidates,audit=mine(src,paid,features,market,year)
    if not candidates:raise RuntimeError("NO_TRAINING_CASH_CONDITIONS")
    p,ledger=evaluate_policies(src,races,paid,features,market,year,candidates)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(RULES,"wt",encoding="utf-8",newline="") as f:
        fields=["schema","conditionCode","market","trainCount","validCount",
          "trainCashYen","validCashYen","trainHits","validHits","trainRoiPct",
          "validRoiPct","scoreCash","scoreHits"]
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        for r in candidates:
            w.writerow({k:r[k] for k in fields})
    with gzip.open(BETS,"wt",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(ledger[0]));w.writeheader();w.writerows(ledger)
    report={"researchOnly":True,
      "officialT15OddsVerified":False,"independentOfficialJraPayoutVerified":False,
      "only2026JanAprAvailable":True,"productionUntouched":True,
      "boundedMultiValuedSchemaEnumeration":True,
      "attributes":list(FEATURES),"subsetDepth":[1,2,3,"twoFormAndTwoRaceContext"],
      "allSixMarkets":True,"all336TopSevenTicketsPerRace":True,
      "trainingYears":[TRAIN_FIRST,TRAIN_LAST],"validationYears":list(VALID),
      "evaluationYears":list(YEARS),"cashConditions":audit,
      "portfolio":p,"adoptable":False,
      "reasonAdoptableFalse":"independent JRA payout and official T-15 odds not verified",
      "totalRuntimeSeconds":round(time.monotonic()-started,1)}
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("ALL_FORM_CONTEXT_MULTI_VALUE_FINANCIAL_FINAL",json.dumps({
      "schemas":audit["schemasScanned"],"observedCells":audit["observedValueMarketCells"],
      "retained":len(candidates),"testedPortfolios":p["pre2023PortfolioConfigs"],
      "cashPass":p["cashPass"],"combined":p["combined"],
      "coverage":p["coverage"],"runtime":report["totalRuntimeSeconds"]},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
