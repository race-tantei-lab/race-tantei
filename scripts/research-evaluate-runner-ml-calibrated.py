#!/usr/bin/env python3
import argparse,collections,importlib.util,itertools,json,math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE_PATH=ROOT/'scripts'/'research-evaluate-runner-ml-market.py'
spec=importlib.util.spec_from_file_location('mlmarketbase',BASE_PATH)
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

TEMPS=[0.5,0.75,1.0,1.25,1.5,2.0,3.0]
ALPHAS=[0.0,0.25,0.5,0.75,1.0]
DEFAULT_T=1.0;DEFAULT_A=0.25
COURSES=base.COURSES


def softmax_scores(rows,temp,active):
    vals={int(r['horseNo']):float(r['abilityScore'])/temp for r in rows if int(r['horseNo']) in active}
    if len(vals)<3:return None
    mx=max(vals.values());e={h:math.exp(max(-50.0,min(50.0,v-mx))) for h,v in vals.items()};s=sum(e.values())
    return {h:v/s for h,v in e.items()}


def market_prob(win):
    q={h:1.0/max(1.01,float(o)) for h,o in win.items() if o is not None and o>1.0}
    s=sum(q.values());return {h:v/s for h,v in q.items()} if s>0 else None


def blend(q,p,a):
    hs=set(q)&set(p);x={h:(1-a)*q[h]+a*p[h] for h in hs};s=sum(x.values());return {h:v/s for h,v in x.items()} if s>0 else None


def winner(rows):
    w=[int(r['horseNo']) for r in rows if int(r.get('finishPosition') or 0)==1]
    return w[0] if len(w)==1 else None


def nll_for(race_ids,preds,odds,temp,alpha):
    loss=0.0;n=0
    for rid in race_ids:
        pr=preds[rid];wr=winner(pr)
        if wr is None:continue
        o=odds[rid]['officialOdds'].get('win',{});win={int(h):base.odds_value(v) for h,v in o.items() if base.odds_value(v) is not None}
        q=market_prob(win);p=softmax_scores(pr,temp,set(win))
        if not q or not p or wr not in q or wr not in p:continue
        b=blend(q,p,alpha);loss-=math.log(max(1e-12,b[wr]));n+=1
    return loss/n if n else float('inf'),n


def choose_params(prior_ids,preds,odds):
    if len(prior_ids)<1000:return {'temperature':DEFAULT_T,'alpha':DEFAULT_A,'priorRaces':len(prior_ids),'selection':'default_insufficient_prior_oos'}
    best=None
    for t in TEMPS:
        for a in ALPHAS:
            ll,n=nll_for(prior_ids,preds,odds,t,a)
            cand=(ll,t,a,n)
            if best is None or cand<best:best=cand
    return {'temperature':best[1],'alpha':best[2],'priorRaces':best[3],'priorLogLoss':round(best[0],8),'selection':'min_prior_oos_logloss'}


def candidate_horses(w):
    return [h for h,_ in sorted(w.items(),key=lambda kv:(-kv[1],kv[0]))[:8]]


