import argparse, sqlite3, json, math, collections, gzip, base64, importlib.util, datetime
from pathlib import Path
BET_TYPES=['単勝','馬連','ワイド','馬単','3連複','3連単'];EN=['win','umaren','wide','umatan','trio','trifecta'];UNORDERED={'馬連','ワイド','3連複'}
PAYOUT_RATIO={'win':1.0,'umaren':0.77,'wide':0.77,'umatan':0.75,'trio':0.75,'trifecta':0.72};ODDS_EDGES=[2,3,5,7,10,15,20,30,50,75,100,150,300,500,800,1200,2000];ODDS_MID=[1.4,2.45,3.9,5.9,8.4,12.2,17.3,24.5,38.7,61.2,86.6,122.5,212.1,387.3,632.5,979.8,1549.2,2500.0];DISTORT_EDGES=[.55,.70,.82,.92,1.02,1.15,1.35,1.70];UNKNOWN={'odds','track','weather','mrank','minpop','maxpop','popsum','favcnt','distort'}
def loadmod(path,name):
 s=importlib.util.spec_from_file_location(name,path)
 if s is None or s.loader is None:raise RuntimeError('MODULE_LOAD_FAILED:'+name)
 m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def bsearch(edges,x):
 i=0
 while i<len(edges) and x>=edges[i]:i+=1
 return i
def mrbin(r):return 0 if r==1 else 1 if r<=3 else 2 if r<=5 else 3 if r<=10 else 4 if r<=20 else 5 if r<=50 else 6 if r<=100 else 7 if r<=250 else 8
def minpb(x):return 0 if x==1 else 1 if x<=3 else 2 if x<=5 else 3 if x<=8 else 4
def maxpb(x):return 0 if x<=2 else 1 if x<=5 else 2 if x<=8 else 3 if x<=11 else 4 if x<=14 else 5
def psb(x):return 0 if x<=3 else 1 if x<=6 else 2 if x<=10 else 3 if x<=15 else 4 if x<=22 else 5 if x<=30 else 6 if x<=40 else 7
def weatherbin(w):return 0 if w=='晴' else 1 if w=='曇' else 3 if w in ('雪','小雪') else 2
def o2(w,a,b):return w[a]*w[b]/max(1e-15,1-w[a])
def o3(w,a,b,c):return w[a]*(w[b]/max(1e-15,1-w[a]))*(w[c]/max(1e-15,1-w[a]-w[b]))
def mprob(pos,typ,w):
 if typ=='win':return w[pos[0]]
 if typ=='umatan':return o2(w,pos[0],pos[1])
 if typ=='umaren':a,b=pos;return o2(w,a,b)+o2(w,b,a)
 if typ=='trifecta':return o3(w,*pos)
 if typ=='trio':
  a,b,c=pos;return sum(o3(w,*p) for p in ((a,b,c),(a,c,b),(b,a,c),(b,c,a),(c,a,b),(c,b,a)))
 a,b=pos;out=0.
 for c in range(len(w)):
  if c in (a,b):continue
  out+=sum(o3(w,*p) for p in ((a,b,c),(a,c,b),(b,a,c),(b,c,a),(c,a,b),(c,b,a)))
 return out
def score(rules,vals,preday=False):
 best=0.
 for rule in rules:
  if all((preday and n in UNKNOWN) or vals.get(n)==v for n,v in rule['conditions']):best=max(best,float(rule['newScore']))
 return best
