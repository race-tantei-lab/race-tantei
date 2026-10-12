#!/usr/bin/env python3
from __future__ import annotations
import collections, datetime as dt, importlib.util, json, math, os, pathlib, sys, urllib.request
import lightgbm as lgb
import numpy as np

ROOT=pathlib.Path(__file__).resolve().parents[2]
FROM="2026-08-10"; TO="2026-10-12"
A=os.environ["CLOUDFLARE_ACCOUNT_ID"];D=os.environ["CLOUDFLARE_D1_DATABASE_ID"];T=os.environ["CLOUDFLARE_API_TOKEN"]
U=f"https://api.cloudflare.com/client/v4/accounts/{A}/d1/database/{D}/query"
def q(sql,p=None):
    req=urllib.request.Request(U,data=json.dumps({"sql":sql,"params":p or []},ensure_ascii=False).encode(),method="POST",
      headers={"Authorization":f"Bearer {T}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r:x=json.loads(r.read().decode())
    if not x.get("success"):raise RuntimeError(x)
    return (x.get("result") or [{}])[0].get("results") or []
class Collector:
    @staticmethod
    def d1_query(sql,params=None):return q(sql,params)
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
core=load(ROOT/"scripts"/"ten-year-production-core.py","rank_core")
learn=load(ROOT/"scripts"/"live-recency-learning.py","rank_learn")
cfg=core.load_config();features=list(cfg["runnerProbabilityModel"]["features"]);booster=lgb.Booster(model_file=str(core.MODEL_PATH))
state=core.load_feature_state();assert state["throughDate"]=="2026-08-09"

sel_rows=q("SELECT state_key k,state_value v FROM rt_system_state WHERE state_key LIKE 'final_daily_selection:%' AND state_key>=? AND state_key<=? ORDER BY state_key",
 [f"final_daily_selection:{FROM}",f"final_daily_selection:{TO}"])
selected={}
for z in sel_rows:
    d=str(z["k"]).split(":")[-1];p=json.loads(z["v"]);ids=[str(x["raceId"]) for x in p.get("selected",[]) if x.get("raceId")]
    if ids:selected[d]=set(ids)
print("SELECTION_DATES "+json.dumps({d:len(v) for d,v in selected.items()},ensure_ascii=False))

bundles=core.bundles_from_d1(Collector,"race_date>=? AND race_date<=?",[FROM,TO])
by_date=collections.defaultdict(list)
for b in bundles:by_date[str(b["race"]["raceDate"])].append(b)
for d in by_date:by_date[d].sort(key=lambda b:(str(b["race"].get("startTimeUtc") or ""),str(b["race"]["raceId"])))
runner_rows=[]
for b in bundles:
    race=b["race"];res={int(x["horseNo"]):x for x in b.get("results",[]) if x.get("horseNo") is not None}
    for r in [x for x in b.get("runners",[]) if (x.get("runnerStatus") or "active")=="active"]:
        rr=res.get(int(r["horseNo"]))
        if not rr or rr.get("finishPosition") is None:continue
        runner_rows.append({"raceId":str(race["raceId"]),"raceDate":str(race["raceDate"]),"startTimeUtc":str(race.get("startTimeUtc") or ""),
          "venue":str(race.get("venue") or ""),"surface":str(race.get("surface") or ""),"distanceM":race.get("distanceM"),
          "horseNo":int(r["horseNo"]),"horseName":str(r.get("horseName") or ""),"jockey":str(r.get("jockey") or ""),
          "trainer":str(r.get("trainer") or ""),"winOdds":r.get("winOdds"),"finishPosition":rr.get("finishPosition")})

refund_rows=q("SELECT race_id raceId,refund_horse_nos_json refunds FROM rt_races WHERE race_date BETWEEN ? AND ?",[FROM,TO])
refunds={}
for x in refund_rows:
    try:refunds[str(x["raceId"])]=set(int(v) for v in json.loads(x.get("refunds") or "[]"))
    except:refunds[str(x["raceId"])]=set()

def cutoff(b):
    x=dt.datetime.fromisoformat(str(b["race"]["startTimeUtc"]).replace("Z","+00:00"))
    return (x-dt.timedelta(seconds=1)).astimezone(dt.timezone.utc).isoformat().replace("+00:00","Z")
def weights(b):
    rs=[r for r in b.get("runners",[]) if (r.get("runnerStatus") or "active")=="active"];rs.sort(key=lambda r:int(r["horseNo"]))
    rows=[core.ml_feature_row(state,b["race"],r,len(rs)) for r in rs]
    x=np.asarray([[float(z[f]) for f in features] for z in rows],dtype=np.float64)
    raw=np.asarray(booster.predict(x),dtype=np.float64);base=raw/raw.sum()
    co=cutoff(b);recent=[z for z in runner_rows if str(z.get("startTimeUtc") or "")<co]
    fac,_,_=learn.build_runner_learning(recent,b["race"],rs,co,str(b["race"]["raceDate"]))
    adj=np.asarray([base[i]*float(fac[i]) for i in range(len(rs))]);full=adj/adj.sum()
    order=sorted(range(len(rs)),key=lambda i:(-float(full[i]),int(rs[i]["horseNo"])))
    return [int(rs[i]["horseNo"]) for i in order]
def canon(bt,c):
    nums=[int(x) for x in str(c).replace("→","-").split("-") if x.strip().isdigit()]
    if bt in ("ワイド","馬連","3連複"):nums.sort()
    return "-".join(map(str,nums))
def payout_map(b):
    out={}
    for x in b.get("payouts",[]):
        if x.get("payoutYen") is None:continue
        bt=str(x["betType"]);out[(bt,canon(bt,x["combination"]))]=int(x["payoutYen"])
    return out
def ret_for(b,bt,combo):
    hs={int(x) for x in combo.split("-")};ref=refunds.get(str(b["race"]["raceId"]),set())
    if hs&ref:return 1000
    return payout_map(b).get((bt,canon(bt,combo)),0)*10

POLICIES={
 "win1_wide12":lambda h:[("単勝",str(h[0])),("ワイド","-".join(map(str,sorted(h[:2]))))],
 "win1_umaren12":lambda h:[("単勝",str(h[0])),("馬連","-".join(map(str,sorted(h[:2]))))],
 "wide12_umaren12":lambda h:[("ワイド","-".join(map(str,sorted(h[:2])))),("馬連","-".join(map(str,sorted(h[:2]))))],
 "win1_umatan12":lambda h:[("単勝",str(h[0])),("馬単",f"{h[0]}-{h[1]}")],
 "wide12_trio123":lambda h:[("ワイド","-".join(map(str,sorted(h[:2])))),("3連複","-".join(map(str,sorted(h[:3]))))],
 "umaren12_trio123":lambda h:[("馬連","-".join(map(str,sorted(h[:2])))),("3連複","-".join(map(str,sorted(h[:3]))))],
}
stats={k:{"races":0,"stakeYen":0,"returnYen":0,"hits":0} for k in POLICIES}
periods={p:{k:{"races":0,"stakeYen":0,"returnYen":0,"hits":0} for k in POLICIES} for p in ("early","middle","recent")}
details=[]
for d in sorted(by_date):
    for b in by_date[d]:
        rid=str(b["race"]["raceId"])
        if d in selected and rid in selected[d] and b.get("results") and b.get("payouts"):
            h=weights(b)
            period="early" if d<="2026-09-13" else ("recent" if d>="2026-10-10" else "middle")
            row={"raceId":rid,"date":d,"top3":h[:3],"returns":{}}
            for name,fn in POLICIES.items():
                ts=fn(h);ret=sum(ret_for(b,bt,c) for bt,c in ts)
                row["returns"][name]=ret
                for target in (stats[name],periods[period][name]):
                    target["races"]+=1;target["stakeYen"]+=2000;target["returnYen"]+=ret;target["hits"]+=int(ret>0)
            details.append(row)
        core.update_feature_state_for_date(state,[b]);state["throughDate"]=d

for block in [stats,*periods.values()]:
    for s in block.values():
        s["roiPct"]=100*s["returnYen"]/s["stakeYen"] if s["stakeYen"] else None
        s["hitPct"]=100*s["hits"]/s["races"] if s["races"] else None
best=max(stats,key=lambda k:stats[k]["roiPct"] if stats[k]["roiPct"] is not None else -1)
report={"selectionDates":{d:len(v) for d,v in selected.items()},"evaluatedRaces":len(details),"stats":stats,"periods":periods,"best":best,"details":details}
(ROOT/"artifacts"/"rank-ticket-policy-validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
print("RANK_POLICY_RESULT "+json.dumps({k:v for k,v in report.items() if k!="details"},ensure_ascii=False))
