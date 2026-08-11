#!/usr/bin/env python3
import argparse,collections,importlib.util,json,math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('tc',ROOT/'scripts'/'research-evaluate-runner-ticket-classifier.py')
tc=importlib.util.module_from_spec(spec);spec.loader.exec_module(tc)
base=tc.base
COURSES=base.COURSES
SELECTORS=('confidence','concentration')
DISCOVERY_MAX_YEAR=2022
MARKETS={'win','umaren','wide','umatan','trio','trifecta'}

def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as fh:
        for line in fh:
            if line.strip():yield json.loads(line)

def complete_six_market(row):
    required=set(row.get('requiredMarkets') or [])
    official=set((row.get('officialOdds') or {}).keys())
    return MARKETS.issubset(required) and MARKETS.issubset(official)

def read_odds(root,selected,odds,existing=False):
    files=list(Path(root).glob('*.jsonl'))
    if existing:
        files.sort(key=lambda p:(0 if p.name.startswith('research-demanded-odds-') else 1,p.name))
    else:files.sort()
    for p in files:
        for r in read_jsonl(p):
            rid=str(r['raceId'])
            if rid not in selected:continue
            if existing and not complete_six_market(r):continue
            odds[rid]=r

def active_rows(rows,official):
    active={int(h) for h,v in (official.get('win') or {}).items() if base.odds_value(v) is not None}
    return [r for r in rows if int(r['horseNo']) in active]

