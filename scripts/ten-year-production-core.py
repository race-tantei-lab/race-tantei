#!/usr/bin/env python3
import collections
import datetime as dt
import gzip
import itertools
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / 'config' / 'ten-year-completed-model.json'
MODEL_PATH = ROOT / 'models' / 'ten-year-completed-model.txt'
FEATURE_STATE_PATH = ROOT / 'models' / 'ten-year-runner-feature-state.json.gz'
SELECTION_STATE_PATH = ROOT / 'models' / 'ten-year-race-selection-state.json.gz'

# Canonical race-selection bins from acf44ad91c83e30f3a3e0363b43bbc8fb4a51a2c.
SEL_VENUES = ['東京','中山','京都','阪神','中京','新潟','福島','小倉','札幌','函館']
SEL_VENUE_MAP = {v:i for i,v in enumerate(SEL_VENUES)}
BET_SPECS = {
    0:(1,'win','単勝',False),
    1:(2,'umaren','馬連',False),
    2:(2,'wide','ワイド',False),
    3:(2,'umatan','馬単',True),
    4:(3,'trio','3連複',False),
    5:(3,'trifecta','3連単',True),
}
SINGLES=('venue','surface','dist','field','raceNo','rclass','bestform','bestspeed','bestj','bestt','expcnt','top3lastsum')
PAIRS=(('surface','bestform'),('dist','bestform'),('rclass','bestform'),('field','expcnt'),('bestform','bestspeed'),('bestj','bestt'),('expcnt','top3lastsum'),('bestform','top3lastsum'))
TOP_HORSES=5
MIN_N=500
KEY_PRIOR=2000
BET_PRIOR=5000
PRIOR_ROI=0.80
TOP_COMPONENTS=8
TICKETS_PER_RACE=3
QUARTER_DECAY=1.0
LOCAL_WEIGHT=0.60

# Canonical runner-ML feature constants from b45f472... plus its runtime G1/G2/G3 patch.
ML_VENUES={'札幌':1,'函館':2,'福島':3,'新潟':4,'東京':5,'中山':6,'中京':7,'京都':8,'阪神':9,'小倉':10}
SURF={'芝':0,'ダート':1,'障害':2}
WEATHER={'晴':0,'曇':1,'雨':2,'小雨':3,'雪':4,'小雪':5}
TRACK={'良':0,'稍重':1,'重':2,'不良':3}
SEX={'牡':0,'牝':1,'セ':2,'騸':2}
PRIOR_WIN=0.08
PRIOR_TOP3=0.24
SMOOTH=12.0


def safe_int(x):
    try: return int(x)
    except Exception: return None


def safe_float(x):
    try: return float(x)
    except Exception: return None


def parse_time(s):
    s=str(s or '').strip()
    if not s: return None
    try:
        if ':' in s:
            a,b=s.split(':',1); return float(a)*60+float(b)
        return float(s)
    except Exception:
        return None


def parse_sex_age(s):
    s=str(s or '').strip(); sex=SEX.get(s[:1],3)
    m=re.search(r'(\d+)',s); age=int(m.group(1)) if m else 0
    return sex,age


def ml_class_code(name,conditions):
    x=(str(name or '')+' '+str(conditions or '')).replace('500万下','1勝クラス').replace('1000万下','2勝クラス').replace('1600万下','3勝クラス')
    if '新馬' in x:return 0
    if '未勝利' in x:return 1
    if '1勝クラス' in x:return 2
    if '2勝クラス' in x:return 3
    if '3勝クラス' in x:return 4
    if 'G1' in x or 'Ｇ１' in x or 'ＧⅠ' in x:return 8
    if 'G2' in x or 'Ｇ２' in x or 'ＧⅡ' in x:return 7
    if 'G3' in x or 'Ｇ３' in x or 'ＧⅢ' in x:return 6
    if 'オープン' in x or 'OPEN' in x.upper():return 5
    return 5


def ml_dist_bin(d):
    if d<1200:return 0
    if d<1600:return 1
    if d<2000:return 2
    if d<2400:return 3
    if d<3000:return 4
    return 5


def rate(stat,kind):
    if not stat:return PRIOR_WIN if kind=='win' else PRIOR_TOP3
    n,w,t=stat
    prior=PRIOR_WIN if kind=='win' else PRIOR_TOP3
    h=w if kind=='win' else t
    return (h+SMOOTH*prior)/(n+SMOOTH)


