import gc
import gzip
import itertools
import json
import math
import pickle
import tempfile
from collections import defaultdict
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "artifacts" / "speed-analysis-input"
RUN = ROOT / "artifacts" / "speed-runner-oos"
OUT = ROOT / "artifacts" / "ticket-market-error-light"
OUT.mkdir(parents=True, exist_ok=True)

with gzip.open(IN / "completion-analysis-dataset.pkl.gz", "rb") as f:
    D = pickle.load(f)
meta = pd.read_pickle(RUN / "runner-meta.pkl.gz").reset_index(drop=True)
Xr = np.load(RUN / "runner-features.npy", mmap_mode="r")
npz = np.load(RUN / "runner-oos-probabilities.npz")
normalP = np.asarray(npz["modelP"], dtype=np.float64)
residP = np.asarray(npz["residualP"], dtype=np.float64)
F = Xr.shape[1]

races = D["races"]
race_ids = [r["raceId"] for r in races]
N = len(race_ids)
dates = []
for r in races:
    if not dates or dates[-1] != r["raceDate"]:
        dates.append(r["raceDate"])
date_index = {d:i for i,d in enumerate(dates)}
race_date_idx = np.asarray([date_index[r["raceDate"]] for r in races], dtype=np.int16)
if N != 7695 or len(dates) != 244:
    raise RuntimeError(f"FIXED_ARCHIVE:{N}:{len(dates)}")

with gzip.open(IN / "all7695-official-odds.jsonl.gz", "rt", encoding="utf-8") as f:
    odds_records = [json.loads(line) for line in f if line.strip()]
if len(odds_records) != N or [x["raceId"] for x in odds_records] != race_ids:
    raise RuntimeError("OFFICIAL_ODDS_ORDER")

race_rows = defaultdict(dict)
for i,r in meta.iterrows():
    race_rows[r["raceId"]][int(r["horseNo"])] = int(i)

payout = defaultdict(lambda: defaultdict(dict))
name_map = {"単勝":"win","ワイド":"wide","馬連":"umaren"}
import re
for x in D["payouts"]:
    bt=name_map.get(x["betType"])
    if not bt: continue
    nums=tuple(int(z) for z in re.findall(r"\d+",str(x["combination"])))
    if not nums: continue
    if bt in ("wide","umaren"): nums=tuple(sorted(nums))
    payout[x["raceId"]][bt][nums]=max(int(x["payoutYen"]),payout[x["raceId"]][bt].get(nums,0))

BTYPES=("win","wide","umaren")
FAMILIES=("rawResidual","underdogResidual","realizedValue")
SHRINKS=(0.25,0.5,0.75,1.0)
EXPERTS=[("market",None,0.0)]+[(f,f,s) for f in FAMILIES for s in SHRINKS]
E=len(EXPERTS); TOPK=12; COLD=1+SHRINKS.index(0.5)  # rawResidual-0.5
BLOCKS=((30,90),(90,150),(150,210),(210,244))

pair_cache={}
def pair_indices(n):
    if n not in pair_cache:
        pair_cache[n]=np.asarray(list(itertools.combinations(range(n),2)),dtype=np.int16)
    return pair_cache[n]

def official_float(v):
    if v is None: return np.nan
    if isinstance(v,list): v=v[0]
    try:
        v=float(v); return v if v>0 else np.nan
    except Exception:return np.nan

def normalize_market(vals,mass=1.0):
    inv=np.where(np.isfinite(vals)&(vals>0),1.0/vals,0.0); s=inv.sum()
    return inv/s*mass if s>0 else inv

def runner_prob(rid,horses,arr):
    v=np.asarray([float(arr[race_rows[rid][h]]) for h in horses],dtype=float);s=v.sum()
    return v/s if s>0 else np.ones(len(horses))/max(1,len(horses))

def combo_pair_probs(p):
    p=np.asarray(p,dtype=float);p=p/p.sum();pairs=pair_indices(len(p))
    a=p[pairs[:,0]];b=p[pairs[:,1]]
    q=a*b/np.maximum(1e-12,1-a)+b*a/np.maximum(1e-12,1-b)
    # exact top-3 inclusion for each pair by summing all ordered top3 permutations containing the pair
    w=np.zeros(len(pairs),dtype=float); idx={tuple(x):i for i,x in enumerate(pairs.tolist())}
    for c in range(len(p)):
        others=[x for x in range(len(p)) if x!=c]
        for ii in range(len(others)):
            a0=others[ii]
            for jj in range(ii+1,len(others)):
                b0=others[jj]
                triple=(a0,b0,c)
                s=0.0
                for x,y,z in itertools.permutations(triple,3):
                    s+=p[x]*p[y]/max(1e-12,1-p[x])*p[z]/max(1e-12,1-p[x]-p[y])
                w[idx[tuple(sorted((a0,b0)))]]+=s
                w[idx[tuple(sorted((a0,c)))]]+=s
                w[idx[tuple(sorted((b0,c)))]]+=s
    # triple loop above counts each unordered triple three times (once for each c); correct it.
    w/=3.0
    return q,w