def build_tickets(w,official):
    pool=candidate_horses(w);tickets=[]
    for bt,(jp,k,ordered) in base.BET_SPECS.items():
        market=official.get(bt,{})
        if len(pool)<k:continue
        seq=itertools.permutations(pool,k) if ordered else itertools.combinations(pool,k)
        for hs in seq:
            combo=base.norm_combo(bt,hs);ov=base.odds_value(market.get(combo))
            if ov is None or ov<=1.0:continue
            p=base.ticket_prob(bt,hs,w);ev=p*ov
            tickets.append({'bt':bt,'betType':jp,'combo':combo,'horses':list(hs),'odds':ov,'prob':p,'ev':ev})
    tickets.sort(key=lambda t:(-t['ev'],-t['prob'],t['odds'],t['bt'],t['combo']))
    if len(tickets)<3:return None
    chosen=[tickets[0]];types={tickets[0]['bt']}
    second=next((t for t in tickets[1:] if t['bt'] not in types),None)
    if second is None:return None
    chosen.append(second);used={(t['bt'],t['combo']) for t in chosen}
    third=next((t for t in tickets if (t['bt'],t['combo']) not in used),None)
    if third is None:return None
    chosen.append(third);chosen.sort(key=lambda t:(-t['ev'],-t['prob'],t['bt'],t['combo']))
    if len({t['bt'] for t in chosen})<2:raise RuntimeError('SECOND_BET_TYPE_GATE_FAILED')
    return chosen


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--predictions-dir',required=True);ap.add_argument('--odds-dir',required=True);ap.add_argument('--history',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    preds=collections.defaultdict(list)
    for p in sorted(Path(a.predictions_dir).glob('runner-ranker-20*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r=json.loads(line);preds[str(r['raceId'])].append(r)
    if len(preds)!=14410:raise RuntimeError(f'PREDICTION_RACE_COUNT_INVALID:{len(preds)}')
    odds={}
    for p in sorted(Path(a.odds_dir).glob('research-continuous-market-odds-20*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r=json.loads(line);rid=str(r['raceId'])
                if rid in preds:odds[rid]=r
    if len(odds)!=14410:raise RuntimeError(f'ODDS_RACE_COUNT_INVALID:{len(odds)}')
    hist={}
    with Path(a.history).open(encoding='utf-8') as fh:
        for line in fh:
            if line.strip():
                b=json.loads(line);rid=str(b['race']['raceId'])
                if rid in preds:hist[rid]=b
    if len(hist)!=14410:raise RuntimeError(f'HISTORY_RACE_COUNT_INVALID:{len(hist)}')

    ids=sorted(preds,key=lambda rid:(odds[rid]['raceDate'],odds[rid]['venue'],int(odds[rid]['raceNo'])))
    ids_by_year=collections.defaultdict(list)
    for rid in ids:ids_by_year[odds[rid]['raceDate'][:4]].append(rid)
    params={};prior=[]
    for y in sorted(ids_by_year):
        params[y]=choose_params(prior,preds,odds);prior.extend(ids_by_year[y])

    rows_by_course=collections.defaultdict(list);errors=[];prob_diag={}
    for y in sorted(ids_by_year):
        t=params[y]['temperature'];alpha=params[y]['alpha'];market_ll,_=nll_for(ids_by_year[y],preds,odds,1.0,0.0);blend_ll,_=nll_for(ids_by_year[y],preds,odds,t,alpha);ability_ll,_=nll_for(ids_by_year[y],preds,odds,t,1.0)
        prob_diag[y]={'marketLogLoss':round(market_ll,8),'abilityLogLoss':round(ability_ll,8),'blendedLogLoss':round(blend_ll,8),'temperature':t,'alpha':alpha}
        for rid in ids_by_year[y]:
            pr=preds[rid];o=odds[rid];win={int(h):base.odds_value(v) for h,v in o['officialOdds'].get('win',{}).items() if base.odds_value(v) is not None}
            q=market_prob(win);p=softmax_scores(pr,t,set(win));w=blend(q,p,alpha) if q and p else None
            if not w:
                errors.append({'raceId':rid,'reason':'CALIBRATED_PROB_FAILED'});continue
            chosen=build_tickets(w,o['officialOdds'])
            if not chosen:
                errors.append({'raceId':rid,'reason':'TICKET_SELECTION_FAILED'});continue
            pays=base.payout_index(hist[rid])
            for course,budget in COURSES.items():
                units=base.allocate([x['odds'] for x in chosen],budget);ret=sum(u*pays.get((x['betType'],x['combo']),0) for x,u in zip(chosen,units))
                rows_by_course[course].append({'raceId':rid,'raceDate':o['raceDate'],'stakeYen':budget,'returnYen':ret})
    if errors:raise RuntimeError(f'EVALUATION_ERRORS:{len(errors)}:{errors[:5]}')
    courses={course:base.robust(rows_by_course[course],budget) for course,budget in COURSES.items()}
    by_year={y:{course:base.robust([r for r in rows_by_course[course] if r['raceDate'].startswith(y)],budget) for course,budget in COURSES.items()} for y in sorted(ids_by_year)}
    periods={'2016-2018':('2016','2018'),'2019-2021':('2019','2021'),'2022-2024':('2022','2024'),'2025-2026':('2025','2026')}
    by_period={name:{course:base.robust([r for r in rows_by_course[course] if lo<=r['raceDate'][:4]<=hi],budget) for course,budget in COURSES.items()} for name,(lo,hi) in periods.items()}
    out={'purpose':'research_only_nested_probability_calibrated_runner_ml','selectedRaces':14410,'calibrationSelectionMetric':'prior_oos_winner_logloss_only','yearParameters':params,'probabilityDiagnosticsByYear':prob_diag,'courses':courses,'byYear':by_year,'byPeriod':by_period,'passesCompletionHardGate':all(courses[c]['top50ExcludedRoiPct']>=200 for c in COURSES),'completionHardGate':{'allCoursesTop50ExcludedRoiPctAtLeast':200.0},'historicalFinalOddsUsed':True,'prestartTimingValidationPerformed':False,'targetRaceResultUsedForPrediction':False,'targetYearRoiUsedForCalibration':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'params':params,'probDiag':prob_diag,'courses':{c:{'roi':x['roiPct'],'top50':x['top50ExcludedRoiPct'],'top100':x['top100ExcludedRoiPct'],'top1pct':x['top1PctExcludedRoiPct']} for c,x in courses.items()},'pass':out['passesCompletionHardGate']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