def avg(hist,key,n,default=0.0):
    rows=list(hist)[-n:]
    vals=[r[key] for r in rows if r.get(key) is not None]
    return sum(vals)/len(vals) if vals else default


def sel_distbin(d): return 0 if d<=1200 else 1 if d<=1500 else 2 if d<=1800 else 3 if d<=2200 else 4 if d<=2600 else 5

def sel_fieldbin(n): return 0 if n<=8 else 1 if n<=11 else 2 if n<=13 else 3 if n<=16 else 4

def sel_rnobin(r): return 0 if r<=3 else 1 if r<=6 else 2 if r<=9 else 3

def sel_seasonbin(m): return 0 if m in (12,1,2) else 1 if m in (3,4,5) else 2 if m in (6,7,8) else 3


def sel_classbin(name,conditions=''):
    s=((name or '')+' '+(conditions or '')).replace(' ','')
    if '(GI)' in s or 'GⅠ' in s or 'ＧⅠ' in s:return 8
    if '(GII)' in s or 'GⅡ' in s or 'ＧⅡ' in s:return 7
    if '(GIII)' in s or 'GⅢ' in s or 'ＧⅢ' in s:return 6
    if '新馬' in s:return 0
    if '未勝利' in s:return 1
    if '1勝' in s:return 2
    if '2勝' in s:return 3
    if '3勝' in s:return 4
    if '(L)' in s or 'オープン' in s or 'OP' in s:return 5
    return 9


def sel_directionbin(venue,surface,distance,direction):
    d=str(direction or '')
    if '直' in d or (venue=='新潟' and surface=='芝' and int(distance or 0)==1000): return 2
    if d=='左' or venue in ('東京','中京','新潟'): return 1
    return 0


def ratecode(rate_): return 0 if rate_<.15 else 1 if rate_<.25 else 2 if rate_<.35 else 3 if rate_<.45 else 4

def formcode(v,has): return 0 if not has else 1 if v<.30 else 2 if v<.50 else 3 if v<.70 else 4

def startsbin(n): return 0 if n==0 else 1 if n<=2 else 2 if n<=5 else 3 if n<=10 else 4


def quarter(date):
    y=int(date[:4]);m=int(date[5:7]);return f'{y}Q{(m-1)//3+1}'


def normalize_class_text(text):
    value=str(text or '')
    return value.replace('500万下','1勝クラス').replace('1000万下','2勝クラス').replace('1600万下','3勝クラス')


def horse_key(race_id,runner):
    name=str(runner.get('horseName') or '').strip()
    return name if name else f"__missing__:{race_id}:{runner.get('horseNo')}"


def _gzip_json(path):
    with gzip.open(path,'rt',encoding='utf-8') as fh:
        return json.load(fh)


def load_config():
    cfg=json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    feats=cfg['runnerProbabilityModel']['features']
    if len(feats)!=56 or 'marketPopularity' in feats:
        raise RuntimeError(f'CANONICAL_FEATURE_CONFIG_INVALID:{len(feats)}')
    return cfg


def load_feature_state():
    p=_gzip_json(FEATURE_STATE_PATH)
    horse_hist=collections.defaultdict(lambda:collections.deque(maxlen=5))
    for k,rows in p['horseHist'].items():
        horse_hist[k]=collections.deque([
            {**x,'date':dt.date.fromisoformat(str(x['date']))} for x in rows
        ],maxlen=5)
    state={
        'throughDate':str(p['throughDate']),
        'horse_hist':horse_hist,
        'horse_total':collections.defaultdict(lambda:[0,0,0],{k:list(v) for k,v in p['horseTotal'].items()}),
        'horse_surface':collections.defaultdict(lambda:[0,0,0]),
        'horse_dist':collections.defaultdict(lambda:[0,0,0]),
        'horse_venue':collections.defaultdict(lambda:[0,0,0]),
        'jockey':collections.defaultdict(lambda:[0,0,0],{k:list(v) for k,v in p['jockey'].items()}),
        'trainer':collections.defaultdict(lambda:[0,0,0],{k:list(v) for k,v in p['trainer'].items()}),
        'pair':collections.defaultdict(lambda:[0,0,0]),
    }
    for h,s,n,w,t in p['horseSurface']: state['horse_surface'][(h,s)]=[n,w,t]
    for h,d,n,w,t in p['horseDist']: state['horse_dist'][(h,int(d))]=[n,w,t]
    for h,v,n,w,t in p['horseVenue']: state['horse_venue'][(h,v)]=[n,w,t]
    for h,j,n,w,t in p['pair']: state['pair'][(h,j)]=[n,w,t]
    return state


