#!/usr/bin/env python3
"""Non-promotable chronological 3/4/5-race, TWO-DISTINCT-ticket hit research.

Asks the opposite of high-jackpot single-win retrospective searches:
for each venue/day, can a locked ranked pair of ticket types cover most
races? No race selection from the result; never fewer than 3 per venue/day.
Payout ROI is intentionally NOT computed because official T-15 two-type
odds were not archived. Archived FINAL win odds as market signal are
post-race and can NOT certify live deployability.

Fits exactly the unchanged 56-feature LightGBM to years preceding 2024,
2025, and 2026 separately, with same-day leakage protection provided by
the canonical chronological features. This is *research*, not promotion.
"""
from __future__ import annotations
import collections
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"scripts/research-chronological-56feature-validation.py"
OUT=ROOT/"analysis-results/research-three-to-five-two-type-hit-oos-20261107.json"
MIN_RACES=3
PREFERRED_RACES=5
KS=(3,4,5)
YEAR_RANGE=("2024","2025","2026")
# Two *different* authorized ticket types, exactly one bet each.
TICKETS={
    "WIN1_WIDE12":(("単勝",(0,)),("ワイド",(0,1))),
    "WIN1_WIDE13":(("単勝",(0,)),("ワイド",(0,2))),
    "WIN1_WIDE23":(("単勝",(0,)),("ワイド",(1,2))),
    "WIN2_WIDE12":(("単勝",(1,)),("ワイド",(0,1))),
    "WIN1_QUINELLA12":(("単勝",(0,)),("馬連",(0,1))),
    "WIDE12_QUINELLA12":(("ワイド",(0,1)),("馬連",(0,1))),
    "WIDE12_TRIO123":(("ワイド",(0,1)),("3連複",(0,1,2))),
    "WIDE12_EXACTA12":(("ワイド",(0,1)),("馬単",(0,1))),
    "WIDE13_QUINELLA12":(("ワイド",(0,2)),("馬連",(0,1))),
    "WIDE23_QUINELLA12":(("ワイド",(1,2)),("馬連",(0,1))),
}
SOURCES={"model":1.0,"market_historical_final":0.0,
         "blend_model30_market70":0.3,"blend_model50_market50":0.5,
         "blend_model70_market30":0.7}
RANKINGS=("top1_prob","top2_mass","top3_mass","top2_product","top1_gap")

def base_module():
    spec=importlib.util.spec_from_file_location("frozen_oos_core",BASE)
    if not spec or not spec.loader:raise RuntimeError("MISSING_CHRONOLOGICAL_MODEL")
    m=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=m
    spec.loader.exec_module(m)
    return m

def settled_meta(by_date):
    """Exactly the same eligible race sequence as canonical chronological_features."""
    meta=[]
    for day in sorted(by_date):
        for b in by_date[day]:
            active=sorted((r for r in b["runners"] if r.get("runnerStatus")
                           in (None,"","active")),key=lambda r:int(r["horseNo"]))
            if len(active)<3:continue
            positions={x["horseNo"]:x.get("finishPosition") for x in b["results"]}
            winners=[i for i,r in enumerate(active) if positions.get(r["horseNo"])==1]
            if len(winners)!=1:continue
            meta.append({"date":day,"venue":str(b["race"]["venue"]),
                "raceNo":int(b["race"]["raceNo"]),"field":len(active),
                "finish":tuple(positions.get(r["horseNo"]) for r in active)})
    return meta

def hit(typ,ranking,finish):
    pos=tuple(finish[ranking[index]] for index in ranking[1]) if False else None
    raise RuntimeError("UNREACHABLE")

def ticket_hit(ticket,order,positions):
    typ,idx=ticket
    nums=tuple(positions[order[i]] for i in idx)
    if typ=="単勝":return nums==(1,)
    if typ=="ワイド":return len(nums)==2 and all(isinstance(p,int) and 1<=p<=3 for p in nums)
    if typ=="馬連":return set(nums)=={1,2}
    if typ=="馬単":return nums==(1,2)
    if typ=="3連複":return set(nums)=={1,2,3}
    if typ=="3連単":return nums==(1,2,3)
    raise ValueError("UNKNOWN_BET_TYPE")

def race_ranking_score(p,kind):
    if kind=="top1_prob":return float(p[0])
    if kind=="top2_mass":return float(p[0]+p[1])
    if kind=="top3_mass":return float(p[0]+p[1]+p[2])
    if kind=="top2_product":return float(p[0]*p[1])
    if kind=="top1_gap":return float(p[0]-p[1])
    raise ValueError(kind)

