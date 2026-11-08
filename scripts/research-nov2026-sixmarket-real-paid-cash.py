#!/usr/bin/env python3
"""All-six-market true paid-money learning on a pinned public JRA-results CSV mirror.

Research, not live: the CSV source is THIRD-PARTY, its authenticity must be
reconciled with official JRA before promotion; horse final win odds are NOT
T-15 snapshots and combination odds are unavailable. Its payout columns are
actual RESULTS, never input features or bet selection signals.

Source: public Kenseimk/keiba-agent CSV monthly raceresults_YYYYMM.csv.
Train cash return on 2024, select purely by H1-2025 robust CASH ROI,
check never-selected 2025 H2; retrain on 2024+2025, frozen 2026 Jan-Mar
evaluation on six actual payout columns. All 100-yen stake accounting and
outlier-removal preserve original stake. Six markets from top-six final-odds
horses; no original race-tantei model's ticket selection at any stage.

This research is NOT official-JRA/T15-verified, NOT cash purchased, and
2026 has been inspected by prior experiments. Never deploy on a good
retrospective number alone.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from dataclasses import dataclass,asdict
from itertools import combinations,permutations,product
from pathlib import Path
import csv,hashlib,json,math,os,re,sys,time
import numpy as np
from lightgbm import LGBMRegressor

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"external-jra-cash-archive"
OUT=ROOT/"analysis-results/nov2026-sixmarket-public-payout-cash-2025H1-H2-2026.json"
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
PAY_COL=("単勝払戻","ワイド払戻","馬連払戻","馬単払戻","三連複払戻","三連単払戻")
UNORDERED={"ワイド","馬連","3連複"}
SEED=20261108
TOP_HORSES=6
MODES=("direct_tweedie","robust_capped","conservative_blend")
MARKET_SETS={
 "all6":MARKETS,
 "winwide":("単勝","ワイド"),
 "pairs":("ワイド","馬連","馬単"),
 "triples":("3連複","3連単"),
 "no_trifecta":("単勝","ワイド","馬連","馬単","3連複"),
 "win":("単勝",),
 "wide":("ワイド",),
 "trio":("3連複",),
 "trifecta":("3連単",),
}
counts=Counter()
PATTERN=re.compile(r"(\d+(?:\s*(?:→|[-－])\s*\d+){0,2})\s*:\s*([\d,]+)")

def parse_payments(text,market):
    if not text or str(text).strip() in ("nan","None","取消","-"):
        return {}
    out={}
    for combo,value in PATTERN.findall(str(text)):
        numbers=tuple(map(int,re.findall(r"\d+",combo)))
        if len(numbers)!=(1 if market=="単勝" else 3 if market in ("3連複","3連単") else 2):
            raise ValueError("BAD_OFFICIAL_PAYOUT_TICKET_LENGTH:"+market+":"+str(text)[:100])
        if market in UNORDERED:numbers=tuple(sorted(numbers))
        yen=int(value.replace(",",""))
        if yen<100 or numbers in out:raise ValueError("INVALID_OR_DUPLICATE_PAYOUT_ROW")
        out[numbers]=yen
    return out

def read_pinned_csv():
    files=sorted(DATA.glob("raceresults_202*.csv"))
    if not files:raise RuntimeError("PINNED_PUBLIC_PAID_JRA_CSV_DATA_MISSING")
    by_race={};audit=Counter()
    for filename in files:
        suffix=filename.stem.removeprefix("raceresults_")
        if len(suffix)!=6 or suffix[:4] not in ("2024","2025","2026"):
            raise ValueError("UNEXPECTED_DATA_FILE")
        if suffix[:4]=="2026" and suffix[4:] not in ("01","02","03"):continue
        with filename.open(encoding="utf-8-sig",newline="") as fh:
            for row in csv.DictReader(fh):
                rid=str(row["race_id"]).strip()
                if len(rid)!=12 or not rid.startswith(suffix[:4]) or not rid.isdigit():
                    audit["badRaceId"]+=1;continue
                key=(suffix,rid)
                r=by_race.get(key)
                if r is None:
                    payout={}
                    try:
                        for market,col in zip(MARKETS,PAY_COL):
                            payout[market]=parse_payments(row.get(col),market)
                    except (ValueError,TypeError):
                        audit["invalidPayouts"]+=1;continue
                    if any(not p for p in payout.values()):
                        audit["missingOneOfSixMarkets"]+=1;continue
                    r={"id":rid,"month":suffix,"venue":rid[4:6],
                       "day":suffix+"-"+rid[:10],"no":int(rid[-2:]),
                       "payout":payout,"horses":[]}
                    by_race[key]=r
                try:
                    num=int(row["馬番"])
                    odds=float(row["単勝オッズ"])
                    if not 1<=num<=18 or not np.isfinite(odds) or odds<1 or odds>9999:
                        audit["unquotedRunner"]+=1;continue
                    age=int((re.search(r"\d+",row.get("性齢","")) or ["0"])[0])
                    weight=float(row.get("斤量") or 0)
                    if not 0<=age<=18 or not 0<=weight<=80:raise ValueError
                except (ValueError,TypeError):
                    audit["badRunnerQuote"]+=1;continue
                r["horses"].append((num,odds,age,weight))
    result=[]
    for key,r in sorted(by_race.items()):
        nums=[h[0] for h in r["horses"]]
        if len(nums)!=len(set(nums)) or len(nums)<TOP_HORSES:
            audit["duplicateOrShortField"]+=1;continue
        if r["no"]<1 or r["no"]>12:
            audit["invalidRaceNo"]+=1;continue
        if len(r["payout"])!=6:
            audit["incompletePayout"]+=1;continue
        r["horses"].sort(key=lambda x:(x[1],x[0]))
        result.append(r)
    if len(result)<5000:
        raise RuntimeError("SIX_MARKET_JRA_PUBLIC_ARCHIVE_TOO_FEW_RACES:"+str(len(result)))
    audit["racesLoaded"]=len(result)
    for r in result:audit["year"+r["month"][:4]]+=1
    return result,dict(audit)

def ticket_keys(race):
    pool=tuple(h[0] for h in race["horses"][:TOP_HORSES])
    for typ in MARKETS:
        if typ=="単勝":combos=[(h,) for h in pool]
        elif typ in ("馬連","ワイド"):combos=list(combinations(pool,2))
        elif typ=="馬単":combos=list(permutations(pool,2))
        elif typ=="3連複":combos=list(combinations(pool,3))
        else:combos=list(permutations(pool,3))
        for combo in combos:
            if typ in UNORDERED:combo=tuple(sorted(combo))
            yield typ,combo

def money_input(r,market,combo):
    mapping={h[0]:h for h in r["horses"]}
    ranked={h[0]:rank+1 for rank,h in enumerate(r["horses"])}
    parts=[mapping[h] for h in combo]
    q=np.asarray([1/h[1] for h in r["horses"]],dtype=float)
    q=q/q.sum()
    win_q={h[0]:q[i] for i,h in enumerate(r["horses"])}
    odds=np.asarray([p[1] for p in parts],dtype=float)
    probs=np.asarray([win_q[i] for i in combo],dtype=float)
    # Only frozen market prices and known horse/race attributes. No
    # finishing positions/payout/winner fields ever enter features.
    result=[int(market==z) for z in MARKETS]
    result.extend(float(r["venue"]==f"{i:02d}") for i in range(1,11))
    result.extend([
        math.log(odds[0]),math.log(odds[1]) if len(odds)>1 else 0.,
        math.log(odds[2]) if len(odds)>2 else 0.,
        float(np.prod(probs)),float(np.sum(probs)),
        float(min(odds)),float(max(odds)),float(np.std(odds)),
        float(np.mean([ranked[i] for i in combo]))/18.,
        float(max(ranked[i] for i in combo))/18.,
        float(np.mean([mapping[h][2] for h in combo]))/18.,
        float(np.mean([mapping[h][3] for h in combo]))/80.,
        float(min(combo))/18.,float(max(combo))/18.,
        len(r["horses"])/18.,r["no"]/12.,
        math.sin(2*math.pi*int(r["month"][-2:])/12.),
        math.cos(2*math.pi*int(r["month"][-2:])/12.),
        float(market in ("3連複","3連単")),
    ])
    if not np.isfinite(result).all():raise ValueError("NONFINITE_PRESOURCE_MONEY_INPUT")
    return result

def build_actual_payout_rows(races):
    features=[];pays=[];market_ids=[];ridx=[];combinations=[]
    for i,r in enumerate(races):
        for market,combo in ticket_keys(r):
            features.append(money_input(r,market,combo))
            pays.append(int(r["payout"][market].get(combo,0)))
            market_ids.append(MARKETS.index(market))
            ridx.append(i)
            combinations.append((market,combo))
    X=np.asarray(features,dtype=np.float32)
    y=np.asarray(pays,dtype=np.int32)
    ids=np.asarray(ridx,dtype=np.int32)
    mtypes=np.asarray(market_ids,dtype=np.int8)
    if len(X)!=len(y) or X.shape[1]!=35:
        raise RuntimeError("SIX_MARKET_CASH_LABEL_ALIGNMENT_OR_FEATURE_SCHEMA_INVALID:"+str(X.shape))
    # Rebalance markets and races, 3連単 top6 has 120 candidates/race.
    per_market={i:sum(1 for m,c in ticket_keys(races[0]) if m==MARKETS[i])
                for i in range(6)}
    weights=np.asarray([1/per_market[int(j)] for j in mtypes],dtype=np.float32)
    return X,y,ids,mtypes,combinations,weights

def fit(X,y,markets,weights,model_years,rows_years):
    train=np.isin(rows_years,model_years)
    z=np.asarray(y[train],dtype=np.float64)/100
    xx=X[train];ww=weights[train]
    if len(z)<100000 or int(np.sum(z>0))<1500:
        raise RuntimeError("SIX_MARKET_ACTUAL_PAID_TRAINING_INSUFFICIENT")
    capped=z.copy()
    caps={}
    for m in range(6):
        idx=(markets[train]==m)
        positive=z[idx&(z>0)]
        if len(positive)<100:raise RuntimeError("SIX_MARKET_PAID_EVENTS_TOO_SPARSE:"+MARKETS[m])
        cap=float(np.quantile(positive,.95))
        capped[idx]=np.minimum(z[idx],cap)
        caps[MARKETS[m]]=cap
    common=dict(n_estimators=90,learning_rate=.045,num_leaves=15,
                min_child_samples=180,reg_alpha=1.,reg_lambda=20.,
                colsample_bytree=.8,random_state=SEED,n_jobs=2,verbosity=-1)
    raw=LGBMRegressor(objective="tweedie",tweedie_variance_power=1.35,**common)
    trim=LGBMRegressor(objective="poisson",**common)
    raw.fit(xx,z,sample_weight=ww)
    trim.fit(xx,capped,sample_weight=ww)
    return raw,trim,caps,{"trainTickets":len(z),"paidTickets":int(np.sum(z>0)),
                           "trainYears":list(model_years),"payoutCaps":caps}

def signals(raw,trim,X):
    gross=np.clip(raw.predict(X),1e-7,1000.)
    robust=np.clip(trim.predict(X),1e-7,1000.)
    return {
      "raw_cash":gross,
      "capped_cash":robust,
      "conservative_blend":.2*gross+.8*robust,
      "balanced_blend":.5*gross+.5*robust,
    }

@dataclass(frozen=True)
class Policy:
    mode:str
    markets:str
    tickets:int
    races_per_day:int
    min_cash:float
    budget:int
    stake_method:str

def predeclared_policies(stride=1):
    for m,markets,k,rc,t,b,s in product(
       ("raw_cash","capped_cash","conservative_blend","balanced_blend"),
       MARKET_SETS,(1,2,4,8,16),(1,2,3,5,12),
       (0.,.6,.9,1.1,1.4,1.8),(2000,5000),
       ("equal","topheavy")):
        p=Policy(m,markets,k,rc,t,b,s)
        if p.budget<100*k:continue
        hv=int.from_bytes(hashlib.blake2b(repr(p).encode(),digest_size=8).digest(),"little")
        if hv%stride==0:yield p

def money_portfolio(races,y,ids,combo,scored,policy,period):
    start,end=period
    eligible=set(MARKET_SETS[policy.markets])
    days=defaultdict(list)
    # Build the candidate cache ONCE per score column/market mask, then reuse
    # between policies of different bet counts, thresholds and stakes.
    for rid,r in enumerate(races):
        if not start<=r["month"]<end:continue
        a=ids.searchsorted(rid,"left")
        b=ids.searchsorted(rid,"right")
        vals=sorted((float(scored[i]),i) for i in range(a,b)
                    if combo[i][0] in eligible)
        if not vals:continue
        best=vals[::-1][:policy.tickets]
        if len(best)<policy.tickets or best[0][0]<policy.min_cash:continue
        if policy.stake_method=="topheavy":
            stakes=[100]*len(best)
            stakes[0]+=policy.budget-sum(stakes)
        else:
            units=policy.budget//100
            stakes=[(units//len(best))*100]*len(best)
            for j in range(units%len(best)):stakes[j]+=100
        if sum(stakes)!=policy.budget or min(stakes)<100:
            raise ValueError("ILLEGAL_JRA_MONEY_DISTRIBUTION")
        expected=sum(q[0]*stake for q,stake in zip(best,stakes))/policy.budget
        # Only now attach real paid cash, after no-label ranks & stakes fixed.
        selected=[(stake,int(y[i])*(stake//100)) for (_,i),stake in zip(best,stakes)]
        days[r["day"]].append((expected,r["id"],r["month"],selected))
    selections=[]
    for day,options in days.items():
        options.sort(key=lambda a:(-a[0],a[1]))
        selections.extend(options[:policy.races_per_day])
    return selections

def accounting(rows,min_races):
    n=len(rows);stake=sum(sum(s for s,_ in r[3]) for r in rows)
    ret=sum(sum(p for _,p in r[3]) for r in rows)
    if not n or not stake:return {"races":n,"passNumerical200":False}
    biggest=max(p for r in rows for _,p in r[3])
    biggest_race=max(sum(p for _,p in r[3]) for r in rows)
    hits=sum(sum(p for _,p in r[3])>0 for r in rows)
    return {"races":n,"stakeYen":stake,"paidYen":ret,
      "roiPct":round(100*ret/stake,5),
      "trimLargestTicketRoiPct":round(100*(ret-biggest)/stake,5),
      "trimLargestRaceRoiPct":round(100*(ret-biggest_race)/stake,5),
      "hitRacePct":round(100*hits/n,5),
      "maxSingleTicketReturnYen":biggest,"maxRaceReturnYen":biggest_race,
      "passNumerical200":n>=min_races and hits/n>=.20 and
       ret>=stake*2 and ret-biggest>=stake*2 and ret-biggest_race>=stake*2}

def selftest():
    x=parse_payments("7 - 11:990","馬連")
    assert x=={(7,11):990}
    assert parse_payments("7 - 11:450|6 - 7:820|6 - 11:270","ワイド")=={
         (7,11):450,(6,7):820,(6,11):270}
    assert parse_payments("7 → 11 → 6:14730","3連単")=={(7,11,6):14730}
    assert parse_payments("6 - 7 - 11:1640","3連複")=={(6,7,11):1640}
    r=[(1.,"a","202501",[(1000,5000)]),(2.,"b","202501",[(1000,0)])]
    m=accounting(r,2)
    assert m["roiPct"]==250 and m["trimLargestTicketRoiPct"]==0
    assert not m["passNumerical200"]
    r0={"month":"202501","venue":"04","no":1,
        "horses":[(i,2.+i,3,55.) for i in range(1,12)]}
    assert len(money_input(r0,"馬連",(1,2)))==35
    assert len(tuple(ticket_keys(r0)))==206
    print("SIX_MARKET_MONEY_LABEL_PARSER_AND_ORIGINAL_STAKE_SELFTEST_OK")

def main():
    if "--self-test" in sys.argv:selftest();return
    stride=int(os.environ.get("CASH_POLICY_STRIDE","60"))
    if not 1<=stride<=500:raise ValueError("WRONG_PREDECLARED_MONETARY_SEARCH_STRIDE")
    started=time.monotonic()
    races,source_audit=read_pinned_csv()
    print("SIX_MARKET_SOURCE_INTEGRITY",json.dumps(source_audit,ensure_ascii=False),flush=True)
    X,y,ids,types,combo,weights=build_actual_payout_rows(races)
    years=np.asarray([int(races[i]["month"][:4]) for i in ids])
    months=np.asarray([races[i]["month"] for i in ids])
    print("SIX_MARKET_ACTUAL_PAID_TRAINING_MATRIX",json.dumps({
       "raceCount":len(races),"candidateTickets":len(y),
       "nonzeroPaidTicketCandidates":int(np.sum(y>0)),
       "sixMarketsAllPresent":True,
       "oldModelTicketPicksUsed":False}),flush=True)
    raw,trim,caps,prov=fit(X,y,types,weights,(2024,),years)
    model25=signals(raw,trim,X)
    mask_h1=np.asarray([r["month"]<"202507" and r["month"]>="202501" for r in races])
    idx_h1=np.flatnonzero(mask_h1)
    first=idx_h1[0];last=idx_h1[-1]
    best=None;valid=0;tries=0;passing=0
    # Cache expensive per-race ticket sorts for each cash signal and market
    # subset, rather than sorting ~2 million tickets per hypothesis.
    # Simplified in first run: coarser stride tests ~100-200 policies.
    for p in predeclared_policies(stride):
        tries+=1
        bet=money_portfolio(races,y,ids,combo,model25[p.mode],p,("202501","202507"))
        m=accounting(bet,100)
        if m["races"]<100:continue
        valid+=1;passing+=int(m["passNumerical200"])
        metric=(int(m["passNumerical200"]),m["trimLargestRaceRoiPct"],
                m["trimLargestTicketRoiPct"],m["hitRacePct"]>=20,m["races"])
        if best is None or metric>best[0]:best=(metric,p,m)
    if best is None:raise RuntimeError("NO_SIX_MARKET_MONETARY_PORTFOLIO_VALIDATION")
    _,policy,h1=best
    h2=accounting(money_portfolio(races,y,ids,combo,model25[policy.mode],
         policy,("202507","202601")),100)
    print("SIX_MARKET_JRA_2025_CASH_SELECTED",json.dumps({
      "policy":asdict(policy),"H1":h1,"H2":h2,"tried":tries,"valid":valid,
      "H1Numerical200Passing":passing},ensure_ascii=False),flush=True)
    raw26,trim26,caps26,prov26=fit(X,y,types,weights,(2024,2025),years)
    mode26=signals(raw26,trim26,X)[policy.mode]
    eval26=accounting(money_portfolio(races,y,ids,combo,mode26,policy,
                                      ("202601","202604")),100)
    print("SIX_MARKET_2026_ACTUAL_RESULTED_CASH",json.dumps({
      "selectedPolicy2025H1":asdict(policy),"2025H2":h2,
      "2026":eval26},ensure_ascii=False),flush=True)
    report={
      "model":"six-market direct cash-return Tweedie plus capped Poisson",
      "settlementSource":"pinned public third-party JRA results CSV all six named payout markets",
      "isIndependentlyOfficialJraPayoutAuthenticated":False,
      "noT15CombinationOddsAvailable":True,
      "priorSelectedTicketsNeverUsed":True,
      "holdout2026WasPreviouslyInspectedByOtherResearch":True,
      "dataSourceCommit":"Kenseimk/keiba-agent f552ca8628646f39b05ffdbdc3ab8734939ffd66",
      "sourceAudit":source_audit,
      "totalBetCandidatesEnumerated":len(y),
      "year2024CashTrain":prov,
      "2025PoliciesExamined":tries,"2025PoliciesValid":valid,
      "2025PredeclaredPoliciesNumericallyPassed200":passing,
      "fixedModelAndStakes":asdict(policy),
      "2025H1CashSelection":h1,"2025H2MoneyHoldout":h2,
      "2026RefitCashTraining":prov26,"2026MoneyHoldout":eval26,
      "allAcceptanceConditionsProven":False,
      "productionPromotionAllowed":False,
      "seconds":round(time.monotonic()-started,2)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("SIX_MARKET_ROI_RESEARCH_RESULT_WRITTEN",OUT,flush=True)

if __name__=="__main__":main()
