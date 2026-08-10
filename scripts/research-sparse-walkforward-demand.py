#!/usr/bin/env python3
import argparse,collections,importlib.util,itertools,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EVAL_START='2016-08-10'; EVAL_END='2026-08-09'
BET_SPECS={0:(1,'win','単勝',False),1:(2,'umaren','馬連',False),2:(2,'wide','ワイド',False),3:(2,'umatan','馬単',True),4:(3,'trio','3連複',False),5:(3,'trifecta','3連単',True)}
SINGLES=('venue','surface','dist','field','raceNo','rclass','bestform','bestspeed','bestj','bestt','expcnt','top3lastsum')
PAIRS=(('surface','bestform'),('dist','bestform'),('rclass','bestform'),('field','expcnt'),('bestform','bestspeed'),('bestj','bestt'),('expcnt','top3lastsum'),('bestform','top3lastsum'))
TOP_HORSES=5
MIN_TICKETS=300; PRIOR_TICKETS=2000; PRIOR_ROI=0.80; MAX_RULES=8; MAX_PER_BET=3

def load(path,name):
    s=importlib.util.spec_from_file_location(name,path)
    if s is None or s.loader is None: raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def norm(s):
    return str(s or '').replace('500万下','1勝クラス').replace('1000万下','2勝クラス').replace('1600万下','3勝クラス')

def safe_int(v):
    try:return int(v)
    except:return None

def payout_index(bundle):
    out={}
    for r in bundle.get('payouts',[]):
        b=str(r.get('betType') or ''); c=str(r.get('combination') or '')
        try:y=int(r.get('payoutYen') or 0)
        except:y=0
        if b and c and y>0: out[(b,c)]=max(out.get((b,c),0),y)
    return out

def base_vals(pmod,race,n):
    v=str(race.get('venue') or ''); s=str(race.get('surface') or '障害'); d=int(race.get('distanceM') or 0); rn=int(race.get('raceNo') or 0)
    return {'venue':pmod.VENUE_MAP[v],'surface':{'芝':0,'ダート':1,'障害':2}.get(s,2),'dist':pmod.distbin(d),'field':pmod.fieldbin(n),'raceNo':pmod.rnobin(rn),'rclass':pmod.classbin(norm(race.get('raceName')),norm(race.get('conditions')))}

def combo_vals(base,bt,fs):
    v=dict(base);v.update({'bet':bt,'goodcnt':min(3,sum(1 for x in fs if x[0]>=3)),'bestform':max(x[0] for x in fs),'bestspeed':max(x[1] for x in fs),'bestj':max(x[2] for x in fs),'bestt':max(x[3] for x in fs),'expcnt':min(3,sum(1 for x in fs if x[4]>=2)),'top3lastsum':min(7,sum(x[5] for x in fs))});return v

def candidate_keys(bt,v):
    for a in SINGLES: yield (bt,(a,),(v[a],))
    for a,b in PAIRS: yield (bt,(a,b),(v[a],v[b]))

def key_conditions(key):
    bt,axes,vals=key
    return [['bet',bt]]+[[a,v] for a,v in zip(axes,vals)]

def strength(feature,hno):
    return (sum(feature[:5])+min(3,feature[5]),feature[0]+feature[1],feature[2]+feature[3],feature[5],-hno)

def ticket_rows(pmod,dmod,state,bundle):
    race=bundle['race']; rid=str(race['raceId'])
    runners=[r for r in bundle.get('runners',[]) if (r.get('runnerStatus') or 'active')=='active']; runners.sort(key=lambda r:int(r.get('horseNo') or 0))
    if len(runners)<3:return []
    feats={int(r['horseNo']):dmod.feature_tuple(pmod,state,rid,r) for r in runners}
    ranked=sorted((int(r['horseNo']) for r in runners),key=lambda h:strength(feats[h],h),reverse=True)[:TOP_HORSES]
    base=base_vals(pmod,race,len(runners)); payouts=payout_index(bundle); out=[]
    for bt,(k,market,jp,ordered) in BET_SPECS.items():
        if len(ranked)<k:continue
        seq=itertools.permutations(ranked,k) if ordered else itertools.combinations(ranked,k)
        for horses in seq:
            combo='-'.join(str(x) for x in (tuple(sorted(horses)) if not ordered else horses))
            fs=[feats[h] for h in horses]; vals=combo_vals(base,bt,fs)
            out.append({'bt':bt,'market':market,'jp':jp,'horses':horses,'combo':combo,'vals':vals,'return100':payouts.get((jp,combo),0)})
    return out

