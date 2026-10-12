#!/usr/bin/env python3
from __future__ import annotations
import collections, datetime as dt, gzip, importlib.util, itertools, json, math, os, pathlib, sys, urllib.request
import lightgbm as lgb
import numpy as np

ROOT=pathlib.Path(__file__).resolve().parents[2]
START="2026-10-10"; END="2026-10-12"; HISTORY_START="2026-08-10"
ODDS_PATH=ROOT/"artifacts"/"mobile-historical-official-odds-retry.jsonl.gz"
OUT=ROOT/"artifacts"/"recency-strength-20261012.json"
ACCOUNT=os.environ["CLOUDFLARE_ACCOUNT_ID"]; DB=os.environ["CLOUDFLARE_D1_DATABASE_ID"]; TOKEN=os.environ["CLOUDFLARE_API_TOKEN"]
URL=f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DB}/query"

def q(sql,params=None):
    body=json.dumps({"sql":sql,"params":params or []},ensure_ascii=False).encode()
    req=urllib.request.Request(URL,data=body,method="POST",headers={"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r: out=json.loads(r.read().decode())
    if not out.get("success"): raise RuntimeError(out)
    z=out.get("result") or []
    return (z[0].get("results") or []) if z else []

class Collector:
    @staticmethod
    def d1_query(sql,params=None): return q(sql,params)

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise RuntimeError(path)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

core=load(ROOT/"scripts"/"ten-year-production-core.py","strength_core")
learn=load(ROOT/"scripts"/"live-recency-learning.py","strength_learning")
gen=load(ROOT/"scripts"/"generate-ten-year-live-bets.py","strength_generator")
cfg=core.load_config(); features=list(cfg["runnerProbabilityModel"]["features"])
booster=lgb.Booster(model_file=str(core.MODEL_PATH))
assert booster.num_feature()==56
state=core.load_feature_state()
assert state["throughDate"]=="2026-08-09", state["throughDate"]

# Freeze exactly the production-selected 10 races per day.
states=q("SELECT state_key AS k,state_value AS v FROM rt_system_state WHERE state_key LIKE 'final_daily_selection:%' ORDER BY state_key")
selected_by_date={}
for row in states:
    date=str(row["k"]).split(":")[-1]
    if not (START<=date<=END): continue
    p=json.loads(row["v"])
    ids=[str(x.get("raceId") or "") for x in p.get("selected",[]) if x.get("raceId")]
    selected_by_date[date]=ids
selected_all={x for xs in selected_by_date.values() for x in xs}
if len(selected_all)!=30:
    raise RuntimeError(f"EXPECTED_30_SELECTED_RACES:{len(selected_all)}:{sorted(selected_by_date.items())}")

odds_art={}
with gzip.open(ODDS_PATH,"rt",encoding="utf-8") as fh:
    for line in fh:
        if line.strip():
            x=json.loads(line); odds_art[str(x["raceId"])]=x
if len(set(odds_art)&selected_all)<29:
    raise RuntimeError(f"OFFICIAL_ODDS_COVERAGE_TOO_LOW:{len(set(odds_art)&selected_all)}/30")

bundles=core.bundles_from_d1(Collector,"race_date>=? AND race_date<=?",[HISTORY_START,END])
by_date=collections.defaultdict(list)
for b in bundles:
    by_date[str(b["race"]["raceDate"])].append(b)
for date in by_date:
    by_date[date].sort(key=lambda b:(str(b["race"].get("startTimeUtc") or ""),str(b["race"]["raceId"])))

# Build the same 30-day runner-learning source rows from completed races.
runner_rows=[]
for b in bundles:
    race=b["race"]; results={int(x["horseNo"]):x for x in b.get("results",[]) if x.get("horseNo") is not None}
    active=[r for r in b.get("runners",[]) if (r.get("runnerStatus") or "active")=="active"]
    for r in active:
        res=results.get(int(r["horseNo"]))
        if not res or res.get("finishPosition") is None: continue
        runner_rows.append({
            "raceId":str(race["raceId"]),"raceDate":str(race["raceDate"]),"startTimeUtc":str(race.get("startTimeUtc") or ""),
            "venue":str(race.get("venue") or ""),"surface":str(race.get("surface") or ""),"distanceM":race.get("distanceM"),
            "horseNo":int(r["horseNo"]),"horseName":str(r.get("horseName") or ""),"jockey":str(r.get("jockey") or ""),
            "trainer":str(r.get("trainer") or ""),"winOdds":r.get("winOdds"),"finishPosition":res.get("finishPosition")
        })

bet_rows=q("""SELECT b.race_id AS raceId,b.bet_type AS betType,b.stake_yen AS stakeYen,COALESCE(b.return_yen,0) AS returnYen,
 b.assumed_odds AS assumedOdds,r.race_date AS raceDate,r.start_time_utc AS startTimeUtc,r.venue
 FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
 WHERE r.race_date>=? AND r.race_date<=? AND b.source_prediction_id=-2
   AND b.course='ライト' AND b.settlement_status='settled'
 ORDER BY r.start_time_utc,b.race_id,b.id""",[HISTORY_START,END])

actual_rows=q("""SELECT r.race_date AS raceDate,b.race_id AS raceId,b.bet_type AS betType,b.combination,
 b.stake_yen AS stakeYen,COALESCE(b.return_yen,0) AS returnYen,b.settlement_status AS settlementStatus
 FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
 WHERE r.race_date>=? AND r.race_date<=? AND b.source_prediction_id=-2 AND b.course='ライト'
 ORDER BY r.race_date,b.race_id,b.id""",[START,END])
actual_by_race=collections.defaultdict(list)
for x in actual_rows: actual_by_race[str(x["raceId"])].append(x)

refund_rows=q("SELECT race_id AS raceId,refund_horse_nos_json AS refunds FROM rt_races WHERE race_date>=? AND race_date<=?",[START,END])
refunds={}
for x in refund_rows:
    try: refunds[str(x["raceId"])]=set(int(v) for v in json.loads(x.get("refunds") or "[]"))
    except Exception: refunds[str(x["raceId"])]=set()

BET_ORDER=("単勝","ワイド","馬連","馬単","3連複","3連単")
STRENGTHS={"none":0.0,"half":0.5,"full":1.0}

def odd_value(v):
    if isinstance(v,list):
        z=[float(x) for x in v if x is not None]; return sum(z)/len(z) if z else None
    try:return float(v)
    except:return None

def odds_map(x):
    horses=[int(v) for v in x["horses"]]; rid=str(x["raceId"]); out={}
    for h,v in zip(horses,x["win"]):
        o=odd_value(v)
        if o and o>0: out[(rid,"単勝",str(h))]=o
    pairs=list(itertools.combinations(horses,2))
    for key,bt in (("wide","ワイド"),("umaren","馬連")):
        for p,v in zip(pairs,x[key]):
            o=odd_value(v)
            if o and o>0: out[(rid,bt,"-".join(map(str,sorted(p))))]=o
    exactas=list(itertools.permutations(horses,2))
    for p,v in zip(exactas,x["umatan"]):
        o=odd_value(v)
        if o and o>0: out[(rid,"馬単","-".join(map(str,p)))]=o
    trios=list(itertools.combinations(horses,3))
    for p,v in zip(trios,x["trio"]):
        o=odd_value(v)
        if o and o>0: out[(rid,"3連複","-".join(map(str,sorted(p))))]=o
    tris=list(itertools.permutations(horses,3))
    for p,v in zip(tris,x["trifecta"]):
        o=odd_value(v)
        if o and o>0: out[(rid,"3連単","-".join(map(str,p)))]=o
    return out

def scaled_factor(full_factor,strength):
    f=max(1e-9,float(full_factor))
    return math.exp(strength*math.log(f))

def choose_strength(rid,runners,w,odds,bet_learning,venue,strength):
    horse_nos=[int(r["horseNo"]) for r in runners]; n=len(runners); by_type=[]
    for bt in BET_ORDER:
        candidates=[]
        for pos in gen.combo_positions(bt,n):
            combo=gen.combo_text(bt,pos,horse_nos); ov=odds.get((rid,bt,combo))
            if ov is None: continue
            p=float(core.combination_probability(bt,pos,w))
            if not math.isfinite(p) or p<=0: continue
            full_fac=float(learn.bet_factor(bet_learning,bt,venue,ov))
            fac=scaled_factor(full_fac,strength)
            candidates.append({"betType":bt,"combination":combo,"predictedProbability":p,"officialOdds":ov,
                               "recencyFactor":fac,"valueProduct":p*ov*fac})
        if not candidates: raise RuntimeError(f"NO_CANDIDATE:{rid}:{bt}")
        candidates.sort(key=lambda x:(-x["valueProduct"],x["officialOdds"],x["combination"]))
        kept=candidates[:5]
        for x in kept:
            x["score"]=math.log(x["predictedProbability"])+0.4*math.log(x["officialOdds"])+math.log(x["recencyFactor"])
        kept.sort(key=lambda x:(-x["score"],-x["predictedProbability"],x["combination"]))
        by_type.append(kept[0])
    by_type.sort(key=lambda x:(-x["score"],BET_ORDER.index(x["betType"]),x["combination"]))
    return by_type[:2]

def canon(bt,c):
    nums=[int(x) for x in str(c).replace("→","-").split("-") if x.strip().isdigit()]
    if bt in ("ワイド","馬連","3連複"): nums.sort()
    return "-".join(map(str,nums))

def settle(bundle,tickets):
    pays={(str(x["betType"]),canon(str(x["betType"]),x["combination"])):int(x["payoutYen"]) for x in bundle.get("payouts",[]) if x.get("payoutYen") is not None}
    ref=refunds.get(str(bundle["race"]["raceId"]),set()); total=0
    for t in tickets:
        hs={int(x) for x in str(t["combination"]).split("-")}
        total += 1000 if hs & ref else pays.get((str(t["betType"]),canon(str(t["betType"]),t["combination"])),0)*10
    return total

def model_weights(state,b):
    runners=[r for r in b.get("runners",[]) if (r.get("runnerStatus") or "active")=="active"]
    runners.sort(key=lambda r:int(r["horseNo"]))
    rows=[core.ml_feature_row(state,b["race"],r,len(runners)) for r in runners]
    x=np.asarray([[float(row[f]) for f in features] for row in rows],dtype=np.float64)
    raw=np.asarray(booster.predict(x),dtype=np.float64)
    if raw.shape!=(len(runners),) or not np.all(np.isfinite(raw)) or np.any(raw<=0): raise RuntimeError("MODEL_INVALID")
    return runners,raw/raw.sum()

def cutoff_before_start(b):
    x=dt.datetime.fromisoformat(str(b["race"]["startTimeUtc"]).replace("Z","+00:00"))
    return (x-dt.timedelta(seconds=1)).astimezone(dt.timezone.utc).isoformat().replace("+00:00","Z")

def actual_ticket_set(rid):
    rows=actual_by_race.get(rid,[])
    return sorted((str(x["betType"]),canon(str(x["betType"]),x["combination"])) for x in rows if x.get("settlementStatus")=="settled")

def actual_return(rid):
    rows=actual_by_race.get(rid,[])
    if len(rows)!=2 or not all(x.get("settlementStatus")=="settled" for x in rows): return None
    return sum(int(x.get("returnYen") or 0) for x in rows)

stats={k:{"races":0,"stakeYen":0,"returnYen":0,"hits":0} for k in STRENGTHS}
actual={"races":0,"stakeYen":0,"returnYen":0,"hits":0}
byday=collections.defaultdict(lambda:{k:{"races":0,"returnYen":0,"hits":0} for k in STRENGTHS})
full_actual_ticket_matches=0
full_actual_both_available=0
changed_vs_full={"none":0,"half":0}
details=[]; excluded=[]

for date in sorted(d for d in by_date if HISTORY_START<=d<=END):
    for b in by_date[date]:
        rid=str(b["race"]["raceId"])
        if START<=date<=END and rid in set(selected_by_date.get(date,[])):
            if rid not in odds_art:
                excluded.append({"raceId":rid,"reason":"official_odds_missing"})
            elif not b.get("payouts") or not b.get("results"):
                excluded.append({"raceId":rid,"reason":"result_or_payout_missing"})
            else:
                try:
                    om=odds_map(odds_art[rid])
                    runners,base_w=model_weights(state,b)
                    cutoff=cutoff_before_start(b)
                    recent_runners=[x for x in runner_rows if str(x.get("startTimeUtc") or "")<cutoff]
                    full_runner_factors,runner_detail,runner_audit=learn.build_runner_learning(recent_runners,b["race"],runners,cutoff,date)
                    recent_bets=[x for x in bet_rows if str(x.get("startTimeUtc") or "")<cutoff]
                    bet_learning=learn.build_bet_learning(recent_bets,cutoff,date)
                    tickets_by_strength={}
                    returns={}
                    for name,strength in STRENGTHS.items():
                        adj=np.asarray([base_w[i]*scaled_factor(full_runner_factors[i],strength) for i in range(len(runners))],dtype=np.float64)
                        w=adj/adj.sum()
                        tickets=choose_strength(rid,runners,w,om,bet_learning,str(b["race"].get("venue") or ""),strength)
                        tickets_by_strength[name]=tickets
                        ret=settle(b,tickets);returns[name]=ret
                        s=stats[name];s["races"]+=1;s["stakeYen"]+=2000;s["returnYen"]+=ret;s["hits"]+=int(ret>0)
                        d=byday[date][name];d["races"]+=1;d["returnYen"]+=ret;d["hits"]+=int(ret>0)
                    full_set=sorted((x["betType"],canon(x["betType"],x["combination"])) for x in tickets_by_strength["full"])
                    for name in ("none","half"):
                        z=sorted((x["betType"],canon(x["betType"],x["combination"])) for x in tickets_by_strength[name])
                        changed_vs_full[name]+=int(z!=full_set)
                    aset=actual_ticket_set(rid);aret=actual_return(rid)
                    if aret is not None:
                        actual["races"]+=1;actual["stakeYen"]+=2000;actual["returnYen"]+=aret;actual["hits"]+=int(aret>0)
                        full_actual_both_available+=1
                        full_actual_ticket_matches+=int(aset==full_set)
                    details.append({"raceId":rid,"date":date,"venue":b["race"].get("venue"),"raceNo":b["race"].get("raceNo"),
                        "actualTickets":aset,"actualReturnYen":aret,
                        "noneTickets":[(x["betType"],x["combination"]) for x in tickets_by_strength["none"]],"noneReturnYen":returns["none"],
                        "halfTickets":[(x["betType"],x["combination"]) for x in tickets_by_strength["half"]],"halfReturnYen":returns["half"],
                        "fullTickets":[(x["betType"],x["combination"]) for x in tickets_by_strength["full"]],"fullReturnYen":returns["full"],
                        "runnerFactorMin":min(full_runner_factors),"runnerFactorMax":max(full_runner_factors),
                        "runnerHistoryRaces":runner_audit.get("runnerHistoryRaces"),"sameDayFinishedRaces":runner_audit.get("sameDayFinishedRaces")})
                except Exception as e:
                    excluded.append({"raceId":rid,"reason":f"{type(e).__name__}:{e}"})
        # Current production feature state learns from each completed earlier race on the same date.
        core.update_feature_state_for_date(state,[b])
        state["throughDate"]=date

for s in list(stats.values())+[actual]:
    s["roiPct"]=100*s["returnYen"]/s["stakeYen"] if s["stakeYen"] else None
    s["hitRacePct"]=100*s["hits"]/s["races"] if s["races"] else None
for date,x in byday.items():
    for name,s in x.items():
        s["stakeYen"]=s["races"]*2000
        s["roiPct"]=100*s["returnYen"]/s["stakeYen"] if s["stakeYen"] else None
        s["hitRacePct"]=100*s["hits"]/s["races"] if s["races"] else None

report={
 "window":[START,END],
 "selectedRaces":len(selected_all),
 "officialOddsRaces":len(set(odds_art)&selected_all),
 "comparedRaces":stats["full"]["races"],
 "excluded":excluded,
 "oddsBasis":"JRA historical official odds after race; identical odds for all three simulated strengths",
 "strengthDefinition":"multiplicative recency factor raised to strength: none=0, half=0.5, full=1",
 "stats":stats,
 "actualProduction":actual,
 "fullVsActualTicketMatch":{"matches":full_actual_ticket_matches,"races":full_actual_both_available,
   "pct":100*full_actual_ticket_matches/full_actual_both_available if full_actual_both_available else None},
 "changedVsFull":changed_vs_full,
 "byDate":dict(sorted(byday.items())),
 "bestSimulated":max(stats,key=lambda k:stats[k]["roiPct"] if stats[k]["roiPct"] is not None else -1),
 "details":details,
}
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("RECENCY_STRENGTH_RESULT "+json.dumps({k:v for k,v in report.items() if k not in ("details","excluded","byDate")},ensure_ascii=False))
print("BY_DATE "+json.dumps(report["byDate"],ensure_ascii=False))
print("EXCLUDED "+json.dumps(excluded,ensure_ascii=False))
