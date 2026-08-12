#!/usr/bin/env python3
import argparse,base64,collections,gzip,io,itertools,json,math
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

BET_ORDER=('単勝','ワイド','馬連','馬単','3連複','3連単')
MARKET_KEY={'単勝':'win','ワイド':'wide','馬連':'umaren','馬単':'umatan','3連複':'trio','3連単':'trifecta'}
EXPECTED={2016:562.6545451120897,2017:519.423611300687,2018:431.43749991638794,2019:409.7847236237592,2020:482.7534727048543,2021:424.72569381611214,2022:386.7812493195137,2023:393.93750012748774,2024:392.0520831603143,2025:401.96875070532167,2026:418.77777779764597}
FEATURES=['horseNoRaw','venue','raceNo','surface','distanceM','direction','fieldSize','monthSin','monthCos','raceClass','weather','trackCondition','horseNo','frameNo','drawPct','sex','age','horseWeight','weightChange','assignedWeight','horseStarts','horseWinRate','horseTop3Rate','daysSinceLast','debutFlag','lastFinishPct','avg3FinishPct','avg5FinishPct','lastTop3','top3Last3','lastFinal3fPct','avg3Final3fPct','avg5Final3fPct','lastSpeedMps','avg3SpeedMps','avg5SpeedMps','sameSurfaceStarts','sameSurfaceWinRate','sameSurfaceTop3Rate','sameDistStarts','sameDistWinRate','sameDistTop3Rate','sameVenueStarts','sameVenueWinRate','sameVenueTop3Rate','distanceChange','surfaceSwitch','jockeyStarts','jockeyWinRate','jockeyTop3Rate','trainerStarts','trainerWinRate','trainerTop3Rate','pairStarts','pairWinRate','pairTop3Rate']

def o2(w,a,b):return w[a]*w[b]/max(1e-15,1-w[a])
def o3(w,a,b,c):return w[a]*(w[b]/max(1e-15,1-w[a]))*(w[c]/max(1e-15,1-w[a]-w[b]))
def cp(k,p,w):
    if k=='単勝':return w[p[0]]
    if k=='馬単':return o2(w,*p)
    if k=='馬連':a,b=p;return o2(w,a,b)+o2(w,b,a)
    if k=='3連単':return o3(w,*p)
    if k=='3連複':
        a,b,c=p;return sum(o3(w,*x) for x in ((a,b,c),(a,c,b),(b,a,c),(b,c,a),(c,a,b),(c,b,a)))
    if k=='ワイド':
        a,b=p;z=0
        for c in range(len(w)):
            if c in (a,b):continue
            z+=sum(o3(w,*x) for x in ((a,b,c),(a,c,b),(b,a,c),(b,c,a),(c,a,b),(c,b,a)))
        return z
    raise ValueError(k)

def positions(k,n):
    if k=='単勝':return ((i,) for i in range(n))
    if k in ('ワイド','馬連'):return itertools.combinations(range(n),2)
    if k=='馬単':return itertools.permutations(range(n),2)
    if k=='3連複':return itertools.combinations(range(n),3)
    if k=='3連単':return itertools.permutations(range(n),3)
    raise ValueError(k)
def combo(k,p,h):
    v=[h[i] for i in p]
    if k in ('ワイド','馬連','3連複'):v=sorted(v)
    return '-'.join(map(str,v))
def odd(v):
    if isinstance(v,(list,tuple)):
        xs=[float(x) for x in v if x is not None]
        return sum(xs)/len(xs) if xs else None
    try:return float(v)
    except:return None
def canon(k,s):
    nums=[int(x) for x in str(s).replace('→','-').replace('–','-').replace('—','-').split('-') if str(x).isdigit()]
    if k in ('ワイド','馬連','3連複'):nums.sort()
    return '-'.join(map(str,nums))