def combo_tuples(horses,bt):
    return [(h,) for h in horses] if bt=="win" else list(itertools.combinations(horses,2))

# candidate arrays for each expert/bet/race
candU={bt:np.full((E,N,TOPK),np.nan,np.float32) for bt in BTYPES}
candR={bt:np.zeros((E,N,TOPK),np.int32) for bt in BTYPES}
candC={bt:np.zeros((E,N),np.int8) for bt in BTYPES}
metrics=[]

model_params={"objective":"huber","learning_rate":0.04,"num_leaves":21,"min_data_in_leaf":100,
              "feature_fraction":0.8,"max_bin":63,"verbosity":-1,"num_threads":4,"seed":20260808,"force_col_wise":True}

def rank_and_store(bt,ri,ei,utility,actual):
    valid=np.flatnonzero(np.isfinite(utility));k=min(TOPK,len(valid));candC[bt][ei,ri]=k
    if not k:return
    if len(valid)<=k:pick=valid[np.argsort(-utility[valid],kind='stable')]
    else:
        sub=valid[np.argpartition(utility[valid],-k)[-k:]];pick=sub[np.argsort(-utility[sub],kind='stable')]
    pick=pick[:k];candU[bt][ei,ri,:k]=utility[pick].astype(np.float32);candR[bt][ei,ri,:k]=actual[pick]

