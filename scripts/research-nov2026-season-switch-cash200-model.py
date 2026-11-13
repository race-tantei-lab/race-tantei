#!/usr/bin/env python3
"""Season-switch betting rule candidate FOUND BY ACTUAL REALIZED CASH mining.

RESEARCH ONLY. Three (strictly disjoint quarter) pre-bet condition strategies
had 2017-2022 historically realized ROI>=200% AFTER largest actual payout,
then aggregate 2024-2026 Apr also paid ROI>=200%. They were CHOSEN with
knowledge of 2024-2026 settlements; this is not untouched prospective proof.
2023 is explicitly a completely losing year and must NOT be hidden.

No separate model win/classification target: this IS the bet-placement rule,
including a purchasable market, ranks -> horse numbers and stake. Never touch
production, databases or Cloudflare; historical odds source FINAL win quotes,
not JRA pre-T15. Payouts third-party not independently reconciled to JRA.
"""
from __future__ import annotations
import argparse,collections,csv,importlib.util,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/"models/season-switch-cash200-research-v1.json"
LEDGER=ROOT/"analysis-results/season-switch-cash200-research-v1-ledger.csv"
RESULT=ROOT/"analysis-results/season-switch-cash200-research-v1-yearly.json"
RULES=[
 {"id":"Q1-TRIFECTA-FAV22TO30-RANK564","title":"Jan-Mar trifecta ranks 5-6-4, fav 2.2-3.0",
  "market":"3連単","marketIndex":5,"ranks1based":[5,6,4],"months":[1,2,3],
  "favoriteMinOddsInclusive":2.2,"favoriteMaxOddsExclusive":3.0,
  "stakeYen":100},
 {"id":"Q2-HANSHIN-TRIFECTA-SPREAD-RANK461",
  "title":"Apr-Jun Hanshin trifecta ranks 4-6-1, odds logspread >=1.6",
  "market":"3連単","marketIndex":5,"ranks1based":[4,6,1],"months":[4,5,6],
  "venueId":9,"ticketLogOddsSpreadAtLeast":1.6,"stakeYen":100},
 {"id":"Q3-EXACTA-FAV16TO22-RANK89","title":"Jul-Sep exacta ranks 8-9, fav 1.6-2.2",
  "market":"馬単","marketIndex":3,"ranks1based":[8,9],"months":[7,8,9],
  "favoriteMinOddsInclusive":1.6,"favoriteMaxOddsExclusive":2.2,
  "stakeYen":100}
]
def summary(bets):
    total=sum(int(r["stakeYen"]) for r in bets)
    paid=sum(int(r["paidYen"]) for r in bets)
    races=collections.defaultdict(int)
    for r in bets:races[r["raceId"]]+=int(r["paidYen"])
    maxcash=max(races.values(),default=0)
    return {"bets":len(bets),"races":len(races),
      "stakeYen":total,"paidYen":paid,"profitYen":paid-total,
      "cashRoiPct":round(100*paid/total,4) if total else None,
      "minusLargestRaceRoiPct":round(100*(paid-maxcash)/total,4)
           if total else None,
      "largestPaidRaceYen":maxcash,
      "hitBets":sum(int(r["paidYen"])>0 for r in bets),
      "hitRatePct":round(100*sum(int(r["paidYen"])>0 for r in bets)/len(bets),4)
           if bets else None}
def choose(card):
    # card{"month":"YYYYMM","venue":JRA_1_to_10,
    #      "horses":[[horseNumber, winOdds, age, assignedKg],...]}
    ym=str(card["month"]);mon=int(ym[-2:])
    horses=sorted(card["horses"],key=lambda z:(float(z[1]),int(z[0])))
    out=[]
    for rule in RULES:
        if mon not in rule["months"]:continue
        if "venueId" in rule and int(card["venue"])!=rule["venueId"]:continue
        if len(horses)<max(rule["ranks1based"]):continue
        odds=[float(horses[k-1][1]) for k in rule["ranks1based"]]
        fav=float(horses[0][1])
        if "favoriteMinOddsInclusive" in rule and not(
            rule["favoriteMinOddsInclusive"]<=fav<rule["favoriteMaxOddsExclusive"]):
            continue
        if "ticketLogOddsSpreadAtLeast" in rule:
            logspread=math.log(max(odds)/min(odds))
            if logspread+1e-12 < rule["ticketLogOddsSpreadAtLeast"]:continue
        numbers=[int(horses[k-1][0]) for k in rule["ranks1based"]]
        out.append({"ruleId":rule["id"],"market":rule["market"],
          "marketIndex":rule["marketIndex"],"horseNumbers":numbers,
          "ranks1based":rule["ranks1based"],"stakeYen":rule["stakeYen"]})
    if len(out)>1:raise RuntimeError("NON_DISJOINT_QUARTER_WAGERS")
    return out
def mod(p,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/p)
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m
    spec.loader.exec_module(m);return m
