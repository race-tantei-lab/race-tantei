import gzip
import itertools
import json
import math
import pickle
from collections import defaultdict
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "artifacts" / "speed-analysis-input"
RUN = ROOT / "artifacts" / "speed-runner-oos"
OUT = ROOT / "artifacts" / "speed-high-order-evaluation"
OUT.mkdir(parents=True, exist_ok=True)

with gzip.open(IN / "completion-analysis-dataset.pkl.gz", "rb") as f:
    D = pickle.load(f)
meta = pd.read_pickle(RUN / "runner-meta.pkl.gz").reset_index(drop=True)
pz = np.load(RUN / "runner-oos-probabilities.npz")
normalP = np.asarray(npz["modelP"], dtype=np.float64)
residP = np.asarray(npz["residualP"], dtype=np.float64)

races = D["races"]
race_ids = [r["raceId"] for r in races]
N = len(race_ids)
race_index = {rid: i for i, rid in enumerate(race_ids)}
dates = []
for r in races:
    if not dates or dates[-1] != r["raceDate"]:
        dates.append(r["raceDate"])
date_index = {d: i for i, d in enumerate(dates)}
race_date_idx = np.array([date_index[r["raceDate"]] for r in races], dtype=np.int16)
if N != 7695 or len(dates) != 244:
    raise RuntimeError(f"FIXED_ARCHIVE:{N}:{len(dates)}")

odds_records = []
with gzip.open(IN / "all7695-official-odds.jsonl.gz", "rt", encoding="utf-8") as f:
    odds_records = [json.loads(x) for x in f if x.strip()]
if len(odds_records) != N or [x["raceId"] for x in odds_records] != race_ids:
    raise RuntimeError("ODDS_ORDER_MISMATCH")

race_rows = defaultdict(dict)
for i, r in meta.iterrows():
    race_rows[r["raceId"]][int(r["horseNo"])] = int(i)

name_map = {"単勝":"win","ワイド":"wide","馬連":"umaren","馬単":"umatan","3連複":"trio","3連単":"trifecta"}
payout = defaultdict(lambda: defaultdict(dict))
for x in D["payouts"]:
    bt = name_map.get(x["betType"])
    if not bt:
        continue
    nums = [int(z) for z in __import__('re').findall(r"\d+", str(x["combination"]))]
    if not nums:
        continue
    tup = tuple(nums)
    if bt in ("wide","umaren","trio"):
        tup = tuple(sorted(tup))
    payout[x["raceId"]][bt][tup] = max(int(x["payoutYen"]), payout[x["raceId"]][bt].get(tup, 0))

EXPERTS = [
    ("market", None, 0.0),
    ("normal25","normal",0.25),("normal50","normal",0.5),("normal75","normal",0.75),("normal100","normal",1.0),
    ("residual25","residual",0.25),("residual50","residual",0.5),("residual75","residual",0.75),("residual100","residual",1.0),
]
E = len(EXPERTS); TOPK = 16; COLD = 2
BET_TYPES = ["win","wide","umaren","umatan","trio","trifecta"]

struct_cache = {}
def structures(n):
    if n in struct_cache:
        return struct_cache[n]
    pairs = np.asarray(list(itertools.combinations(range(n),2)), dtype=np.int16)
    exacta = np.asarray([(a,b) for a in range(n) for b in range(n) if a!=b], dtype=np.int16)
    trio = np.asarray(list(itertools.combinations(range(n),3)), dtype=np.int16)
    trifecta = np.asarray([(a,b,c) for a in range(n) for b in range(n) for c in range(n) if len({a,b,c})==3], dtype=np.int16)
    pair_index = {tuple(x):i for i,x in enumerate(pairs.tolist())}
    struct_cache[n] = (pairs, exacta, trio, trifecta, pair_index)
    return struct_cache[n]

def ordered3(p,a,b,c):
    return p[a] * p[b] / max(1e-12,1-p[a]) * p[c] / max(1e-12,1-p[a]-p[b])

