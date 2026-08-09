import argparse, sqlite3, json, math, itertools, collections, gzip, base64, importlib.util, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[0]
BET_TYPES=['単勝','馬連','ワイド','馬単','3連複','3連単']
EN=['win','umaren','wide','umatan','trio','trifecta']
UNORDERED={'馬連','ワイド','3連複'}
PAYOUT_RATIO={'win':1.0,'umaren':0.77,'wide':0.77,'umatan':0.75,'trio':0.75,'trifecta':0.72}
ODDS_EDGES=[2,3,5,7,10,15,20,30,50,75,100,150,300,500,800,1200,2000]
ODDS_MID=[1.4,2.45,3.9,5.9,8.4,12.2,17.3,24.5,38.7,61.2,86.6,122.5,212.1,387.3,632.5,979.8,1549.2,2500.0]
DISTORT_EDGES=[0.55,0.70,0.82,0.92,1.02,1.15,1.35,1.70]
UNKNOWN={'odds','track','weather','mrank','minpop','maxpop','popsum','favcnt','distort'}


def load_selection_module(repo):
    p=Path(repo)/'scripts'/'generate-final-preday-selection.py'
    spec=importlib.util.spec_from_file_location('predaymod',p)
    if spec is None or spec.loader is None: raise RuntimeError('PREDAY_MODULE_LOAD_FAILED')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def load_rules_module(repo):
    p=Path(repo)/'scripts'/'final-rules-payload.py'
    spec=importlib.util.spec_from_file_location('finalrules',p)
    if spec is None or spec.loader is None: raise RuntimeError('FINAL_RULES_LOAD_FAILED')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def load_collector(repo):
    p=Path(repo)/'scripts'/'collect-jra-official-odds.py'
    spec=importlib.util.spec_from_file_location('oddsmod',p)
    if spec is None or spec.loader is None: raise RuntimeError('ODDS_MODULE_LOAD_FAILED')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def bsearch(edges,x):
    lo=0
    while lo<len(edges) and x>=edges[lo]:lo+=1
    return lo

def market_rank_bin(r):
    return 0 if r==1 else 1 if r<=3 else 2 if r<=5 else 3 if r<=10 else 4 if r<=20 else 5 if r<=50 else 6 if r<=100 else 7 if r<=250 else 8

def minpop_bin(x): return 0 if x==1 else 1 if x<=3 else 2 if x<=5 else 3 if x<=8 else 4
def maxpop_bin(x): return 0 if x<=2 else 1 if x<=5 else 2 if x<=8 else 3 if x<=11 else 4 if x<=14 else 5
def popsum_bin(x): return 0 if x<=3 else 1 if x<=6 else 2 if x<=10 else 3 if x<=15 else 4 if x<=22 else 5 if x<=30 else 6 if x<=40 else 7
def weatherbin(w): return 0 if w=='晴' else 1 if w=='曇' else 3 if w in ('雪','小雪') else 2

def ordered2(w,a,b):
    den=max(1e-15,1-w[a]);return w[a]*w[b]/den

def ordered3(w,a,b,c):
    return w[a]*(w[b]/max(1e-15,1-w[a]))*(w[c]/max(1e-15,1-w[a]-w[b]))

def market_prob(pos,typ,w):
    if typ=='win':return w[pos[0]]
    if typ=='umatan':return ordered2(w,pos[0],pos[1])
    if typ=='umaren':
        a,b=pos;return ordered2(w,a,b)+ordered2(w,b,a)
    if typ=='trifecta':return ordered3(w,*pos)
    if typ=='trio':
        a,b,c=pos
        return sum(ordered3(w,*p) for p in ((a,b,c),(a,c,b),(b,a,c),(b,c,a),(c,a,b),(c,b,a)))
    a,b=pos;out=0.0
    for c in range(len(w)):
        if c in (a,b):continue
        out+=sum(ordered3(w,*p) for p in ((a,b,c),(a,c,b),(b,a,c),(b,c,a),(c,a,b),(c,b,a)))
    return out

def rule_score(rules_by_bet,bet,vals,preday=False):
    best=0.0
    for rule in rules_by_bet.get(bet,[]):
        ok=True
        for name,val in rule['conditions']:
            if preday and name in UNKNOWN:continue
            if vals.get(name)!=val:
                ok=False;break
        if ok:best=max(best,float(rule['newScore']))
    return best

