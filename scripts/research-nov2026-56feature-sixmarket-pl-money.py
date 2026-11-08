#!/usr/bin/env python3
"""NEW algorithm: chronology-safe 56-feature horse-strength -> six-market
ordered PL payouts, combined with a conditional actual-paid-amount learner.

Financial return = probability of the EXACT paid market event x its JRA
payout amount, never top1 accuracy or log loss optimization. All candidate
tickets are independently enumerated; all different two-market pairs remain
eligible; select 5 races per venue-day. This is historical OFFLINE research
only: results mirror is not independently verified against official JRA,
and final WIN odds are not officially archived T-15 combination quotations.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import asdict,dataclass
from itertools import permutations,combinations,product
from pathlib import Path
import csv,importlib.util,json,math,sys,time,unicodedata
import numpy as np
from lightgbm import LGBMClassifier,LGBMRegressor

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-56feature-sixmarket-pl-cash.json"
TYPE_NAMES=("単勝","ワイド","馬連","馬単","3連複","3連単")
PAIR_IDS=tuple(combinations(range(6),2))

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if spec is None or spec.loader is None:raise RuntimeError(f"MISSING_RESEARCH_DEPENDENCY:{path}")
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module

def historical_horse_features():
    hist=load("scripts/postaug-support-chronological-56feature-validation.py","pl_horse_history")
    other=load("scripts/research-nov2026-all-runner-direct-money.py","pl_allrunner_join")
    cal=hist.load_public_archive()
    days=hist.load_bundles(cal)
    identity_names={}
    for date in days:
        for b in days[date]:
            identity_names[b["race"]["raceId"]]={
                int(h["horseNo"]):str(h["horseName"]) for h in b["runners"]}
    X,won,counts,dates,offsets,winners,dropped,num_races,odds=hist.chronological_features(
        hist.core_module(),days)
    rows=other.standalone_runner_index(days,counts,winners)
    if len(rows)!=len(counts):raise RuntimeError("CHRONOLOGY_ALIGNMENT")
    return X,won,offsets,rows,identity_names,dropped

VENUES={"札幌":"01","函館":"02","福島":"03","新潟":"04","東京":"05",
        "中山":"06","中京":"07","京都":"08","阪神":"09","小倉":"10",
        "sapporo":"01","hakodate":"02","fukushima":"03","niigata":"04",
        "tokyo":"05","nakayama":"06","chukyo":"07","kyoto":"08",
        "hanshin":"09","kokura":"10"}

def normalize_horse(s):
    return unicodedata.normalize("NFKC",str(s)).strip().replace(" ","").replace("　","")

def read_source_horse_names():
    result=defaultdict(dict);columns=None
    paths=sorted((ROOT/"external-jra-cash-archive").glob("raceresults_202*.csv"))
    for file in paths:
        with file.open(encoding="utf-8-sig",newline="") as fh:
            reader=csv.DictReader(fh)
            if columns is None:columns=reader.fieldnames
            for r in reader:
                rid=str(r.get("race_id","")).strip()
                if len(rid)!=12:continue
                raw_name=r.get("馬名") or r.get("馬名(漢字)") or r.get("horse_name")
                try:horse=int(r["馬番"])
                except (ValueError,KeyError):continue
                if raw_name:result[rid][horse]=normalize_horse(raw_name)
    if not result:raise RuntimeError("NO_PRE_RESULT_HORSE_IDENTITIES_IN_PAYOUT_CSV:"+str(columns))
    print("PAYOUT_MIRROR_PRE_RESULT_IDENTITY_COLUMNS",json.dumps({
        "headers":columns,"namedRaces":len(result),
        "sampleHorseNames":list(next(iter(result.values())).items())[:3]},
         ensure_ascii=False),flush=True)
    return result

def join_pre_result_races_by_horse_identity(races,metadata,archive_names,source_names):
    """Join different ID namespaces only by known-before-start horse identity.
    No outcome or payoff information is used to establish race alignment.
    """
    index=defaultdict(list)
    for i,m in enumerate(metadata):
        venue=next((code for name,code in VENUES.items() if name in m["venue"]),None)
        if venue:
            index[(m["date"][:4],venue,int(m["raceNo"]))].append(i)
    resolved={};no_match=0;ambiguous=0;best_scores=[]
    used=set()
    sample_debug=[]
    for race in races:
        key=(race["month"][:4],race["venue"],int(race["no"]))
        source=source_names.get(race["id"],{})
        candidates=[]
        for i in index.get(key,()):
            target=archive_names.get(metadata[i]["raceId"],{})
            matching=sum(normalize_horse(target.get(n,""))==name for n,name in source.items() if n in target)
            candidates.append((matching,i))
        candidates.sort(reverse=True)
        if len(sample_debug)<3:
            sample_debug.append({"sourceRaceId":race["id"],"sourceNames":list(source.items())[:4],
               "indexCandidates":len(candidates),
               "bestMatched":candidates[0][0] if candidates else None,
               "bestArchiveId":metadata[candidates[0][1]]["raceId"] if candidates else None,
               "bestArchiveNames":list(archive_names.get(metadata[candidates[0][1]]["raceId"],{}).items())[:4] if candidates else []})
        if not candidates or candidates[0][0]<4:
            no_match+=1;continue
        if len(candidates)>1 and candidates[0][0]==candidates[1][0]:
            ambiguous+=1;continue
        count,i=candidates[0]
        if i in used:raise RuntimeError("DUPLICATE_HORSE_IDENTITY_RACE_JOIN")
        used.add(i);resolved[race["id"]]=i;best_scores.append(count)
    print("PUBLIC_JRA_HORSE_IDENTITY_RACE_JOIN",json.dumps({
        "sourceRaces":len(races),"matched":len(resolved),
        "withoutFourHorseMatches":no_match,"ambiguous":ambiguous,
        "exampleAlignments":sample_debug,"minAccepted":min(best_scores) if best_scores else None},
        ensure_ascii=False),flush=True)
    if len(resolved)<len(races)*.75:
        raise RuntimeError("SOURCE_ARCHIVE_HORSE_NAME_IDENTITY_PROOF_TOO_SMALL")
    return resolved

def fit_pre_result_horse(X,labels,metadata,offsets,through_year):
    yrs=np.asarray([int(m["date"][:4]) for m in metadata],dtype=np.int16)
    event_year=np.repeat(yrs,np.diff(offsets))
    eligible=(event_year>=2019)&(event_year<=through_year)
    model=LGBMClassifier(objective="binary",n_estimators=220,
        learning_rate=.035,num_leaves=23,min_child_samples=120,
        colsample_bytree=.82,reg_lambda=25.,reg_alpha=1.5,
        random_state=20261108,n_jobs=2,verbosity=-1)
    if int(eligible.sum())<30000:raise RuntimeError("HORSE_PRIOR_TRAIN_TOO_SMALL")
    model.fit(X[eligible],labels[eligible])
    # All needed candidate race strengths; held-out outcomes NEVER used in fit.
    vals=model.predict_proba(X)[:,1].astype(np.float32)
    return vals,{"trainThroughYear":through_year,"allTrainRunnerRows":int(eligible.sum())}

def fit_paid_amount(base_X,actual_y,mtypes,ids,races,through_year):
    year=np.asarray([int(races[int(i)]["month"][:4]) for i in ids],dtype=np.int16)
    eligible=(year>=2024)&(year<=through_year)&(actual_y>0)
    if eligible.sum()<10000:raise RuntimeError("CASH_AMOUNT_PAID_TRAIN_INSUFFICIENT")
    # Train ONLY on paid outcomes; the probability of payout comes from the
    # chronology-safe horse model / six-market joint finishing distribution.
    model=LGBMRegressor(objective="huber",alpha=.8,
        n_estimators=210,learning_rate=.035,num_leaves=18,
        min_child_samples=75,colsample_bytree=.8,
        reg_lambda=27.,reg_alpha=2.,random_state=20261108,
        n_jobs=2,verbosity=-1)
    paid_y=actual_y[eligible].astype(np.float64)
    model.fit(base_X[eligible],np.log(np.maximum(paid_y,100.)))
    predicted=model.predict(base_X)
    positive_train=eligible & (actual_y>0)
    multipliers=[]
    for m in range(6):
        local=positive_train & (mtypes==m)
        ratios=actual_y[local]/np.maximum(np.exp(predicted[local]),100.)
        if len(ratios)<300:raise RuntimeError("PAID_COMBINATION_SAMPLE_MISSING")
        # Upper tail shrink is an architectural decision using training only.
        multiplier=float(np.clip(np.mean(np.minimum(ratios,10)),1.,5.))
        multipliers.append(multiplier)
    amount=np.minimum(np.exp(predicted)*np.asarray(multipliers)[mtypes],2e7)
    return amount.astype(np.float32),{"trainThroughYear":through_year,
        "trainingActualPaidTickets":int(eligible.sum()),
        "moneySmearMultipliers":dict(zip(TYPE_NAMES,multipliers))}

def normalized_strengths(race,horse_model,archive,offsets,race_lookup,alpha):
    h=race["horses"]
    nums=[n for n,odds,age,w in h]
    market=np.asarray([1/horse[1] for horse in h],dtype=np.float64)
    market/=market.sum()
    rid=race_lookup.get(race["id"])
    if rid is None:return dict(zip(nums,market)),False
    source=archive[rid]["horseNos"]
    start=int(offsets[rid])
    scores=horse_model[start:start+len(source)]
    prior={int(i):float(s) for i,s in zip(source,scores)}
    if len(set(nums).intersection(prior))<len(nums):
        # Not all active runners can be joined to the pre-result state.
        return dict(zip(nums,market)),False
    horse_model_strength=np.maximum(np.asarray([prior[i] for i in nums]),1e-6)
    horse_model_strength/=horse_model_strength.sum()
    q=(market**(1-alpha))*(horse_model_strength**alpha)
    q/=q.sum()
    return dict(zip(nums,q)),True

def paid_event_probability(market,combo,strength):
    # Proper PL denominators include ALL original priced runners, not just top6.
    def ordered(*seq):
        total=1.;p=1.
        for i in seq:
            s=strength[i]
            if total<=0:return 0.
            p*=s/total
            total-=s
        return p
    if market=="単勝":return ordered(combo[0])
    if market=="馬単":return ordered(*combo)
    if market=="3連単":return ordered(*combo)
    if market=="馬連":return ordered(*combo)+ordered(*combo[::-1])
    if market=="3連複":
        return sum(ordered(*perm) for perm in permutations(combo))
    if market=="ワイド":
        a,b=combo
        return sum(ordered(*perm) for k in strength if k not in (a,b)
                   for perm in permutations((a,b,k)))
    raise RuntimeError("UNKNOWN_JRA_MARKET")

def pay_event_fixture():
    s={1:.5,2:.3,3:.2}
    assert abs(sum(paid_event_probability("単勝",(i,),s) for i in s)-1)<1e-9
    assert abs(sum(paid_event_probability("馬連",tuple(c),s)
                   for c in combinations(s,2))-1)<1e-9
    assert abs(sum(paid_event_probability("馬単",tuple(c),s)
                   for c in permutations(s,2))-1)<1e-9
    assert abs(sum(paid_event_probability("3連複",tuple(c),s)
                   for c in combinations(s,3))-1)<1e-9
    assert abs(sum(paid_event_probability("3連単",tuple(c),s)
                   for c in permutations(s,3))-1)<1e-9
    # With exactly three finishers, all pairs must cash WIDE.
    assert abs(paid_event_probability("ワイド",(1,2),s)-1)<1e-9
    print("SIX_MARKET_CORRECT_PL_EVENT_PROBABILITY_OK",flush=True)

def all_event_probabilities(races,model,metadata,offsets,ix,ids,tickets,alpha):
    event=np.zeros(len(ids),dtype=np.float32)
    joined=0
    for rid,r in enumerate(races):
        s,good=normalized_strengths(r,model,metadata,offsets,ix,alpha)
        joined+=int(good)
        a=int(np.searchsorted(ids,rid,'left'))
        b=int(np.searchsorted(ids,rid,'right'))
        if b-a!=206:raise RuntimeError("SIX_MARKET_NO_INDEPENDENT_ENUMERATION")
        # Exact same deterministic tuple order as the six-market payout source.
        for j in range(a,b):
            typ,combo=tickets[j]
            event[j]=paid_event_probability(typ,combo,s)
    if joined<len(races)*.75:
        raise RuntimeError(f"TOO_MANY_SOURCE_RACES_CANNOT_JOIN_PRE_RESULT_ARCHIVE:{joined}/{len(races)}")
    return event,joined

def by_race_market_best(races,ids,mtypes,all_y,tickets,score):
    market_best=[]
    for rid,r in enumerate(races):
        a=int(np.searchsorted(ids,rid,'left'))
        b=int(np.searchsorted(ids,rid,'right'))
        ss=score[a:b]
        types=mtypes[a:b]
        this=[]
        for m in range(6):
            available=np.flatnonzero(types==m)
            ix=int(available[np.argmax(ss[available])])+a
            this.append((float(score[ix]),int(all_y[ix]),tickets[ix][1]))
        market_best.append(this)
    return market_best

def pick_two(candidates,pair,overlap):
    pairs=PAIR_IDS if pair<0 else (PAIR_IDS[pair],)
    winner=None
    for a,b in pairs:
        ca,cb=candidates[a],candidates[b]
        penalty=(1-overlap*len(set(ca[2]).intersection(cb[2]))/3)
        val=(ca[0]+cb[0])*penalty
        k=(val,-a,-b,a,b,ca[1],cb[1])
        if winner is None or k[:3]>winner[:3]:winner=k
    return winner

def settle(races,best,period,pair,overlap):
    groups=defaultdict(list)
    start,end=period
    for i,r in enumerate(races):
        if not start<=r["month"]<end:continue
        val,_,__,a,b,paid1,paid2=pick_two(best[i],pair,overlap)
        groups[r["day"]].append((val,r["id"],r["month"],a,b,paid1,paid2))
    rows=[];missed=0
    for day,rs in groups.items():
        if len(rs)<5:
            missed+=1
            continue
        rs.sort(key=lambda p:(-p[0],p[1]))
        rows.extend(rs[:5])
    return rows,missed,len(groups)

def accounting(rows,missing,days):
    stake=len(rows)*2000
    pays=[(r[5]+r[6])*10 for r in rows]
    total=sum(pays)
    single=max((x*10 for r in rows for x in (r[5],r[6])),default=0)
    bymonth=defaultdict(lambda:[0,0,0])
    for r,p in zip(rows,pays):
        entry=bymonth[r[2]]
        entry[0]+=1;entry[1]+=p;entry[2]+=int(p>0)
    return {"races":len(rows),"stakeYen":stake,"payoutYen":total,
      "profitYen":total-stake,"roiPct":round(total*100/stake,5) if stake else None,
      "roiNoLargestTicketPct":round((total-single)*100/stake,5) if stake else None,
      "roiNoLargestRacePct":round((total-max(pays))*100/stake,5) if stake else None,
      "paidRacePct":round(sum(p>0 for p in pays)*100/len(rows),4) if rows else None,
      "eligibleVenueDays":days,"missingVenueDays":missing,
      "byMonth":{k:{"races":v[0],"roi":round(100*v[1]/(v[0]*2000),4),
          "hitPct":round(100*v[2]/v[0],4)} for k,v in sorted(bymonth.items())},
      "numericallyPass200":bool(stake and len(rows)>=100 and
         total>=2*stake and total-single>=2*stake and
         total-max(pays)>=2*stake)}

@dataclass(frozen=True)
class MoneyPolicy:
    alpha:float
    conditional_power:float
    tail_risk:float
    pair:int
    overlap:float

def evaluate_model(races,X,y,ids,mtypes,tickets,archive,offsets,ix,
                   horse_X,horse_labels,train_horse_meta,horse_cutoff,amount_cutoff,
                   policy=None):
    odds_prediction,horse_fit=fit_pre_result_horse(
        horse_X,horse_labels,train_horse_meta,offsets,horse_cutoff)
    amount,amount_fit=fit_paid_amount(X,y,mtypes,ids,races,amount_cutoff)
    options=([(policy.alpha,policy.conditional_power,policy.tail_risk)]
             if policy else list(product((0.,.3,.6,1.),(.6,.85,1.),(0.,.3))))
    outcomes={}
    all_join={}
    for alpha in sorted(set(x[0] for x in options)):
        ev,joined=all_event_probabilities(races,odds_prediction,
                       archive,offsets,ix,ids,tickets,alpha)
        all_join[alpha]=joined
        # Prediction is expected CASH RETURN per ¥100, not horse win ranking.
        for a,power,risk in options:
            if a!=alpha:continue
            if risk:
                score=ev*amount**power/(
                    1+risk*np.maximum(0,np.log1p(amount/1000)))
            else:
                score=ev*amount**power
            outcomes[(a,power,risk)]=by_race_market_best(
                races,ids,mtypes,y,tickets,score)
    return outcomes,{"horseFit":horse_fit,"conditionalPayoutFit":amount_fit,
                     "archiveRaceJoinCounts":all_join}

def main():
    if "--self-test" in sys.argv:pay_event_fixture();return
    started=time.monotonic()
    pay_event_fixture()
    base=load("scripts/research-nov2026-sixmarket-real-paid-cash.py","pl_paid_jra_source")
    races,audit=base.read_pinned_csv()
    cash_X,paid_y,ids,mtypes,tickets,_=base.build_actual_payout_rows(races)
    source_names=read_source_horse_names()
    horse_X,horse_label,off,meta,archive_names,missing=historical_horse_features()
    lookup=join_pre_result_races_by_horse_identity(races,meta,archive_names,source_names)
    print("PL_DATA_JOIN",json.dumps({"sourceRaces":len(races),
      "candidateTickets":len(paid_y),"paidTickets":int((paid_y>0).sum()),
      "historicalHorseRaces":len(meta)},ensure_ascii=False),flush=True)
    options,fit25=evaluate_model(races,cash_X,paid_y,ids,mtypes,tickets,
        meta,off,lookup,horse_X,horse_label,meta,2024,2024)
    chosen=None
    tested=0
    for (alpha,power,risk),candidates in options.items():
        for pair,overlap in product((-1,)+tuple(range(15)),(0.,.35)):
            policy=MoneyPolicy(alpha,power,risk,pair,overlap)
            rows,missed,days=settle(races,candidates,("202501","202507"),
                                   pair,overlap)
            met=accounting(rows,missed,days)
            tested+=1
            if met["races"]<250 or met["missingVenueDays"]:continue
            rank=(met["roiNoLargestRacePct"],met["roiPct"],met["paidRacePct"])
            if chosen is None or rank>chosen[0]:chosen=(rank,policy,met)
    if chosen is None:raise RuntimeError("NO_SIX_MARKET_MODEL_WITH_FIVE_RACES_PER_VENUE_DAY")
    _,policy,h1=chosen
    print("PL_CASH_2025_H1_POLICY",json.dumps({"policy":asdict(policy),
          "money":h1,"tested":tested},ensure_ascii=False),flush=True)
    k=(policy.alpha,policy.conditional_power,policy.tail_risk)
    a=options[k]
    rows,missed,days=settle(races,a,("202507","202601"),
                             policy.pair,policy.overlap)
    h2=accounting(rows,missed,days)
    print("PL_CASH_2025_H2_HOLDOUT",json.dumps(h2,ensure_ascii=False),flush=True)
    options26,fit26=evaluate_model(races,cash_X,paid_y,ids,mtypes,tickets,
        meta,off,lookup,horse_X,horse_label,meta,2025,2025,policy)
    b=options26[k]
    rows,missed,days=settle(races,b,("202601","202604"),
                             policy.pair,policy.overlap)
    h26=accounting(rows,missed,days)
    print("PL_CASH_2026_FROZEN_TEST",json.dumps(h26,ensure_ascii=False),flush=True)
    result={"algorithm":"56 chronological horse features + normalized horse-market power blend + exact six-market Plackett-Luce joint events + conditional paid-yen LightGBM",
      "candidateCount":int(len(paid_y)),
      "oldModelSelectedBetsUsed":False,"top1OrLoglossOptimized":False,
      "policyCandidatesExamined":tested,"2024Fitting":fit25,
      "selectedBy2025H1":asdict(policy),"2025H1":h1,"2025H2":h2,
      "2026ModelRefit":fit26,"2026JanMar":h26,
      "fullSixMarketDistinctPairCoverage":True,
      "requiresActualPreT15OfficialCombinationOddsBeforeProduction":True,
      "thirdPartyJraPayoutMirrorNotVerified":True,
      "2026PreviouslyInspectedIsNotUntouched":True,
      "accepted":False,"productionChanged":False,
      "elapsedSeconds":round(time.monotonic()-started,2)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("PL_SIX_MARKET_ROI_MODEL_EVALUATED",str(OUT),flush=True)

if __name__=="__main__":main()
