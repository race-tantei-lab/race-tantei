#!/usr/bin/env python3
import argparse,collections,importlib.util,json,math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EVAL_START='2016-08-10';EVAL_END='2016-12-31'
MARKET_WEIGHTS=(0.0,0.5,1.0,1.5)
LOCAL_WEIGHT=0.60
RACE_PRIOR_TICKETS=1200.0
RACE_PRIOR_ROI=0.80
RACE_MIN_TICKETS=60.0


def load(path,name):
    s=importlib.util.spec_from_file_location(name,path)
    if s is None or s.loader is None:raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

core=load(ROOT/'scripts/research-continuous-walkforward-demand.py','market_select_core')
smod=core.smod;dmod=core.dmod


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
    scored=[]
    for t in rows:scored.append({**t,'score':ticket_score(t,stats,bet_stats)})
    scored.sort(key=lambda x:(-x['score'],x['bt'],x['combo']))
    chosen=scored[:3]
    if len(chosen)<3:raise RuntimeError('FEWER_THAN_3_TICKETS')
    types={t['bt'] for t in chosen}
    if len(types)<2:
        alt=next((t for t in scored[3:] if t['bt'] not in types),None)
        if alt is None:raise RuntimeError('NO_SECOND_BET_TYPE')
        chosen[-1]=alt
    chosen.sort(key=lambda x:(-x['score'],x['bt'],x['combo']))
    return chosen


def bin_index(x,edges):
    i=0
    while i<len(edges) and x>=edges[i]:i+=1
    return i


def market_features(odds_row):
    vals=[]
    for _,v in (odds_row.get('officialOdds',{}).get('win') or {}).items():
        try:o=float(v)
        except:continue
        if o>=1.0:vals.append(o)
    if len(vals)<3:raise RuntimeError(f'WIN_MARKET_TOO_SMALL:{len(vals)}')
    vals.sort();inv=[1/x for x in vals];over=sum(inv);q=[x/over for x in inv];entropy=-sum(p*math.log(max(p,1e-15)) for p in q)/math.log(len(q));fav=vals[0];gap=vals[1]/vals[0]
    return {'favBin':bin_index(fav,[1.5,2.0,2.5,3.0,4.0,5.0,7.0]),'entropyBin':bin_index(entropy,[0.70,0.80,0.88,0.93,0.96]),'overroundBin':bin_index(over,[1.05,1.10,1.15,1.20,1.30]),'gapBin':bin_index(gap,[1.10,1.25,1.50,2.0,3.0]),'favOdds':fav,'entropy':entropy,'overround':over,'gap':gap}


def race_keys(f):
    for n in ('favBin','entropyBin','overroundBin','gapBin'):yield ((n,), (f[n],))
    yield (('favBin','entropyBin'),(f['favBin'],f['entropyBin']))
    yield (('favBin','gapBin'),(f['favBin'],f['gapBin']))
    yield (('entropyBin','gapBin'),(f['entropyBin'],f['gapBin']))