def build_bt(bt):
    # exact active ticket count and dimensions
    counts=[]
    for rec in odds_records:
        active=race_rows[rec["raceId"]];n=sum(1 for h in rec["horses"] if int(h) in active)
        counts.append(n if bt=="win" else math.comb(n,2))
    total=sum(counts);dim=F+6 if bt=="win" else 2*F+7
    tmp=Path(tempfile.mkdtemp(prefix=f"merr-{bt}-"))
    X=np.lib.format.open_memmap(tmp/'X.npy',mode='w+',dtype=np.float32,shape=(total,dim))
    y=np.lib.format.open_memmap(tmp/'y.npy',mode='w+',dtype=np.int8,shape=(total,))
    market=np.lib.format.open_memmap(tmp/'market.npy',mode='w+',dtype=np.float32,shape=(total,))
    odds=np.lib.format.open_memmap(tmp/'odds.npy',mode='w+',dtype=np.float32,shape=(total,))
    actual=np.lib.format.open_memmap(tmp/'actual.npy',mode='w+',dtype=np.int32,shape=(total,))
    racearr=np.lib.format.open_memmap(tmp/'race.npy',mode='w+',dtype=np.int32,shape=(total,))
    start=np.zeros(N,dtype=np.int64);end=np.zeros(N,dtype=np.int64)
    pos=0
    for ri,rec in enumerate(odds_records):
        rid=rec["raceId"];active=race_rows[rid];allh=[int(x) for x in rec["horses"]];horses=[h for h in allh if h in active]
        if bt=="win":
            allc=[(h,) for h in allh];keep=[j for j,c in enumerate(allc) if c[0] in active];combos=[(h,) for h in horses]
        else:
            allc=list(itertools.combinations(allh,2));keep=[j for j,c in enumerate(allc) if c[0] in active and c[1] in active];combos=list(itertools.combinations(horses,2))
        vals=np.asarray([official_float(rec[bt][j]) for j in keep],dtype=float)
        if len(vals)!=len(combos):raise RuntimeError(f"ALIGN:{bt}:{rid}")
        pm=normalize_market(vals,3.0 if bt=="wide" else 1.0)
        pn=runner_prob(rid,horses,normalP);pr=runner_prob(rid,horses,residP)
        if bt=="win": mn=pn;mr=pr
        else:
            qn,wn=combo_pair_probs(pn);qr,wr=combo_pair_probs(pr);mn=wn if bt=="wide" else qn;mr=wr if bt=="wide" else qr
        start[ri]=pos
        for j,c in enumerate(combos):
            if bt=="win":
                ix=active[c[0]];X[pos,:F]=Xr[ix];X[pos,F:]=[vals[j],pm[j],mn[j],mr[j],mn[j]/max(pm[j],1e-9),mr[j]/max(pm[j],1e-9)]
            else:
                ia=active[c[0]];ib=active[c[1]];va=np.asarray(Xr[ia]);vb=np.asarray(Xr[ib]);X[pos,:F]=(va+vb)*.5;X[pos,F:2*F]=np.abs(va-vb);X[pos,2*F:]=[vals[j],pm[j],mn[j],mr[j],mn[j]/max(pm[j],1e-9),mr[j]/max(pm[j],1e-9),abs(mn[j]-mr[j])]
            key=c if bt=="win" else tuple(sorted(c));pay=payout[rid][bt].get(key,0)
            y[pos]=1 if pay>0 else 0;market[pos]=pm[j];odds[pos]=vals[j];actual[pos]=pay;racearr[pos]=ri;pos+=1
        end[ri]=pos
        # cold and market expert candidates are known without result-derived model
        util=pm*vals-1.0;act=np.asarray(actual[start[ri]:end[ri]],dtype=np.int32)
        for ei in range(E):rank_and_store(bt,ri,ei,util,act)
        if ri%1000==0:print(json.dumps({'build':bt,'race':ri,'rows':pos}),flush=True)
    if pos!=total:raise RuntimeError(f"TOTAL:{bt}:{pos}:{total}")
    first_race_by_date=[next(i for i,r in enumerate(races) if date_index[r['raceDate']]==d) for d in range(len(dates))]
    offsets=np.asarray([start[i] for i in first_race_by_date]+[total],dtype=np.int64)
    # train three fixed families and populate 12 non-market experts in strict OOS blocks
    for b,nxt in BLOCKS:
        a=int(offsets[b]);z=int(offsets[nxt]);trainX=X[:a];testX=X[a:z]
        target_raw=np.asarray(y[:a],float)-np.asarray(market[:a],float)
        pred_by={}
        mdl=lgb.train(model_params,lgb.Dataset(trainX,label=target_raw),num_boost_round=120,callbacks=[lgb.log_evaluation(0)]);pred_by['rawResidual']=mdl.predict(testX);del mdl
        weights=np.minimum(8.0,1.0/np.sqrt(np.maximum(np.asarray(market[:a],float),0.002)))
        mdl=lgb.train(model_params,lgb.Dataset(trainX,label=target_raw,weight=weights),num_boost_round=120,callbacks=[lgb.log_evaluation(0)]);pred_by['underdogResidual']=mdl.predict(testX);del mdl
        target_value=np.clip(np.asarray(y[:a],float)*np.asarray(odds[:a],float)-1.0,-1.0,20.0)
        mdl=lgb.train(model_params,lgb.Dataset(trainX,label=target_value),num_boost_round=120,callbacks=[lgb.log_evaluation(0)]);pred_by['realizedValue']=mdl.predict(testX);del mdl;gc.collect()
        trr=np.asarray(racearr[a:z],dtype=np.int32);m=np.asarray(market[a:z],float);o=np.asarray(odds[a:z],float);act=np.asarray(actual[a:z],np.int32)
        # contiguous per race
        st=0
        while st<len(trr):
            ri=int(trr[st]);en=st+1
            while en<len(trr) and int(trr[en])==ri:en+=1
            mm=m[st:en];oo=o[st:en];aa=act[st:en]
            for ei,(ename,fam,sh) in enumerate(EXPERTS[1:],start=1):
                pp=pred_by[fam][st:en]
                if fam in ('rawResidual','underdogResidual'):
                    corr=np.clip(mm+sh*pp,1e-8,1.0);mass=3.0 if bt=='wide' else 1.0;s=corr.sum();corr=corr/s*mass if s>0 else mm
                    utility=corr*oo-1.0
                else:
                    market_ev=mm*oo-1.0;utility=(1-sh)*market_ev+sh*pp
                rank_and_store(bt,ri,ei,utility,aa)
            st=en
        metrics.append({'betType':bt,'start':b,'end':nxt,'trainRows':a,'testRows':z-a,
                        'rawResidualMeanAbs':float(np.mean(np.abs(pred_by['rawResidual']))),
                        'underdogResidualMeanAbs':float(np.mean(np.abs(pred_by['underdogResidual']))),
                        'realizedValueMean':float(np.mean(pred_by['realizedValue']))})
        print(json.dumps(metrics[-1]),flush=True)
    del X,y,market,odds,actual,racearr;gc.collect()
    for p in tmp.glob('*'):
        try:p.unlink()
        except Exception:pass
    try:tmp.rmdir()
    except Exception:pass

for bt in BTYPES:
    build_bt(bt);print(json.dumps({'complete':bt}),flush=True)

# prior-date expert selection and deterministic value-based race selection
priorN=50.0;priorSum=40.0
stats={bt:[[0.0,0] for _ in range(E)] for bt in BTYPES}
def shr(bt,e):
    s,n=stats[bt][e];return (s+priorSum)/(n+priorN)
