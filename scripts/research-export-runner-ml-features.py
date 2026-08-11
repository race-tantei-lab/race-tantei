#!/usr/bin/env python3
import argparse,collections,csv,datetime as dt,json,math,re
from pathlib import Path

VENUES={'札幌':1,'函館':2,'福島':3,'新潟':4,'東京':5,'中山':6,'中京':7,'京都':8,'阪神':9,'小倉':10}
SURF={'芝':0,'ダート':1,'障害':2}
WEATHER={'晴':0,'曇':1,'雨':2,'小雨':3,'雪':4,'小雪':5}
TRACK={'良':0,'稍重':1,'重':2,'不良':3}
SEX={'牡':0,'牝':1,'セ':2,'騸':2}
PRIOR_WIN=0.08;PRIOR_TOP3=0.24;SMOOTH=12.0

FEATURES=[
 'venue','raceNo','surface','distanceM','direction','fieldSize','monthSin','monthCos','raceClass','weather','trackCondition',
 'horseNo','frameNo','drawPct','sex','age','horseWeight','weightChange','assignedWeight','marketPopularity',
 'horseStarts','horseWinRate','horseTop3Rate','daysSinceLast','debutFlag','lastFinishPct','avg3FinishPct','avg5FinishPct',
 'lastTop3','top3Last3','lastFinal3fPct','avg3Final3fPct','avg5Final3fPct','lastSpeedMps','avg3SpeedMps','avg5SpeedMps',
 'sameSurfaceStarts','sameSurfaceWinRate','sameSurfaceTop3Rate','sameDistStarts','sameDistWinRate','sameDistTop3Rate',
 'sameVenueStarts','sameVenueWinRate','sameVenueTop3Rate','distanceChange','surfaceSwitch',
 'jockeyStarts','jockeyWinRate','jockeyTop3Rate','trainerStarts','trainerWinRate','trainerTop3Rate',
 'pairStarts','pairWinRate','pairTop3Rate'
]
HEADER=['raceId','raceDate','horseNoRaw','finishPosition','labelWin','labelTop3']+FEATURES

def safe_int(x):
    try:return int(x)
    except:return None

def safe_float(x):
    try:return float(x)
    except:return None

def parse_time(s):
    s=str(s or '').strip()
    if not s:return None
    try:
        if ':' in s:
            a,b=s.split(':',1);return float(a)*60+float(b)
        return float(s)
    except:return None

def parse_sex_age(s):
    s=str(s or '').strip();sex=SEX.get(s[:1],3)
    m=re.search(r'(\d+)',s);age=int(m.group(1)) if m else 0
    return sex,age

def class_code(name,conditions):
    x=(str(name or '')+' '+str(conditions or '')).replace('500万下','1勝クラス').replace('1000万下','2勝クラス').replace('1600万下','3勝クラス')
    if '新馬' in x:return 0
    if '未勝利' in x:return 1
    if '1勝クラス' in x:return 2
    if '2勝クラス' in x:return 3
    if '3勝クラス' in x:return 4
    if 'オープン' in x or 'OPEN' in x.upper():return 5
    if 'G3' in x or 'Ｇ３' in x:return 6
    if 'G2' in x or 'Ｇ２' in x:return 7
    if 'G1' in x or 'Ｇ１' in x:return 8
    return 5

def dist_bin(d):
    if d<1200:return 0
    if d<1600:return 1
    if d<2000:return 2
    if d<2400:return 3
    if d<3000:return 4
    return 5

def rate(stat,kind):
    if not stat:return PRIOR_WIN if kind=='win' else PRIOR_TOP3
    n,w,t=stat
    prior=PRIOR_WIN if kind=='win' else PRIOR_TOP3;h=w if kind=='win' else t
    return (h+SMOOTH*prior)/(n+SMOOTH)
