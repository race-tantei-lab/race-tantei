#!/usr/bin/env python3
import argparse,collections,json,math
from pathlib import Path

COURSES={'light':2000,'standard':5000,'premium':10000}
VARIANTS=('confidence','concentration','disagreement','hybrid')
TEMPLATES=('pair','spread','trio','ordered')
BET_JP={'win':'単勝','umaren':'馬連','wide':'ワイド','umatan':'馬単','trio':'3連複','trifecta':'3連単'}
MARKETS={'win','umaren','wide','umatan','trio','trifecta'}
ODDS_EDGES=[2,3,5,7,10,15,20,30,50,75,100,150,300,500,800,1200,2000]
ODDS_MID=[1.4,2.45,3.9,5.9,8.4,12.2,17.3,24.5,38.7,61.2,86.6,122.5,212.1,387.3,632.5,979.8,1549.2,2500.0]

def odds_value(v):
    if isinstance(v,list):
        x=[float(q) for q in v if q is not None];return sum(x)/len(x) if x else None
    return float(v) if v is not None else None

def norm_combo(bt,hs):
    hs=tuple(hs)
    if bt in ('umaren','wide','trio'):hs=tuple(sorted(hs))
    return '-'.join(map(str,hs))

def bsearch(edges,x):
    i=0
    while i<len(edges) and x>=edges[i]:i+=1
    return i

def allocate(odds_list,budget):
    U=budget//100;n=len(odds_list);cap=max(1,int(math.floor(U*.35+1e-12)))
    if n!=3 or n*cap<U:raise RuntimeError(f'ALLOCATION_SHAPE_INVALID:{n}:{U}:{cap}')
    bins=[bsearch(ODDS_EDGES,o) for o in odds_list];units=[1]*n;rem=U-n
    weights=[min(1.0,(100.0/ODDS_MID[b])**1.5) for b in bins];tw=sum(weights);targets=[U*w/tw for w in weights]
    while rem>0:
        elig=[i for i in range(n) if units[i]<cap]
        if not elig:raise RuntimeError('ALLOCATION_FAILED')
        elig.sort(key=lambda i:(-(targets[i]-units[i]),-weights[i],ODDS_MID[bins[i]],i));units[elig[0]]+=1;rem-=1
    if sum(units)!=U or max(units)>cap:raise RuntimeError('ALLOCATION_GATE_FAILED')
    return units

def template_tickets(name,top3):
    h1,h2,h3=top3
    if name=='pair':return [('win',(h1,)),('wide',(h1,h2)),('umaren',(h1,h2))]
    if name=='spread':return [('win',(h1,)),('wide',(h1,h2)),('wide',(h1,h3))]
    if name=='trio':return [('win',(h1,)),('wide',(h1,h2)),('trio',(h1,h2,h3))]
    if name=='ordered':return [('win',(h1,)),('umatan',(h1,h2)),('trifecta',(h1,h2,h3))]
    raise KeyError(name)

def payout_index(bundle):
    out={}
    for p in bundle.get('payouts',[]):
        bt=str(p.get('betType') or '');combo=str(p.get('combination') or '');pay=p.get('payoutYen')
        if bt and combo and pay is not None:out[(bt,combo)]=int(pay)
    return out

def robust(rows):
    stake=sum(r['stakeYen'] for r in rows);ret=sum(r['returnYen'] for r in rows)
    by_return=sorted(rows,key=lambda r:(-r['returnYen'],r['raceId']))
    by_profit=sorted(rows,key=lambda r:(-(r['returnYen']-r['stakeYen']),r['raceId']))
    def cut(order,n):
        n=min(n,len(order));rm=order[:n];s=stake-sum(r['stakeYen'] for r in rm);v=ret-sum(r['returnYen'] for r in rm)
        return round(100*v/s,4) if s else None
    n1=max(1,math.ceil(len(rows)*.01))
    ret50=cut(by_return,50);profit50=cut(by_profit,50)
    return {
      'races':len(rows),'stakeYen':stake,'returnYen':ret,
      'roiPct':round(100*ret/stake,4) if stake else None,
      'top50ExcludedRoiPct':ret50,
      'top50ReturnExcludedRoiPct':ret50,
      'top50ProfitExcludedRoiPct':profit50,
      'top50RobustRoiPct':min(ret50,profit50) if ret50 is not None and profit50 is not None else None,
      'top100ExcludedRoiPct':cut(by_return,100),
      'top1PctExcludedRaceCount':n1,
      'top1PctExcludedRoiPct':cut(by_return,n1),
      'top50ReturnSharePct':round(100*sum(r['returnYen'] for r in by_return[:50])/ret,4) if ret else 0.0,
      'hardGateTop50AtLeast200':bool(ret50 is not None and profit50 is not None and ret50>=200.0 and profit50>=200.0),
    }

