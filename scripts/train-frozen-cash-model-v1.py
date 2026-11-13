#!/usr/bin/env python3
"""Cash Bet Model v1: an actual frozen, callable betting inference model.

NO adoption gates: always freeze the learned parameters and emit actionable
horse-number tickets. Training target: actual JPY paid for a 100 JPY
specific-market bet. Source: pinned third-party JRA settled-results mirror.
Training: 2017-2022 inclusive. Chronological evaluation: 2023-2026 Apr.

Only race card + odds-ranked horse numbers, win quotes, venue, date, field
size and program number enter model inference. Past after-race FINAL win odds
are a proxy, NOT official T-minus-15 quote history. No real-money ROI is
claimed and production is not changed by this experimental model.
"""
from __future__ import annotations
import argparse,collections,csv,datetime,importlib.util,json,math,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/"models/cash-bet-model-v1.json"
EVAL=ROOT/"analysis-results/cash-bet-model-v1-evaluation.json"
LEDGER=ROOT/"analysis-results/cash-bet-model-v1-settled-bets.csv"
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")
UNORDERED={1,2,4}
# Horse slots are 0-indexed by ascending WIN odds, before the race.
SLOTS=(
    ((0,),(1,),(2,)),
    ((0,1),(0,2),(1,2),(0,3),(1,3),(2,3)),
    ((0,1),(0,2),(1,2),(0,3),(1,3),(2,3)),
    ((0,1),(1,0),(0,2),(2,0),(1,2),(2,1)),
    ((0,1,2),(0,1,3),(0,2,3),(1,2,3)),
    ((0,1,2),(0,2,1),(1,0,2),(1,2,0),(2,0,1),(2,1,0)),
)
ACTIONS=[{"market":m,"ranks":list(s),"key":str(m)+":"+"-".join(map(str,s))}
         for m,v in enumerate(SLOTS) for s in v]
assert len(ACTIONS)==31
PANEL_NAMES=("all","fav","field","quarter","venue","program")
MIN_HORSES=4

def mod(file,name):
    path=ROOT/file
    spec=importlib.util.spec_from_file_location(name,path)
    out=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=out;spec.loader.exec_module(out);return out

def band(x):
    for i,edge in enumerate((2.,3.,5.,8.)):
        if x<edge:return i
    return 4

