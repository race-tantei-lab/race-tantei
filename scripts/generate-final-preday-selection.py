import argparse, sqlite3, json, itertools, collections, math, gzip, base64
from pathlib import Path

RULES_B64='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[... ELLIPSIZATION ...]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'

UNKNOWN={'odds','track','weather','mrank','minpop','maxpop','popsum','favcnt','distort'}
VENUES=['東京','中山','京都','阪神','中京','新潟','福島','小倉','札幌','函館']
VENUE_MAP={v:i for i,v in enumerate(VENUES)}
FEATURES=['bet','venue','surface','dist','odds','track','weather','field','raceNo','season','mrank','minpop','maxpop','popsum','favcnt','distort','rclass','direction']
HF=['goodcnt','bestform','bestspeed','bestj','bestt','expcnt','top3lastsum']

def distbin(d): return 0 if d<=1200 else 1 if d<=1500 else 2 if d<=1800 else 3 if d<=2200 else 4 if d<=2600 else 5
def fieldbin(n): return 0 if n<=8 else 1 if n<=11 else 2 if n<=13 else 3 if n<=16 else 4
def rnobin(r): return 0 if r<=3 else 1 if r<=6 else 2 if r<=9 else 3
def seasonbin(m): return 0 if m in (12,1,2) else 1 if m in (3,4,5) else 2 if m in (6,7,8) else 3
def classbin(name,conditions=''):
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
def directionbin(venue,surface,distance,direction):
 d=str(direction or '')
 if '直' in d or (venue=='新潟' and surface=='芝' and int(distance or 0)==1000): return 2
 if d=='左' or venue in ('東京','中京','新潟'): return 1
 return 0
def ratecode(rate): return 0 if rate<.15 else 1 if rate<.25 else 2 if rate<.35 else 3 if rate<.45 else 4
def formcode(v,has): return 0 if not has else 1 if v<.30 else 2 if v<.50 else 3 if v<.70 else 4
def startsbin(n): return 0 if n==0 else 1 if n<=2 else 2 if n<=5 else 3 if n<=10 else 4