def model_combo_probs(p):
    p = np.asarray(p,dtype=float); p = p/p.sum()
    n=len(p); pairs, exactas, trios, trifectas, pair_index=structures(n)
    ex = p[exactas[:,0]] * p[exactas[:,1]] / np.maximum(1e-12, 1-p[exactas[:,0]])
    ex_map={(int(a),int(b)):float(v) for (a,b),v in zip(exactas,ex)}
    q=np.array([ex_map[(int(a),int(b))]+ex_map[(int(b),int(a))] for a,b in pairs],dtype=float)
    tri=np.empty(len(trios),dtype=float)
    for i,(a,b,c) in enumerate(trios):
        a=int(a);b=int(b);c=int(c)
        tri[i]=sum(ordered3(p,*perm) for perm in ((a,b,c),(a,c,b),(b,a,c),(b,c,a),(c,a,b),(c,b,a)))
    wide=np.zeros(len(pairs),dtype=float)
    for val,(a,b,c) in zip(tri,trios):
        aa,bb,cc=int(a),int(b),int(c)
        wide[pair_index[tuple(sorted((aa,bb)))]] += val
        wide[pair_index[tuple(sorted((aa,cc)))]] += val
        wide[pair_index[tuple(sorted((bb,cc)))]] += val
    tf = (p[trifectas[:,0]] * p[trifectas[:,1]] / np.maximum(1e-12,1-p[trifectas[:,0]]) *
          p[trifectas[:,2]] / np.maximum(1e-12,1-p[trifectas[:,0]]-p[trifectas[:,1]]))
    return {"win":p,"wide":wide,"umaren":q,"umatan":ex,"trio":tri,"trifecta":tf}

def official_values(rec,bt):
    vals=rec[bt]
    return np.asarray([np.nan if v is None else float(v[0] if isinstance(v,list) else v) for v in vals],dtype=float)

def official_market(vals,mass):
    inv=np.where(np.isfinite(vals)&(vals>0),1.0/vals,0.0); s=inv.sum()
    return inv/s*mass if s>0 else inv

def combo_tuples(horses,bt):
    if bt=="win": return [(h,) for h in horses]
    if bt in ("wide","umaren"): return list(itertools.combinations(horses,2))
    if bt=="umatan": return [(a,b) for a in horses for b in horses if a!=b]
    if bt=="trio": return list(itertools.combinations(horses,3))
    return [(a,b,c) for a in horses for b in horses for c in horses if len({a,b,c})==3]

def runner_prob(rid,horses,arr):
    v=np.asarray([float(arr[race_rows[rid][int(h)]]) for h in horses],dtype=float); s=v.sum()
    return v/s if s>0 else np.ones(len(horses))/len(horses)

scores={bt:np.full((E,N,TOPK),np.nan,np.float32) for bt in BET_TYPES}
returns={bt:np.zeros((E,N,TOPK),np.int32) for bt in BET_TYPES}
counts={bt:np.zeros((E,N),np.int8) for bt in BET_TYPES}
for ri,rec in enumerate(odds_records):
    rid=rec["raceId"]; horses=[int(x) for x in rec["horses"]]
    pn=model_combo_probs(runner_prob(rid,horses,normalP)); pr=model_combo_probs(runner_prob(rid,horses,residP))
    for bt in BET_TYPES:
        vals=official_values(rec,bt); mass=3.0 if bt=="wide" else 1.0; pm=official_market(vals,mass)
        combos=combo_tuples(horses,bt); actual_map=payout[rid][bt]
        actual=np.asarray([actual_map.get(tuple(sorted(c)) if bt in ("wide","umaren","trio") else c,0) for c in combos],dtype=np.int32)
        for ei,(name,fam,w) in enumerate(EXPERTS):
            if fam is None: pp=pm
            else: pp=(1-w)*pm+w*(pn[bt] if fam=="normal" else pr[bt])
            sc=pp*vals; valid=np.flatnonzero(np.isfinite(sc)&(vals>0)); k=min(TOPK,len(valid)); counts[bt][ei,ri]=k
            if k:
                if len(valid)<=k: pick=valid[np.argsort(-sc[valid],kind='stable')]
                else:
                    sub=valid[np.argpartition(sc[valid],-k)[-k:]]; pick=sub[np.argsort(-sc[sub],kind='stable')]
                pick=pick[:k]; scores[bt][ei,ri,:k]=sc[pick].astype(np.float32); returns[bt][ei,ri,:k]=actual[pick]
    if ri%500==0:
        print(json.dumps({"candidateRace":ri,"raceId":rid}),flush=True)