def load_selection_state():
    p=_gzip_json(SELECTION_STATE_PATH)
    horse_hist=collections.defaultdict(lambda:collections.deque(maxlen=3))
    for k,rows in p['horseHist'].items(): horse_hist[k]=collections.deque([tuple(x) for x in rows],maxlen=3)
    stats=collections.defaultdict(lambda:[0.0,0.0])
    for bt,axes,vals,n,ret in p['stats']: stats[(int(bt),tuple(axes),tuple(vals))]=[float(n),float(ret)]
    bet_stats=collections.defaultdict(lambda:[0.0,0.0])
    for bt,n,ret in p['betStats']: bet_stats[int(bt)]=[float(n),float(ret)]
    return {
        'throughDate':str(p['throughDate']),
        'currentQuarter':str(p['currentQuarter']),
        'horse_hist':horse_hist,
        'horse_starts':collections.Counter({k:int(v) for k,v in p['horseStarts'].items()}),
        'jstats':collections.defaultdict(lambda:[0,0],{k:list(v) for k,v in p['jstats'].items()}),
        'tstats':collections.defaultdict(lambda:[0,0],{k:list(v) for k,v in p['tstats'].items()}),
        'stats':stats,
        'bet_stats':bet_stats,
    }


def bundles_from_d1(collector, where_sql, params):
    races=collector.d1_query(f'''SELECT race_id AS raceId,race_date AS raceDate,venue,meeting_no AS meetingNo,meeting_day AS meetingDay,race_no AS raceNo,race_name AS raceName,conditions,surface,distance_m AS distanceM,direction,start_time_jst AS startTimeJst,start_time_utc AS startTimeUtc,weather,track_condition AS trackCondition,entry_url AS entryUrl,result_url AS resultUrl,status FROM rt_races WHERE {where_sql} ORDER BY race_date,venue,race_no''',params)
    if not races:return []
    ids=[str(r['raceId']) for r in races]
    by={rid:{'race':next(r for r in races if str(r['raceId'])==rid),'runners':[],'results':[],'payouts':[],'provenance':{}} for rid in ids}
    for start in range(0,len(ids),20):
        chunk=ids[start:start+20]; q=','.join('?' for _ in chunk)
        rr=collector.d1_query(f'''SELECT race_id AS raceId,horse_no AS horseNo,frame_no AS frameNo,horse_name AS horseName,sex_age AS sexAge,coat_color AS coatColor,horse_weight AS horseWeight,weight_change AS weightChange,jockey,assigned_weight AS assignedWeight,trainer,stable,win_odds AS winOdds,popularity,runner_status AS runnerStatus FROM rt_runners WHERE race_id IN ({q}) ORDER BY race_id,horse_no''',chunk)
        for r in rr: by[str(r['raceId'])]['runners'].append(r)
        rs=collector.d1_query(f'''SELECT race_id AS raceId,horse_no AS horseNo,finish_position AS finishPosition,result_status AS resultStatus,time_text AS timeText,margin_text AS marginText,final3f FROM rt_results WHERE race_id IN ({q}) ORDER BY race_id,horse_no''',chunk)
        for r in rs: by[str(r['raceId'])]['results'].append(r)
        pp=collector.d1_query(f'''SELECT race_id AS raceId,bet_type AS betType,combination,payout_yen AS payoutYen,popularity FROM rt_payouts WHERE race_id IN ({q}) ORDER BY race_id,bet_type,combination''',chunk)
        for r in pp: by[str(r['raceId'])]['payouts'].append(r)
    return [by[str(r['raceId'])] for r in races]


def target_bundles(collector,date):
    return bundles_from_d1(collector,'race_date=?',[date])


def delta_bundles(collector,through_date,target_date):
    if through_date>=target_date:return []
    return bundles_from_d1(collector,'race_date>? AND race_date<?',[through_date,target_date])


def group_by_date(bundles):
    out=[]; current=None; day=[]
    for b in bundles:
        d=str(b['race']['raceDate'])
        if current is None: current=d
        if d!=current:
            out.append((current,day)); current=d; day=[]
        day.append(b)
    if current is not None: out.append((current,day))
    return out