def history(con,target,p):
 hh=collections.defaultdict(lambda:collections.deque(maxlen=3));hs=collections.defaultdict(lambda:[0,0,0]);js=collections.defaultdict(lambda:[0,0,0]);ts=collections.defaultdict(lambda:[0,0,0])
 races=con.execute("SELECT race_id,race_date FROM rt_races WHERE race_date<=? ORDER BY race_date,venue,race_no",(target,)).fetchall();rr=collections.defaultdict(list)
 for r in con.execute("SELECT race_id,horse_no,horse_name,jockey,trainer,runner_status FROM rt_runners WHERE race_id IN (SELECT race_id FROM rt_races WHERE race_date<=?) ORDER BY race_id,horse_no",(target,)):rr[r['race_id']].append(r)
 res=collections.defaultdict(dict)
 for x in con.execute("SELECT race_id,horse_no,finish_position,final3f FROM rt_results WHERE race_id IN (SELECT race_id FROM rt_races WHERE race_date<?)",(target,)):res[x['race_id']][int(x['horse_no'])]=x
 out={}
 for race in races:
  rid,date=race['race_id'],race['race_date'];rs=[x for x in rr[rid] if (x['runner_status'] or 'active')=='active'];n=len(rs);vf=[]
  if date<target:
   for r in rs:
    x=res[rid].get(int(r['horse_no']));v=x['final3f'] if x else None
    if v is not None:vf.append((int(r['horse_no']),float(v)))
   vf.sort(key=lambda z:z[1]);fscore={h:1.-i/max(1,len(vf)-1) for i,(h,_) in enumerate(vf)}
  else:fscore={}
  hf={}
  for r in rs:
   hn=r['horse_name'] or str(r['horse_no']);jk=r['jockey'] or '';tr=r['trainer'] or '';q=hh[hn];a=hs[hn];b=js[jk];c=ts[tr]
   if q:form=sum(z[0] for z in q)/len(q);speed=sum(z[1] for z in q)/len(q);top3=sum(z[2] for z in q)
   else:form=speed=0.;top3=0
   hf[int(r['horse_no'])]=(p.formcode(form,bool(q)),p.formcode(speed,bool(q)),p.ratecode((b[2]+3)/(b[0]+15)),p.ratecode((c[2]+3)/(c[0]+15)),p.startsbin(a[0]),min(3,top3))
  if date==target:out[rid]=hf
  if date<target:
   for r in rs:
    x=res[rid].get(int(r['horse_no']))
    if not x:continue
    try:pos=int(x['finish_position'])
    except:continue
    if pos<=0:continue
    hn=r['horse_name'] or str(r['horse_no']);jk=r['jockey'] or '';tr=r['trainer'] or '';fs=max(0.,1.-(pos-1)/max(1,n-1));sp=fscore.get(int(r['horse_no']),.5);i3=int(pos<=3);i1=int(pos==1);hh[hn].append((fs,sp,i3))
    for st in (hs[hn],js[jk],ts[tr]):st[0]+=1;st[1]+=i1;st[2]+=i3
 return out
def alloc(bins,U):
 n=len(bins);cap=max(1,int(math.floor(U*.35+1e-12)))
 if n<3 or n>10 or n*cap<U:raise RuntimeError('INVALID_ALLOCATION')
 units=[1]*n;rem=U-n;w=[min(1.,(100./ODDS_MID[b])**1.5) for b in bins];sw=sum(w);t=[U*x/sw for x in w]
 while rem:
  e=[i for i in range(n) if units[i]<cap];e.sort(key=lambda i:(-(t[i]-units[i]),-w[i],ODDS_MID[bins[i]],i));units[e[0]]+=1;rem-=1
 return units
