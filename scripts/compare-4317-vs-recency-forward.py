#!/usr/bin/env python3
from __future__ import annotations
import collections, copy, datetime as dt, gzip, importlib.util, itertools, json, math, os, pathlib, sys, urllib.request
import lightgbm as lgb
import numpy as np

ROOT=pathlib.Path(__file__).resolve().parents[1]
ODDS_PATH=ROOT/"artifacts"/"selected-historical-official-odds.jsonl.gz"
OUT=ROOT/"artifacts"/"forward-4317-vs-recency.json"
START="2026-08-10"; END="2026-09-13"; HISTORY_START="2026-07-16"
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

core=load(ROOT/"scripts"/"ten-year-production-core.py","cmp_core")
learn=load(ROOT/"scripts"/"live-recency-learning.py","cmp_learning")
gen=load(ROOT/"scripts"/"generate-ten-year-live-bets.py","cmp_generator")
cfg=core.load_config(); features=list(cfg["runnerProbabilityModel"]["features"])
booster=lgb.Booster(model_file=str(core.MODEL_PATH))
assert booster.num_feature()==56
exact_state=core.load_feature_state(); rec_state=core.load_feature_state()
assert exact_state["throughDate"]=="2026-08-09", exact_state["throughDate"]
assert rec_state["throughDate"]=="2026-08-09", rec_state["throughDate"]

# Actual frozen selections only; no outcome-based race selection.
states=q("SELECT state_key AS k,state_value AS v FROM rt_system_state WHERE state_key LIKE 'final_daily_selection:%' ORDER BY state_key")
selected_by_date={}
for row in states:
    date=str(row["k"]).split(":")[-1]
    if not (START<=date<=END): continue
    p=json.loads(row["v"])
    if p.get("sourceModel")!="ten-year-completed-model" or p.get("resultDataUsedForTargetDay") is not False: continue
    selected_by_date[date]=[str(x["raceId"]) for x in p.get("selected",[]) if x.get("raceId")]
selected_all={x for xs in selected_by_date.values() for x in xs}

# Odds export contains every eligible selected race fetched from JRA historical official pages.
odds_art={}
with gzip.open(ODDS_PATH,"rt",encoding="utf-8") as fh:
    for line in fh:
        if line.strip():
            x=json.loads(line); odds_art[str(x["raceId"])]=x

# Load only JRA dates needed for state advancement / recency history.
bundles=core.bundles_from_d1(Collector, "race_date>=? AND race_date<=?", [HISTORY_START,END])
by_date=collections.defaultdict(list); by_id={}
for b in bundles:
    rid=str(b["race"]["raceId"]); date=str(b["race"]["raceDate"])
    by_id[rid]=b; by_date[date].append(b)
for date in by_date:
    by_date[date].sort(key=lambda b:(str(b["race"].get("startTimeUtc") or ""),str(b["race"]["raceId"])))