def update_feature_state_for_date(state,bundles):
    for b in bundles:
        race=b['race']; rid=str(race['raceId'])
        active=[r for r in b.get('runners',[]) if (r.get('runnerStatus') or 'active')=='active'];active.sort(key=lambda r:int(r.get('horseNo') or 0))
        field=len(active)
        if field<2: continue
        results={safe_int(r.get('horseNo')):r for r in b.get('results',[]) if safe_int(r.get('horseNo')) is not None}
        distance=int(race.get('distanceM') or 0);surf=str(race.get('surface') or '障害');db=ml_dist_bin(distance);venue=str(race.get('venue') or '');ddate=dt.date.fromisoformat(str(race['raceDate']))
        byno={int(r['horseNo']):r for r in active};valid=[]
        for hno,res in results.items():
            pos=safe_int(res.get('finishPosition'));tm=parse_time(res.get('timeText'));f3=safe_float(res.get('final3f'))
            if hno in byno and pos is not None and pos>0:valid.append((hno,pos,tm,f3))
        f3s=sorted((x[3],x[0]) for x in valid if x[3] is not None);f3rank={h:i for i,(_,h) in enumerate(f3s)};nf=len(f3s)
        for hno,pos,tm,f3 in valid:
            r=byno[hno];name=str(r.get('horseName') or f'__{rid}:{hno}');finish_pct=max(0.0,1.0-(pos-1)/max(1,field-1));f3pct=(1.0-f3rank[hno]/max(1,nf-1)) if f3 is not None else 0.5;speed=(distance/tm) if tm and tm>0 and distance>0 else 0.0;win=int(pos==1);top3=int(pos<=3)
            state['horse_hist'][name].append({'date':ddate,'finishPct':finish_pct,'final3fPct':f3pct,'speedMps':speed,'top3':top3,'distance':distance,'surface':surf})
            for stat in (state['horse_total'][name],state['horse_surface'][(name,surf)],state['horse_dist'][(name,db)],state['horse_venue'][(name,venue)],state['jockey'][str(r.get('jockey') or '')],state['trainer'][str(r.get('trainer') or '')],state['pair'][(name,str(r.get('jockey') or ''))]):
                stat[0]+=1;stat[1]+=win;stat[2]+=top3


def advance_feature_state(state,bundles):
    for date,day in group_by_date(bundles):
        update_feature_state_for_date(state,day); state['throughDate']=date


