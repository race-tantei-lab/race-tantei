#!/usr/bin/env python3
import argparse,collections,json
from pathlib import Path

MARKETS=['win','umaren','wide','umatan','trio','trifecta']
VARIANTS=('confidence','concentration','disagreement','hybrid')

def read_ids(path,max_year):
    rows=[]
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip():continue
        r=json.loads(line)
        if int(str(r['raceDate'])[:4])<=max_year:rows.append(r)
    return rows

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--selections-dir',required=True);ap.add_argument('--existing-odds-dir',required=True);ap.add_argument('--history',required=True);ap.add_argument('--max-year',type=int,default=2022);ap.add_argument('--out',required=True);ap.add_argument('--meta',required=True);a=ap.parse_args()
    sels={}
    for v in VARIANTS:
        p=Path(a.selections_dir)/f'ml-five-selection-{v}.jsonl';rows=read_ids(p,a.max_year);sels[v]=rows
    existing=set()
    for p in sorted(Path(a.existing_odds_dir).glob('research-continuous-market-odds-20*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():existing.add(str(json.loads(line)['raceId']))
    union={str(r['raceId']) for rows in sels.values() for r in rows};missing=union-existing
    race_meta={}
    with Path(a.history).open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():continue
            b=json.loads(line);r=b['race'];rid=str(r['raceId'])
            if rid in missing:
                race_meta[rid]={'raceId':rid,'raceDate':str(r['raceDate']),'venue':str(r['venue']),'raceNo':int(r['raceNo']),'resultUrl':str(r.get('resultUrl') or ''),'requiredMarkets':MARKETS,'targetDayResultsUsedForSelection':False,'historicalFinalOddsUsedForSelection':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False}
    unresolved=sorted(missing-set(race_meta))
    bad_url=[rid for rid,r in race_meta.items() if not r['resultUrl']]
    if unresolved or bad_url:raise RuntimeError(f'RACE_META_UNRESOLVED:{len(unresolved)}:{len(bad_url)}:{unresolved[:5]}:{bad_url[:5]}')
    rows=sorted(race_meta.values(),key=lambda r:(r['raceDate'],r['venue'],r['raceNo'],r['raceId']))
    Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in rows),encoding='utf-8')
    by_year=collections.Counter(r['raceDate'][:4] for r in rows)
    meta={'purpose':'research_only_discovery_period_missing_official_odds_demand','discoveryMaxYear':a.max_year,'existingOfficialOddsRaces':len(existing),'unionSelectedRaces':len(union),'reusedRaces':len(union&existing),'missingRaces':len(rows),'missingByYear':dict(sorted(by_year.items())),'variants':{v:{'selectedRaces':len(sels[v]),'reusedRaces':sum(str(r['raceId']) in existing for r in sels[v]),'missingRaces':sum(str(r['raceId']) not in existing for r in sels[v])} for v in VARIANTS},'requiredMarkets':MARKETS,'targetRaceResultUsedForDemand':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    Path(a.meta).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(meta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