def predicted_market_roi(f,stats):
    comps=[]
    for key in race_keys(f):
        n,ret=stats.get(key,(0.0,0.0))
        if n<RACE_MIN_TICKETS:continue
        mean=(ret+RACE_PRIOR_TICKETS*100*RACE_PRIOR_ROI)/(100*(n+RACE_PRIOR_TICKETS));rel=n/(n+RACE_PRIOR_TICKETS);complexity=1.0 if len(key[0])==1 else 0.94;comps.append((mean,rel*complexity,n))
    if not comps:return RACE_PRIOR_ROI
    comps.sort(key=lambda x:(x[0],x[1],x[2]),reverse=True);top=comps[:4];w=sum(x[1] for x in top);local=sum(x[0]*x[1] for x in top)/w if w else RACE_PRIOR_ROI
    return 0.35*RACE_PRIOR_ROI+0.65*local


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--corpus',required=True);ap.add_argument('--win-odds',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    win={}
    for line in (ROOT/a.win_odds).read_text().splitlines():
        if line.strip():
            r=json.loads(line);win[str(r['raceId'])]=r
    state={'horse_hist':collections.defaultdict(lambda:collections.deque(maxlen=3)),'horse_starts':collections.Counter(),'jstats':collections.defaultdict(lambda:[0,0]),'tstats':collections.defaultdict(lambda:[0,0])};stats=collections.defaultdict(lambda:[0,0]);bet_stats=collections.defaultdict(lambda:[0,0]);race_stats=collections.defaultdict(lambda:[0.0,0.0]);cur=None;day=[]
    totals={w:{'races':0,'tickets':0,'returnYen':0,'selected':[]} for w in MARKET_WEIGHTS};struct={w:[] for w in MARKET_WEIGHTS};market_errors=[];all_eval_seen=0

    def process(date,bundles):
        nonlocal all_eval_seen
        generated={};race_rows=[]
        for b in bundles:
            rid=str(b['race']['raceId']);rows=core.candidate_rows(state,b);chosen=choose_tickets(rows,stats,bet_stats);generated[rid]=(rows,chosen)
            if EVAL_START<=date<=EVAL_END:
                all_eval_seen+=1
                if rid not in win:
                    market_errors.append({'raceId':rid,'raceDate':date,'error':'WIN_ODDS_MISSING'});continue
                try:f=market_features(win[rid])
                except Exception as e:market_errors.append({'raceId':rid,'raceDate':date,'error':f'{type(e).__name__}:{e}'});continue
                pre=sum(t['score'] for t in chosen)/len(chosen);mr=predicted_market_roi(f,race_stats);race_rows.append((b,chosen,pre,mr,f))
        if EVAL_START<=date<=EVAL_END:
            by=collections.defaultdict(list)
            for row in race_rows:by[str(row[0]['race'].get('venue'))].append(row)
            for wgt in MARKET_WEIGHTS:
                for venue,rows in by.items():
                    scored=[]
                    for row in rows:
                        pre,mr=row[2],row[3];score=pre*((max(0.05,mr)/RACE_PRIOR_ROI)**wgt);scored.append((score,row))
                    scored.sort(key=lambda x:(-x[0],int(x[1][0]['race'].get('raceNo') or 0)))
                    if len(scored)<5:
                        struct[wgt].append({'date':date,'venue':venue,'eligible':len(scored)});continue
                    for score,row in scored[:5]:
                        b,chosen=row[0],row[1];pays=smod.payout_index(b);ret=sum(int(pays.get((t['betType'],t['combo']),0) or 0) for t in chosen);totals[wgt]['races']+=1;totals[wgt]['tickets']+=len(chosen);totals[wgt]['returnYen']+=ret;totals[wgt]['selected'].append(str(b['race']['raceId']))
        # Learn race-market regime from every race only after the full date is frozen.
        if EVAL_START<=date<=EVAL_END:
            for b,chosen,_,_,f in race_rows:
                pays=smod.payout_index(b);ret=sum(int(pays.get((t['betType'],t['combo']),0) or 0) for t in chosen);n=len(chosen)
                for key in race_keys(f):race_stats[key][0]+=n;race_stats[key][1]+=ret
        # Learn ticket model after date freeze.
        for b in bundles:
            rid=str(b['race']['raceId']);pays=smod.payout_index(b)
            for t in generated[rid][0]:
                ret=int(pays.get((t['betType'],t['combo']),0) or 0);bet_stats[t['bt']][0]+=1;bet_stats[t['bt']][1]+=ret
                for key in smod.candidate_keys(t['bt'],t['vals']):stats[key][0]+=1;stats[key][1]+=ret
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
        roi=100*t['returnYen']/(100*t['tickets']) if t['tickets'] else None;variants[str(wgt)]={'marketWeight':wgt,'selectedRaces':t['races'],'tickets':t['tickets'],'returnYen':t['returnYen'],'proxyTicketRoiPct':round(roi,4) if roi is not None else None,'structuralExceptions':struct[wgt]}
    ranking=sorted(variants,key=lambda k:(variants[k]['proxyTicketRoiPct'] or 0),reverse=True)
    result={'purpose':'research_only_online_win_market_aware_race_selection_2016','evaluationStart':EVAL_START,'evaluationEnd':EVAL_END,'allEvaluationRacesSeen':all_eval_seen,'winOddsRows':len(win),'marketFeatureErrors':market_errors,'raceMarketStatsUpdatedOnlyAfterDateFreeze':True,'ticketStatsUpdatedOnlyAfterDateFreeze':True,'targetDayResultsUsedForSelection':False,'historicalFinalWinOddsUsedForSelection':True,'prestartTimingValidationPerformed':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'variants':variants,'ranking':ranking,'bestVariant':ranking[0]}
    out=ROOT/a.out;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'best':result['bestVariant'],'variants':{k:v['proxyTicketRoiPct'] for k,v in variants.items()},'marketErrors':len(market_errors)},ensure_ascii=False))

if __name__=='__main__':main()