def ml_feature_row(state,race,runner,field):
    rid=str(race['raceId']);date=str(race['raceDate']);ddate=dt.date.fromisoformat(date);distance=int(race.get('distanceM') or 0);surf=str(race.get('surface') or '障害');db=ml_dist_bin(distance);venue=str(race.get('venue') or '');month=int(date[5:7]);rc=ml_class_code(race.get('raceName'),race.get('conditions'))
    hno=int(runner['horseNo']);name=str(runner.get('horseName') or f'__{rid}:{hno}');hist=state['horse_hist'].get(name,());ht=state['horse_total'].get(name);ss=state['horse_surface'].get((name,surf));ds=state['horse_dist'].get((name,db));vs=state['horse_venue'].get((name,venue));j=str(runner.get('jockey') or '');t=str(runner.get('trainer') or '');js=state['jockey'].get(j);ts=state['trainer'].get(t);ps=state['pair'].get((name,j))
    sex,age=parse_sex_age(runner.get('sexAge'));last=hist[-1] if hist else None;days=(ddate-last['date']).days if last else 999;last_dist=last['distance'] if last else distance;last_surf=last['surface'] if last else surf
    return {
        'horseNoRaw':hno,'venue':ML_VENUES.get(venue,0),'raceNo':int(race.get('raceNo') or 0),'surface':SURF.get(surf,2),'distanceM':distance,'direction':1 if str(race.get('direction') or '').startswith('右') else (2 if str(race.get('direction') or '').startswith('左') else 0),'fieldSize':field,'monthSin':math.sin(2*math.pi*month/12),'monthCos':math.cos(2*math.pi*month/12),'raceClass':rc,'weather':WEATHER.get(str(race.get('weather') or ''),6),'trackCondition':TRACK.get(str(race.get('trackCondition') or ''),4),
        'horseNo':hno,'frameNo':int(runner.get('frameNo') or 0),'drawPct':hno/max(1,field),'sex':sex,'age':age,'horseWeight':safe_float(runner.get('horseWeight')) or 0.0,'weightChange':safe_float(runner.get('weightChange')) or 0.0,'assignedWeight':safe_float(runner.get('assignedWeight')) or 0.0,
        'horseStarts':ht[0] if ht else 0,'horseWinRate':rate(ht,'win'),'horseTop3Rate':rate(ht,'top3'),'daysSinceLast':min(999,days),'debutFlag':int(not hist),'lastFinishPct':last['finishPct'] if last else 0.0,'avg3FinishPct':avg(hist,'finishPct',3),'avg5FinishPct':avg(hist,'finishPct',5),'lastTop3':last['top3'] if last else 0,'top3Last3':sum(x['top3'] for x in list(hist)[-3:]) if hist else 0,'lastFinal3fPct':last['final3fPct'] if last else 0.0,'avg3Final3fPct':avg(hist,'final3fPct',3),'avg5Final3fPct':avg(hist,'final3fPct',5),'lastSpeedMps':last['speedMps'] if last else 0.0,'avg3SpeedMps':avg(hist,'speedMps',3),'avg5SpeedMps':avg(hist,'speedMps',5),
        'sameSurfaceStarts':ss[0] if ss else 0,'sameSurfaceWinRate':rate(ss,'win'),'sameSurfaceTop3Rate':rate(ss,'top3'),'sameDistStarts':ds[0] if ds else 0,'sameDistWinRate':rate(ds,'win'),'sameDistTop3Rate':rate(ds,'top3'),'sameVenueStarts':vs[0] if vs else 0,'sameVenueWinRate':rate(vs,'win'),'sameVenueTop3Rate':rate(vs,'top3'),'distanceChange':abs(distance-last_dist),'surfaceSwitch':int(last_surf!=surf),
        'jockeyStarts':js[0] if js else 0,'jockeyWinRate':rate(js,'win'),'jockeyTop3Rate':rate(js,'top3'),'trainerStarts':ts[0] if ts else 0,'trainerWinRate':rate(ts,'win'),'trainerTop3Rate':rate(ts,'top3'),'pairStarts':ps[0] if ps else 0,'pairWinRate':rate(ps,'win'),'pairTop3Rate':rate(ps,'top3'),
    }


def selection_feature_tuple(state,race_id,runner):
    hkey=horse_key(race_id,runner);prior=state['horse_hist'].get(hkey,())
    if prior:
        form=sum(row[0] for row in prior)/len(prior);speed=sum(row[1] for row in prior)/len(prior);top3=sum(row[2] for row in prior);has=True
    else: form=0.0;speed=0.0;top3=0;has=False
    jockey=str(runner.get('jockey') or '');trainer=str(runner.get('trainer') or '')
    jstarts,jtop3=state['jstats'].get(jockey,(0,0)) if jockey else (0,0);tstarts,ttop3=state['tstats'].get(trainer,(0,0)) if trainer else (0,0)
    jr=(jtop3+3)/(jstarts+15);tr=(ttop3+3)/(tstarts+15);starts=int(state['horse_starts'].get(hkey,0))
    return (formcode(form,has),formcode(speed,has),ratecode(jr),ratecode(tr),startsbin(starts),int(top3))


def selection_strength(feature,hno):
    return (sum(feature[:5])+min(3,feature[5]),feature[0]+feature[1],feature[2]+feature[3],feature[5],-hno)


def selection_base_vals(race,n):
    v=str(race.get('venue') or '');s=str(race.get('surface') or '障害');d=int(race.get('distanceM') or 0);rn=int(race.get('raceNo') or 0)
    return {'venue':SEL_VENUE_MAP[v],'surface':{'芝':0,'ダート':1,'障害':2}.get(s,2),'dist':sel_distbin(d),'field':sel_fieldbin(n),'raceNo':sel_rnobin(rn),'rclass':sel_classbin(normalize_class_text(race.get('raceName')),normalize_class_text(race.get('conditions')))}


def combo_vals(base,bt,fs):
    v=dict(base);v.update({'bet':bt,'goodcnt':min(3,sum(1 for x in fs if x[0]>=3)),'bestform':max(x[0] for x in fs),'bestspeed':max(x[1] for x in fs),'bestj':max(x[2] for x in fs),'bestt':max(x[3] for x in fs),'expcnt':min(3,sum(1 for x in fs if x[4]>=2)),'top3lastsum':min(7,sum(x[5] for x in fs))});return v


