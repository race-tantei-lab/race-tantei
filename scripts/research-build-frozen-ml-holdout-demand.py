#!/usr/bin/env python3
import argparse,json
from pathlib import Path

TEMPLATE_MARKETS={
 'pair':['win','wide','umaren'],
 'spread':['win','wide'],
 'trio':['win','wide','trio'],
 'ordered':['win','umatan','trifecta'],
}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--frozen',required=True);ap.add_argument('--selections-dir',required=True);ap.add_argument('--existing-odds-dir',required=True);ap.add_argument('--history',required=True);ap.add_argument('--out',required=True);ap.add_argument('--meta',required=True);a=ap.parse_args()
    frozen=json.loads(Path(a.frozen).read_text(encoding='utf-8'));w=frozen['practicalDiscoveryWinner']
    if not w['eligibleForHistoricalHoldout']:raise RuntimeError('PRACTICAL_WINNER_NOT_HOLDOUT_ELIGIBLE')
    selector=w['selector'];template=w['template'];required=TEMPLATE_MARKETS[template]
    sel_path=Path(a.selections_dir)/f'ml-five-selection-{selector}.jsonl'
    selected=[]
    for line in sel_path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            r=json.loads(line);y=int(str(r['raceDate'])[:4])
            if 2023<=y<=2026:selected.append(r)
    if len(selected)!=5220:raise RuntimeError(f'HOLDOUT_SELECTION_COUNT_INVALID:{len(selected)}')
    selected_ids={str(r['raceId']) for r in selected}
    existing={}
    for p in sorted(Path(a.existing_odds_dir).glob('*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r=json.loads(line);rid=str(r['raceId'])
                if rid in selected_ids:existing[rid]=r
    race_meta={}
    with Path(a.history).open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():continue
            b=json.loads(line);r=b['race'];rid=str(r['raceId'])
            if rid in selected_ids:
                race_meta[rid]={'raceId':rid,'raceDate':str(r['raceDate']),'venue':r['venue'],'raceNo':int(r['raceNo']),'resultUrl':r['resultUrl']}
    if len(race_meta)!=len(selected_ids):raise RuntimeError(f'HOLDOUT_RACE_META_MISSING:{len(selected_ids)-len(race_meta)}')
    reuse=0;demand=[]
    for rid in sorted(selected_ids,key=lambda x:(race_meta[x]['raceDate'],race_meta[x]['venue'],race_meta[x]['raceNo'])):
        ex=existing.get(rid);available=set((ex or {}).get('officialOdds',{}))
        if set(required).issubset(available):reuse+=1;continue
        row=dict(race_meta[rid]);row['requiredMarkets']=required;demand.append(row)
    Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in demand),encoding='utf-8')
    meta={'purpose':'frozen_practical_ml_historical_holdout_odds_demand','selector':selector,'template':template,'requiredMarkets':required,'holdoutStart':'2023-01-01','holdoutEnd':'2026-08-09','selectedRaces':len(selected_ids),'reusedExistingOfficialOddsRaces':reuse,'newOfficialOddsDemandRaces':len(demand),'discoveryWinnerFrozenBeforeHoldout':True,'holdoutRaceResultsUsedToChooseCandidate':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    Path(a.meta).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(meta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