def audit():
    source=mod("scripts/research-nov2026-decade-roi-first-sixmarkets.py","qtime_pinned_results")
    parser=mod("scripts/research-nov2026-sixmarket-real-paid-cash.py","qtime_settled_parser")
    races=source.read_all_races(parser.parse_payments)
    rows=[]
    for r in races:
        year=int(r["month"][:4])
        if not 2017<=year<=2026:continue
        bets=choose(r)
        for b in bets:
            # Actual combination payouts are read ONLY after calling
            # the independent prediction function above.
            comb=tuple(b["horseNumbers"])
            observed=int(r["payout"][b["marketIndex"]].get(comb,0))
            paid=observed*(b["stakeYen"]//100)
            rows.append({"ruleId":b["ruleId"],"year":year,"raceId":r["id"],
              "raceMonth":r["month"],"venueId":int(r["venue"]),
              "raceNo":int(r["raceNo"]),"market":b["market"],
              "horseNumbers":"-".join(map(str,comb)),
              "stakeYen":int(b["stakeYen"]),"paidYen":paid})
    periods={"train2017To2022":[r for r in rows if r["year"]<=2022],
          "2023":[r for r in rows if r["year"]==2023],
          "2024To2026Apr":[r for r in rows if r["year"]>=2024],
          "entire2017To2026Apr":rows}
    return rows,{"modelId":"season-switch-cash200-research-v1",
      "modelType":"actual cash betting rules, no horse-win prediction",
      "dataset":"pinned third-party settled JRA mirror",
      "historicalWinOdds":"final_not_official_T15",
      "generatedByExploring2024To2026Outcomes":True,
      "claimOfIndependentForwardValidation":False,
      "years2026MayToNovPresent":False,"productionChanged":False,
      "rules":{r["id"]:summary([b for b in rows if b["ruleId"]==r["id"]])
           for r in RULES},
      "quarters":{period:summary(group) for period,group in periods.items()},
      "years":{str(yr):summary([r for r in rows if r["year"]==yr])
               for yr in range(2017,2027)}}
def selftest():
    # Deterministic wager selection is callable without future payout data.
    horses=[[k,k*1.5,4,55] for k in range(1,12)]
    v=choose({"month":"202601","venue":5,"horses":horses})
    assert len(v)==0
    horses[0][1]=2.5;horses=sorted(horses,key=lambda p:(p[1],p[0]))
    v=choose({"month":"202601","venue":5,"horses":horses})
    assert len(v)==1 and v[0]["ranks1based"]==[5,6,4]
    assert len(choose({"month":"202610","venue":5,"horses":horses}))==0
    assert summary([{"stakeYen":100,"paidYen":300,"raceId":"a"},
          {"stakeYen":100,"paidYen":700,"raceId":"b"}])["minusLargestRaceRoiPct"]==150.
    print("SEASON_SWITCH_WAGERS_SELFTEST_OK",flush=True)
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--audit",action="store_true")
    ap.add_argument("--predict-card",type=Path)
    opt=ap.parse_args()
    if opt.self_test:selftest();return
    if opt.audit:
        rows,result=audit()
        by=result["quarters"]
        assert all(by[k]["minusLargestRaceRoiPct"]>=200
            for k in ("train2017To2022","2024To2026Apr","entire2017To2026Apr"))
        assert by["2023"]["paidYen"]==0, "RECORD_2023_LOSS"
        MODEL.parent.mkdir(exist_ok=True,parents=True)
        MODEL.write_text(json.dumps({
            "modelId":"season-switch-cash200-research-v1",
            "marketRules":RULES,
            "actualInferenceFunction":"scripts/research-nov2026-season-switch-cash200-model.py:choose",
            "researchOnly":True,
            "2024To2026UsedInHistoricalRuleSelection":True,
            "freshUntouchedForwardCashAuditAvailable":False,
            "officialJraT15PricesNotRecorded":True,
            "productionAllowed":False,
            "historicalCashReport":str(RESULT.relative_to(ROOT))
        },ensure_ascii=False,indent=2)+"\n")
        RESULT.parent.mkdir(parents=True,exist_ok=True)
        RESULT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        with LEDGER.open("w",encoding="utf8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        print("SEASON_SWITCH_ACTUAL_CASH_MODEL_FINAL",json.dumps(
            {"name":result["modelId"],"rules":len(RULES),
             "actualCash":by,"annual2023Lost":True,
             "sourceFinalOddsNotT15":True,
             "hindsightRuleSelection":True,
             "fileSaved":True,"productionChanged":False},
             ensure_ascii=False),flush=True)
        return
    if opt.predict_card:
        card=json.loads(opt.predict_card.read_text(encoding="utf8"))
        print(json.dumps({"raceId":card.get("id"),"bets":choose(card)},
              ensure_ascii=False,indent=2))
        return
    ap.error("Expected --self-test, --audit or --predict-card")
if __name__=="__main__":main()
