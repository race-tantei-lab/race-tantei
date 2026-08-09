import argparse, sqlite3, json, itertools, collections, gzip, base64
from pathlib import Path

RULES_B64='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'
UNKNOWN={'odds','track','weather','mrank','minpop','maxpop','popsum','favcnt','distort'}
VENUES=['東京','中山','京都','阪神','中京','新潟','福島','小倉','札幌','函館']
VENUE_MAP={v:i for i,v in enumerate(VENUES)}

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
 return list(itertools.permutations(range(n),k) if ordered else itertools.combinations(range(n),k))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--db',required=True);ap.add_argument('--date',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
 con=sqlite3.connect(a.db);con.row_factory=sqlite3.Row
 rules=json.loads(gzip.decompress(base64.b64decode(RULES_B64)).decode('utf-8')); assert len(rules)==264
 horse_hist=collections.defaultdict(lambda:collections.deque(maxlen=3));horse_stats=collections.defaultdict(lambda:[0,0,0]);jstats=collections.defaultdict(lambda:[0,0,0]);tstats=collections.defaultdict(lambda:[0,0,0])
 races=con.execute("SELECT race_id,race_date,venue,race_no,race_name,conditions,surface,distance_m,direction,start_time_jst FROM rt_races WHERE race_date<=? ORDER BY race_date,venue,race_no",(a.date,)).fetchall()
 runner_rows=collections.defaultdict(list)
 for r in con.execute("SELECT race_id,horse_no,horse_name,jockey,trainer,runner_status FROM rt_runners WHERE race_id IN (SELECT race_id FROM rt_races WHERE race_date<=?) ORDER BY race_id,horse_no",(a.date,)): runner_rows[r['race_id']].append(r)
 res=collections.defaultdict(dict)
 for x in con.execute("SELECT race_id,horse_no,finish_position,final3f FROM rt_results WHERE race_id IN (SELECT race_id FROM rt_races WHERE race_date<?)",(a.date,)): res[x['race_id']][int(x['horse_no'])]=x
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
   for bt,k,ordered in [(0,1,False),(1,2,False),(2,2,False),(3,2,True),(4,3,False),(5,3,True)]:
    for pos in combos(n,k,ordered):
     fs=[hfeat[horse_nos[i]] for i in pos];vals=dict(base);vals['bet']=bt
     vals.update({'goodcnt':min(3,sum(1 for q in fs if q[0]>=3)),'bestform':max(q[0] for q in fs),'bestspeed':max(q[1] for q in fs),'bestj':max(q[2] for q in fs),'bestt':max(q[3] for q in fs),'expcnt':min(3,sum(1 for q in fs if q[4]>=2)),'top3lastsum':min(7,sum(q[5] for q in fs))})
     score=0.
     for rule in rules:
      if all(vals.get(name)==val for name,val in rule['conditions']): score=max(score,float(rule['newScore']))
     if score>race_score:race_score=score;best=[{'bet':bt,'horses':[horse_nos[i] for i in pos],'predayScore':score}]
     elif score==race_score and score>0 and len(best)<8:best.append({'bet':bt,'horses':[horse_nos[i] for i in pos],'predayScore':score})
   targets.append({'raceId':rid,'raceDate':date,'venue':venue,'raceNo':rn,'raceName':race['race_name'],'startTimeJst':race['start_time_jst'],'surface':surface,'distanceM':dm,'raceScore':race_score,'bestPredayTickets':best})
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
  if len(chosen)!=5: raise RuntimeError(f'INSUFFICIENT_TARGET_RACES:{venue}:{len(chosen)}')
  for x in chosen:x['selected']=True
  selected.extend(chosen)
 out={'date':a.date,'selected':selected,'allRaces':targets,'sourceRuleCount':316,'deduplicatedPredayRuleCount':len(rules),'selectionRule':'previous-day score, top five per venue, tie raceNo ascending','resultDataUsedForTargetDay':False}
 Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'selected':[(x['venue'],x['raceNo'],round(x['raceScore'],3)) for x in selected]},ensure_ascii=False))
if __name__=='__main__':main()