def avg(hist,key,n,default=0.0):
    rows=list(hist)[-n:]
    vals=[r[key] for r in rows if r.get(key) is not None]
    return sum(vals)/len(vals) if vals else default

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--corpus',required=True);ap.add_argument('--out',required=True);ap.add_argument('--meta',required=True);a=ap.parse_args()
    horse_hist=collections.defaultdict(lambda:collections.deque(maxlen=5));horse_total=collections.defaultdict(lambda:[0,0,0]);horse_surface=collections.defaultdict(lambda:[0,0,0]);horse_dist=collections.defaultdict(lambda:[0,0,0]);horse_venue=collections.defaultdict(lambda:[0,0,0]);jockey=collections.defaultdict(lambda:[0,0,0]);trainer=collections.defaultdict(lambda:[0,0,0]);pair=collections.defaultdict(lambda:[0,0,0])
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);fo=out.open('w',newline='',encoding='utf-8');wr=csv.DictWriter(fo,fieldnames=HEADER);wr.writeheader()
    current=None;day=[];race_count=0;runner_count=0;valid_labels=0;by_year=collections.Counter()
    def process(date,bundles):
        nonlocal race_count,runner_count,valid_labels
        ddate=dt.date.fromisoformat(date)
        staged=[]
        # Feature rows for the entire date are emitted before any result on the date updates state.
        for b in bundles:
            race=b['race'];rid=str(race['raceId']);active=[r for r in b.get('runners',[]) if (r.get('runnerStatus') or 'active')=='active'];active.sort(key=lambda r:int(r.get('horseNo') or 0));field=len(active)
            if field<2:continue
            results={safe_int(r.get('horseNo')):r for r in b.get('results',[]) if safe_int(r.get('horseNo')) is not None}
            distance=int(race.get('distanceM') or 0);surf=str(race.get('surface') or '障害');db=dist_bin(distance);venue=str(race.get('venue') or '');month=int(date[5:7]);rc=class_code(race.get('raceName'),race.get('conditions'))
            for r in active:
                hno=int(r['horseNo']);name=str(r.get('horseName') or f'__{rid}:{hno}');hist=horse_hist.get(name,());ht=horse_total.get(name);ss=horse_surface.get((name,surf));ds=horse_dist.get((name,db));vs=horse_venue.get((name,venue));j=str(r.get('jockey') or '');t=str(r.get('trainer') or '');js=jockey.get(j);ts=trainer.get(t);ps=pair.get((name,j))
                sex,age=parse_sex_age(r.get('sexAge'));last=hist[-1] if hist else None;days=(ddate-last['date']).days if last else 999;last_dist=last['distance'] if last else distance;last_surf=last['surface'] if last else surf
                res=results.get(hno);pos=safe_int(res.get('finishPosition')) if res else None;valid=pos is not None and pos>0
                row={'raceId':rid,'raceDate':date,'horseNoRaw':hno,'finishPosition':pos or 0,'labelWin':int(valid and pos==1),'labelTop3':int(valid and pos<=3),
                    'venue':VENUES.get(venue,0),'raceNo':int(race.get('raceNo') or 0),'surface':SURF.get(surf,2),'distanceM':distance,'direction':1 if str(race.get('direction') or '').startswith('右') else (2 if str(race.get('direction') or '').startswith('左') else 0),'fieldSize':field,'monthSin':math.sin(2*math.pi*month/12),'monthCos':math.cos(2*math.pi*month/12),'raceClass':rc,'weather':WEATHER.get(str(race.get('weather') or ''),6),'trackCondition':TRACK.get(str(race.get('trackCondition') or ''),4),
                    'horseNo':hno,'frameNo':int(r.get('frameNo') or 0),'drawPct':hno/max(1,field),'sex':sex,'age':age,'horseWeight':safe_float(r.get('horseWeight')) or 0.0,'weightChange':safe_float(r.get('weightChange')) or 0.0,'assignedWeight':safe_float(r.get('assignedWeight')) or 0.0,'marketPopularity':safe_int(r.get('popularity')) or 0,
                    'horseStarts':ht[0] if ht else 0,'horseWinRate':rate(ht,'win'),'horseTop3Rate':rate(ht,'top3'),'daysSinceLast':min(999,days),'debutFlag':int(not hist),'lastFinishPct':last['finishPct'] if last else 0.0,'avg3FinishPct':avg(hist,'finishPct',3),'avg5FinishPct':avg(hist,'finishPct',5),'lastTop3':last['top3'] if last else 0,'top3Last3':sum(x['top3'] for x in list(hist)[-3:]) if hist else 0,'lastFinal3fPct':last['final3fPct'] if last else 0.0,'avg3Final3fPct':avg(hist,'final3fPct',3),'avg5Final3fPct':avg(hist,'final3fPct',5),'lastSpeedMps':last['speedMps'] if last else 0.0,'avg3SpeedMps':avg(hist,'speedMps',3),'avg5SpeedMps':avg(hist,'speedMps',5),
                    'sameSurfaceStarts':ss[0] if ss else 0,'sameSurfaceWinRate':rate(ss,'win'),'sameSurfaceTop3Rate':rate(ss,'top3'),'sameDistStarts':ds[0] if ds else 0,'sameDistWinRate':rate(ds,'win'),'sameDistTop3Rate':rate(ds,'top3'),'sameVenueStarts':vs[0] if vs else 0,'sameVenueWinRate':rate(vs,'win'),'sameVenueTop3Rate':rate(vs,'top3'),'distanceChange':abs(distance-last_dist),'surfaceSwitch':int(last_surf!=surf),
                    'jockeyStarts':js[0] if js else 0,'jockeyWinRate':rate(js,'win'),'jockeyTop3Rate':rate(js,'top3'),'trainerStarts':ts[0] if ts else 0,'trainerWinRate':rate(ts,'win'),'trainerTop3Rate':rate(ts,'top3'),'pairStarts':ps[0] if ps else 0,'pairWinRate':rate(ps,'win'),'pairTop3Rate':rate(ps,'top3')}
                if valid:wr.writerow(row);runner_count+=1;valid_labels+=1;by_year[date[:4]]+=1
            staged.append((b,active,results,distance,surf,db,venue,ddate))
            race_count+=1
        # Update states only after all feature rows for the date are frozen.
        for b,active,results,distance,surf,db,venue,ddate in staged:
            byno={int(r['horseNo']):r for r in active};valid=[]
            for hno,res in results.items():
                pos=safe_int(res.get('finishPosition'));tm=parse_time(res.get('timeText'));f3=safe_float(res.get('final3f'))
                if hno in byno and pos is not None and pos>0:valid.append((hno,pos,tm,f3))
            f3s=sorted((x[3],x[0]) for x in valid if x[3] is not None);f3rank={h:i for i,(_,h) in enumerate(f3s)};nf=len(f3s);field=len(active)
            for hno,pos,tm,f3 in valid:
                r=byno[hno];name=str(r.get('horseName') or f'__{b["race"]["raceId"]}:{hno}');finish_pct=max(0.0,1.0-(pos-1)/max(1,field-1));f3pct=(1.0-f3rank[hno]/max(1,nf-1)) if f3 is not None else 0.5;speed=(distance/tm) if tm and tm>0 and distance>0 else 0.0;win=int(pos==1);top3=int(pos<=3)
                horse_hist[name].append({'date':ddate,'finishPct':finish_pct,'final3fPct':f3pct,'speedMps':speed,'top3':top3,'distance':distance,'surface':surf})
                for stat in (horse_total[name],horse_surface[(name,surf)],horse_dist[(name,db)],horse_venue[(name,venue)],jockey[str(r.get('jockey') or '')],trainer[str(r.get('trainer') or '')],pair[(name,str(r.get('jockey') or ''))]):stat[0]+=1;stat[1]+=win;stat[2]+=top3
    with Path(a.corpus).open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():continue
            b=json.loads(line);date=str(b['race'].get('raceDate') or '')
            if current is None:current=date
            if date!=current:process(current,day);day=[];current=date
            day.append(b)
    if current:process(current,day)
    fo.close();meta={'purpose':'research_only_runner_ml_features_prior_history_only','racesProcessed':race_count,'runnerRows':runner_count,'rowsByYear':dict(sorted(by_year.items())),'featureCount':len(FEATURES),'features':FEATURES,'sameDayResultsUsedForFeatures':False,'currentRaceFinishOrPayoutUsedForFeatures':False,'marketPopularityIncludedAsSeparateFeatureForMarketAwareVariant':True,'syntheticDataUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    Path(a.meta).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(meta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
