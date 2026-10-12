#!/usr/bin/env python3
from __future__ import annotations
import collections, datetime as dt, importlib.util, json, math, os, pathlib, statistics, sys, urllib.request
import lightgbm as lgb
import numpy as np

ROOT=pathlib.Path(__file__).resolve().parents[2]
START="2026-10-10"; END="2026-10-12"; HISTORY_START="2026-08-10"
ACCOUNT=os.environ["CLOUDFLARE_ACCOUNT_ID"]; DB=os.environ["CLOUDFLARE_D1_DATABASE_ID"]; TOKEN=os.environ["CLOUDFLARE_API_TOKEN"]
URL=f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DB}/query"

def q(sql,params=None):
    req=urllib.request.Request(URL,data=json.dumps({"sql":sql,"params":params or []},ensure_ascii=False).encode(),
      method="POST",headers={"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json"})
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

core=load(ROOT/"scripts"/"ten-year-production-core.py","rc_core")
learn=load(ROOT/"scripts"/"live-recency-learning.py","rc_learn")
cfg=core.load_config();features=list(cfg["runnerProbabilityModel"]["features"])
booster=lgb.Booster(model_file=str(core.MODEL_PATH))
assert booster.num_feature()==56

feature_state=core.load_feature_state()
selection_state=core.load_selection_state()
assert feature_state["throughDate"]=="2026-08-09",feature_state["throughDate"]
assert selection_state["throughDate"]=="2026-08-09",selection_state["throughDate"]

# Actual immutable production selections.
selection_rows=q("SELECT state_key k,state_value v FROM rt_system_state WHERE state_key IN (?,?,?) ORDER BY state_key",[
 "final_daily_selection:2026-10-10","final_daily_selection:2026-10-11","final_daily_selection:2026-10-12"])
selected_by_date={}
selected_meta={}
for row in selection_rows:
    date=str(row["k"]).split(":")[-1];p=json.loads(row["v"])
    ids=[str(x["raceId"]) for x in p.get("selected",[]) if x.get("raceId")]
    selected_by_date[date]=set(ids)
    selected_meta.update({str(x["raceId"]):x for x in p.get("selected",[]) if x.get("raceId")})
assert sum(len(v) for v in selected_by_date.values())==30,selected_by_date

# Production Light tickets/returns for failure decomposition.
bet_rows=q("""SELECT r.race_date raceDate,b.race_id raceId,b.bet_type betType,b.combination,
 b.stake_yen stakeYen,COALESCE(b.return_yen,0) returnYen,b.settlement_status settlementStatus
 FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
 WHERE r.race_date BETWEEN ? AND ? AND b.source_prediction_id=-2 AND b.course='ライト'
 ORDER BY r.race_date,b.race_id,b.id""",[START,END])
bets_by_race=collections.defaultdict(list)
for x in bet_rows:bets_by_race[str(x["raceId"])].append(x)

bundles=core.bundles_from_d1(Collector,"race_date>=? AND race_date<=?",[HISTORY_START,END])
by_date=collections.defaultdict(list)
for b in bundles:
    by_date[str(b["race"]["raceDate"])].append(b)
for date in by_date:
    by_date[date].sort(key=lambda b:(str(b["race"].get("startTimeUtc") or ""),str(b["race"]["raceId"])))

runner_rows=[]
for b in bundles:
    race=b["race"];results={int(x["horseNo"]):x for x in b.get("results",[]) if x.get("horseNo") is not None}
    active=[r for r in b.get("runners",[]) if (r.get("runnerStatus") or "active")=="active"]
    for r in active:
        res=results.get(int(r["horseNo"]))
        if not res or res.get("finishPosition") is None:continue
        runner_rows.append({
          "raceId":str(race["raceId"]),"raceDate":str(race["raceDate"]),"startTimeUtc":str(race.get("startTimeUtc") or ""),
          "venue":str(race.get("venue") or ""),"surface":str(race.get("surface") or ""),"distanceM":race.get("distanceM"),
          "horseNo":int(r["horseNo"]),"horseName":str(r.get("horseName") or ""),"jockey":str(r.get("jockey") or ""),
          "trainer":str(r.get("trainer") or ""),"winOdds":r.get("winOdds"),"finishPosition":res.get("finishPosition")})

def cutoff_before_start(b):
    x=dt.datetime.fromisoformat(str(b["race"]["startTimeUtc"]).replace("Z","+00:00"))
    return (x-dt.timedelta(seconds=1)).astimezone(dt.timezone.utc).isoformat().replace("+00:00","Z")

