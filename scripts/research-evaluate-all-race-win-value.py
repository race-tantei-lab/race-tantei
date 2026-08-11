#!/usr/bin/env python3
import argparse, collections, hashlib, json
from pathlib import Path
import numpy as np
from lightgbm import LGBMClassifier, LGBMRegressor

COURSES={'light':2000,'standard':5000,'premium':10000}
UNITS={'light':(7,7,6),'standard':(17,17,16),'premium':(35,35,30)}
GAMMAS=(0.0,0.25,0.5,0.75,1.0,1.25)
TEMPLATES=('pair','spread','trio','ordered')
JP={'win':'単勝','wide':'ワイド','umaren':'馬連','trio':'3連複','umatan':'馬単','trifecta':'3連単'}

def read_jsonl(p):
    with Path(p).open(encoding='utf-8') as f:
        for line in f:
            if line.strip(): yield json.loads(line)

def ov(v):
    if isinstance(v,list):
        a=[float(x) for x in v if x is not None]; return sum(a)/len(a) if a else None
    return float(v) if v is not None else None

def softmax(rows):
    x=np.asarray([float(r['abilityScore']) for r in rows],np.float64);x-=x.max();e=np.exp(np.clip(x,-50,50));return e/e.sum()

def ent(p):
    p=np.asarray(p);p=p[p>0];return float(-(p*np.log(p)).sum()) if len(p) else 0.0

def norm(bt,hs):
    hs=tuple(map(int,hs))
    if bt in ('wide','umaren','trio'): hs=tuple(sorted(hs))
    return '-'.join(map(str,hs))

def tickets(t,top):
    a,b,c=top
    if t=='pair': return [('win',(a,)),('wide',(a,b)),('umaren',(a,b))]
    if t=='spread': return [('win',(a,)),('wide',(a,b)),('wide',(a,c))]
    if t=='trio': return [('win',(a,)),('wide',(a,b)),('trio',(a,b,c))]
    return [('win',(a,)),('umatan',(a,b)),('trifecta',(a,b,c))]

def fold(rid): return int(hashlib.sha1(str(rid).encode()).hexdigest()[:8],16)%5

def robust(r,budget):
    r=np.asarray(r,np.float64);roi=100*r.sum()/(len(r)*budget);o=np.argsort(-r);k=o[min(50,len(o)):]
    r50=100*r[k].sum()/(len(k)*budget) if len(k) else 0.0
    return {'races':int(len(r)),'roiPct':round(roi,4),'top50ExcludedRoiPct':round(r50,4)}

def evaluate(scores,R,groups):
    ba=np.argmax(scores,axis=1);bs=scores[np.arange(len(scores)),ba];gmap=collections.defaultdict(list)
    for i,g in enumerate(groups):gmap[str(g)].append(i)
    sel=[]
    for inds in gmap.values():
        ix=np.asarray(inds,np.int32);sel.extend(ix[np.argsort(-bs[ix])[:min(5,len(ix))]].tolist())
    sel=np.asarray(sel,np.int32);acts=ba[sel];courses={}
    for ci,(c,b) in enumerate(COURSES.items()):courses[c]=robust(R[sel,acts,ci],b)
    return {'selectedRaces':int(len(sel)),'venueDays':len(gmap),'venueDaysWithFewerThanFiveFinishedRaces':sum(len(v)<5 for v in gmap.values()),
            'courses':courses,'minRoiPct':min(v['roiPct'] for v in courses.values()),
            'minTop50ExcludedRoiPct':min(v['top50ExcludedRoiPct'] for v in courses.values()),
            'passesCompletionGate':all(v['roiPct']>=200 and v['top50ExcludedRoiPct']>=150 for v in courses.values())}