def choose(pred,od):
    hp={int(x[0]):float(x[1]) for x in pred}
    horses=[int(x) for x in od.get('horses',[]) if int(x) in hp]
    if len(horses)<3:raise RuntimeError(f'COMMON_HORSES_LT3:{od.get("raceId","")}')
    raw=[hp[h] for h in horses];total=sum(raw);w=[x/total for x in raw]
    official=od.get('officialOdds',{}) or {};best=[]
    for bt in BET_ORDER:
        market=official.get(MARKET_KEY[bt],{}) or {};candidates=[]
        for p in positions(bt,len(horses)):
            c=combo(bt,p,horses);v=market.get(c)
            if v is None and bt=='単勝':v=market.get(str(horses[p[0]]))
            ov=odd(v)
            if ov is None or ov<=0:continue
            pr=float(cp(bt,p,w))
            if pr<=0:continue
            candidates.append((pr*ov,c,ov,pr))
        candidates.sort(key=lambda x:(-x[0],x[2],x[1]));top=candidates[:5]
        scored=[(math.log(pr)+0.4*math.log(ov),c,ov,pr) for _,c,ov,pr in top]
        scored.sort(key=lambda x:(-x[0],-x[3],x[1]))
        if not scored:raise RuntimeError(f'NO_CANDIDATE:{od.get("raceId","")}:{bt}')
        q=scored[0];best.append((q[0],bt,q[1],q[2],q[3]))
    best.sort(key=lambda x:(-x[0],BET_ORDER.index(x[1]),x[2]));return best[:2]

def load_selected(path):
    out={}
    for line in open(path,encoding='utf-8'):
        if not line.strip():continue
        x=json.loads(line);rid=str(x['raceId']);out[rid]=x
    if len(out)!=14410:raise RuntimeError(f'SELECTED_COUNT:{len(out)}')
    return out

def build_predictions(csv_path,model_path,selected):
    booster=lgb.Booster(model_file=model_path);out={};use=['raceId','horseNoRaw',*FEATURES[1:]]
    for chunk in pd.read_csv(csv_path,usecols=use,chunksize=100000):
        chunk=chunk[chunk['raceId'].astype(str).isin(selected)]
        if chunk.empty:continue
        x=chunk[FEATURES].to_numpy(dtype=np.float64);p=booster.predict(x)
        for rid,h,pr in zip(chunk['raceId'].astype(str),chunk['horseNoRaw'],p):out.setdefault(rid,[]).append((int(h),float(pr)))
    if len(out)!=14410:raise RuntimeError(f'PRED_COUNT:{len(out)}')
    return out

def load_history(path,selected):
    calendar=[];hist={}
    for line in open(path,encoding='utf-8'):
        if not line.strip():continue
        b=json.loads(line);r=b['race'];date=str(r['raceDate'])
        if not ('2016-08-10'<=date<='2026-08-09'):continue
        rid=str(r['raceId']);calendar.append([rid,date,str(r.get('venue') or ''),int(r.get('raceNo') or 0),r.get('raceName'),r.get('startTimeJst'),r.get('surface'),r.get('distanceM'),None])
        if rid in selected:hist[rid]=b
    if len(calendar)!=34566:raise RuntimeError(f'CALENDAR_COUNT:{len(calendar)}')
    if len(hist)!=14410:raise RuntimeError(f'HISTORY_COUNT:{len(hist)}')
    return calendar,hist

def load_year_odds(path,need):
    out={}
    for line in open(path,encoding='utf-8'):
        if not line.strip():continue
        x=json.loads(line);rid=str(x.get('raceId') or '')
        if rid in need:out[rid]=x
    return out