def choose(bt,di):
    if di<30:return COLD
    vals=[shr(bt,e) for e in range(E)];mx=max(vals)
    if abs(vals[COLD]-mx)<1e-12:return COLD
    return max(range(E),key=lambda e:(vals[e],-e))
def alloc(chosen,perf,ri):
    units={};pool=[];used=0
    for bt in BTYPES:
        e=chosen[bt];k=int(candC[bt][e,ri])
        if k<1:raise RuntimeError(f"NO_CAND:{bt}:{ri}")
        units[(bt,0)]=1;used+=1
        for j in range(k):
            u=float(candU[bt][e,ri,j])
            if np.isfinite(u):pool.append((u*max(0.0,perf[bt]),bt,j))
    pool.sort(key=lambda x:(-x[0],x[1],x[2]));rem=20-used
    for util,bt,j in pool:
        if rem<=0:break
        cur=units.get((bt,j),0);add=min(2-cur,rem)
        if add>0:units[(bt,j)]=cur+add;rem-=add
    if rem:raise RuntimeError(f"BUDGET:{ri}:{rem}")
    ret=0;largest=0
    for (bt,j),u in units.items():
        e=chosen[bt];val=int(candR[bt][e,ri,j])*u;ret+=val;largest=max(largest,val)
    return ret,largest

totalStake=totalReturn=largest=0;selected=[];periods=defaultdict(lambda:[0,0]);trace=[]
for di,date in enumerate(dates):
    idx=np.flatnonzero(race_date_idx==di);chosen={bt:choose(bt,di) for bt in BTYPES};perf={bt:(0.8 if di<30 else shr(bt,chosen[bt])) for bt in BTYPES}
    raceScore=[];settle=[]
    for ri in idx:
        parts=[]
        for bt in BTYPES:
            e=chosen[bt];k=min(3,int(candC[bt][e,int(ri)]));u=np.asarray(candU[bt][e,int(ri),:k],float);u=u[np.isfinite(u)]
            pos=u[u>0];base=float(pos.mean()) if len(pos) else (float(u.mean()) if len(u) else -1e9);parts.append(base*max(0.0,perf[bt]))
        raceScore.append(float(np.mean(parts)));settle.append(alloc(chosen,perf,int(ri)))
    byv=defaultdict(list)
    for loc,ri in enumerate(idx):byv[races[int(ri)]['venue']].append(loc)
    locs=[]
    for venue,group in byv.items():
        pick=sorted(group,key=lambda j:(-raceScore[j],int(races[int(idx[j])]['raceNo'])))[:5]
        if len(pick)!=5:raise RuntimeError(f"FIVE:{date}:{venue}")
        locs+=pick
    for loc in locs:
        ri=int(idx[loc]);r,lg=settle[loc];selected.append(ri);totalStake+=2000;totalReturn+=r;largest=max(largest,lg);half=f"{date[:4]}-H{1 if int(date[5:7])<=6 else 2}";periods[half][0]+=2000;periods[half][1]+=r
    # all counterfactual expert updates only after date decisions
    if di>=30:
        for bt in BTYPES:
            for e in range(E):
                for ri in idx:
                    k=min(10,int(candC[bt][e,int(ri)]))
                    if k:stats[bt][e][0]+=float(np.asarray(candR[bt][e,int(ri),:k],float).sum()/100.0);stats[bt][e][1]+=k
    if di in (0,29,30,89,90,149,150,209,210,243):
        row={'dateIndex':di,'date':date,'selected':len(selected),'roiPct':100*totalReturn/totalStake if totalStake else 0,'experts':{bt:EXPERTS[chosen[bt]][0] for bt in BTYPES}};trace.append(row);print(json.dumps(row),flush=True)

roi=100*totalReturn/totalStake;trim=100*(totalReturn-largest)/totalStake
result={'status':'not_a_model_unless_completion_gates_pass','races':len(selected),'selectedUnique':len(set(selected)),'stakeYen':totalStake,'returnYen':totalReturn,'roiPct':roi,'largestTicketReturnYen':largest,'trimmedRoiPct':trim,'periods':{k:{'stake':v[0],'return':v[1],'roiPct':100*v[1]/v[0]} for k,v in sorted(periods.items())},'trace':trace,'metrics':metrics,'finalExpertReturns':{bt:{EXPERTS[e][0]:shr(bt,e) for e in range(E)} for bt in BTYPES},'officialOddsOnly':True,'syntheticOddsUsed':False,'sameDateLeakage':False,'completionGatePass':bool(roi>=200 and trim>=100 and len(selected)==3210)}
(OUT/'ticket-market-error-light-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True)
