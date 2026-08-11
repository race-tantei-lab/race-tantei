#!/usr/bin/env python3
import argparse,collections,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EVAL_START='2016-08-10';EVAL_END='2026-08-09'
RACE_WEIGHTS=(0.0,0.25,0.50,0.75,1.0,1.25)
LOCAL_WEIGHT=0.60
RACE_MIN_N=50
RACE_PRIOR_N=500
RACE_PRIOR_ROI=0.80
TOP_RACE_COMPONENTS=8


def load(path,name):
    s=importlib.util.spec_from_file_location(name,path)
    if s is None or s.loader is None:raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

core=load(ROOT/'scripts/research-continuous-walkforward-demand.py','race_level_core');smod=core.smod;dmod=core.dmod


def ticket_score(ticket,stats,bet_stats):
    bt=ticket['bt'];bn,bret=bet_stats[bt];bmean=core.mean_roi(bn,bret,core.BET_PRIOR,core.PRIOR_ROI);comps=[]
    for key in smod.candidate_keys(bt,ticket['vals']):
        n,ret=stats.get(key,(0,0))
        if n<core.MIN_N:continue
        km=core.mean_roi(n,ret,core.KEY_PRIOR,bmean);rel=n/(n+core.KEY_PRIOR);complexity=1.0 if len(key[1])==1 else 0.92;comps.append((km,rel*complexity,n))
    if not comps:return bmean*0.95
    comps.sort(key=lambda x:(x[0],x[1],x[2]),reverse=True);top=comps[:core.TOP_COMPONENTS];w=sum(x[1] for x in top);local=sum(x[0]*x[1] for x in top)/w if w else bmean
    return (1-LOCAL_WEIGHT)*bmean+LOCAL_WEIGHT*local


def choose_tickets(rows,stats,bet_stats):
    scored=[{**t,'score':ticket_score(t,stats,bet_stats)} for t in rows];scored.sort(key=lambda x:(-x['score'],x['bt'],x['combo']))
    if len(scored)<3:raise RuntimeError('FEWER_THAN_3_TICKETS')
    chosen=list(scored[:3]);types={t['bt'] for t in chosen}
    if len(types)<2:
        alt=next((t for t in scored[3:] if t['bt'] not in types),None)
        if alt is None:raise RuntimeError('NO_SECOND_BET_TYPE')
        chosen[-1]=alt
    chosen.sort(key=lambda x:(-x['score'],x['bt'],x['combo']));return chosen


def race_vals(bundle,rows,chosen):
    race=bundle['race'];base=smod.base_vals(core.pmod,race,len([r for r in bundle.get('runners',[]) if (r.get('runnerStatus') or 'active')=='active']))
    vals=dict(base);vals['typeCount']=len({t['bt'] for t in chosen});vals['topBet']=chosen[0]['bt'];vals['secondBet']=chosen[1]['bt'];return vals

SINGLES=('venue','surface','dist','field','raceNo','rclass','typeCount','topBet')
PAIRS=(('venue','surface'),('venue','dist'),('surface','dist'),('surface','rclass'),('field','rclass'),('raceNo','rclass'),('rclass','typeCount'),('surface','topBet'))

def race_keys(vals):
    for a in SINGLES:yield ((a,),(vals[a],))
    for a,b in PAIRS:yield ((a,b),(vals[a],vals[b]))