def make_records(base,features,years_meta,counts,offsets,dates,odds,year):
    train=np.where(dates<year+"-01-01")[0]
    target=np.where((dates>=year+"-01-01")&(dates<str(int(year)+1)+"-01-01"))[0]
    if len(train)<8000 or len(target)<700:
        raise RuntimeError("INSUFFICIENT_DATE_SEPARATED_SAMPLE:"+year)
    if str(dates[train[-1]])>=year+"-01-01":
        raise AssertionError("TRAINING_TARGET_LEAKAGE")
    model=base.fit(features,base.LABELS if False else _labels_ref,
                   offsets,train,base.CANDIDATES["adopted_complexity_500x127"])
    start=int(offsets[target[0]])
    probs=model.predict_proba(features[start:int(offsets[target[-1]+1])])[:,1]
    out=collections.defaultdict(list)
    dropped=collections.Counter()
    for i in target:
        m=years_meta[i]
        if m["field"]<8:
            dropped["field_under_8_wide_ineligible"]+=1
            continue
        a,b=int(offsets[i])-start,int(offsets[i+1])-start
        pp=np.maximum(probs[a:b],1e-14)
        pp/=pp.sum()
        oo=odds[i]
        if len(oo)!=len(pp) or not all(isinstance(o,(float,int)) and math.isfinite(o) and o>1 for o in oo):
            dropped["archived_final_market_odds_missing"]+=1
            # Drop cannot be hidden as complete days: candidate universes
            # are diagnostics, not a certifiable production record.
            continue
        q=1/np.asarray(oo,dtype=float)
        q/=q.sum()
        pair_hits={}
        pre_scores={}
        for source,model_fraction in SOURCES.items():
            mix=model_fraction*pp+(1-model_fraction)*q
            order=tuple(int(x) for x in np.argsort(-mix,kind="stable"))
            if len(order)<3:continue
            p_sorted=tuple(float(mix[x]) for x in order)
            pre_scores[source]={k:race_ranking_score(p_sorted,k) for k in RANKINGS}
            pair_hits[source]={name:(int(ticket_hit(pair[0],order,m["finish"])),
                                    int(ticket_hit(pair[1],order,m["finish"])))
                               for name,pair in TICKETS.items()}
        out[(m["date"],m["venue"])].append({
            "raceNo":m["raceNo"],"preScores":pre_scores,"hits":pair_hits})
    del model,probs
    return out,dict(dropped),int(len(target))

def score_fixed(groups,source,pair,ranking,k):
    if k not in KS:raise AssertionError("INVALID_LESS_THAN_3_RACES")
    count=hits=both=tickets_hit=all_hit_days=zero_hit_days=mostly_hit_days=0
    venue_days=0
    for group,rows in groups.items():
        if len(rows)<k:continue
        chosen=sorted(rows,key=lambda x:(-x["preScores"][source][ranking],x["raceNo"]))[:k]
        state=[x["hits"][source][pair] for x in chosen]
        race_hits=[any(v) for v in state]
        count+=len(state)
        venue_days+=1
        hits+=sum(race_hits)
        both+=sum(all(v) for v in state)
        tickets_hit+=sum(sum(v) for v in state)
        all_hit_days+=int(all(race_hits))
        zero_hit_days+=int(not any(race_hits))
        mostly_hit_days+=int(sum(race_hits)>=math.ceil(0.8*k))
    return {"venueDays":venue_days,"races":count,
        "hitRaces":hits,"hitRacePct":round(100*hits/count,2) if count else None,
        "winningTickets":tickets_hit,"hitTicketPct":round(100*tickets_hit/(2*count),2) if count else None,
        "bothTicketsHitRaces":both,"allRacesHitVenueDays":all_hit_days,
        "allRacesHitVenueDayPct":round(100*all_hit_days/venue_days,2) if venue_days else None,
        "noRacesHitVenueDays":zero_hit_days,
        "atLeast80PctHitVenueDays":mostly_hit_days}

def selftest():
    assert KS==(3,4,5) and MIN_RACES==3 and PREFERRED_RACES==5
    assert all(len(v)==2 and v[0][0]!=v[1][0] for v in TICKETS.values())
    pos=(1,3,2,4,5,6,7,8,9)
    order=tuple(range(len(pos)))
    assert ticket_hit(("単勝",(0,)),order,pos)
    assert ticket_hit(("ワイド",(0,1)),order,pos)
    assert ticket_hit(("馬連",(0,2)),order,pos)
    assert not ticket_hit(("馬単",(0,1)),order,pos)
    assert ticket_hit(("3連複",(0,1,2)),order,pos)
    assert not ticket_hit(("3連単",(0,1,2)),order,pos)
    sample={}
    for i in range(5):
        sample[("2024-06-01","東京")]=sample.get(("2024-06-01","東京"),[])+[
          {"raceNo":i+1,"preScores":{"model":{"top1_prob":0.6-i*0.05}},
           "hits":{"model":{"WIN1_WIDE12":(1 if i<3 else 0,0)}}}]
    summary=score_fixed(sample,"model","WIN1_WIDE12","top1_prob",3)
    assert summary["hitRacePct"]==100 and summary["allRacesHitVenueDays"]==1
    assert score_fixed(sample,"model","WIN1_WIDE12","top1_prob",5)["hitRacePct"]==60.0
    print("HIGH_HIT_3_TO_5_TWO_DISTINCT_TICKET_SELFTEST_OK",flush=True)

