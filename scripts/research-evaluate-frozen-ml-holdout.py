#!/usr/bin/env python3
import argparse,collections,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('disc',ROOT/'scripts'/'research-evaluate-ml-five-discovery.py')
disc=importlib.util.module_from_spec(spec);spec.loader.exec_module(disc)
COURSES=disc.COURSES
BET_JP=disc.BET_JP

def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as fh:
        for line in fh:
            if line.strip():yield json.loads(line)

def file_priority(p):return (0 if p.name.startswith('research-demanded-odds-') else 1,p.name)
def load_odds(existing_dir,new_dir,ids):
    out={}
    for p in sorted(Path(existing_dir).glob('*.jsonl'),key=file_priority):
        for r in read_jsonl(p):
            rid=str(r['raceId'])
            if rid in ids:out[rid]=r
    for p in sorted(Path(new_dir).glob('*.jsonl')):
        for r in read_jsonl(p):
            rid=str(r['raceId'])
            if rid in ids:out[rid]=r
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--frozen',required=True);ap.add_argument('--predictions-dir',required=True);ap.add_argument('--selections-dir',required=True);ap.add_argument('--existing-odds-dir',required=True);ap.add_argument('--new-odds-dir',required=True);ap.add_argument('--history',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    frozen=json.loads(Path(a.frozen).read_text());w=frozen['practicalDiscoveryWinner']
    if not frozen.get('historicalHoldoutMayBeOpened') or not w.get('eligibleForHistoricalHoldout'):raise RuntimeError('HOLDOUT_OPENING_GATE_FALSE')
    selector=w['selector'];template=w['template']
    if selector not in ('confidence','concentration'):raise RuntimeError(f'HOLDOUT_SELECTOR_TIMING_INVALID:{selector}')
    selected=[]
    for r in read_jsonl(Path(a.selections_dir)/f'ml-five-selection-{selector}.jsonl'):
        y=int(str(r['raceDate'])[:4])
        if 2023<=y<=2026:selected.append(r)
    if len(selected)!=5220:raise RuntimeError(f'HOLDOUT_SELECTION_COUNT_INVALID:{len(selected)}')
    ids={str(r['raceId']) for r in selected}
    preds=collections.defaultdict(list)
    for p in sorted(Path(a.predictions_dir).glob('all-race-ranker-20*.jsonl')):
        for r in read_jsonl(p):
            rid=str(r['raceId'])
            if rid in ids:preds[rid].append(r)
    if len(preds)!=5220:raise RuntimeError(f'HOLDOUT_PREDICTION_RACES_INVALID:{len(preds)}')
    odds=load_odds(a.existing_odds_dir,a.new_odds_dir,ids)
    if len(odds)!=5220:raise RuntimeError(f'HOLDOUT_ODDS_RACES_INVALID:{len(odds)}:{len(ids-set(odds))}')
    hist={}
    for b in read_jsonl(a.history):
        rid=str(b['race']['raceId'])
        if rid in ids:hist[rid]=b
    if len(hist)!=5220:raise RuntimeError(f'HOLDOUT_HISTORY_RACES_INVALID:{len(hist)}')
    rows={c:[] for c in COURSES};errors=[];inactive_filtered=0
    for s in sorted(selected,key=lambda r:(str(r['raceDate']),str(r.get('venueCode') or ''),int(r['raceNo']))):
        rid=str(s['raceId']);official=odds[rid]['officialOdds'];win=official.get('win',{})
        active={int(h) for h,v in win.items() if disc.odds_value(v) is not None}
        allp=preds[rid];pr=[r for r in allp if int(r['horseNo']) in active];inactive_filtered+=max(0,len(allp)-len(pr))
        ranked=sorted(pr,key=lambda r:(-float(r['abilityScore']),int(r['horseNo'])))
        if len(ranked)<3:errors.append({'raceId':rid,'reason':'ACTIVE_TOP3_MISSING'});continue
        top3=tuple(int(r['horseNo']) for r in ranked[:3]);tickets=[]
        for bt,hs in disc.template_tickets(template,top3):
            combo=disc.norm_combo(bt,hs);ov=disc.odds_value(official.get(bt,{}).get(combo))
            if ov is None or ov<=1.0:errors.append({'raceId':rid,'reason':'OFFICIAL_ODDS_MISSING','bet':bt,'combo':combo});tickets=[];break
            tickets.append((bt,combo,ov))
        if len(tickets)!=3:continue
        if len({x[0] for x in tickets})<2:raise RuntimeError(f'HOLDOUT_BET_TYPE_GATE:{rid}')
        pays=disc.payout_index(hist[rid]);date=str(odds[rid]['raceDate'])
        for course,budget in COURSES.items():
            units=disc.allocate([x[2] for x in tickets],budget);ret=sum(u*pays.get((BET_JP[bt],combo),0) for (bt,combo,_),u in zip(tickets,units));rows[course].append({'raceId':rid,'raceDate':date,'stakeYen':budget,'returnYen':ret})
    if errors:raise RuntimeError(f'HOLDOUT_EVALUATION_ERRORS:{len(errors)}:{errors[:10]}')
    courses={c:disc.robust(rows[c]) for c in COURSES}
    by_year={y:{c:disc.robust([r for r in rows[c] if r['raceDate'].startswith(y)]) for c in COURSES} for y in ('2023','2024','2025','2026')}
    by_period={n:{c:disc.robust([r for r in rows[c] if lo<=r['raceDate'][:4]<=hi]) for c in COURSES} for n,(lo,hi) in {'2023-2024':('2023','2024'),'2025-2026':('2025','2026')}.items()}
    out={'purpose':'research_only_frozen_practical_ml_historical_holdout','discoveryPeriod':{'start':'2016-08-10','end':'2022-12-31'},'holdoutPeriod':{'start':'2023-01-01','end':'2026-08-09'},'selector':selector,'template':template,'selectedRaces':5220,'candidateFrozenBeforeHoldout':True,'holdoutResultsUsedToChooseCandidate':False,'historicalFinalOddsUsed':True,'prestartOddsTimingValidationPerformed':False,'inactiveHorsesFilteredBeforeRanking':True,'inactivePredictionRowsFiltered':inactive_filtered,'courses':courses,'byYear':by_year,'byPeriod':by_period,'passesHoldoutTop50Gate':all(courses[c]['top50RobustRoiPct']>=200 for c in COURSES),'holdoutTop50DiagnosticThresholdPct':200.0,'fullTenYearCompletionNotEvaluatedHere':True,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'selector':selector,'template':template,'courses':{c:{'roi':v['roiPct'],'top50':v['top50RobustRoiPct'],'top100':v['top100ExcludedRoiPct'],'top1pct':v['top1PctExcludedRoiPct']} for c,v in courses.items()},'passesHoldoutTop50Gate':out['passesHoldoutTop50Gate']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