def market_has_official_value(official,market):
    values=official.get(market)
    return isinstance(values,dict) and any(value is not None for value in values.values())

def complete_six_market(row):
    req=set(row.get('requiredMarkets') or [])
    official=row.get('officialOdds') or {}
    return (
        MARKETS.issubset(req)
        and MARKETS.issubset(set(official))
        and all(market_has_official_value(official,market) for market in MARKETS)
    )

def read_odds_dir(root,union,odds,existing=False):
    files=list(Path(root).glob('*.jsonl'))
    if existing:
        # Canonical 297 is a fallback; later current/meta files may replace it, but only if the row
        # satisfies the exact same complete-six-market policy used by the demand builder.
        files.sort(key=lambda p:(0 if p.name.startswith('research-demanded-odds-') else 1,p.name))
    else:
        files.sort()
    for p in files:
        for line in p.read_text(encoding='utf-8').splitlines():
            if not line.strip():continue
            r=json.loads(line);rid=str(r['raceId'])
            if rid not in union:continue
            if existing and not complete_six_market(r):continue
            odds[rid]=r

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--predictions-dir',required=True);ap.add_argument('--selections-dir',required=True);ap.add_argument('--existing-odds-dir',required=True);ap.add_argument('--new-odds-dir',required=True);ap.add_argument('--history',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    pred=collections.defaultdict(list)
    for p in sorted(Path(a.predictions_dir).glob('all-race-ranker-20*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():r=json.loads(line);pred[str(r['raceId'])].append(r)
    sels={};union=set()
    for v in VARIANTS:
        rows=[]
        for line in (Path(a.selections_dir)/f'ml-five-selection-{v}.jsonl').read_text(encoding='utf-8').splitlines():
            if line.strip():
                r=json.loads(line)
                if int(str(r['raceDate'])[:4])<=2022:rows.append(r);union.add(str(r['raceId']))
        if len(rows)!=9190:raise RuntimeError(f'SELECTION_COUNT_INVALID:{v}:{len(rows)}')
        sels[v]=rows
    odds={}
    read_odds_dir(a.existing_odds_dir,union,odds,existing=True)
    read_odds_dir(a.new_odds_dir,union,odds,existing=False)
    missing=sorted(union-set(odds))
    if missing:raise RuntimeError(f'ODDS_MISSING:{len(missing)}:{missing[:5]}')
    hist={}
    with Path(a.history).open(encoding='utf-8') as fh:
        for line in fh:
            if line.strip():
                b=json.loads(line);rid=str(b['race']['raceId'])
                if rid in union:hist[rid]=b
    if len(hist)!=len(union):raise RuntimeError(f'HISTORY_MISSING:{len(union)-len(hist)}')
    top3={};inactive_filtered=0
    for rid in union:
        win=odds[rid].get('officialOdds',{}).get('win',{})
        active={int(h) for h,v in win.items() if odds_value(v) is not None}
        all_rows=pred.get(rid,[]);rows=[r for r in all_rows if int(r['horseNo']) in active]
        inactive_filtered+=max(0,len(all_rows)-len(rows))
        ordered=sorted(rows,key=lambda r:(-float(r['abilityScore']),int(r['horseNo'])))
        if len(ordered)<3:raise RuntimeError(f'ACTIVE_PREDICTION_MISSING:{rid}:{len(ordered)}:{len(active)}')
        top3[rid]=tuple(int(r['horseNo']) for r in ordered[:3])
    results={};errors=[]
    for v in VARIANTS:
        selected_ids=[str(r['raceId']) for r in sels[v]]
        for tname in TEMPLATES:
            key=f'{v}__{tname}';results[key]={c:[] for c in COURSES}
            for rid in selected_ids:
                official=odds[rid]['officialOdds'];tickets=[]
                for bt,hs in template_tickets(tname,top3[rid]):
                    combo=norm_combo(bt,hs);ov=odds_value(official.get(bt,{}).get(combo))
                    if ov is None or ov<=1.0:
                        errors.append({'raceId':rid,'selector':v,'template':tname,'bet':bt,'combo':combo,'reason':'OFFICIAL_ODDS_MISSING'});tickets=[];break
                    tickets.append((bt,combo,ov))
                if len(tickets)!=3:continue
                if len({x[0] for x in tickets})<2:raise RuntimeError(f'BET_TYPE_GATE:{key}:{rid}')
                pays=payout_index(hist[rid]);date=str(odds[rid]['raceDate'])
                for course,budget in COURSES.items():
                    units=allocate([x[2] for x in tickets],budget);ret=sum(u*pays.get((BET_JP[bt],combo),0) for (bt,combo,_),u in zip(tickets,units))
                    results[key][course].append({'raceId':rid,'raceDate':date,'stakeYen':budget,'returnYen':ret})
    if errors:raise RuntimeError(f'EVALUATION_ERRORS:{len(errors)}:{errors[:10]}')
    combos={}
    for key,byc in results.items():
        selector,template=key.split('__');x={'selector':selector,'template':template,'courses':{},'byPeriod':{}}
        for c,rows in byc.items():
            if len(rows)!=9190:raise RuntimeError(f'RACE_COUNT_INVALID:{key}:{c}:{len(rows)}')
            x['courses'][c]=robust(rows)
        for name,(lo,hi) in {'2016-2018':('2016','2018'),'2019-2022':('2019','2022')}.items():
            x['byPeriod'][name]={c:robust([r for r in byc[c] if lo<=r['raceDate'][:4]<=hi]) for c in COURSES}
        x['minTop50ReturnExcludedRoiPct']=min(x['courses'][c]['top50ReturnExcludedRoiPct'] for c in COURSES)
        x['minTop50ProfitExcludedRoiPct']=min(x['courses'][c]['top50ProfitExcludedRoiPct'] for c in COURSES)
        x['minTop50RobustRoiPct']=min(x['courses'][c]['top50RobustRoiPct'] for c in COURSES)
        x['minTop100ExcludedRoiPct']=min(x['courses'][c]['top100ExcludedRoiPct'] for c in COURSES)
        x['minOverallRoiPct']=min(x['courses'][c]['roiPct'] for c in COURSES)
        x['passesDiscoveryGate']=all(x['courses'][c]['hardGateTop50AtLeast200'] for c in COURSES)
        x['selectorUsesHistoricalFinalPopularity']=selector in ('disagreement','hybrid')
        combos[key]=x
    best_key=max(combos,key=lambda k:(combos[k]['minTop50RobustRoiPct'],combos[k]['minTop100ExcludedRoiPct'],combos[k]['minOverallRoiPct'],k))
    best=combos[best_key];passed=bool(best['passesDiscoveryGate'])
    frozen={'key':best_key,'selector':best['selector'],'template':best['template'],'minTop50RobustRoiPct':best['minTop50RobustRoiPct'],'minTop100ExcludedRoiPct':best['minTop100ExcludedRoiPct'],'minOverallRoiPct':best['minOverallRoiPct'],'selectorUsesHistoricalFinalPopularity':best['selectorUsesHistoricalFinalPopularity']} if passed else None
    summary={'purpose':'research_only_2016_2022_discovery_for_result_blind_ml_five_race_selection','discoveryPeriod':{'start':'2016-08-10','end':'2022-12-31'},'holdoutPeriodUntouched':{'start':'2023-01-01','end':'2026-08-09'},'selectionVariants':list(VARIANTS),'ticketTemplates':list(TEMPLATES),'candidateCombinations':len(combos),'selectedRacesPerCombination':9190,'completionHardGate':{'allCoursesTop50ReturnAndProfitExcludedRoiPctAtLeast':200.0},'historicalFinalOddsUsed':True,'prestartOddsTimingValidationPerformed':False,'targetRaceResultUsedForRaceSelection':False,'targetRaceResultUsedForHorseRanking':False,'inactiveHorsesFilteredBeforeRanking':True,'inactivePredictionRowsFiltered':inactive_filtered,'existingOddsPrecedence':'new_fetch_over_complete_current_or_meta_over_complete_canonical297','existingOddsReuseRequiresAllSixMarkets':True,'existingOddsReuseRequiresAtLeastOneOfficialValuePerMarket':True,'discoveryResultsUsedOnlyToChooseOneFrozenCombinationForHistoricalHoldout':True,'productionDatabaseWritten':False,'productionModelChanged':False,'combinations':combos,'discoveryBestCandidate':{'key':best_key,'selector':best['selector'],'template':best['template'],'minTop50RobustRoiPct':best['minTop50RobustRoiPct'],'minTop100ExcludedRoiPct':best['minTop100ExcludedRoiPct'],'minOverallRoiPct':best['minOverallRoiPct'],'passesDiscoveryGate':best['passesDiscoveryGate'],'selectorUsesHistoricalFinalPopularity':best['selectorUsesHistoricalFinalPopularity']},'discoveryPassed':passed,'frozenCombination':frozen}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'discoveryPassed':passed,'best':summary['discoveryBestCandidate'],'frozenCombination':frozen,'inactivePredictionRowsFiltered':inactive_filtered},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