def candidate_keys(bt,v):
    for a in SINGLES: yield (bt,(a,),(v[a],))
    for a,b in PAIRS: yield (bt,(a,b),(v[a],v[b]))


def payout_index(bundle):
    out={}
    for r in bundle.get('payouts',[]):
        b=str(r.get('betType') or '');c=str(r.get('combination') or '')
        try:y=int(r.get('payoutYen') or 0)
        except Exception:y=0
        if b and c and y>0:out[(b,c)]=max(out.get((b,c),0),y)
    return out


def selection_candidate_rows(state,bundle):
    race=bundle['race'];rid=str(race['raceId']);runners=[r for r in bundle.get('runners',[]) if (r.get('runnerStatus') or 'active')=='active'];runners.sort(key=lambda r:int(r.get('horseNo') or 0))
    if len(runners)<3:return []
    feats={int(r['horseNo']):selection_feature_tuple(state,rid,r) for r in runners};ranked=sorted(feats,key=lambda h:selection_strength(feats[h],h),reverse=True)[:TOP_HORSES];base=selection_base_vals(race,len(runners));out=[]
    for bt,(k,market,jp,ordered) in BET_SPECS.items():
        if len(ranked)<k:continue
        seq=itertools.permutations(ranked,k) if ordered else itertools.combinations(ranked,k)
        for horses in seq:
            combo='-'.join(str(x) for x in (tuple(sorted(horses)) if not ordered else horses));vals=combo_vals(base,bt,[feats[h] for h in horses]);out.append({'bt':bt,'market':market,'betType':jp,'horses':list(horses),'combo':combo,'vals':vals})
    return out


def mean_roi(n,ret,prior_n,prior_roi):return (ret+prior_n*100.0*prior_roi)/(100.0*(n+prior_n))


def selection_ticket_score(ticket,stats,bet_stats):
    bt=ticket['bt'];bn,bret=bet_stats[bt];bmean=mean_roi(bn,bret,BET_PRIOR,PRIOR_ROI);comps=[]
    for key in candidate_keys(bt,ticket['vals']):
        n,ret=stats.get(key,(0,0))
        if n<MIN_N:continue
        km=mean_roi(n,ret,KEY_PRIOR,bmean);reliability=n/(n+KEY_PRIOR);complexity=1.0 if len(key[1])==1 else 0.92;comps.append((km,reliability*complexity,n,key))
    if not comps:return bmean*0.95
    comps.sort(key=lambda x:(x[0],x[1],x[2]),reverse=True);top=comps[:TOP_COMPONENTS];w=sum(x[1] for x in top);local=sum(x[0]*x[1] for x in top)/w if w else bmean
    return (1.0-LOCAL_WEIGHT)*bmean+LOCAL_WEIGHT*local


def select_proxy_tickets(rows,stats,bet_stats):
    scored=[{**t,'score':selection_ticket_score(t,stats,bet_stats)} for t in rows];scored.sort(key=lambda x:(-x['score'],x['bt'],x['combo']))
    if len(scored)<TICKETS_PER_RACE:raise RuntimeError('TOO_FEW_CANDIDATE_TICKETS')
    chosen=scored[:TICKETS_PER_RACE];types={t['bt'] for t in chosen}
    if len(types)<2:
        alt=next((t for t in scored[TICKETS_PER_RACE:] if t['bt'] not in types),None)
        if alt is None:raise RuntimeError('NO_SECOND_BET_TYPE')
        chosen[-1]=alt
    chosen.sort(key=lambda x:(-x['score'],x['bt'],x['combo']))
    if len(chosen)!=3 or len({t['bt'] for t in chosen})<2:raise RuntimeError('PROXY_TICKET_GATE_FAILED')
    return chosen