def main():
    if "--self-test" in sys.argv:
        selftest();return
    began=time.monotonic()
    base=base_module()
    core=base.core_module()
    arc=base.load_public_archive()
    by_date=base.load_bundles(arc)
    X,y,counts,dates,offsets,winners,dropped,total,odds=base.chronological_features(core,by_date)
    meta=settled_meta(by_date)
    if len(meta)!=len(counts) or any(meta[i]["date"]!=str(dates[i])
                                   or meta[i]["field"]!=counts[i] for i in range(len(meta))):
        raise AssertionError("RACE_ORDER_OR_COUNT_PROVENANCE_MISMATCH")
    global _labels_ref
    _labels_ref=y
    years={}
    specs=[(src,pair,rank) for src in SOURCES for pair in TICKETS for rank in RANKINGS]
    for year in YEAR_RANGE:
        groups,missing,n=make_records(base,X,meta,counts,offsets,dates,odds,year)
        score={(src,pair,rank,k):score_fixed(groups,src,pair,rank,k)
               for src,pair,rank in specs for k in KS}
        years[year]={"scores":score,"missing":missing,"targetRaceCount":n,
                     "availableVenueDays":len(groups)}
        print("HIGH_HIT_YEAR_DONE",json.dumps({"year":year,"modelHeldoutRaces":n,
            "venueDays":len(groups),"missing":missing}),flush=True)
    def s(y,key):return years[y]["scores"][key]
    # Discover on 2024 only, with a hard preference for 5 races.
    pool=[(src,pair,rank,5) for src,pair,rank in specs]
    selected=sorted(pool,key=lambda spec:(
        -(s("2024",spec)["hitRacePct"] or 0),
        -(s("2024",spec)["hitTicketPct"] or 0),
        -s("2024",spec)["venueDays"],spec))[:20]
    def series(key):
        return {"strategy":{"signal":key[0],"twoTypes":key[1],
                "raceRanking":key[2],"racesPerVenueDay":key[3]},
            "years":{y:s(y,key) for y in YEAR_RANGE}}
    follow3=[(src,pair,rank,3) for src,pair,rank,_ in selected]
    follow4=[(src,pair,rank,4) for src,pair,rank,_ in selected]
    output={"status":"RESEARCH_ONLY_NO_TWO_TYPE_T15_ODDS_NO_ROI",
      "goal":"maximize high-confidence actual hit races, never one jackpot",
      "minimumVenueRaces":3,"preferFiveRaces":True,
      "ticketTypesPerRace":2,
      "frozen2024FiveRaceShortlist":[series(key) for key in selected],
      "samePoliciesAtThreeRaces":[series(key) for key in follow3],
      "samePoliciesAtFourRaces":[series(key) for key in follow4],
      "yearSourceCoverage":{year:{"modelTestRaces":v["targetRaceCount"],
        "availableVenueDays":v["availableVenueDays"],"dropped":v["missing"]}
        for year,v in years.items()},
      "exploredPatterns":len(specs)*len(KS),
      "selectionYear2024AlreadyInspected":True,
      "validationYear2025UsedOnlyForMeasurement":True,
      "year2026PreviouslyInspectedNotPristineHoldout":True,
      "officialT15QuoteProvenance":False,
      "allBetsUseDistinctTypes":True,
      "profitRoiPct":None,
      "deploymentEligible":False,
      "warnings":["Historical postrace-final win odds were used for market-based ranks",
        "Only strike rates can be measured; there are no full historical T15 six-market odds or exact two-ticket payouts",
        "Some races are excluded for missing archived odds or runner results; blocked days cannot certify complete live coverage",
        "No post-hoc strategy may be promoted based on 2025/26 transfer after those years were inspected",
        "Race selections are chronological research proxies, not frozen actual Worker decisions"],
      "elapsedSeconds":round(time.monotonic()-began,1)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("HIGH_HIT_3_TO_5_TWO_TYPE_OOF_RESULT",json.dumps({
      "patterns":len(specs)*len(KS),"bestFiveRacesBy2024":output["frozen2024FiveRaceShortlist"][:3],
      "theirThreeRaceVersions":output["samePoliciesAtThreeRaces"][:3],
      "sourceCoverage":output["yearSourceCoverage"],
      "productionEligible":False,"elapsedSeconds":output["elapsedSeconds"]},ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