def model_weights(state,b):
    runners=[r for r in b.get("runners",[]) if (r.get("runnerStatus") or "active")=="active"]
    runners.sort(key=lambda r:int(r["horseNo"]))
    if len(runners)<3:raise RuntimeError("TOO_FEW_RUNNERS")
    rows=[core.ml_feature_row(state,b["race"],r,len(runners)) for r in runners]
    x=np.asarray([[float(row[f]) for f in features] for row in rows],dtype=np.float64)
    raw=np.asarray(booster.predict(x),dtype=np.float64)
    if raw.shape!=(len(runners),) or not np.all(np.isfinite(raw)) or np.any(raw<=0):raise RuntimeError("MODEL_INVALID")
    return runners,raw/raw.sum()

def rank_map(runners,weights):
    order=sorted(range(len(runners)),key=lambda i:(-float(weights[i]),int(runners[i]["horseNo"])))
    return {int(runners[i]["horseNo"]):rank+1 for rank,i in enumerate(order)},[int(runners[i]["horseNo"]) for i in order]

def winner_and_podium(b):
    xs=[]
    for r in b.get("results",[]):
        try:h=int(r["horseNo"]);p=int(r["finishPosition"])
        except:continue
        if p>0:xs.append((p,h))
    xs.sort()
    winner=next((h for p,h in xs if p==1),None)
    podium=[h for p,h in xs if p<=3]
    return winner,podium

def selection_scores_for_day(state,day):
    core._selection_quarter_transition(state,str(day[0]["race"]["raceDate"]))
    out={}
    byvenue=collections.defaultdict(list)
    for b in day:
        rows=core.selection_candidate_rows(state,b)
        chosen=core.select_proxy_tickets(rows,state["stats"],state["bet_stats"])
        score=sum(float(t["score"]) for t in chosen)/len(chosen)
        rid=str(b["race"]["raceId"]);venue=str(b["race"].get("venue") or "")
        out[rid]=score;byvenue[venue].append((rid,score,int(b["race"].get("raceNo") or 0)))
    ranks={}
    for venue,rows in byvenue.items():
        rows.sort(key=lambda x:(-x[1],x[2]))
        for rank,(rid,score,rno) in enumerate(rows,1):ranks[rid]=rank
    return out,ranks

# Bring both states through 10/09.
for date in sorted(d for d in by_date if HISTORY_START<=d<START):
    day=by_date[date]
    core.advance_selection_state(selection_state,day)
    for b in day:core.update_feature_state_for_date(feature_state,[b])
    feature_state["throughDate"]=date

records=[]
for date in [START,"2026-10-11",END]:
    day=by_date.get(date,[])
    assert len(day)==24,(date,len(day))
    scores,score_ranks=selection_scores_for_day(selection_state,day)
    selected=selected_by_date[date]
    for b in day:
        rid=str(b["race"]["raceId"]);winner,podium=winner_and_podium(b)
        runners,base=model_weights(feature_state,b)
        cutoff=cutoff_before_start(b)
        recent=[x for x in runner_rows if str(x.get("startTimeUtc") or "")<cutoff]
        factors,details,audit=learn.build_runner_learning(recent,b["race"],runners,cutoff,date)
        adj=np.asarray([base[i]*float(factors[i]) for i in range(len(runners))],dtype=np.float64);full=adj/adj.sum()
        br,border=rank_map(runners,base);fr,forder=rank_map(runners,full)
        actual=bets_by_race.get(rid,[])
        actual_settled=len(actual)==2 and all(x.get("settlementStatus")=="settled" for x in actual)
        actual_return=sum(int(x.get("returnYen") or 0) for x in actual) if actual_settled else None
        rec={
          "raceId":rid,"date":date,"venue":b["race"].get("venue"),"raceNo":int(b["race"].get("raceNo") or 0),
          "selected":rid in selected,"selectionScore":scores[rid],"selectionRankWithinVenue":score_ranks[rid],
          "winner":winner,"podium":podium,
          "baseWinnerRank":br.get(winner),"fullWinnerRank":fr.get(winner),
          "baseTopHorse":border[0] if border else None,"fullTopHorse":forder[0] if forder else None,
          "baseTopHorseFinish":next((int(x["finishPosition"]) for x in b.get("results",[]) if int(x.get("horseNo") or -1)==border[0]),None) if border else None,
          "fullTopHorseFinish":next((int(x["finishPosition"]) for x in b.get("results",[]) if int(x.get("horseNo") or -1)==forder[0]),None) if forder else None,
          "basePodiumInTop5":sum(1 for h in podium if br.get(h,999)<=5),
          "fullPodiumInTop5":sum(1 for h in podium if fr.get(h,999)<=5),
          "fullPodiumRanks":[fr.get(h) for h in podium],
          "runnerFactorMin":min(factors),"runnerFactorMax":max(factors),
          "sameDayFinishedRaces":audit.get("sameDayFinishedRaces"),
          "actualReturnYen":actual_return,
          "actualBetTypes":[str(x["betType"]) for x in actual] if actual else [],
          "actualCombinations":[str(x["combination"]) for x in actual] if actual else [],
        }
        if rec["selected"] and actual_settled and actual_return==0:
            wr=rec["fullWinnerRank"] or 999;pc=rec["fullPodiumInTop5"]
            if wr>5:reason="model_winner_outside_top5"
            elif wr<=3 and pc>=2:reason="ticket_or_value_layer"
            elif wr<=5:reason="model_partially_saw_race"
            else:reason="model_rank_miss"
            rec["missClass"]=reason
        elif rec["selected"] and actual_settled and actual_return>0:rec["missClass"]="hit"
        records.append(rec)
        # Same-day feature state must advance race by race, matching live behavior.
        core.update_feature_state_for_date(feature_state,[b]);feature_state["throughDate"]=date
    # Selection state learns only after the whole date is over.
    core.advance_selection_state(selection_state,day)

