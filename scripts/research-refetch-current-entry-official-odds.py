#!/usr/bin/env python3
import argparse, importlib.util, json, sys, urllib.parse
from collections import deque
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CURRENT=ROOT/'scripts'/'collect-current-jra-official-odds.py'
spec=importlib.util.spec_from_file_location('research_current_entry_odds',CURRENT)
if spec is None or spec.loader is None: raise RuntimeError('CURRENT_COLLECTOR_IMPORT_FAILED')
current=importlib.util.module_from_spec(spec);sys.modules[spec.name]=current;spec.loader.exec_module(current)
current.self_test()
runtime=current.runtime;base=runtime.base
JP_TO_EN={'単勝':'win','馬連':'umaren','ワイド':'wide','馬単':'umatan','3連複':'trio','3連単':'trifecta'}
MARKETS=('win','umaren','wide','umatan','trio','trifecta')


def odds_value(low,high):
    lo=float(low);hi=float(high)
    return lo if abs(lo-hi)<1e-12 else [lo,hi]


def same_target_hint(cname,target):
    decoded=urllib.parse.unquote(str(cname or ''))
    date_digits=str(target['raceDate']).replace('-','')
    if date_digits not in decoded: return False
    return current.current_race_no_from_cname(decoded)==int(target['raceNo'])


def fetch_one(target):
    wanted=(str(target['raceDate']),str(target['venue']),int(target['raceNo']))
    entry=str(target.get('entryUrl') or '')
    if not entry: raise RuntimeError(f'ENTRY_URL_MISSING:{target["raceId"]}')
    entry_html=runtime.fetch_url(entry)
    queue=deque()
    for cname,_ in base.action_links(entry_html):
        if same_target_hint(cname,target): queue.append(cname)
    if not queue: raise RuntimeError(f'ENTRY_ODDS_LINKS_MISSING:{target["raceId"]}')
    seen=set(); parsed={}; source={}; pages=0
    while queue and pages<80 and len(parsed)<6:
        cname=queue.popleft()
        if cname in seen: continue
        seen.add(cname)
        try:
            page=runtime.fetch_url(base.JRA_ODDS_URL,cname=cname,referer=entry)
            pages+=1
        except Exception:
            continue
        identity=runtime.parse_page_identity(page,cname)
        if identity!=wanted: continue
        bet_type=base.detect_bet_type(page,'')
        if bet_type in JP_TO_EN:
            market=JP_TO_EN[bet_type]
            rows=runtime.parse_odds_rows(page,bet_type)
            if rows:
                parsed[market]=rows;source[market]=cname
        for child,_ in base.action_links(page):
            if child not in seen and same_target_hint(child,target): queue.append(child)
    missing=[m for m in MARKETS if m not in parsed]
    if missing: raise RuntimeError(f'CURRENT_MARKETS_MISSING:{target["raceId"]}:{missing}:pages={pages}')
    win_rows=parsed['win']
    horses=sorted({int(combo) for combo,_,_ in win_rows if str(combo).isdigit()})
    if len(horses)<2: raise RuntimeError(f'CURRENT_WIN_HORSES_INVALID:{target["raceId"]}:{horses}')
    official={}; coverage={}
    for market in MARKETS:
        values={str(combo):odds_value(low,high) for combo,low,high in parsed[market]}
        official[market]=values
        coverage[market]={'present':len(values)}
    # Independently re-fetch each accepted source page and re-check identity before finalizing.
    for market,cname in source.items():
        page=runtime.fetch_url(base.JRA_ODDS_URL,cname=cname,referer=entry)
        identity=runtime.parse_page_identity(page,cname)
        if identity!=wanted: raise RuntimeError(f'SOURCE_IDENTITY_CHANGED:{target["raceId"]}:{market}:{identity}:{wanted}')
    return {
        'raceId':str(target['raceId']),'raceDate':wanted[0],'venue':wanted[1],'raceNo':wanted[2],
        'requiredMarkets':list(MARKETS),'horses':horses,'officialOdds':official,'officialOddsCoverage':coverage,
        'provenance':{
            'entryUrl':entry,'resultUrl':None,'officialOddsSource':'jra_current_official_final_odds_entry_route_identity_verified',
            'sourceCnames':source,'officialPageIdentityVerified':True,'syntheticOddsUsed':False,'estimatedOddsUsed':False,
            'productionDatabaseWritten':False,'productionModelChanged':False,
        },
    }


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--targets',required=True);ap.add_argument('--out',required=True);ap.add_argument('--meta',required=True);a=ap.parse_args()
    targets=[json.loads(x) for x in Path(a.targets).read_text(encoding='utf-8').splitlines() if x.strip()]
    rows=[];fail=[]
    for t in targets:
        try:
            row=fetch_one(t);rows.append(row);print(json.dumps({'raceId':t['raceId'],'status':'ok','horses':len(row['horses'])},ensure_ascii=False),flush=True)
        except Exception as e:
            fail.append({'raceId':t.get('raceId'),'error':f'{type(e).__name__}:{e}'});print(json.dumps(fail[-1],ensure_ascii=False),flush=True)
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    Path(a.out).write_text(''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in rows),encoding='utf-8')
    meta={'targetCount':len(targets),'completedRaces':len(rows),'failures':fail,'syntheticOddsUsed':False,'estimatedOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    Path(a.meta).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if fail or len(rows)!=len(targets): raise RuntimeError(f'TARGET_REFETCH_INCOMPLETE:{meta}')

if __name__=='__main__': main()