def quarter(date):
    y=int(date[:4]);m=int(date[5:7]);return f'{y}Q{(m-1)//3+1}'

def select_rules(stats,year_stats,cutoff):
    ranked=[]
    for key,(n,ret) in stats.items():
        if n<MIN_TICKETS:continue
        raw=ret/(100*n); shr=(ret+PRIOR_TICKETS*100*PRIOR_ROI)/(100*(n+PRIOR_TICKETS))
        yr=[]
        for y,(yn,yrt) in year_stats.get(key,{}).items():
            if yn>=100:yr.append(yrt/(100*yn))
        stable=sum(x>=0.90 for x in yr)/len(yr) if yr else 0.0
        worst=min(yr) if yr else 0.0
        if raw<0.95 or shr<0.90:continue
        complexity=1.0 if len(key[1])==1 else 0.94
        score=shr*(0.82+0.18*stable)*complexity
        ranked.append((score,shr,raw,stable,worst,n,key))
    if not ranked:
        for key,(n,ret) in stats.items():
            if n>=MIN_TICKETS:
                raw=ret/(100*n);shr=(ret+PRIOR_TICKETS*100*PRIOR_ROI)/(100*(n+PRIOR_TICKETS));ranked.append((shr,shr,raw,0.0,0.0,n,key))
    ranked.sort(reverse=True,key=lambda x:(x[0],x[1],x[5],-len(x[6][1])))
    chosen=[];per=collections.Counter()
    for row in ranked:
        bt=row[6][0]
        if per[bt]>=MAX_PER_BET:continue
        chosen.append(row);per[bt]+=1
        if len(chosen)>=MAX_RULES:break
    if len({r[6][0] for r in chosen})<2:
        seen={r[6][0] for r in chosen}
        extra=next((r for r in ranked if r[6][0] not in seen),None)
        if extra:
            if len(chosen)>=MAX_RULES:chosen[-1]=extra
            else:chosen.append(extra)
    rules=[]
    for i,(score,shr,raw,stable,worst,n,key) in enumerate(chosen):
        rules.append({'id':f'{cutoff}-{i+1}','conditions':key_conditions(key),'newScore':round(score,8),'trainingTickets':n,'trainingRoiPct':round(raw*100,3),'shrunkRoiPct':round(shr*100,3),'stableYearShare':round(stable,4),'worstQualifiedYearRoiPct':round(worst*100,3)})
    return rules

def group_rules(rules):
    d=collections.defaultdict(list)
    for r in rules:d[int(r['conditions'][0][1])].append(r)
    return d

def matches(rule,vals):
    return all(vals.get(a)==v for a,v in rule['conditions'])