def history_features(con,target,pmod):
    horse_hist=collections.defaultdict(lambda:collections.deque(maxlen=3));horse_stats=collections.defaultdict(lambda:[0,0,0]);jstats=collections.defaultdict(lambda:[0,0,0]);tstats=collections.defaultdict(lambda:[0,0,0])
    races=con.execute("SELECT race_id,race_date,venue,race_no FROM rt_races WHERE race_date<=? ORDER BY race_date,venue,race_no",(target,)).fetchall()
    rr=collections.defaultdict(list)
    for r in con.execute("SELECT race_id,horse_no,horse_name,jockey,trainer,runner_status FROM rt_runners WHERE race_id IN (SELECT race_id FROM rt_races WHERE race_date<=?) ORDER BY race_id,horse_no",(target,)):
        rr[r['race_id']].append(r)
    res=collections.defaultdict(dict)
    for x in con.execute("SELECT race_id,horse_no,finish_position,final3f FROM rt_results WHERE race_id IN (SELECT race_id FROM rt_races WHERE race_date<?)",(target,)):
        res[x['race_id']][int(x['horse_no'])]=x
    target_feat={}
    for race in races:
        rid=race['race_id'];date=race['race_date'];rs=[x for x in rr[rid] if (x['runner_status'] or 'active')=='active'];n=len(rs)
        validf=[]
        if date<target:
            for r in rs:
                x=res[rid].get(int(r['horse_no']));v=x['final3f'] if x else None
                if v is not None:validf.append((int(r['horse_no']),float(v)))
            validf.sort(key=lambda z:z[1]);fscore={h:(1.0-(i/max(1,len(validf)-1))) for i,(h,_) in enumerate(validf)}
        else:fscore={}
        hf={}
        for r in rs:
            hn=r['horse_name'] or str(r['horse_no']);jk=r['jockey'] or '';tr=r['trainer'] or '';hh=horse_hist[hn];hs=horse_stats[hn];js=jstats[jk];ts=tstats[tr]
            if hh:form=sum(q[0] for q in hh)/len(hh);speed=sum(q[1] for q in hh)/len(hh);top3=sum(q[2] for q in hh)
            else:form=speed=0.;top3=0
            jr=(js[2]+3)/(js[0]+15);trr=(ts[2]+3)/(ts[0]+15)
            hf[int(r['horse_no'])]=(pmod.formcode(form,bool(hh)),pmod.formcode(speed,bool(hh)),pmod.ratecode(jr),pmod.ratecode(trr),pmod.startsbin(hs[0]),min(3,top3))
        if date==target:target_feat[rid]=hf
        if date<target:
            for r in rs:
                x=res[rid].get(int(r['horse_no']))
                if not x:continue
                try:pos=int(x['finish_position'])
                except:continue
                if pos<=0:continue
                hn=r['horse_name'] or str(r['horse_no']);jk=r['jockey'] or '';tr=r['trainer'] or '';finishscore=max(0.,1.0-(pos-1)/max(1,n-1));sp=fscore.get(int(r['horse_no']),.5);is3=int(pos<=3);is1=int(pos==1)
                horse_hist[hn].append((finishscore,sp,is3))
                for st in (horse_stats[hn],jstats[jk],tstats[tr]):st[0]+=1;st[1]+=is1;st[2]+=is3
    return target_feat

def allocate(bin_codes,U):
    n=len(bin_codes);cap=max(1,int(math.floor(U*.35+1e-12)))
    if n<3 or n>10 or n*cap<U:raise RuntimeError(f'INVALID_ALLOCATION:{n}:{U}:{cap}')
    units=[1]*n;rem=U-n;weights=[min(1.0,(100.0/ODDS_MID[b])**1.5) for b in bin_codes];tw=sum(weights);targets=[U*w/tw for w in weights]
    while rem>0:
        elig=[i for i in range(n) if units[i]<cap]
        elig.sort(key=lambda i:(-(targets[i]-units[i]),-weights[i],ODDS_MID[bin_codes[i]],i))
        if not elig:raise RuntimeError('ALLOCATION_FAILED')
        units[elig[0]]+=1;rem-=1
    return units