# Build recency input rows once, then filter by cutoff locally.
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
 WHERE r.race_date>=? AND r.race_date<=? AND b.source_prediction_id=-2 AND b.course='ライト' AND b.settlement_status='settled'
 ORDER BY r.start_time_utc,b.race_id,b.id""",[HISTORY_START,END])

refund_rows=q("SELECT race_id AS raceId,refund_horse_nos_json AS refunds FROM rt_races WHERE race_date>=? AND race_date<=?",[START,END])
refunds={}
for x in refund_rows:
    try: refunds[str(x["raceId"])]=set(int(v) for v in json.loads(x.get("refunds") or "[]"))
    except Exception: refunds[str(x["raceId"])]=set()

BET_ORDER=("単勝","ワイド","馬連","馬単","3連複","3連単")

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

def choose_recency(rid,runners,w,odds,bet_learning,venue):
    horse_nos=[int(r["horseNo"]) for r in runners]; n=len(runners); by_type=[]
    for bt in BET_ORDER:
        candidates=[]
        for pos in gen.combo_positions(bt,n):
            combo=gen.combo_text(bt,pos,horse_nos); ov=odds.get((rid,bt,combo))
            if ov is None: continue
            p=float(core.combination_probability(bt,pos,w))
            if not math.isfinite(p) or p<=0: continue
            fac=float(learn.bet_factor(bet_learning,bt,venue,ov))
            candidates.append({"betType":bt,"combination":combo,"horses":[horse_nos[i] for i in pos],
                "predictedProbability":p,"officialOdds":ov,"recencyFactor":fac,"valueProduct":p*ov*fac})
        if not candidates: raise RuntimeError(f"NO_CANDIDATE:{rid}:{bt}")
        candidates.sort(key=lambda x:(-x["valueProduct"],x["officialOdds"],x["combination"]))
        kept=candidates[:5]
        for x in kept:x["score"]=math.log(x["predictedProbability"])+0.4*math.log(x["officialOdds"])+math.log(x["recencyFactor"])
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
    runners=[r for r in b.get("runners",[]) if (r.get("runnerStatus") or "active")=="active"];runners.sort(key=lambda r:int(r["horseNo"]))
    if len(runners)<3: raise RuntimeError("TOO_FEW_RUNNERS")
    rows=[core.ml_feature_row(state,b["race"],r,len(runners)) for r in runners]
    x=np.asarray([[float(row[f]) for f in features] for row in rows],dtype=np.float64)
    raw=np.asarray(booster.predict(x),dtype=np.float64)
    if raw.shape!=(len(runners),) or not np.all(np.isfinite(raw)) or np.any(raw<=0): raise RuntimeError("MODEL_INVALID")
    return runners,raw/raw.sum()

def cutoff_before_start(b):
    s=str(b["race"].get("startTimeUtc") or "")
    x=dt.datetime.fromisoformat(s.replace("Z","+00:00"))
    return (x-dt.timedelta(seconds=1)).astimezone(dt.timezone.utc).isoformat().replace("+00:00","Z")

stats={k:{"races":0,"stakeYen":0,"returnYen":0,"hits":0} for k in ("exact4317","recency")}
byday=collections.defaultdict(lambda:{k:{"races":0,"returnYen":0,"hits":0} for k in stats})
different=0; compared=[]; excluded=[]

# Start at 8/10 so state is advanced exactly one day at a time; selected dates begin 8/15.
dates=sorted(d for d in by_date if "2026-08-10"<=d<=END)
for date in dates:
    day=by_date[date]
    selected=set(selected_by_date.get(date,[]))
    # Exact policy sees no results from this same date. Recency state is updated race-by-race.
    for b in day:
        rid=str(b["race"]["raceId"])
        if rid in selected:
            if rid not in odds_art:
                excluded.append({"raceId":rid,"reason":"historical_official_odds_missing"})
            elif not b.get("payouts") or not b.get("results"):
                excluded.append({"raceId":rid,"reason":"result_or_payout_missing"})
            else:
                try:
                    om=odds_map(odds_art[rid])
                    er,ew=model_weights(exact_state,b)
                    exact=gen.choose_two(core,rid,er,ew,om)
                    rr,rw0=model_weights(rec_state,b)
                    cutoff=cutoff_before_start(b)
                    recent_runners=[x for x in runner_rows if str(x.get("startTimeUtc") or "")<cutoff]
                    factors,_,_=learn.build_runner_learning(recent_runners,b["race"],rr,cutoff,date)
                    adj=np.asarray([rw0[i]*float(factors[i]) for i in range(len(rr))],dtype=np.float64); rw=adj/adj.sum()
                    recent_bets=[x for x in bet_rows if str(x.get("startTimeUtc") or "")<cutoff]
                    bl=learn.build_bet_learning(recent_bets,cutoff,date)
                    rec=choose_recency(rid,rr,rw,om,bl,str(b["race"].get("venue") or ""))
                    eret=settle(b,exact); rret=settle(b,rec)
                    for name,ret in (("exact4317",eret),("recency",rret)):
                        s=stats[name];s["races"]+=1;s["stakeYen"]+=2000;s["returnYen"]+=ret;s["hits"]+=int(ret>0)
                        d=byday[date][name];d["races"]+=1;d["returnYen"]+=ret;d["hits"]+=int(ret>0)
                    es=[(x["betType"],x["combination"]) for x in exact]; rs=[(x["betType"],x["combination"]) for x in rec]
                    different+=int(es!=rs)
                    compared.append({"raceId":rid,"date":date,"exactReturn":eret,"recencyReturn":rret,"exact":es,"recency":rs})
                except Exception as e:
                    excluded.append({"raceId":rid,"reason":f"{type(e).__name__}:{e}"})
        # After this race, old recency policy can use its result for later same-day races.
        core.update_feature_state_for_date(rec_state,[b])
        rec_state["throughDate"]=date
    # 431.7 policy advances only after the entire date, so no same-day leakage.
    core.update_feature_state_for_date(exact_state,day)
    exact_state["throughDate"]=date

for name,s in stats.items():
    s["roiPct"]=100*s["returnYen"]/s["stakeYen"] if s["stakeYen"] else None
    s["hitRacePct"]=100*s["hits"]/s["races"] if s["races"] else None
for date,x in byday.items():
    for name,s in x.items():
        s["stakeYen"]=s["races"]*2000
        s["roiPct"]=100*s["returnYen"]/s["stakeYen"] if s["stakeYen"] else None

report={
 "basis":"future-only races after frozen model end 2026-08-09; actual frozen daily selections; same JRA historical official odds for both policies",
 "oddsTiming":"JRA historical official odds pages (not saved T-15 snapshots)",
 "selectedRaces":len(selected_all),"officialOddsFetchedRaces":len(odds_art),"comparedRaces":stats["exact4317"]["races"],
 "excludedRaces":len(excluded),"differentTicketRaces":different,"stats":stats,"byDate":dict(sorted(byday.items())),
 "winner":("exact4317" if stats["exact4317"]["returnYen"]>stats["recency"]["returnYen"] else "recency" if stats["recency"]["returnYen"]>stats["exact4317"]["returnYen"] else "tie"),
 "returnDifferenceYen":stats["exact4317"]["returnYen"]-stats["recency"]["returnYen"],
 "excluded":excluded,"races":compared
}
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("FORWARD_POLICY_COMPARISON "+json.dumps({k:v for k,v in report.items() if k not in ("excluded","races","byDate")},ensure_ascii=False))
print("BY_DATE "+json.dumps(report["byDate"],ensure_ascii=False))