def scored_race(pmod,dmod,state,bundle,rules):
    tickets=ticket_rows(pmod,dmod,state,bundle); rb=group_rules(rules); matched=[]
    for t in tickets:
        best=0.0
        for r in rb.get(t['bt'],[]):
            if matches(r,t['vals']):best=max(best,float(r['newScore']))
        if best>0:matched.append({**t,'score':best})
    matched.sort(key=lambda x:(-x['score'],x['bt'],x['combo']))
    if not matched:return {'score':0.0,'tickets':[],'types':set()}
    mx=matched[0]['score'];chosen=[t for t in matched if t['score']>=mx*0.85-1e-12][:10]
    if len(chosen)<3:
        for t in matched:
            if t not in chosen:chosen.append(t)
            if len(chosen)>=3:break
    types={t['bt'] for t in chosen}
    if len(types)<2:
        alt=next((t for t in matched if t['bt'] not in types),None)
        if alt:
            if len(chosen)<10:chosen.append(alt)
            else:chosen[-1]=alt
            types={t['bt'] for t in chosen}
    return {'score':matched[0]['score']+0.01*len(types)+0.001*min(10,len(chosen)),'tickets':chosen,'types':types}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--corpus',required=True);ap.add_argument('--out',required=True);ap.add_argument('--rules-out',required=True);ap.add_argument('--meta',required=True);a=ap.parse_args()
    pmod=load(ROOT/'scripts/generate-final-preday-selection.py','sparse_bins');dmod=load(ROOT/'scripts/research-ten-year-canonical-demand.py','sparse_hist')
    state={'horse_hist':collections.defaultdict(lambda:collections.deque(maxlen=3)),'horse_starts':collections.Counter(),'jstats':collections.defaultdict(lambda:[0,0]),'tstats':collections.defaultdict(lambda:[0,0])}
    stats=collections.defaultdict(lambda:[0,0]);years=collections.defaultdict(lambda:collections.defaultdict(lambda:[0,0]))
    selected=[];fold_rules=[];proxy={'tickets':0,'returnYen':0};struct=[];backfills=[];current_fold=None;rules=[]
    current_date=None;day=[]
    def process(date,bundles):
        nonlocal current_fold,rules
        f=quarter(date)
        if f!=current_fold:
            rules=select_rules(stats,years,date);current_fold=f;fold_rules.append({'fold':f,'startDate':date,'trainingThroughExclusive':date,'ruleCount':len(rules),'predicateCount':sum(len(r['conditions']) for r in rules),'rules':rules})
        if EVAL_START<=date<=EVAL_END:
            by=collections.defaultdict(list)
            for b in bundles:
                race=b['race'];s=scored_race(pmod,dmod,state,b,rules);by[str(race.get('venue'))].append((b,s))
            for venue,rows in by.items():
                rows.sort(key=lambda x:(-x[1]['score'],-len(x[1]['types']),-len(x[1]['tickets']),int(x[0]['race'].get('raceNo') or 0)))
                take=min(5,len(rows))
                if take<5:struct.append({'date':date,'venue':venue,'eligible':len(rows)})
                for b,s in rows[:take]:
                    race=b['race'];valid=len(s['tickets'])>=3 and len(s['types'])>=2
                    if not valid:backfills.append(str(race['raceId']))
                    req={'win'}|{BET_SPECS[t['bt']][1] for t in s['tickets']}
                    selected.append({'raceId':str(race['raceId']),'raceDate':date,'venue':venue,'raceNo':race.get('raceNo'),'resultUrl':race.get('resultUrl') or (b.get('provenance') or {}).get('resultUrl'),'fold':f,'raceScore':s['score'],'proxyTicketCount':len(s['tickets']),'proxyBetTypes':sorted(s['types']),'requiredMarkets':[m for m in ('win','umaren','wide','umatan','trio','trifecta') if m in req],'targetDayResultsUsedForSelection':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False})
                    for t in s['tickets']:
                        proxy['tickets']+=1;proxy['returnYen']+=t['return100']
        for b in bundles:
            for t in ticket_rows(pmod,dmod,state,b):
                y=date[:4]
                for k in candidate_keys(t['bt'],t['vals']):
                    stats[k][0]+=1;stats[k][1]+=t['return100'];years[k][y][0]+=1;years[k][y][1]+=t['return100']
        dmod.update_state_for_date(state,bundles)
    with (ROOT/a.corpus).open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():continue
            b=json.loads(line);d=str(b.get('race',{}).get('raceDate') or '')
            if current_date is None:current_date=d
            if d!=current_date:process(current_date,day);day=[];current_date=d
            day.append(b)
    if current_date:process(current_date,day)
    selected.sort(key=lambda x:(x['raceDate'],x['venue'],int(x['raceNo'] or 0)))
    out=ROOT/a.out;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in selected),encoding='utf-8')
    (ROOT/a.rules_out).write_text(json.dumps(fold_rules,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    meta={'purpose':'research_only_sparse_walk_forward_demand','evaluationStart':EVAL_START,'evaluationEnd':EVAL_END,'selectedRaces':len(selected),'folds':len(fold_rules),'maxRulesPerFold':MAX_RULES,'maxPredicatesPerRule':3,'topHorseCandidatePool':TOP_HORSES,'proxyTickets':proxy['tickets'],'proxyTicketRoiPct':round(100*proxy['returnYen']/(100*proxy['tickets']),4) if proxy['tickets'] else None,'constraintBackfillCount':len(backfills),'constraintBackfillRaceIds':backfills,'structuralCancellationExceptions':struct,'targetDayResultsUsedForSelection':False,'historicalFinalOddsUsedForDiscovery':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    (ROOT/a.meta).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(meta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