def combos(n,k,ordered=False):
 if k==1:return [(i,) for i in range(n)]
 if ordered:return list(itertools.permutations(range(n),k))
 return list(itertools.combinations(range(n),k))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--db',required=True);ap.add_argument('--date',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
 con=sqlite3.connect(a.db);con.row_factory=sqlite3.Row
 rules=json.loads(gzip.decompress(base64.b64decode(RULES_B64)).decode('utf-8')); assert len(rules)==316
 # history state built strictly chronologically; target-day results are never touched
 horse_hist=collections.defaultdict(lambda:collections.deque(maxlen=3));horse_stats=collections.defaultdict(lambda:[0,0,0]);jstats=collections.defaultdict(lambda:[0,0,0]);tstats=collections.defaultdict(lambda:[0,0,0])
 races=con.execute("SELECT race_id,race_date,venue,race_no,race_name,conditions,surface,distance_m,direction FROM rt_races WHERE race_date<=? ORDER BY race_date,venue,race_no",(a.date,)).fetchall()
 runner_rows=collections.defaultdict(list)
 for r in con.execute("SELECT race_id,horse_no,horse_name,jockey,trainer,runner_status FROM rt_runners WHERE race_id IN (SELECT race_id FROM rt_races WHERE race_date<=?) ORDER BY race_id,horse_no",(a.date,)):
  runner_rows[r['race_id']].append(r)
 res=collections.defaultdict(dict)
 for x in con.execute("SELECT race_id,horse_no,finish_position,final3f FROM rt_results WHERE race_id IN (SELECT race_id FROM rt_races WHERE race_date<?)",(a.date,)):
  res[x['race_id']][int(x['horse_no'])]=x
 targets=[]
 for race in races:
  rid=race['race_id'];date=race['race_date'];rs=[x for x in runner_rows[rid] if (x['runner_status'] or 'active')=='active'];n=len(rs)
  validf=[]
  if date<a.date:
   for rr in rs:
    x=res[rid].get(int(rr['horse_no']));v=x['final3f'] if x else None
    if v is not None:validf.append((int(rr['horse_no']),float(v)))
   validf.sort(key=lambda z:z[1]);fscore={h:(1.0-(i/max(1,len(validf)-1))) for i,(h,_) in enumerate(validf)}
  else:fscore={}
  hfeat={}
  for rr in rs:
   hn=rr['horse_name'] or str(rr['horse_no']);jk=rr['jockey'] or '';tr=rr['trainer'] or '';hh=horse_hist[hn];hs=horse_stats[hn];js=jstats[jk];ts=tstats[tr]
   if hh: form=sum(q[0] for q in hh)/len(hh);speed=sum(q[1] for q in hh)/len(hh);top3=sum(q[2] for q in hh)
   else:form=speed=0.;top3=0
   jr=(js[2]+3)/(js[0]+15);trr=(ts[2]+3)/(ts[0]+15)
   hfeat[int(rr['horse_no'])]=(formcode(form,bool(hh)),formcode(speed,bool(hh)),ratecode(jr),ratecode(trr),startsbin(hs[0]),min(3,top3))
  if date==a.date and n>=3:
   venue=race['venue'];surface=race['surface'] or '障害';dm=int(race['distance_m'] or 0);rn=int(race['race_no']);base={'venue':VENUE_MAP[venue],'surface':{'芝':0,'ダート':1,'障害':2}.get(surface,2),'dist':distbin(dm),'field':fieldbin(n),'raceNo':rnobin(rn),'season':seasonbin(int(date[5:7])),'rclass':classbin(race['race_name'],race['conditions']),'direction':directionbin(venue,surface,dm,race['direction'])}
   horse_nos=[int(x['horse_no']) for x in rs];race_score=0.;best=[]
   type_specs=[(0,1,False),(1,2,False),(2,2,False),(3,2,True),(4,3,False),(5,3,True)]
   for bt,k,ordered in type_specs:
    for pos in combos(n,k,ordered):
     fs=[hfeat[horse_nos[i]] for i in pos];vals=dict(base);vals['bet']=bt
     vals.update({'goodcnt':min(3,sum(1 for q in fs if q[0]>=3)),'bestform':max(q[0] for q in fs),'bestspeed':max(q[1] for q in fs),'bestj':max(q[2] for q in fs),'bestt':max(q[3] for q in fs),'expcnt':min(3,sum(1 for q in fs if q[4]>=2)),'top3lastsum':min(7,sum(q[5] for q in fs))})
     score=0.
     for rule in rules:
      ok=True
      for name,val in rule['conditions']:
       if name in UNKNOWN:continue
       if vals.get(name)!=val:ok=False;break
      if ok:score=max(score,float(rule['newScore']))
     if score>race_score:race_score=score;best=[{'bet':bt,'horses':[horse_nos[i] for i in pos],'predayScore':score}]
     elif score==race_score and score>0 and len(best)<8:best.append({'bet':bt,'horses':[horse_nos[i] for i in pos],'predayScore':score})
   targets.append({'raceId':rid,'raceDate':date,'venue':venue,'raceNo':rn,'raceName':race['race_name'],'startTimeJst':con.execute('SELECT start_time_jst FROM rt_races WHERE race_id=?',(rid,)).fetchone()[0],'surface':surface,'distanceM':dm,'raceScore':race_score,'bestPredayTickets':best})
  # update only after feature snapshot, and only races strictly before target date
  if date<a.date:
   for rr in rs:
    x=res[rid].get(int(rr['horse_no']))
    if not x:continue
    pos=x['finish_position']
    if not isinstance(pos,int) or pos<=0:continue
    hn=rr['horse_name'] or str(rr['horse_no']);jk=rr['jockey'] or '';tr=rr['trainer'] or '';finishscore=max(0.,1.0-(pos-1)/max(1,n-1));sp=fscore.get(int(rr['horse_no']),.5);is3=int(pos<=3);is1=int(pos==1)
    horse_hist[hn].append((finishscore,sp,is3))
    for st in (horse_stats[hn],jstats[jk],tstats[tr]):st[0]+=1;st[1]+=is1;st[2]+=is3
 selected=[]
 for venue in sorted({x['venue'] for x in targets}):
  rows=[x for x in targets if x['venue']==venue];rows.sort(key=lambda x:(-x['raceScore'],x['raceNo']));chosen=rows[:5]
  assert len(chosen)==5
  for x in chosen:x['selected']=True
  selected.extend(chosen)
 out={'date':a.date,'selected':selected,'allRaces':targets,'ruleCount':len(rules),'selectionRule':'previous-day score, top five per venue, tie raceNo ascending','resultDataUsedForTargetDay':False}
 Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'selected':[(x['venue'],x['raceNo'],round(x['raceScore'],3)) for x in selected]},ensure_ascii=False))
if __name__=='__main__':main()
