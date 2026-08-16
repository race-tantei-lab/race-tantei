#!/usr/bin/env python3
import html
import importlib.util
import json
import pathlib
import re
import sys
import urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
RACE_ID='2026-08-16-niigata-02'

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise RuntimeError(path)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

collector=load(ROOT/'scripts'/'collect-jra-official-odds.py','diag_collector')
runtime=load(ROOT/'scripts'/'collect-jra-official-odds-runtime.py','diag_runtime')
rows=collector.d1_query('SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,entry_url AS entryUrl,start_time_utc AS startTimeUtc FROM rt_races WHERE race_id=? LIMIT 1',[RACE_ID])
if not rows: raise RuntimeError('RACE_NOT_FOUND')
race=rows[0]
url=str(race['entryUrl'])
page=runtime.fetch_url(url)
print(json.dumps({'race':race,'htmlLength':len(page),'actionLinks':runtime.base.action_links(page)[:40]},ensure_ascii=False))
patterns=[r'accessO\.html',r'doAction\([^\)]{0,500}\)',r'href=["\'][^"\']*(?:odds|accessO|JRADB)[^"\']*["\']',r'オッズ']
for pat in patterns:
    print('PATTERN',pat)
    n=0
    for m in re.finditer(pat,page,re.I):
        s=max(0,m.start()-500);e=min(len(page),m.end()+700)
        print(page[s:e].replace('\n',' ')[:1800])
        n+=1
        if n>=12: break
    print('COUNT_SHOWN',n)
# dump forms/buttons/data attributes near odds-related text
for m in re.finditer('オッズ',page):
    s=max(0,m.start()-1500);e=min(len(page),m.end()+1500)
    frag=page[s:e]
    print('ODDS_CONTEXT',frag.replace('\n',' ')[:3500])
    break