def update_selection_state_for_date(state,bundles):
    for bundle in bundles:
        race=bundle['race'];race_id=str(race['raceId']);runners=[row for row in bundle.get('runners',[]) if (row.get('runnerStatus') or 'active')=='active'];runners_by_no={int(row['horseNo']):row for row in runners if safe_int(row.get('horseNo')) is not None};field_count=len(runners);results=[]
        for row in bundle.get('results',[]):
            hno=safe_int(row.get('horseNo'));pos=safe_int(row.get('finishPosition'))
            if hno is None or pos is None or pos<=0 or hno not in runners_by_no:continue
            f3=safe_float(row.get('final3f'));results.append((hno,pos,f3))
        valid3f=sorted((f3,hno) for hno,_,f3 in results if f3 is not None);speed_rank={hno:i for i,(_,hno) in enumerate(valid3f)};vf=len(valid3f)
        for hno,pos,f3 in results:
            runner=runners_by_no[hno];hkey=horse_key(race_id,runner);form=max(0.0,1.0-(pos-1)/max(1,field_count-1));speed=0.5 if f3 is None else 1.0-(speed_rank[hno]/max(1,vf-1));state['horse_hist'][hkey].append((form,speed,int(pos<=3)));state['horse_starts'][hkey]+=1
            jockey=str(runner.get('jockey') or '');trainer=str(runner.get('trainer') or '')
            if jockey:state['jstats'][jockey][0]+=1;state['jstats'][jockey][1]+=int(pos<=3)
            if trainer:state['tstats'][trainer][0]+=1;state['tstats'][trainer][1]+=int(pos<=3)


def _selection_quarter_transition(state,date):
    q=quarter(date)
    if state['currentQuarter']!=q:
        if QUARTER_DECAY<1.0:
            for v in state['stats'].values():v[0]*=QUARTER_DECAY;v[1]*=QUARTER_DECAY
            for v in state['bet_stats'].values():v[0]*=QUARTER_DECAY;v[1]*=QUARTER_DECAY
        state['currentQuarter']=q


def advance_selection_state(state,bundles):
    for date,day in group_by_date(bundles):
        _selection_quarter_transition(state,date)
        for b in day:
            pays=payout_index(b)
            for t in selection_candidate_rows(state,b):
                ret=pays.get((t['betType'],t['combo']),0);state['bet_stats'][t['bt']][0]+=1;state['bet_stats'][t['bt']][1]+=ret
                for key in candidate_keys(t['bt'],t['vals']):state['stats'][key][0]+=1;state['stats'][key][1]+=ret
        update_selection_state_for_date(state,day);state['throughDate']=date


def select_target_races(state,bundles,date):
    _selection_quarter_transition(state,date);by=collections.defaultdict(list)
    for b in bundles:
        rows=selection_candidate_rows(state,b);chosen=select_proxy_tickets(rows,state['stats'],state['bet_stats']);score=sum(t['score'] for t in chosen)/len(chosen);by[str(b['race'].get('venue'))].append((b,score))
    selected=[]
    for venue,rows in by.items():
        rows.sort(key=lambda x:(-x[1],int(x[0]['race'].get('raceNo') or 0)))
        if len(rows)<5:raise RuntimeError(f'TARGET_VENUE_FEWER_THAN_FIVE:{venue}:{len(rows)}')
        for b,score in rows[:5]:
            r=b['race'];selected.append({'raceId':str(r['raceId']),'raceDate':date,'venue':venue,'raceNo':int(r.get('raceNo') or 0),'raceName':r.get('raceName'),'startTimeJst':r.get('startTimeJst'),'raceScore':round(score,8)})
    selected.sort(key=lambda r:(SEL_VENUE_MAP.get(r['venue'],99),r['raceNo']))
    return selected


def ordered2(w,a,b):return w[a]*w[b]/max(1e-15,1-w[a])

def ordered3(w,a,b,c):return w[a]*(w[b]/max(1e-15,1-w[a]))*(w[c]/max(1e-15,1-w[a]-w[b]))


def combination_probability(kind,pos,w):
    if kind=='単勝':return w[pos[0]]
    if kind=='馬単':return ordered2(w,pos[0],pos[1])
    if kind=='馬連':
        a,b=pos;return ordered2(w,a,b)+ordered2(w,b,a)
    if kind=='3連単':return ordered3(w,*pos)
    if kind=='3連複':
        a,b,c=pos
        return sum(ordered3(w,*p) for p in ((a,b,c),(a,c,b),(b,a,c),(b,c,a),(c,a,b),(c,b,a)))
    if kind=='ワイド':
        a,b=pos;out=0.0
        for c in range(len(w)):
            if c in (a,b):continue
            out+=sum(ordered3(w,*p) for p in ((a,b,c),(a,c,b),(b,a,c),(b,c,a),(c,a,b),(c,b,a)))
        return out
    raise RuntimeError(f'UNKNOWN_BET_TYPE:{kind}')