venue_vals={x:i+1 for i,x in enumerate(sorted({r['venue'] for r in races}))}
surface_vals={x:i+1 for i,x in enumerate(sorted(meta['surface'].unique()))}
bucket_vals={x:i+1 for i,x in enumerate(sorted(meta['distBucket'].unique()))}
class_vals={x:i+1 for i,x in enumerate(sorted(meta['raceClass'].unique()))}
race_base=np.zeros((N,15),np.float32)
for ri,rid in enumerate(race_ids):
    g=meta[meta['raceIndex']==ri]; ids=g.index.to_numpy(int); mp=g['marketP'].to_numpy(float); pn=normalP[ids]; pr=residP[ids]; row=g.iloc[0]
    ent=-float(np.sum(mp*np.log(mp+1e-12)))
    race_base[ri]=[float(row['fieldSize']),float(row['raceNo']),float(row['distanceM']),float(venue_vals.get(row['venue'],0)),
                   float(surface_vals.get(row['surface'],0)),float(bucket_vals.get(row['distBucket'],0)),float(class_vals.get(row['raceClass'],0)),
                   float(np.mean(np.abs(pn-mp))),float(np.max(np.abs(pn-mp))),float(np.mean(np.abs(pr-mp))),float(np.max(np.abs(pr-mp))),
                   ent,float(np.max(mp)),float(np.max(pn)),float(np.max(pr))]

COURSES={
 'standard':{'budget':5000,'cap':5,'types':['win','wide','umaren','umatan','trio']},
 'premium':{'budget':10000,'cap':10,'types':['win','wide','umaren','umatan','trio','trifecta']}
}
prior_n=40.0; prior_sum=32.0
stats={c:{bt:[[0.0,0] for _ in range(E)] for bt in cfg['types']} for c,cfg in COURSES.items()}
def shr(c,bt,e):
    s,n=stats[c][bt][e]; return (s+prior_sum)/(n+prior_n)
def choose(c,bt):
    vals=[shr(c,bt,e) for e in range(E)]; mx=max(vals)
    if abs(vals[COLD]-mx)<1e-12:return COLD
    return max(range(E),key=lambda e:(vals[e],-e))
def summary(bt,e,ri,perf):
    k=int(counts[bt][e,ri]); s=np.asarray(scores[bt][e,ri,:k],float); s=s[np.isfinite(s)]
    if len(s)==0:s=np.array([0.0])
    one=[0.0]*E;one[e]=1.0
    return [float(s[0]),float(s[:3].mean()),float(s[:5].mean()),float(s[:5].std()),float(perf)]+one

def allocate(course,chosen,perf,ri):
    cfg=COURSES[course]; units={}; total=0; pool=[]
    for bt in cfg['types']:
        e=chosen[bt]; k=int(counts[bt][e,ri])
        if k<1: raise RuntimeError(f"NO_TICKET:{course}:{bt}:{ri}")
        units[(bt,0)]=1; total+=1
        for j in range(k):
            sc=float(scores[bt][e,ri,j])
            if np.isfinite(sc):pool.append((max(0,sc)*max(0,perf[bt]),bt,j))
    pool.sort(key=lambda x:(-x[0],x[1],x[2])); target=cfg['budget']//100; rem=target-total
    for util,bt,j in pool:
        if rem<=0:break
        cur=units.get((bt,j),0); add=min(cfg['cap']-cur,rem)
        if add>0:units[(bt,j)]=cur+add;rem-=add
    if rem:raise RuntimeError(f"BUDGET_UNFILLED:{course}:{ri}:{rem}")
    total_ret=0;largest=0;bytype=defaultdict(int)
    for (bt,j),u in units.items():
        e=chosen[bt]; val=int(returns[bt][e,ri,j])*u;total_ret+=val;largest=max(largest,val);bytype[bt]+=u*100
    if sum(bytype.values())!=cfg['budget'] or any(bytype[x]<100 for x in cfg['types']):raise RuntimeError("STRUCTURE_GATE")
    return total_ret,largest

