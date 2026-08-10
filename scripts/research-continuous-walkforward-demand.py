#!/usr/bin/env python3
import argparse,collections,importlib.util,itertools,json,os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EVAL_START='2016-08-10'; EVAL_END='2026-08-09'
MIN_N=int(os.environ.get('CONT_MIN_N','100'))
KEY_PRIOR=int(os.environ.get('CONT_KEY_PRIOR','1000'))
BET_PRIOR=int(os.environ.get('CONT_BET_PRIOR','5000'))
PRIOR_ROI=float(os.environ.get('CONT_PRIOR_ROI','0.80'))
TOP_COMPONENTS=int(os.environ.get('CONT_TOP_COMPONENTS','4'))
TICKETS_PER_RACE=int(os.environ.get('CONT_TICKETS_PER_RACE','3'))


def load(path,name):
    s=importlib.util.spec_from_file_location(name,path)
    if s is None or s.loader is None: raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

smod=load(ROOT/'scripts/research-sparse-walkforward-demand.py','continuous_sparse_utils')
pmod=load(ROOT/'scripts/generate-final-preday-selection.py','continuous_bins')
dmod=load(ROOT/'scripts/research-ten-year-canonical-demand.py','continuous_history')


def candidate_rows(state,bundle):
    race=bundle['race']; rid=str(race['raceId'])
    runners=[r for r in bundle.get('runners',[]) if (r.get('runnerStatus') or 'active')=='active']
    runners.sort(key=lambda r:int(r.get('horseNo') or 0))
    if len(runners)<3:return []
    feats={int(r['horseNo']):dmod.feature_tuple(pmod,state,rid,r) for r in runners}
    ranked=sorted(feats,key=lambda h:smod.strength(feats[h],h),reverse=True)[:smod.TOP_HORSES]
    base=smod.base_vals(pmod,race,len(runners));out=[]
    for bt,(k,market,jp,ordered) in smod.BET_SPECS.items():
        if len(ranked)<k:continue
        seq=itertools.permutations(ranked,k) if ordered else itertools.combinations(ranked,k)
        for horses in seq:
            combo='-'.join(str(x) for x in (tuple(sorted(horses)) if not ordered else horses))
            vals=smod.combo_vals(base,bt,[feats[h] for h in horses])
            out.append({'bt':bt,'market':market,'betType':jp,'horses':list(horses),'combo':combo,'vals':vals})
    return out


def mean_roi(n,ret,prior_n,prior_roi):
    return (ret + prior_n*100.0*prior_roi)/(100.0*(n+prior_n))


def ticket_score(ticket,stats,bet_stats):
    bt=ticket['bt'];bn,bret=bet_stats[bt]
    bmean=mean_roi(bn,bret,BET_PRIOR,PRIOR_ROI)
    comps=[]
    for key in smod.candidate_keys(bt,ticket['vals']):
        n,ret=stats.get(key,(0,0))
        if n<MIN_N:continue
        km=mean_roi(n,ret,KEY_PRIOR,bmean)
        reliability=n/(n+KEY_PRIOR)
        complexity=1.0 if len(key[1])==1 else 0.92
        comps.append((km,reliability*complexity,n,key))
    if not comps:
        return bmean*0.95
    comps.sort(key=lambda x:(x[0],x[1],x[2]),reverse=True)
    top=comps[:TOP_COMPONENTS]
    w=sum(x[1] for x in top)
    local=sum(x[0]*x[1] for x in top)/w if w else bmean
    return 0.25*bmean+0.75*local