def predicted_race_roi(vals,stats):
    comps=[]
    for key in race_keys(vals):
        n,ret=stats.get(key,(0,0))
        if n<RACE_MIN_N:continue
        mean=(ret+RACE_PRIOR_N*300*RACE_PRIOR_ROI)/(300*(n+RACE_PRIOR_N));rel=n/(n+RACE_PRIOR_N);complexity=1.0 if len(key[0])==1 else 0.94;comps.append((mean,rel*complexity,n))
    if not comps:return RACE_PRIOR_ROI
    comps.sort(key=lambda x:(x[0],x[1],x[2]),reverse=True);top=comps[:TOP_RACE_COMPONENTS];w=sum(x[1] for x in top);local=sum(x[0]*x[1] for x in top)/w if w else RACE_PRIOR_ROI
    return 0.30*RACE_PRIOR_ROI+0.70*local


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--corpus',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    state={'horse_hist':collections.defaultdict(lambda:collections.deque(maxlen=3)),'horse_starts':collections.Counter(),'jstats':collections.defaultdict(lambda:[0,0]),'tstats':collections.defaultdict(lambda:[0,0])};ticket_stats=collections.defaultdict(lambda:[0,0]);bet_stats=collections.defaultdict(lambda:[0,0]);rstats=collections.defaultdict(lambda:[0,0]);cur=None;day=[]
    totals={w:{'races':0,'tickets':0,'returnYen':0,'byYear':collections.defaultdict(lambda:[0,0]),'struct':[]} for w in RACE_WEIGHTS}

    def process(date,bundles):
        rows=[];generated={}
        for b in bundles:
            rid=str(b['race']['raceId']);cand=core.candidate_rows(state,b);chosen=choose_tickets(cand,ticket_stats,bet_stats);vals=race_vals(b,cand,chosen);pre=sum(t['score'] for t in chosen)/3;rr=predicted_race_roi(vals,rstats);rows.append((b,cand,chosen,vals,pre,rr));generated[rid]=cand
        if EVAL_START<=date<=EVAL_END:
            by=collections.defaultdict(list)
            for row in rows:by[str(row[0]['race'].get('venue'))].append(row)
            for wgt in RACE_WEIGHTS:
                for venue,vr in by.items():
                    scored=[(row[4]*((max(0.05,row[5])/RACE_PRIOR_ROI)**wgt),row) for row in vr];scored.sort(key=lambda x:(-x[0],int(x[1][0]['race'].get('raceNo') or 0)))
                    if len(scored)<5:
                        totals[wgt]['struct'].append({'date':date,'venue':venue,'eligible':len(scored)});continue
                    for _,row in scored[:5]:
                        b,_,chosen=row[0],row[1],row[2];pays=smod.payout_index(b);ret=sum(int(pays.get((t['betType'],t['combo']),0) or 0) for t in chosen);totals[wgt]['races']+=1;totals[wgt]['tickets']+=3;totals[wgt]['returnYen']+=ret;totals[wgt]['byYear'][date[:4]][0]+=3;totals[wgt]['byYear'][date[:4]][1]+=ret
        # Update direct race ROI model only after whole date selection is frozen.
        for b,_,chosen,vals,_,_ in rows:
            pays=smod.payout_index(b);ret=sum(int(pays.get((t['betType'],t['combo']),0) or 0) for t in chosen)
            for key in race_keys(vals):rstats[key][0]+=1;rstats[key][1]+=ret
        # Update ticket model only after whole date selection is frozen.
        for b,cand,_,_,_,_ in rows:
            pays=smod.payout_index(b)
            for t in cand:
                ret=int(pays.get((t['betType'],t['combo']),0) or 0);bet_stats[t['bt']][0]+=1;bet_stats[t['bt']][1]+=ret
                for key in smod.candidate_keys(t['bt'],t['vals']):ticket_stats[key][0]+=1;ticket_stats[key][1]+=ret
        dmod.update_state_for_date(state,bundles)

    with (ROOT/a.corpus).open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():continue
            b=json.loads(line);date=str(b['race'].get('raceDate') or '')
            if cur is None:cur=date
            if date!=cur:process(cur,day);day=[];cur=date
            day.append(b)
    if cur:process(cur,day)
    variants={}
    for wgt,t in totals.items():
        roi=100*t['returnYen']/(100*t['tickets']) if t['tickets'] else None;by={y:round(100*v[1]/(100*v[0]),4) if v[0] else None for y,v in sorted(t['byYear'].items())};variants[str(wgt)]={'raceWeight':wgt,'selectedRaces':t['races'],'tickets':t['tickets'],'proxyTicketRoiPct':round(roi,4) if roi is not None else None,'proxyRoiByYearPct':by,'structuralCancellationExceptions':t['struct']}
    ranking=sorted(variants,key=lambda k:(variants[k]['proxyTicketRoiPct'] or 0),reverse=True);result={'purpose':'research_only_direct_race_level_roi_walk_forward_selection','evaluationStart':EVAL_START,'evaluationEnd':EVAL_END,'variants':variants,'ranking':ranking,'bestVariant':ranking[0],'raceStatsUpdatedOnlyAfterDateFreeze':True,'ticketStatsUpdatedOnlyAfterDateFreeze':True,'targetDayResultsUsedForSelection':False,'historicalOddsUsed':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    out=ROOT/a.out;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'best':result['bestVariant'],'roi':{k:v['proxyTicketRoiPct'] for k,v in variants.items()},'byYearBest':variants[result['bestVariant']]['proxyRoiByYearPct']},ensure_ascii=False))

if __name__=='__main__':main()