def choose(tickets):
 full=[t for t in tickets if t['full']>0];chosen=[]
 if full:
  mx=max(t['full'] for t in full);chosen=sorted([t for t in full if t['full']>=mx*.85-1e-9],key=lambda t:(-t['full'],-t['pre'],t['bet'],t['combo']))[:10]
 keys={(t['bet'],t['combo']) for t in chosen}
 if len(chosen)<3:
  for t in sorted([t for t in tickets if t['pre']>0 and (t['bet'],t['combo']) not in keys],key=lambda t:(-t['pre'],-t['full'],t['bet'],t['combo'])):
   chosen.append(t);keys.add((t['bet'],t['combo']))
   if len(chosen)>=3:break
 if len(chosen)<3:raise RuntimeError('FEWER_THAN_3_TICKETS')
 types={t['bet'] for t in chosen}
 if len(types)<2:
  cand=sorted([t for t in tickets if t['pre']>0 and t['bet'] not in types and (t['bet'],t['combo']) not in keys],key=lambda t:(-(t['full']>0),-t['full'],-t['pre'],t['bet'],t['combo']))
  if not cand:raise RuntimeError('NO_SECOND_BET_TYPE')
  if len(chosen)<10:chosen.append(cand[0])
  else:chosen[min(range(len(chosen)),key=lambda i:(chosen[i]['pre'],chosen[i]['full'],chosen[i]['combo']))]=cand[0]
 chosen.sort(key=lambda t:(-t['full'],-t['pre'],t['bet'],t['combo']))
 if not(3<=len(chosen)<=10) or len({t['bet'] for t in chosen})<2:raise RuntimeError('FINAL_TICKET_GATE_FAILED')
 return chosen
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--repo',default='.');ap.add_argument('--db',required=True);ap.add_argument('--date',default='2026-08-09');ap.add_argument('--selection',default='analysis-results/final-aug9-selection.json');ap.add_argument('--out',default='analysis-results/final-aug9-bets.json');ap.add_argument('--insert',action='store_true');a=ap.parse_args();repo=Path(a.repo).resolve()
 p=loadmod(repo/'scripts'/'generate-final-preday-selection.py','preday');collector=loadmod(repo/'scripts'/'collect-jra-official-odds.py','collector');rules=json.loads(gzip.decompress(base64.b64decode(p.RULES_B64)).decode());assert len(rules)==316
 by=collections.defaultdict(list)
 for r in rules:
  b=next((v for n,v in r['conditions'] if n=='bet'),None)
  if b is None:
   for i in range(6):by[i].append(r)
  else:by[int(b)].append(r)
 sel=json.loads((repo/a.selection).read_text());ids=[x['raceId'] for x in sel['selected']];assert len(ids)==15 and sel.get('resultDataUsedForTargetDay') is False
 con=sqlite3.connect(a.db);con.row_factory=sqlite3.Row;hf=history(con,a.date,p);q=','.join('?'*len(ids));races={r['race_id']:r for r in con.execute(f"SELECT race_id,venue,race_no,race_name,conditions,surface,distance_m,direction,weather,track_condition,start_time_jst FROM rt_races WHERE race_id IN ({q})",ids)}
 runners={rid:[r for r in con.execute("SELECT horse_no,runner_status FROM rt_runners WHERE race_id=? ORDER BY horse_no",(rid,)) if (r['runner_status'] or 'active')=='active'] for rid in ids};od=collections.defaultdict(lambda:collections.defaultdict(dict))
 for r in con.execute(f"SELECT race_id,bet_type,combination,odds_min,odds_max FROM rt_official_odds_latest WHERE race_id IN ({q})",ids):od[r['race_id']][r['bet_type']][r['combination']]=(float(r['odds_min'])+float(r['odds_max']))/2
 specs=[(0,'単勝','win',1,False),(1,'馬連','umaren',2,False),(2,'ワイド','wide',2,False),(3,'馬単','umatan',2,True),(4,'3連複','trio',3,False),(5,'3連単','trifecta',3,True)];out=[]
 for rid in ids:
  race=races[rid];hn=[int(x['horse_no']) for x in runners[rid]];n=len(hn);single=od[rid].get('単勝',{})
  if any(str(h) not in single for h in hn):raise RuntimeError('WIN_ODDS_INCOMPLETE:'+rid)
  win=[single[str(h)] for h in hn];raw=[1/x for x in win];sw=sum(raw);w=[x/sw for x in raw];order=sorted(range(n),key=lambda i:(win[i],i));pop=[0]*n
  for rank,i in enumerate(order,1):pop[i]=rank
  surface=race['surface'] or '障害';dm=int(race['distance_m'] or 0);venue=race['venue'];rn=int(race['race_no']);base={'venue':p.VENUE_MAP[venue],'surface':{'芝':0,'ダート':1,'障害':2}.get(surface,2),'dist':p.distbin(dm),'track':{'良':0,'稍重':1,'重':2,'不良':3}.get(race['track_condition'],0),'weather':weatherbin(race['weather']),'field':p.fieldbin(n),'raceNo':p.rnobin(rn),'season':p.seasonbin(int(a.date[5:7])),'rclass':p.classbin(race['race_name'],race['conditions']),'direction':p.directionbin(venue,surface,dm,race['direction'])};tickets=[]
  for bt,jp,en,k,ordered in specs:
   om=od[rid].get(jp,{})
   if not om:continue
   rows=[]
   for pp in p.combos(n,k,ordered):
    hs=[hn[i] for i in pp];combo='-'.join(map(str,sorted(hs) if jp in UNORDERED else hs));odd=om.get(combo)
    if odd is not None and odd>1:rows.append((pp,hs,combo,float(odd)))
   ranks={orig:rank for rank,(orig,_) in enumerate(sorted(enumerate(rows),key=lambda z:(z[1][3],z[0])),1)}
   for idx,(pp,hs,combo,odd) in enumerate(rows):
    fs=[hf[rid][h] for h in hs];pops=[pop[hn.index(h)] for h in hs];ratio=odd/(PAYOUT_RATIO[en]/max(mprob(pp,en,w),1e-15));vals=dict(base);vals.update({'bet':bt,'odds':bsearch(ODDS_EDGES,odd),'mrank':mrbin(ranks[idx]),'minpop':minpb(min(pops)),'maxpop':maxpb(max(pops)),'popsum':psb(sum(pops)),'favcnt':min(3,sum(x<=1 for x in pops)),'distort':bsearch(DISTORT_EDGES,ratio),'goodcnt':min(3,sum(x[0]>=3 for x in fs)),'bestform':max(x[0] for x in fs),'bestspeed':max(x[1] for x in fs),'bestj':max(x[2] for x in fs),'bestt':max(x[3] for x in fs),'expcnt':min(3,sum(x[4]>=2 for x in fs)),'top3lastsum':min(7,sum(x[5] for x in fs))});f=score(by[bt],vals);pr=score(by[bt],vals,True)
    if f>0 or pr>0:tickets.append({'bet':bt,'betType':jp,'combo':combo,'odds':odd,'oddsBin':vals['odds'],'full':f,'pre':pr})
  chosen=choose(tickets);courses=[]
  for course,budget in [('ライト',2000),('スタンダード',5000),('プレミアム',10000)]:
   units=alloc([t['oddsBin'] for t in chosen],budget//100);courses += [{'course':course,'betType':t['betType'],'combination':t['combo'],'stakeYen':u*100,'assumedOdds':t['odds']} for t,u in zip(chosen,units)]
  out.append({'raceId':rid,'venue':venue,'raceNo':rn,'raceName':race['race_name'],'startTimeJst':race['start_time_jst'],'tickets':[{'betType':t['betType'],'combination':t['combo'],'odds':t['odds'],'fullScore':t['full'],'predayScore':t['pre']} for t in chosen],'courseBets':courses})
 art={'date':a.date,'selectedRaceCount':15,'sourceRuleCount':316,'resultDataUsedForTargetDay':False,'officialOddsOnly':True,'generatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'races':out};(repo/a.out).write_text(json.dumps(art,ensure_ascii=False,indent=2)+'\n')
 if a.insert:
  collector.d1_query('''CREATE TABLE IF NOT EXISTS rt_public_bets(id INTEGER PRIMARY KEY AUTOINCREMENT,race_id TEXT NOT NULL,course TEXT NOT NULL,bet_type TEXT NOT NULL,combination TEXT NOT NULL,stake_yen INTEGER NOT NULL,assumed_odds REAL,return_yen INTEGER,settlement_status TEXT NOT NULL,locked_at TEXT,source_prediction_id INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(race_id,course,bet_type,combination))''');existing=collector.d1_query("SELECT race_id,course,bet_type,combination,stake_yen,assumed_odds FROM rt_public_bets WHERE race_id LIKE '2026-08-09-%'");desired=[]
  for r in out:
   for b in r['courseBets']:desired.append((r['raceId'],b['course'],b['betType'],b['combination'],b['stakeYen'],round(b['assumedOdds'],6)))
  if existing:
   ex={(x['race_id'],x['course'],x['bet_type'],x['combination'],int(x['stake_yen']),round(float(x['assumed_odds'] or 0),6)) for x in existing}
   if ex!=set(desired):raise RuntimeError('IMMUTABLE_EXISTING_AUG9_BETS_MISMATCH')
  else:
   for rid,course,bt,combo,stake,odd in desired:collector.d1_query("INSERT INTO rt_public_bets(race_id,course,bet_type,combination,stake_yen,assumed_odds,return_yen,settlement_status,locked_at,source_prediction_id) VALUES(?,?,?,?,?,?,NULL,'pending',?,-2)",[rid,course,bt,combo,stake,odd,art['generatedAt']])
 print(json.dumps({'races':15,'tickets':[(r['raceId'],len(r['tickets'])) for r in out],'insert':a.insert},ensure_ascii=False))
if __name__=='__main__':main()
