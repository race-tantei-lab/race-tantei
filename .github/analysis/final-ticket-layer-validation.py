#!/usr/bin/env python3
from __future__ import annotations
import collections, datetime as dt, gzip, importlib.util, itertools, json, math, os, pathlib, sys, urllib.request
import lightgbm as lgb
import numpy as np

ROOT=pathlib.Path(__file__).resolve().parents[2]
FROM="2026-08-10"; TO="2026-10-12"; ODDS=ROOT/"artifacts"/"ticket-layer-official-odds.jsonl.gz"
A=os.environ["CLOUDFLARE_ACCOUNT_ID"];D=os.environ["CLOUDFLARE_D1_DATABASE_ID"];T=os.environ["CLOUDFLARE_API_TOKEN"];U=f"https://api.cloudflare.com/client/v4/accounts/{A}/d1/database/{D}/query"
def q(sql,p=None):
    req=urllib.request.Request(U,data=json.dumps({"sql":sql,"params":p or []},ensure_ascii=False).encode(),method="POST",headers={"Authorization":f"Bearer {T}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r:x=json.loads(r.read().decode())
    if not x.get("success"):raise RuntimeError(x)
    return (x.get("result") or [{}])[0].get("results") or []
class Collector:
    @staticmethod
    def d1_query(sql,params=None):return q(sql,params)
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
core=load(ROOT/"scripts"/"ten-year-production-core.py","tl_core");learn=load(ROOT/"scripts"/"live-recency-learning.py","tl_learn");gen=load(ROOT/"scripts"/"generate-ten-year-live-bets.py","tl_gen")
cfg=core.load_config();features=list(cfg["runnerProbabilityModel"]["features"]);booster=lgb.Booster(model_file=str(core.MODEL_PATH))
state=core.load_feature_state();assert state["throughDate"]=="2026-08-09"

selrows=q("SELECT state_key k,state_value v FROM rt_system_state WHERE state_key LIKE 'final_daily_selection:%' AND state_key>=? AND state_key<=? ORDER BY state_key",[f"final_daily_selection:{FROM}",f"final_daily_selection:{TO}"])
selected={}
for z in selrows:
    d=str(z["k"]).split(":")[-1]
    if "2026-08-15"<=d<="2026-10-12":
        p=json.loads(z["v"]);selected[d]=set(str(x["raceId"]) for x in p.get("selected",[]) if x.get("raceId"))
expected=sum(len(v) for v in selected.values());assert expected==245,(expected,{k:len(v) for k,v in selected.items()})

odds_art={}
with gzip.open(ODDS,"rt",encoding="utf-8") as fh:
    for line in fh:
        if line.strip():
            x=json.loads(line);odds_art[str(x["raceId"])]=x
assert 230<=len(odds_art)<=238,len(odds_art)

bundles=core.bundles_from_d1(Collector,"race_date>=? AND race_date<=?",[FROM,TO]);bydate=collections.defaultdict(list)
for b in bundles:bydate[str(b["race"]["raceDate"])].append(b)
for d in bydate:bydate[d].sort(key=lambda b:(str(b["race"].get("startTimeUtc") or ""),str(b["race"]["raceId"])))
runner_rows=[]
for b in bundles:
    race=b["race"];res={int(x["horseNo"]):x for x in b.get("results",[]) if x.get("horseNo") is not None}
    for r in [x for x in b.get("runners",[]) if (x.get("runnerStatus") or "active")=="active"]:
        rr=res.get(int(r["horseNo"]))
        if not rr or rr.get("finishPosition") is None:continue
        runner_rows.append({"raceId":str(race["raceId"]),"raceDate":str(race["raceDate"]),"startTimeUtc":str(race.get("startTimeUtc") or ""),"venue":str(race.get("venue") or ""),"surface":str(race.get("surface") or ""),"distanceM":race.get("distanceM"),"horseNo":int(r["horseNo"]),"horseName":str(r.get("horseName") or ""),"jockey":str(r.get("jockey") or ""),"trainer":str(r.get("trainer") or ""),"winOdds":r.get("winOdds"),"finishPosition":rr.get("finishPosition")})
bet_rows=q("""SELECT b.race_id raceId,b.bet_type betType,b.stake_yen stakeYen,COALESCE(b.return_yen,0) returnYen,b.assumed_odds assumedOdds,r.race_date raceDate,r.start_time_utc startTimeUtc,r.venue
 FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id WHERE r.race_date BETWEEN ? AND ? AND b.source_prediction_id=-2 AND b.course='ライト' AND b.settlement_status='settled' ORDER BY r.start_time_utc,b.race_id,b.id""",[FROM,TO])
refundrows=q("SELECT race_id raceId,refund_horse_nos_json refunds FROM rt_races WHERE race_date BETWEEN ? AND ?",[FROM,TO]);refunds={}
for x in refundrows:
    try:refunds[str(x["raceId"])]=set(int(v) for v in json.loads(x.get("refunds") or "[]"))
    except:refunds[str(x["raceId"])]=set()

BET_ORDER=("単勝","ワイド","馬連","馬単","3連複","3連単")
VARIANTS={
 "current":{"prefilter":"ev","power":0.4,"topk":None,"includeTop1":False},
 "consistent00":{"prefilter":"score","power":0.0,"topk":None,"includeTop1":False},
 "consistent01":{"prefilter":"score","power":0.1,"topk":None,"includeTop1":False},
 "consistent02":{"prefilter":"score","power":0.2,"topk":None,"includeTop1":False},
 "consistent03":{"prefilter":"score","power":0.3,"topk":None,"includeTop1":False},
 "consistent04":{"prefilter":"score","power":0.4,"topk":None,"includeTop1":False},
 "consistent05":{"prefilter":"score","power":0.5,"topk":None,"includeTop1":False},
 "top5_consistent01":{"prefilter":"score","power":0.1,"topk":5,"includeTop1":False},
 "top5_consistent02":{"prefilter":"score","power":0.2,"topk":5,"includeTop1":False},
 "top5_consistent03":{"prefilter":"score","power":0.3,"topk":5,"includeTop1":False},
 "include_top1_consistent01":{"prefilter":"score","power":0.1,"topk":None,"includeTop1":True},
 "include_top1_consistent02":{"prefilter":"score","power":0.2,"topk":None,"includeTop1":True},
 "include_top1_consistent03":{"prefilter":"score","power":0.3,"topk":None,"includeTop1":True},
}

def oddv(v):
    if isinstance(v,list):
        z=[float(x) for x in v if x is not None];return sum(z)/len(z) if z else None
    try:return float(v)
    except:return None
def omap(x):
    hs=[int(v) for v in x["horses"]];rid=str(x["raceId"]);o={}
    for h,v in zip(hs,x["win"]):
        z=oddv(v)
        if z:o[(rid,"単勝",str(h))]=z
    pairs=list(itertools.combinations(hs,2));exact=list(itertools.permutations(hs,2));trios=list(itertools.combinations(hs,3));tris=list(itertools.permutations(hs,3))
    for key,bt,seq in (("wide","ワイド",pairs),("umaren","馬連",pairs),("umatan","馬単",exact),("trio","3連複",trios),("trifecta","3連単",tris)):
        for p,v in zip(seq,x[key]):
            z=oddv(v)
            if z:o[(rid,bt,"-".join(map(str,sorted(p) if bt in ("ワイド","馬連","3連複") else p)))]=z
    return o
def cutoff(b):
    x=dt.datetime.fromisoformat(str(b["race"]["startTimeUtc"]).replace("Z","+00:00"));return (x-dt.timedelta(seconds=1)).astimezone(dt.timezone.utc).isoformat().replace("+00:00","Z")
def model(b):
    rs=[r for r in b.get("runners",[]) if (r.get("runnerStatus") or "active")=="active"];rs.sort(key=lambda r:int(r["horseNo"]))
    rows=[core.ml_feature_row(state,b["race"],r,len(rs)) for r in rs];x=np.asarray([[float(z[f]) for f in features] for z in rows],dtype=np.float64)
    raw=np.asarray(booster.predict(x),dtype=np.float64);base=raw/raw.sum();co=cutoff(b);recent=[z for z in runner_rows if str(z.get("startTimeUtc") or "")<co]
    fac,_,_=learn.build_runner_learning(recent,b["race"],rs,co,str(b["race"]["raceDate"]));adj=np.asarray([base[i]*float(fac[i]) for i in range(len(rs))]);w=adj/adj.sum()
    rank=sorted(range(len(rs)),key=lambda i:(-float(w[i]),int(rs[i]["horseNo"])))
    return rs,w,rank,co
def choose(rid,rs,w,rank,co,b,odds,var):
    rankpos={i:k+1 for k,i in enumerate(rank)};top1=rank[0];bl=learn.build_bet_learning([x for x in bet_rows if str(x.get("startTimeUtc") or "")<co],co,str(b["race"]["raceDate"]))
    best=[]
    for bt in BET_ORDER:
        cand=[]
        for pos in gen.combo_positions(bt,len(rs)):
            if var["topk"] and any(rankpos[i]>var["topk"] for i in pos):continue
            if var["includeTop1"] and top1 not in pos:continue
            combo=gen.combo_text(bt,pos,[int(r["horseNo"]) for r in rs]);od=odds.get((rid,bt,combo))
            if od is None:continue
            p=float(core.combination_probability(bt,pos,w))
            if p<=0 or not math.isfinite(p):continue
            fac=float(learn.bet_factor(bl,bt,str(b["race"].get("venue") or ""),od))
            score=math.log(p)+var["power"]*math.log(od)+math.log(fac)
            ev=p*od*fac
            cand.append({"bt":bt,"combo":combo,"p":p,"od":od,"fac":fac,"score":score,"ev":ev})
        if not cand:raise RuntimeError(f"NO_CAND:{rid}:{bt}:{var}")
        if var["prefilter"]=="ev":
            cand.sort(key=lambda x:(-x["ev"],x["od"],x["combo"]));cand=cand[:5]
            cand.sort(key=lambda x:(-x["score"],-x["p"],x["combo"]))
        else:
            cand.sort(key=lambda x:(-x["score"],-x["p"],x["combo"]));cand=cand[:5]
        best.append(cand[0])
    best.sort(key=lambda x:(-x["score"],BET_ORDER.index(x["bt"]),x["combo"]))
    return best[:2]
def canon(bt,c):
    ns=[int(x) for x in str(c).split("-") if x.strip().isdigit()]
    if bt in ("ワイド","馬連","3連複"):ns.sort()
    return "-".join(map(str,ns))
def settle(b,tix):
    pays={(str(x["betType"]),canon(str(x["betType"]),x["combination"])):int(x["payoutYen"]) for x in b.get("payouts",[]) if x.get("payoutYen") is not None}
    ref=refunds.get(str(b["race"]["raceId"]),set());ret=0
    for t in tix:
        hs={int(x) for x in t["combo"].split("-")};ret+=1000 if hs&ref else pays.get((t["bt"],canon(t["bt"],t["combo"])),0)*10
    return ret

stats={k:{"races":0,"stakeYen":0,"returnYen":0,"hits":0} for k in VARIANTS}
periods={p:{k:{"races":0,"stakeYen":0,"returnYen":0,"hits":0} for k in VARIANTS} for p in ("early","middle","recent")}
venue_stats=collections.defaultdict(lambda:{k:{"races":0,"stakeYen":0,"returnYen":0,"hits":0} for k in VARIANTS})
sequence={k:[] for k in VARIANTS}
for d in sorted(bydate):
    for b in bydate[d]:
        rid=str(b["race"]["raceId"])
        if d in selected and rid in selected[d]:
            if rid not in odds_art or not b.get("results") or not b.get("payouts"):
                continue
            rs,w,rank,co=model(b);oo=omap(odds_art[rid]);period="early" if d<="2026-09-13" else ("recent" if d>="2026-10-10" else "middle")
            for name,var in VARIANTS.items():
                t=choose(rid,rs,w,rank,co,b,oo,var);ret=settle(b,t)
                for s in (stats[name],periods[period][name],venue_stats[str(b["race"].get("venue") or "")][name]):
                    s["races"]+=1;s["stakeYen"]+=2000;s["returnYen"]+=ret;s["hits"]+=int(ret>0)
                sequence[name].append({"date":d,"raceId":rid,"returnYen":ret})
        core.update_feature_state_for_date(state,[b]);state["throughDate"]=d
def finalize(block):
    for s in block.values():
        s["roiPct"]=100*s["returnYen"]/s["stakeYen"] if s["stakeYen"] else None
        s["hitPct"]=100*s["hits"]/s["races"] if s["races"] else None
for block in [stats,*periods.values(),*venue_stats.values()]: finalize(block)

risk={}
for name,rows in sequence.items():
    bankroll=0;peak=0;max_dd=0;cur_loss=0;max_loss=0
    returns=[]
    for row in rows:
        pnl=int(row["returnYen"])-2000
        bankroll+=pnl;peak=max(peak,bankroll);max_dd=max(max_dd,peak-bankroll)
        if row["returnYen"]>0:cur_loss=0
        else:cur_loss+=1;max_loss=max(max_loss,cur_loss)
        returns.append(int(row["returnYen"]))
    risk[name]={"maxConsecutiveMisses":max_loss,"maxDrawdownYen":max_dd,"endingProfitYen":bankroll,
                "positiveReturnRaces":sum(1 for x in returns if x>0)}

robust={}
for name in VARIANTS:
    slices=[periods[p][name]["roiPct"] for p in ("early","middle","recent") if periods[p][name]["races"]]
    venue_rois=[venue_stats[v][name]["roiPct"] for v in venue_stats if venue_stats[v][name]["races"]>=5]
    robust[name]={
      "minPeriodRoiPct":min(slices) if slices else None,
      "medianPeriodRoiPct":float(np.median(slices)) if slices else None,
      "profitablePeriods":sum(1 for x in slices if x>=100),
      "minVenueRoiPct":min(venue_rois) if venue_rois else None,
      "profitableVenues":sum(1 for x in venue_rois if x>=100),
      "score":(stats[name]["roiPct"] or 0)+0.35*(min(slices) if slices else 0)-0.002*risk[name]["maxDrawdownYen"]-0.5*risk[name]["maxConsecutiveMisses"],
    }
ranked=sorted(VARIANTS,key=lambda n:(-robust[n]["score"],-(stats[n]["roiPct"] or 0),risk[n]["maxDrawdownYen"]))
eligible_ids=set(odds_art)
missing_eligibility=sorted({rid for ids in selected.values() for rid in ids}-eligible_ids)
report={"recordedRaces":expected,"officialOddsRaces":len(odds_art),"comparedRaces":stats["current"]["races"],"unevaluatedIds":missing_eligibility,"stats":stats,"periods":periods,"venues":dict(venue_stats),"risk":risk,"robustness":robust,"ranked":ranked}
print("TICKET_LAYER_FULL_VALIDATION "+json.dumps(report,ensure_ascii=False))