def ctx(r):
    # Model can be called before the race on current official WIN quotes.
    horses=sorted(r["horses"],key=lambda h:(float(h[1]),int(h[0])))
    if len(horses)<MIN_HORSES:raise ValueError("NEED_FOUR_RUNNERS")
    favourite=float(horses[0][1])
    venue=int(r["venue"])
    no=int(r["raceNo"])
    month=int(r["month"][4:6])
    if not(1<=venue<=10 and 1<=no<=12 and 1<=month<=12):
        raise ValueError("INVALID_JRA_CARD")
    return horses,{"all":"0","fav":str(band(favourite)),
            "field":str(int(len(horses)>=14)),
            "quarter":str((month-1)//3),
            "venue":str(venue),
            "program":str((no-1)//4)}

def ticket(horses,act):
    raw=tuple(int(horses[k][0]) for k in act["ranks"])
    return tuple(sorted(raw)) if act["market"] in UNORDERED else raw

def update(b,x):
    b["n"]+=1
    b["paid"]+=int(x)
    b["hits"]+=int(x>0)
    b["maxPaid"]=max(b["maxPaid"],int(x))

def fresh():
    return {"n":0,"paid":0,"hits":0,"maxPaid":0}

def fit(races):
    # No post-race feature enters the grouping. Money is solely a label.
    lookup={}
    train=collections.Counter()
    for r in races:
        year=int(r["month"][:4])
        if year<2017 or year>2022:continue
        horses,context=ctx(r)
        train[year]+=1
        for a in ACTIONS:
            paid=int(r["payout"][a["market"]].get(ticket(horses,a),0))
            for name,key in context.items():
                k=(a["key"],name,key)
                if k not in lookup:lookup[k]=fresh()
                update(lookup[k],paid)
    if min((train[y] for y in range(2017,2023)),default=0)<2000:
        raise ValueError("TRAINING_YEAR_NOT_COMPLETE")
    # Freeze all empirical cash sums, paid-event counts, largest payouts.
    # Conditional panels use hierarchical shrinkage toward unconditional
    # action mean. Payout amount is monetary yen, NEVER a win-probability.
    frozen={}
    for a in ACTIONS:
        frozen[a["key"]]={}
        for k,s in lookup.items():
            if k[0]==a["key"]:
                frozen[a["key"]][k[1]+":"+k[2]]=s
    return {"modelId":"cash-bet-baseline-v1",
        "trainedOn":"actual JPY paid for 100 yen per specific betting ticket",
        "trainYears":[2017,2018,2019,2020,2021,2022],
        "trainRaceCounts":{str(k):v for k,v in sorted(train.items())},
        "dataSource":"third_party_settled_JRA_mirror",
        "historicalWinOdds":"FINAL_NOT_T_MINUS_15",
        "returnUnit":"100_JPY_ticket",
        "unconditionalModelFreeze":True,
        "modelsCanBeRejectedByProfitGate":False,
        "actions":ACTIONS,
        "params":{"priorContextRaces":280,
                  "cashScoreFloorYen":1,
                  "maxOnePayoutBlend":0.75,
                  "perRaceMarkets":2,
                  "stakePerTicketYen":100,
                  "racesPerVenueDay":3},
        "panels":frozen}

def panel_score(s,base,prior,trim):
    n=s["n"]
    if not n:return float(base)
    # Mean JPY paid per 100 yen; largest payout is damped to reduce
    # a one-jackpot policy from taking over the entire model.
    retained=s["paid"]-(1-trim)*s["maxPaid"]
    return (retained+prior*base)/(n+prior)

def action_score(model,action,context):
    p=model["params"]
    panel=model["panels"][action["key"]]
    global_ =panel["all:0"]
    base=panel_score(global_,75.,250,p["maxOnePayoutBlend"])
    # Fully frozen, pre-declared blend, NOT a search on test results.
    signals={"fav":.3,"field":.2,"quarter":.15,"venue":.25,"program":.1}
    means=[]
    for name,weight in signals.items():
        s=panel.get(name+":"+context[name])
        pred=panel_score(s,base,p["priorContextRaces"],p["maxOnePayoutBlend"]) if s else base
        means.append(weight*pred)
    score=0.4*base+0.6*sum(means)
    return max(float(p["cashScoreFloorYen"]),float(score))

def predict_one(model,card):
    horses,context=ctx(card)
    by_market={}
    for a in model["actions"]:
        score=action_score(model,a,context)
        bet={"market":MARKETS[a["market"]],"marketIndex":a["market"],
            "horseNumbers":list(ticket(horses,a)),
            "horseRankSlots":[x+1 for x in a["ranks"]],
            "stakeYen":int(model["params"]["stakePerTicketYen"]),
            "historicalModelMoneyScoreYenPer100":round(score,4),
            "actionKey":a["key"]}
        m=a["market"]
        if m not in by_market or score>by_market[m]["historicalModelMoneyScoreYenPer100"]:
            by_market[m]=bet
    ordered=sorted(by_market.values(),key=lambda x:(
        -x["historicalModelMoneyScoreYenPer100"],x["marketIndex"]))
    picks=ordered[:int(model["params"]["perRaceMarkets"])]
    return {"raceId":str(card.get("id", "")),
        "venue":int(card["venue"]),"raceNo":int(card["raceNo"]),
        "month":str(card["month"]),
        "bets":picks,
        "totalStakeYen":sum(b["stakeYen"] for b in picks),
        "selectionScore":round(sum(b["historicalModelMoneyScoreYenPer100"] for b in picks),4)}

def actual_money(picks):
    rows=list(picks)
    wager=sum(row["stakeYen"] for row in rows)
    paid=sum(row["paidYen"] for row in rows)
    byrace=collections.defaultdict(int)
    for row in rows:byrace[row["raceId"]]+=row["paidYen"]
    largest=max(byrace.values(),default=0)
    return {"races":len(byrace),"bets":len(rows),"stakeYen":wager,
        "paidYen":paid,
        "roiPct":round(100*paid/wager,4) if wager else None,
        "minusLargestRaceRoiPct":round(100*(paid-largest)/wager,4) if wager else None,
        "hitRaces":sum(n>0 for n in byrace.values()),
        "hitRacePct":round(100*sum(n>0 for n in byrace.values())/len(byrace),4) if byrace else None}

def backtest(model,races):
    # Every prediction happens before looking up settlement; selection only
    # sorts pre-odds score and race number. Post-final historical odds caveat.
    grouped=collections.defaultdict(list)
    for r in races:
        y=int(r["month"][:4])
        if y<2023 or y>2026:continue
        if len(r["horses"])<4:continue
        rec=predict_one(model,r)
        grouped[(r["day"],r["venue"])].append((rec,r))
    ledger=[];coverage=collections.Counter()
    for key,values in sorted(grouped.items()):
        chosen=sorted(values,key=lambda x:(-x[0]["selectionScore"],
                      int(x[1]["raceNo"]),str(x[1]["id"])))[:model["params"]["racesPerVenueDay"]]
        coverage[str(key[0])[:4]]+=1
        for pred,race in chosen:
            for bet in pred["bets"]:
                m=int(bet["marketIndex"])
                comb=tuple(bet["horseNumbers"])
                payout=int(race["payout"][m].get(comb,0))
                stake=int(bet["stakeYen"])
                paid=payout*stake//100
                ledger.append({"raceId":race["id"],"year":int(race["month"][:4]),
                   "raceDate":race["day"],"venue":race["venue"],
                   "raceNo":race["raceNo"],"market":bet["market"],
                   "horseNumbers":"-".join(map(str,comb)),
                   "stakeYen":stake,"paidYen":paid})
    metrics_by_year={str(y):actual_money([r for r in ledger if r["year"]==y])
                     for y in range(2023,2027)}
    total=actual_money(ledger)
    return {"evaluatedYearRange":"2023_2026_JAN_APR",
        "evaluatedRaceDayCounts":dict(coverage),
        "metricsByYear":metrics_by_year,"allYears":total,
        "historicalOfficialT15Verified":False,
        "realMoneyPurchasesAsserted":False,
        "modelReadyForInference":True},ledger

def selftest():
    model={"params":{"priorContextRaces":20,"cashScoreFloorYen":1,
            "maxOnePayoutBlend":.75,"perRaceMarkets":2,
            "stakePerTicketYen":100},
           "actions":ACTIONS,
           "panels":{a["key"]:{
                "all:0":{"n":20,"paid":1200,"hits":6,"maxPaid":300}}
                  for a in ACTIONS}}
    sample={"month":"202610","venue":5,"raceNo":9,"id":"demo",
            "horses":[(1,2.5,4,55),(2,3.9,3,56),
                      (3,5.5,4,55),(4,8.1,5,56)]}
    p=predict_one(model,sample)
    assert len(p["bets"])==2 and p["totalStakeYen"]==200
    assert p["bets"][0]["marketIndex"]!=p["bets"][1]["marketIndex"]
    assert len(set(p["bets"][0]["horseNumbers"]))==len(p["bets"][0]["horseNumbers"])
    assert actual_money([{"raceId":"a","stakeYen":100,"paidYen":250},
                         {"raceId":"a","stakeYen":100,"paidYen":0}])["roiPct"]==125
    print("CASH_BET_FROZEN_MODEL_SELFTEST_OK")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--train",action="store_true")
    parser.add_argument("--predict-card",type=str)
    parser.add_argument("--model-file",type=Path,default=MODEL)
    args=parser.parse_args()
    if args.self_test:selftest();return
    if args.train:
        archive=mod("scripts/research-nov2026-decade-roi-first-sixmarkets.py","source_cash")
        parser_=mod("scripts/research-nov2026-sixmarket-real-paid-cash.py","source_pay")
        races=archive.read_all_races(parser_.parse_payments)
        model=fit(races)
        MODEL.parent.mkdir(parents=True,exist_ok=True)
        MODEL.write_text(json.dumps(model,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf8")
        result,ledger=backtest(model,races)
        EVAL.parent.mkdir(parents=True,exist_ok=True)
        EVAL.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        with LEDGER.open("w",encoding="utf8",newline="") as f:
            cols=list(ledger[0]) if ledger else ["raceId"]
            w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(ledger)
        print("CASH_BET_BASELINE_FROZEN",json.dumps({
            "modelId":model["modelId"],"trainedYears":model["trainYears"],
            "actionCount":len(model["actions"]),
            "modelFile":str(MODEL.relative_to(ROOT)),
            "backtest":result["allYears"],
            "annual":result["metricsByYear"]},ensure_ascii=False),flush=True)
        assert model["modelId"]=="cash-bet-baseline-v1"
        assert all(v["bets"]>0 for v in result["metricsByYear"].values()),"MODEL_EMITTED_NO_BETS"
        return
    if args.predict_card:
        model=json.loads(args.model_file.read_text(encoding="utf8"))
        card=json.loads(Path(args.predict_card).read_text(encoding="utf8"))
        print(json.dumps(predict_one(model,card),ensure_ascii=False,indent=2))
        return
    parser.error("Run --self-test, --train, or --predict-card <JSON file>")
if __name__=="__main__":main()