Xhist={c:[] for c in COURSES}; yhist={c:[] for c in COURSES}; selectors={c:None for c in COURSES}
results={c:{'stake':0,'return':0,'largest':0,'selected':[],'periods':defaultdict(lambda:[0,0]),'trace':[]} for c in COURSES}
for di,date in enumerate(dates):
    idx=np.flatnonzero(race_date_idx==di)
    day_cache={}
    for c,cfg in COURSES.items():
        chosen={bt:(COLD if di<30 else choose(c,bt)) for bt in cfg['types']}; perf={bt:(0.8 if di<30 else shr(c,bt,chosen[bt])) for bt in cfg['types']}
        dx=[];dy=[];info=[];cold=[]
        for ri in idx:
            feat=list(race_base[ri]); cs=[]
            for bt in cfg['types']:
                e=chosen[bt];feat.extend(summary(bt,e,ri,perf[bt]));k=int(counts[bt][e,ri]);ss=np.asarray(scores[bt][e,ri,:k],float);ss=ss[np.isfinite(ss)];cs.append(float(ss[:3].mean()) if len(ss) else 0.0)
            rr,lg=allocate(c,chosen,perf,int(ri));dx.append(feat);dy.append(rr/cfg['budget']);info.append((rr,lg));cold.append(float(np.mean(cs)))
        dx=np.asarray(dx,np.float32);dy=np.asarray(dy,np.float32)
        if di in (30,90,150,210):
            p={"objective":"huber","learning_rate":0.04,"num_leaves":15,"min_data_in_leaf":80,"feature_fraction":0.8,"max_bin":63,"verbosity":-1,"num_threads":4,"seed":20260810,"force_col_wise":True}
            selectors[c]=lgb.train(p,lgb.Dataset(np.asarray(Xhist[c],np.float32),label=np.asarray(yhist[c],np.float32)),num_boost_round=100,callbacks=[lgb.log_evaluation(0)])
        sel_score=np.asarray(cold) if di<30 or selectors[c] is None else selectors[c].predict(dx)
        byv=defaultdict(list)
        for loc,ri in enumerate(idx):byv[races[int(ri)]['venue']].append(loc)
        loc_selected=[]
        for venue,locs in byv.items():
            pick=sorted(locs,key=lambda j:(-float(sel_score[j]),int(races[int(idx[j])]['raceNo'])))[:5]
            if len(pick)!=5:raise RuntimeError(f"FIVE_RACE_GATE:{c}:{date}:{venue}:{len(pick)}")
            loc_selected.extend(pick)
        for loc in loc_selected:
            ri=int(idx[loc]);rr,lg=info[loc];R=results[c];R['stake']+=cfg['budget'];R['return']+=rr;R['largest']=max(R['largest'],lg);R['selected'].append(ri)
            half=f"{date[:4]}-H{1 if int(date[5:7])<=6 else 2}";R['periods'][half][0]+=cfg['budget'];R['periods'][half][1]+=rr
        Xhist[c].extend(dx.tolist());yhist[c].extend(dy.tolist());day_cache[c]=(chosen,perf)
    # Full-information expert updates only after all course/date decisions are frozen.
    for c,cfg in COURSES.items():
        for bt in cfg['types']:
            for e in range(E):
                for ri in idx:
                    k=min(10,int(counts[bt][e,int(ri)]))
                    if k:
                        stats[c][bt][e][0]+=float(np.asarray(returns[bt][e,int(ri),:k],float).sum()/100.0);stats[c][bt][e][1]+=k
    if di in (0,29,30,89,90,149,150,209,210,243):
        for c in COURSES:
            R=results[c];R['trace'].append({'dateIndex':di,'date':date,'selected':len(R['selected']),'roiPct':100*R['return']/R['stake'] if R['stake'] else 0})
        print(json.dumps({'dateIndex':di,'date':date,'standardRoi':results['standard']['trace'][-1]['roiPct'],'premiumRoi':results['premium']['trace'][-1]['roiPct']}),flush=True)

out={}
for c,cfg in COURSES.items():
    R=results[c];roi=100*R['return']/R['stake'];trim=100*(R['return']-R['largest'])/R['stake']
    out[c]={"races":len(R['selected']),"selectedUnique":len(set(R['selected'])),"stakeYen":R['stake'],"returnYen":R['return'],"roiPct":roi,"largestTicketReturnYen":R['largest'],"trimmedRoiPct":trim,
            "periods":{k:{'stake':v[0],'return':v[1],'roiPct':100*v[1]/v[0]} for k,v in sorted(R['periods'].items())},"trace":R['trace'],"completionGatePass":bool(roi>=200 and trim>=100 and len(R['selected'])==3210)}
summary={"status":"not_a_model_unless_all_completion_gates_pass","experts":[x[0] for x in EXPERTS],"standard":out['standard'],"premium":out['premium'],"officialOddsOnly":True,"sameDateLeakage":False,"syntheticOddsUsed":False}
(OUT/'speed-high-order-result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False),flush=True)