def robust(rows):
    stake=sum(r['stakeYen'] for r in rows);ret=sum(r['returnYen'] for r in rows)
    by_return=sorted(rows,key=lambda r:(-r['returnYen'],r['raceId']))
    by_profit=sorted(rows,key=lambda r:(-(r['returnYen']-r['stakeYen']),r['raceId']))
    def cut(order,n):
        rm=order[:min(n,len(order))];s=stake-sum(r['stakeYen'] for r in rm);v=ret-sum(r['returnYen'] for r in rm)
        return round(100*v/s,4) if s else None
    n1=max(1,math.ceil(len(rows)*.01));r50=cut(by_return,50);p50=cut(by_profit,50)
    return {'races':len(rows),'stakeYen':stake,'returnYen':ret,'roiPct':round(100*ret/stake,4) if stake else None,
            'top50ReturnExcludedRoiPct':r50,'top50ProfitExcludedRoiPct':p50,'top50RobustRoiPct':min(r50,p50),
            'top100ExcludedRoiPct':cut(by_return,100),'top1PctExcludedRaceCount':n1,'top1PctExcludedRoiPct':cut(by_return,n1),
            'top50ReturnSharePct':round(100*sum(r['returnYen'] for r in by_return[:50])/ret,4) if ret else 0.0,
            'hardGateTop50AtLeast200':r50>=200.0 and p50>=200.0}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--predictions-dir',required=True);ap.add_argument('--selections-dir',required=True)
    ap.add_argument('--existing-odds-dir',required=True);ap.add_argument('--new-odds-dir',required=True)
    ap.add_argument('--history',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()

    preds=collections.defaultdict(list)
    for p in sorted(Path(a.predictions_dir).glob('all-race-ranker-20*.jsonl')):
        for r in read_jsonl(p):preds[str(r['raceId'])].append(r)
    selections={};union=set()
    for selector in SELECTORS:
        rows=[]
        for r in read_jsonl(Path(a.selections_dir)/f'ml-five-selection-{selector}.jsonl'):
            if int(str(r['raceDate'])[:4])<=DISCOVERY_MAX_YEAR:
                rows.append(r);union.add(str(r['raceId']))
        if len(rows)!=9190:raise RuntimeError(f'SELECTION_COUNT_INVALID:{selector}:{len(rows)}')
        selections[selector]=rows

    odds={};read_odds(a.existing_odds_dir,union,odds,True);read_odds(a.new_odds_dir,union,odds,False)
    missing=sorted(union-set(odds))
    if missing:raise RuntimeError(f'ODDS_MISSING:{len(missing)}:{missing[:5]}')
    hist={}
    for b in read_jsonl(a.history):
        rid=str(b['race']['raceId'])
        if rid in union:hist[rid]=b
    if len(hist)!=len(union):raise RuntimeError(f'HISTORY_MISSING:{len(union)-len(hist)}')

    results={};global_errors=[]
    for selector in SELECTORS:
        ids=[str(r['raceId']) for r in selections[selector]]
        byyear=collections.defaultdict(list)
        for rid in ids:byyear[str(odds[rid]['raceDate'])[:4]].append(rid)
        prior=collections.defaultdict(list);race_rows=collections.defaultdict(list);diag={};filtered=0
        for year in sorted(byyear):
            models,counts=tc.train_models(prior);diag[year]={'models':sorted(models),'priorCounts':counts}
            frozen=[]
            for rid in sorted(byyear[year],key=lambda x:(odds[x]['raceDate'],odds[x]['venue'],int(odds[x]['raceNo']))):
                rows=active_rows(preds.get(rid,[]),odds[rid]['officialOdds']);filtered+=max(0,len(preds.get(rid,[]))-len(rows))
                cands=tc.candidates(rows,odds[rid]['officialOdds']);chosen=tc.select(cands,models)
                if not chosen:
                    global_errors.append({'selector':selector,'raceId':rid,'year':year,'reason':'TICKET_SELECTION_FAILED'});continue
                pays=base.payout_index(hist[rid]);frozen.append((rid,chosen,pays))
                for course,budget in COURSES.items():
                    units=base.allocate([r['odds'] for r in chosen],budget)
                    ret=sum(u*pays.get((r['betType'],r['combo']),0) for r,u in zip(chosen,units))
                    race_rows[course].append({'raceId':rid,'raceDate':str(odds[rid]['raceDate']),'stakeYen':budget,'returnYen':ret})
            # Freeze the entire target year first. Only then may its outcomes enter next-year training.
            for rid in byyear[year]:
                rows=active_rows(preds.get(rid,[]),odds[rid]['officialOdds']);pays=base.payout_index(hist[rid])
                for c in tc.candidates(rows,odds[rid]['officialOdds'],pays):prior[c['bt']].append(c)
        courses={c:robust(race_rows[c]) for c in COURSES}
        for c in COURSES:
            if courses[c]['races']!=9190:raise RuntimeError(f'RACE_COUNT_INVALID:{selector}:{c}:{courses[c]["races"]}')
        by_period={}
        for name,(lo,hi) in {'2016-2018':('2016','2018'),'2019-2022':('2019','2022')}.items():
            by_period[name]={c:robust([r for r in race_rows[c] if lo<=r['raceDate'][:4]<=hi]) for c in COURSES}
        results[selector]={'courses':courses,'byPeriod':by_period,'trainingDiagnosticsByYear':diag,
                           'inactivePredictionRowsFiltered':filtered,
                           'minTop50RobustRoiPct':min(courses[c]['top50RobustRoiPct'] for c in COURSES),
                           'minTop100ExcludedRoiPct':min(courses[c]['top100ExcludedRoiPct'] for c in COURSES),
                           'minOverallRoiPct':min(courses[c]['roiPct'] for c in COURSES),
                           'passesDiscoveryGate':all(courses[c]['hardGateTop50AtLeast200'] for c in COURSES)}
    if global_errors:raise RuntimeError(f'EVALUATION_ERRORS:{len(global_errors)}:{global_errors[:10]}')
    best_key=max(results,key=lambda k:(results[k]['minTop50RobustRoiPct'],results[k]['minTop100ExcludedRoiPct'],results[k]['minOverallRoiPct'],k))
    best=results[best_key];passed=bool(best['passesDiscoveryGate'])
    frozen={'selector':best_key,'model':'prior_year_ticket_classifier','minTop50RobustRoiPct':best['minTop50RobustRoiPct'],'minTop100ExcludedRoiPct':best['minTop100ExcludedRoiPct'],'minOverallRoiPct':best['minOverallRoiPct']} if passed else None
    out={'purpose':'strict_2016_2022_nested_walkforward_ticket_classifier_discovery','discoveryPeriod':{'start':'2016-08-10','end':'2022-12-31'},
         'holdoutPeriodUntouched':{'start':'2023-01-01','end':'2026-08-09'},'selectors':list(SELECTORS),'selectedRacesPerSelector':9190,
         'trainingBoundary':'prior_years_only','targetYearResultsUsedForTicketModel':False,'targetYearRoiUsedForTuning':False,
         'inactiveHorsesFilteredBeforeCandidateGeneration':True,'existingOddsReuseRequiresAllSixMarkets':True,'historicalFinalOddsUsed':True,'prestartTimingValidationPerformed':False,
         'completionHardGate':{'allCoursesTop50ReturnAndProfitExcludedRoiPctAtLeast':200.0},'productionDatabaseWritten':False,'productionModelChanged':False,
         'selectorsEvaluation':results,'discoveryBestCandidate':{'selector':best_key,'minTop50RobustRoiPct':best['minTop50RobustRoiPct'],'minTop100ExcludedRoiPct':best['minTop100ExcludedRoiPct'],'minOverallRoiPct':best['minOverallRoiPct'],'passesDiscoveryGate':best['passesDiscoveryGate']},
         'discoveryPassed':passed,'frozenClassifier':frozen}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'best':out['discoveryBestCandidate'],'passed':passed,'frozenClassifier':frozen},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