def percentile(z):
    out=np.empty_like(z)
    for j in range(z.shape[1]):
        o=np.argsort(z[:,j]);r=np.empty(len(z),np.float32);r[o]=np.arange(len(z),dtype=np.float32)/max(1,len(z)-1);out[:,j]=r
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--predictions-dir',required=True);ap.add_argument('--win-odds-dir',required=True);ap.add_argument('--history',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    preds=collections.defaultdict(list)
    for p in sorted(Path(a.predictions_dir).glob('all-race-ranker-20*.jsonl')):
        for r in read_jsonl(p):preds[str(r['raceId'])].append(r)
    odds={}
    for p in sorted(Path(a.win_odds_dir).glob('all-race-win-odds-20*.jsonl')):
        for r in read_jsonl(p):odds[str(r['raceId'])]=r
    hist={}
    for b in read_jsonl(a.history):
        d=str(b['race']['raceDate'])
        if '2016-08-10'<=d<='2026-08-09':hist[str(b['race']['raceId'])]=b
    if (len(preds),len(odds),len(hist))!=(34566,34566,34566):raise RuntimeError(f'INPUT_COUNTS:{len(preds)}:{len(odds)}:{len(hist)}')
    ids=sorted(hist,key=lambda r:(hist[r]['race']['raceDate'],hist[r]['race']['venue'],int(hist[r]['race']['raceNo'])))
    acts=[(g,t) for g in GAMMAS for t in TEMPLATES];n=len(ids);na=len(acts)
    X=np.zeros((n,na,32),np.float32);R=np.zeros((n,na,3),np.float32);folds=np.zeros(n,np.int8);groups=np.empty(n,dtype='U20')
    dev=np.full((n,na),-1e30,np.float32);ded=np.full((n,na),-1e30,np.float32)
    for i,rid in enumerate(ids):
        b=hist[rid];rr=b['race'];groups[i]=f"{rr['raceDate']}|{rr['venue']}";folds[i]=fold(rid)
        win=(odds[rid].get('officialOdds') or {}).get('win') or {};wo0={int(h):ov(v) for h,v in win.items() if ov(v) is not None and ov(v)>1}
        rows=[r for r in preds[rid] if int(r['horseNo']) in wo0]
        if len(rows)<3:raise RuntimeError(f'ACTIVE_ROWS_TOO_FEW:{rid}:{len(rows)}')
        apv=softmax(rows);hs=np.asarray([int(r['horseNo']) for r in rows],np.int16);wo=np.asarray([wo0[int(h)] for h in hs],np.float64)
        inv=1/wo;q=inv/inv.sum();ev=apv*wo;edge=apv/np.maximum(q,1e-12);mr=np.argsort(np.argsort(wo))+1;ao=np.argsort(-apv)
        gf=[len(rows),int(rr['raceNo']),float(wo.min()),float(np.partition(wo,1)[1]),float(np.median(wo)),float(inv.sum()),ent(q),ent(apv),float(apv[ao[0]]),float(apv[ao[1]]),float(apv[ao[2]]),float(apv[ao[0]]-apv[ao[1]]),float(apv[ao[:3]].sum()),float(ev.max()),float(edge.max())]
        pays={(str(p.get('betType') or ''),str(p.get('combination') or '')):int(p['payoutYen']) for p in b.get('payouts',[]) if p.get('payoutYen') is not None}
        for ai,(g,t) in enumerate(acts):
            s=np.log(np.maximum(apv,1e-12))+g*np.log(np.maximum(wo,1.000001));o=np.argsort(-s);ix=o[:3];top=tuple(int(hs[j]) for j in ix)
            sf=gf+[g,float(TEMPLATES.index(t))]+[float(apv[j]) for j in ix]+[float(q[j]) for j in ix]+[float(wo[j]) for j in ix]+[float(ev[j]) for j in ix]+[float(mr[j]) for j in ix]
            assert len(sf)==32,len(sf);X[i,ai]=sf;dev[i,ai]=max(ev[j] for j in ix);ded[i,ai]=max(edge[j] for j in ix)
            pv=[pays.get((JP[bt],norm(bt,hset)),0) for bt,hset in tickets(t,top)]
            for ci,c in enumerate(COURSES):R[i,ai,ci]=sum(u*p for u,p in zip(UNITS[c],pv))
        if i and i%5000==0:print(json.dumps({'builtRaces':i}),flush=True)
    FX=X.reshape(n*na,-1);FF=np.repeat(folds,na);ratio=(R[:,:,1]/5000).reshape(-1);cfg={'direct_max_ev':evaluate(dev,R,groups),'direct_max_edge':evaluate(ded,R,groups)}
    specs=(('reg_cap3','reg',3.),('reg_cap5','reg',5.),('reg_cap10','reg',10.),('weighted_cap5','weighted',5.),('weighted_cap10','weighted',10.));oof={k:np.zeros((n,na),np.float32) for k,_,_ in specs}
    for f in range(5):
        tr=FF!=f;vr=np.flatnonzero(folds==f);vi=np.concatenate([np.arange(i*na,(i+1)*na) for i in vr])
        for name,kind,cap in specs:
            if kind=='reg':
                m=LGBMRegressor(objective='regression_l1',n_estimators=180,learning_rate=.035,num_leaves=31,min_child_samples=120,subsample=.9,colsample_bytree=.9,reg_alpha=.6,reg_lambda=7,random_state=20260811+f,n_jobs=-1,verbosity=-1);m.fit(FX[tr],np.minimum(ratio[tr],cap));p=m.predict(FX[vi])
            else:
                hit=(ratio[tr]>0).astype(np.int8);w=np.where(hit>0,np.minimum(ratio[tr],cap),1).astype(np.float32);m=LGBMClassifier(objective='binary',n_estimators=180,learning_rate=.035,num_leaves=31,min_child_samples=120,subsample=.9,colsample_bytree=.9,reg_alpha=.6,reg_lambda=7,random_state=20260911+f,n_jobs=-1,verbosity=-1);m.fit(FX[tr],hit,sample_weight=w);p=m.predict_proba(FX[vi])[:,1]
            oof[name][vr]=p.reshape(len(vr),na)
        print(json.dumps({'crossFitFoldComplete':f}),flush=True)
    for k,v in oof.items():cfg[k]=evaluate(v,R,groups)
    cfg['stable_ensemble']=evaluate((percentile(oof['reg_cap5'])+percentile(oof['weighted_cap5']))*.5,R,groups)
    best=max(cfg,key=lambda k:(cfg[k]['passesCompletionGate'],cfg[k]['minTop50ExcludedRoiPct'],cfg[k]['minRoiPct']));w=cfg[best]
    out={'purpose':'all_2016_2026_price_aware_race_level_crossfit_five_race_selection','period':{'start':'2016-08-10','end':'2026-08-09'},'allResultRaces':n,'officialWinOddsRaces':len(odds),'venueDays':len(set(groups)),'targetRaceResultUsedForOwnScore':False,'crossFitUnit':'race','historicalFinalWinOddsUsed':True,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False,'ticketCountPerRace':3,'minimumBetTypesPerRace':2,'maxTicketBudgetSharePct':35.0,'completionGate':{'allCoursesRoiPctAtLeast':200.0,'allCoursesTop50ExcludedRoiPctAtLeast':150.0},'candidateHorseValueParameterGammas':list(GAMMAS),'ticketTemplates':list(TEMPLATES),'configs':cfg,'bestCandidate':{'name':best,**w},'completed':bool(w['passesCompletionGate'])}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'completed':out['completed'],'bestCandidate':out['bestCandidate']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