def calculate(pred,hist,odds_dir,calendar_rows):
    byrow={r[0]:r for r in calendar_rows};full_stake=full_return=full_hits=0
    for year in range(2016,2027):
        ids={rid for rid,b in hist.items() if str(b['race']['raceDate']).startswith(str(year))};od=load_year_odds(Path(odds_dir)/f'research-continuous-market-odds-{year}.jsonl',ids)
        if len(od)!=len(ids):raise RuntimeError(f'ODDS_COUNT:{year}:{len(od)}/{len(ids)}')
        stake=ret=hits=0
        for rid in sorted(ids):
            chosen=choose(pred[rid],od[rid]);b=hist[rid];pays={(str(x['betType']),canon(str(x['betType']),x['combination'])):int(x['payoutYen']) for x in b.get('payouts',[])};refunds={int(x) for x in b.get('race',{}).get('refundHorseNos',[]) or []};tickets=[];race_ret=0
            for _,bt,c,ov,_ in chosen:
                horses=[int(x) for x in c.split('-')];py=1000 if any(h in refunds for h in horses) else pays.get((bt,canon(bt,c)),0)*10;race_ret+=py;tickets.append([bt,c,round(float(ov),6),int(py)])
            byrow[rid][8]=tickets;stake+=2000;ret+=race_ret;hits+=race_ret>0
        value=ret/stake*100
        if abs(value-EXPECTED[year])>1e-5:raise RuntimeError(f'YEAR_ROI_MISMATCH:{year}:{value}/{EXPECTED[year]}')
        full_stake+=stake;full_return+=ret;full_hits+=hits
    roi=full_return/full_stake*100
    if abs(roi-431.6505898681471)>1e-7:raise RuntimeError(f'FULL_ROI_MISMATCH:{roi}')
    if sum(1 for r in calendar_rows if r[8])!=14410:raise RuntimeError('TICKET_COUNT_MISMATCH')
    return {'races':14410,'roiPct':roi,'hitRacePct':full_hits/14410*100,'stakeYen':full_stake,'returnYen':full_return}

def write_assets(out_dir,calendar_rows,summary,chunk_chars=90000):
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    for p in out.glob('bin-*.ts'):p.unlink()
    payload=json.dumps({'start':'2016-08-10','end':'2026-08-09','races':calendar_rows},ensure_ascii=False,separators=(',',':')).encode()
    bio=io.BytesIO()
    with gzip.GzipFile(fileobj=bio,mode='wb',compresslevel=9,mtime=0) as g:g.write(payload)
    encoded=base64.b64encode(bio.getvalue()).decode('ascii');chunks=[encoded[i:i+chunk_chars] for i in range(0,len(encoded),chunk_chars)]
    for i,ch in enumerate(chunks):(out/f'bin-{i:02d}.ts').write_text(f'export default {json.dumps(ch)};\n',encoding='utf-8')
    imports='\n'.join(f'import b{i} from "./bin-{i:02d}.js";' for i in range(len(chunks)))
    joined='+'.join(f'b{i}' for i in range(len(chunks))) or '""'
    (out/'index.ts').write_text(imports+f'\nexport default {joined};\n',encoding='utf-8')
    (out/'meta.ts').write_text('export const TEN_YEAR_HISTORY_CHUNKS='+str(len(chunks))+';\nexport const TEN_YEAR_HISTORY_RACES=34566;\nexport const TEN_YEAR_HISTORY_SELECTED=14410;\n',encoding='utf-8')
    (out/'audit.json').write_text(json.dumps({**summary,'archiveBytes':len(bio.getvalue()),'base64Chars':len(encoded),'chunks':len(chunks)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({**summary,'archiveBytes':len(bio.getvalue()),'base64Chars':len(encoded),'chunks':len(chunks)},ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--feature-csv',required=True);ap.add_argument('--demand',required=True);ap.add_argument('--history',required=True);ap.add_argument('--odds-dir',required=True);ap.add_argument('--model',required=True);ap.add_argument('--out-dir',required=True);a=ap.parse_args()
    selected=load_selected(a.demand);pred=build_predictions(a.feature_csv,a.model,selected);calendar,hist=load_history(a.history,selected);summary=calculate(pred,hist,a.odds_dir,calendar);write_assets(a.out_dir,calendar,summary)
if __name__=='__main__':main()