def select_tickets(tickets):
    full=[t for t in tickets if t['full']>0]
    chosen=[]
    if full:
        mx=max(t['full'] for t in full);eligible=[t for t in full if t['full']>=mx*.85-1e-9]
        eligible.sort(key=lambda t:(-t['full'],-t['pre'],t['bet'],t['combo']))
        chosen=eligible[:10]
    chosen_keys={(t['bet'],t['combo']) for t in chosen}
    if len(chosen)<3:
        supp=[t for t in tickets if t['pre']>0 and (t['bet'],t['combo']) not in chosen_keys]
        supp.sort(key=lambda t:(-t['pre'],-t['full'],t['bet'],t['combo']))
        for t in supp:
            chosen.append(t);chosen_keys.add((t['bet'],t['combo']))
            if len(chosen)>=3:break
    if len(chosen)<3:raise RuntimeError('FEWER_THAN_3_TICKETS')
    types={t['bet'] for t in chosen}
    if len(types)<2:
        cand=[t for t in tickets if t['pre']>0 and t['bet'] not in types and (t['bet'],t['combo']) not in chosen_keys]
        cand.sort(key=lambda t:(-(1 if t['full']>0 else 0),-t['full'],-t['pre'],t['bet'],t['combo']))
        if not cand:raise RuntimeError('NO_SECOND_BET_TYPE')
        t=cand[0]
        if len(chosen)<10:chosen.append(t)
        else:
            weak=min(range(len(chosen)),key=lambda i:(chosen[i]['pre'],chosen[i]['full'],tuple(-x for x in chosen[i]['horses'])))
            chosen[weak]=t
    chosen.sort(key=lambda t:(-t['full'],-t['pre'],t['bet'],t['combo']))
    if not(3<=len(chosen)<=10) or len({t['bet'] for t in chosen})<2:raise RuntimeError('FINAL_TICKET_GATE_FAILED')
    return chosen

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--repo',default='.');ap.add_argument('--db',required=True);ap.add_argument('--date',default='2026-08-09');ap.add_argument('--selection',default='analysis-results/final-aug9-selection.json');ap.add_argument('--out',default='analysis-results/final-live-bets.json');ap.add_argument('--odds-file',default='current-selected-official-odds.json.gz');ap.add_argument('--insert',action='store_true');a=ap.parse_args()
    repo=Path(a.repo).resolve();pmod=load_selection_module(repo);collector=load_collector(repo);rmod=load_rules_module(repo)
    rules=rmod.load_rules();assert len(rules)==316
    rb=collections.defaultdict(list)
    for rule in rules:
        b=next((v for n,v in rule['conditions'] if n=='bet'),None)
        if b is not None:rb[int(b)].append(rule)
        else:
            for bt in range(6):rb[bt].append(rule)
    sel=json.loads((repo/a.selection).read_text(encoding='utf-8'));ids=[r['raceId'] for r in sel['selected']];assert len(ids)==15 and sel.get('resultDataUsedForTargetDay') is False
    con=sqlite3.connect(a.db);con.row_factory=sqlite3.Row
    hf_all=history_features(con,a.date,pmod)
    q=','.join('?'*len(ids))
    races={r['race_id']:r for r in con.execute(f"SELECT race_id,race_date,venue,race_no,race_name,conditions,surface,distance_m,direction,weather,track_condition,start_time_jst FROM rt_races WHERE race_id IN ({q})",ids)}
    runner={rid:[r for r in con.execute("SELECT horse_no,horse_name,jockey,trainer,runner_status FROM rt_runners WHERE race_id=? ORDER BY horse_no",(rid,)) if (r['runner_status'] or 'active')=='active'] for rid in ids}
    odds=collections.defaultdict(lambda:collections.defaultdict(dict))
    odds_path=repo/a.odds_file
    if not odds_path.exists(): raise RuntimeError(f'ODDS_FILE_MISSING:{odds_path}')
    with gzip.open(odds_path,'rt',encoding='utf-8') as fh: odds_rows=json.load(fh)
    captured_by_race={}
    for r in odds_rows:
        rid=str(r.get('raceId',''))
        if rid not in ids: continue
        bt=str(r.get('betType',''));combo=str(r.get('combination',''))
        if not bt or not combo: continue
        odds[rid][bt][combo]=(float(r['oddsMin'])+float(r['oddsMax']))/2
        captured_by_race[rid]=max(captured_by_race.get(rid,''),str(r.get('capturedAtUtc','')))
    available=[]
    needed=set(BET_TYPES)
    for rid in ids:
        if set(odds[rid].keys())>=needed: available.append(rid)
    if not available: raise RuntimeError('NO_COMPLETE_SELECTED_RACE_ODDS')
    ids=available
    out=[]
    specs=[(0,'単勝','win',1,False),(1,'馬連','umaren',2,False),(2,'ワイド','wide',2,False),(3,'馬単','umatan',2,True),(4,'3連複','trio',3,False),(5,'3連単','trifecta',3,True)]
    existing_remote=collector.d1_query("SELECT DISTINCT race_id FROM rt_public_bets WHERE race_id LIKE ?",[a.date+'-%']) if a.insert else []
    already={str(x['race_id']) for x in existing_remote}
    ids=[rid for rid in ids if rid not in already]
    if not ids:
        artifact={'date':a.date,'lockedRaceCount':0,'selectedRaceCount':len(sel['selected']),'sourceRuleCount':316,'resultDataUsedForTargetDay':False,'officialOddsOnly':True,'generatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'races':[]}
        (repo/a.out).write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'races':0,'alreadyLocked':len(already),'inserted':False},ensure_ascii=False));return
    for rid in ids:
        race=races.get(rid);rs=runner.get(rid,[])
        if race is None or len(rs)<3:raise RuntimeError(f'RACE_INPUT_MISSING:{rid}')
        hnos=[int(r['horse_no']) for r in rs];pos_by_h={h:i for i,h in enumerate(hnos)};hf=hf_all.get(rid,{})
        single=odds[rid].get('単勝',{})
        if any(str(h) not in single for h in hnos):raise RuntimeError(f'WIN_ODDS_INCOMPLETE:{rid}:{len(single)}/{len(hnos)}')
        win=[single[str(h)] for h in hnos];raw=[1/x for x in win];s=sum(raw);w=[x/s for x in raw]
        pop_order=sorted(range(len(hnos)),key=lambda i:(win[i],i));pop=[0]*len(hnos)
        for rank,i in enumerate(pop_order,1):pop[i]=rank
        surface=race['surface'] or '障害';dm=int(race['distance_m'] or 0);venue=race['venue'];rn=int(race['race_no']);n=len(hnos)
        base={'venue':pmod.VENUE_MAP[venue],'surface':{'芝':0,'ダート':1,'障害':2}.get(surface,2),'dist':pmod.distbin(dm),'track':{'良':0,'稍重':1,'重':2,'不良':3}.get(race['track_condition'],-1),'weather':weatherbin(race['weather']) if race['weather'] in ('晴','曇','雨','小雨','雪','小雪') else -1,'field':pmod.fieldbin(n),'raceNo':pmod.rnobin(rn),'season':pmod.seasonbin(int(a.date[5:7])),'rclass':pmod.classbin(race['race_name'],race['conditions']),'direction':pmod.directionbin(venue,surface,dm,race['direction'])}
        tickets=[]
        for bt,jp,en,k,ordered in specs:
            omap=odds[rid].get(jp,{})
            if not omap:continue
            theory=pmod.combos(n,k,ordered)
            rows=[]
            for pp in theory:
                hs=[hnos[i] for i in pp];combo='-'.join(map(str,sorted(hs) if jp in UNORDERED else hs))
                odd=omap.get(combo)
                if odd is not None and odd>1:rows.append((pp,hs,combo,float(odd)))
            rows_sorted=sorted(enumerate(rows),key=lambda x:(x[1][3],x[0]));rank_by_index={orig:rank for rank,(orig,_) in enumerate(rows_sorted,1)}
            for idx,(pp,hs,combo,odd) in enumerate(rows):
                fs=[hf[h] for h in hs];pops=[pop[pos_by_h[h]] for h in hs];mp=market_prob(pp,en,w);assumed=PAYOUT_RATIO[en]/max(mp,1e-15);ratio=odd/assumed
                vals=dict(base);vals.update({'bet':bt,'odds':bsearch(ODDS_EDGES,odd),'mrank':market_rank_bin(rank_by_index[idx]),'minpop':minpop_bin(min(pops)),'maxpop':maxpop_bin(max(pops)),'popsum':popsum_bin(sum(pops)),'favcnt':min(3,sum(1 for p in pops if p<=1)),'distort':bsearch(DISTORT_EDGES,ratio),'goodcnt':min(3,sum(1 for x in fs if x[0]>=3)),'bestform':max(x[0] for x in fs),'bestspeed':max(x[1] for x in fs),'bestj':max(x[2] for x in fs),'bestt':max(x[3] for x in fs),'expcnt':min(3,sum(1 for x in fs if x[4]>=2)),'top3lastsum':min(7,sum(x[5] for x in fs))})
                f=rule_score(rb,bt,vals,False);p=rule_score(rb,bt,vals,True)
                if f>0 or p>0:tickets.append({'bet':bt,'betType':jp,'horses':hs,'combo':combo,'odds':odd,'oddsBin':vals['odds'],'full':f,'pre':p})
        chosen=select_tickets(tickets)
        courses=[]
        for course,budget in [('ライト',2000),('スタンダード',5000),('プレミアム',10000)]:
            units=allocate([t['oddsBin'] for t in chosen],budget//100)
            course_rows=[]
            for t,u in zip(chosen,units):course_rows.append({'course':course,'betType':t['betType'],'combination':t['combo'],'stakeYen':u*100,'assumedOdds':t['odds']})
            assert sum(x['stakeYen'] for x in course_rows)==budget and max(x['stakeYen'] for x in course_rows)<=budget*.35+1e-9
            courses.extend(course_rows)
        out.append({'raceId':rid,'venue':venue,'raceNo':rn,'raceName':race['race_name'],'startTimeJst':race['start_time_jst'],'tickets':[{'betType':t['betType'],'combination':t['combo'],'odds':t['odds'],'fullScore':t['full'],'predayScore':t['pre']} for t in chosen],'courseBets':courses})
    artifact={'date':a.date,'lockedRaceCount':len(out),'selectedRaceCount':len(sel['selected']),'sourceRuleCount':316,'resultDataUsedForTargetDay':False,'officialOddsOnly':True,'generatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'races':out}
    (repo/a.out).write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if a.insert:
        collector.d1_query('''CREATE TABLE IF NOT EXISTS rt_public_bets (id INTEGER PRIMARY KEY AUTOINCREMENT,race_id TEXT NOT NULL,course TEXT NOT NULL,bet_type TEXT NOT NULL,combination TEXT NOT NULL,stake_yen INTEGER NOT NULL,assumed_odds REAL,return_yen INTEGER,settlement_status TEXT NOT NULL,locked_at TEXT,source_prediction_id INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(race_id,course,bet_type,combination))''')
        locked=artifact['generatedAt']
        desired=[]
        for r in out:
            for b in r['courseBets']:
                desired.append((r['raceId'],b['course'],b['betType'],b['combination'],b['stakeYen'],round(b['assumedOdds'],6)))
        for rid,course,bt,combo,stake,odd in desired:
            collector.d1_query("INSERT OR IGNORE INTO rt_public_bets(race_id,course,bet_type,combination,stake_yen,assumed_odds,return_yen,settlement_status,locked_at,source_prediction_id) VALUES(?,?,?,?,?,?,NULL,'pending',?,-2)",[rid,course,bt,combo,stake,odd,locked])
        for r in out:
            saved=collector.d1_query("SELECT course,bet_type,combination,stake_yen,assumed_odds FROM rt_public_bets WHERE race_id=? ORDER BY course,bet_type,combination",[r['raceId']])
            exp={(b['course'],b['betType'],b['combination'],int(b['stakeYen']),round(float(b['assumedOdds']),6)) for b in r['courseBets']}
            got={(x['course'],x['bet_type'],x['combination'],int(x['stake_yen']),round(float(x['assumed_odds'] or 0),6)) for x in saved}
            if got!=exp: raise RuntimeError(f'PUBLIC_BET_LOCK_VERIFY_FAILED:{r["raceId"]}:{len(got)}:{len(exp)}')
    print(json.dumps({'races':len(out),'ticketCounts':[(r['raceId'],len(r['tickets'])) for r in out],'alreadyLocked':len(already),'inserted':bool(a.insert)},ensure_ascii=False))

if __name__=='__main__':main()