def select_tickets(rows,stats,bet_stats):
    scored=[]
    for t in rows:
        s=ticket_score(t,stats,bet_stats)
        scored.append({**t,'score':s})
    scored.sort(key=lambda x:(-x['score'],x['bt'],x['combo']))
    if len(scored)<TICKETS_PER_RACE:raise RuntimeError('TOO_FEW_CANDIDATE_TICKETS')
    chosen=scored[:TICKETS_PER_RACE]
    types={t['bt'] for t in chosen}
    if len(types)<2:
        alt=next((t for t in scored[TICKETS_PER_RACE:] if t['bt'] not in types),None)
        if alt is None:raise RuntimeError('NO_SECOND_BET_TYPE')
        chosen[-1]=alt
    chosen.sort(key=lambda x:(-x['score'],x['bt'],x['combo']))
    if not(3<=len(chosen)<=10) or len({t['bt'] for t in chosen})<2:raise RuntimeError('TICKET_GATE_FAILED')
    return chosen


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--corpus',required=True);ap.add_argument('--out',required=True);ap.add_argument('--meta',required=True);a=ap.parse_args()
    state={'horse_hist':collections.defaultdict(lambda:collections.deque(maxlen=3)),'horse_starts':collections.Counter(),'jstats':collections.defaultdict(lambda:[0,0]),'tstats':collections.defaultdict(lambda:[0,0])}
    stats=collections.defaultdict(lambda:[0,0]);bet_stats=collections.defaultdict(lambda:[0,0])
    selected=[];struct=[];proxy={'tickets':0,'returnYen':0};by_year=collections.defaultdict(lambda:[0,0])
    current_date=None;day=[]

    def process(date,bundles):
        if EVAL_START<=date<=EVAL_END:
            by=collections.defaultdict(list)
            for b in bundles:
                race=b['race'];rows=candidate_rows(state,b);chosen=select_tickets(rows,stats,bet_stats)
                race_score=sum(t['score'] for t in chosen)/len(chosen)
                by[str(race.get('venue'))].append((b,chosen,race_score))
            for venue,rows in by.items():
                rows.sort(key=lambda x:(-x[2],int(x[0]['race'].get('raceNo') or 0)))
                if len(rows)<5:
                    struct.append({'date':date,'venue':venue,'eligible':len(rows)})
                    continue
                for b,chosen,race_score in rows[:5]:
                    race=b['race'];pays=smod.payout_index(b);ret=0
                    frozen=[]
                    for t in chosen:
                        pay=pays.get((t['betType'],t['combo']),0);ret+=pay
                        frozen.append({'bet':t['bt'],'betType':t['betType'],'market':t['market'],'horses':t['horses'],'combo':t['combo'],'score':round(t['score'],8)})
                    proxy['tickets']+=len(chosen);proxy['returnYen']+=ret
                    by_year[date[:4]][0]+=len(chosen);by_year[date[:4]][1]+=ret
                    req={'win'}|{t['market'] for t in chosen}
                    selected.append({'raceId':str(race['raceId']),'raceDate':date,'venue':venue,'raceNo':race.get('raceNo'),'resultUrl':race.get('resultUrl') or (b.get('provenance') or {}).get('resultUrl'),'raceScore':round(race_score,8),'tickets':frozen,'requiredMarkets':[m for m in ('win','umaren','wide','umatan','trio','trifecta') if m in req],'targetDayResultsUsedForSelection':False,'historicalFinalOddsUsedForSelection':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False})
        # Only after the whole target date is frozen do its outcomes enter the model.
        for b in bundles:
            pays=smod.payout_index(b)
            for t in candidate_rows(state,b):
                ret=pays.get((t['betType'],t['combo']),0)
                bet_stats[t['bt']][0]+=1;bet_stats[t['bt']][1]+=ret
                for key in smod.candidate_keys(t['bt'],t['vals']):
                    stats[key][0]+=1;stats[key][1]+=ret
        dmod.update_state_for_date(state,bundles)

    with (ROOT/a.corpus).open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():continue
            b=json.loads(line);d=str(b['race'].get('raceDate') or '')
            if current_date is None:current_date=d
            if d!=current_date:
                process(current_date,day);day=[];current_date=d
            day.append(b)
    if current_date:process(current_date,day)

    selected.sort(key=lambda x:(x['raceDate'],x['venue'],int(x['raceNo'] or 0)))
    out=ROOT/a.out;out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in selected),encoding='utf-8')
    yearly={y:round(100*v[1]/(100*v[0]),4) if v[0] else None for y,v in sorted(by_year.items())}
    meta={'purpose':'research_only_continuous_walk_forward_demand','evaluationStart':EVAL_START,'evaluationEnd':EVAL_END,'selectedRaces':len(selected),'ticketsPerRace':TICKETS_PER_RACE,'minHistoricalCellN':MIN_N,'keyPriorTickets':KEY_PRIOR,'betPriorTickets':BET_PRIOR,'priorRoi':PRIOR_ROI,'topComponents':TOP_COMPONENTS,'proxyTickets':proxy['tickets'],'proxyTicketRoiPct':round(100*proxy['returnYen']/(100*proxy['tickets']),4) if proxy['tickets'] else None,'proxyRoiByYearPct':yearly,'structuralCancellationExceptions':struct,'constraintBackfillCount':0,'targetDayResultsUsedForSelection':False,'historicalFinalOddsUsedForDiscovery':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    (ROOT/a.meta).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(meta,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