def summarize(rows):
    n=len(rows);valid=[r for r in rows if r.get("fullWinnerRank") is not None]
    def pct(k,limit):return 100*sum(1 for r in valid if int(r[k])<=limit)/len(valid) if valid else None
    vals=[int(r["fullWinnerRank"]) for r in valid];bvals=[int(r["baseWinnerRank"]) for r in valid]
    return {
      "races":n,
      "fullTop1WinPct":pct("fullWinnerRank",1),"fullWinnerTop3Pct":pct("fullWinnerRank",3),"fullWinnerTop5Pct":pct("fullWinnerRank",5),
      "fullMeanWinnerRank":sum(vals)/len(vals) if vals else None,"fullMedianWinnerRank":statistics.median(vals) if vals else None,
      "baseTop1WinPct":100*sum(1 for r in valid if int(r["baseWinnerRank"])<=1)/len(valid) if valid else None,
      "baseWinnerTop3Pct":100*sum(1 for r in valid if int(r["baseWinnerRank"])<=3)/len(valid) if valid else None,
      "baseWinnerTop5Pct":100*sum(1 for r in valid if int(r["baseWinnerRank"])<=5)/len(valid) if valid else None,
      "baseMeanWinnerRank":sum(bvals)/len(bvals) if bvals else None,
      "avgSelectionScore":sum(float(r["selectionScore"]) for r in rows)/n if n else None,
      "avgPodiumInFullTop5":sum(int(r["fullPodiumInTop5"]) for r in valid)/len(valid) if valid else None,
    }

sel=[r for r in records if r["selected"]];unsel=[r for r in records if not r["selected"]]
miss_counts=collections.Counter(r.get("missClass") for r in sel if r.get("missClass"))
by_date={}
for date in [START,"2026-10-11",END]:
    s=[r for r in sel if r["date"]==date];u=[r for r in unsel if r["date"]==date]
    by_date[date]={"selected":summarize(s),"unselected":summarize(u),
      "actualSelected":{"races":len(s),"hits":sum(1 for r in s if (r.get("actualReturnYen") or 0)>0),
        "returnYen":sum(int(r.get("actualReturnYen") or 0) for r in s if r.get("actualReturnYen") is not None),
        "stakeYen":sum(2000 for r in s if r.get("actualReturnYen") is not None)}}

# How often does the selector's top-5 within venue actually correspond to easier model races?
rank_buckets=collections.defaultdict(list)
for r in records:rank_buckets[int(r["selectionRankWithinVenue"])].append(r)
selector_rank_summary={str(k):summarize(v) for k,v in sorted(rank_buckets.items())}

report={
 "window":[START,END],"allRaces":len(records),"selectedRaces":len(sel),"unselectedRaces":len(unsel),
 "selected":summarize(sel),"unselected":summarize(unsel),
 "missClasses":dict(miss_counts),"byDate":by_date,"selectorRankSummary":selector_rank_summary,
 "selectedDetails":sel,
 "worstSelectedByWinnerRank":sorted(sel,key=lambda r:(-(r.get("fullWinnerRank") or 0),r["date"],r["raceId"]))[:15],
}
out=ROOT/"artifacts"/"root-cause-20261012.json";out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
print("ROOT_CAUSE_SUMMARY "+json.dumps({k:v for k,v in report.items() if k not in ("selectedDetails","worstSelectedByWinnerRank","selectorRankSummary")},ensure_ascii=False))
print("MISS_CLASSES "+json.dumps(dict(miss_counts),ensure_ascii=False))
print("SELECTED_DETAILS "+json.dumps(sel,ensure_ascii=False))
