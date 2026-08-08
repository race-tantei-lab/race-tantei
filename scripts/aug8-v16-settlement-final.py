import importlib.util, itertools, json, re, sys
from collections import defaultdict
from pathlib import Path
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec); sys.modules[name]=mod; spec.loader.exec_module(mod); return mod

src=load('aug8_src',ROOT/'scripts'/'aug8-v16-readonly-settlement.py')
base,selector,prob=src.base,src.selector,src.prob
OUT=ROOT/'artifacts'/'aug8-v16-settlement-final'; OUT.mkdir(parents=True,exist_ok=True)

def parse_entry(spec,html):
    return src.parse_entry(spec,html.replace('初出走','0'))

def parse_odds(spec):
    maps={}
    for typ,(prefix,add,mid) in src.ADDS.items():
        cd=(spec['entrySuffix']+add)%256
        html=src.post(prefix+spec['body']+mid+f'{cd:02X}')
        soup=BeautifulSoup(html,'html.parser')
        out={}
        if typ in ('umaren','wide','umatan'):
            cls={'umaren':'umaren','wide':'wide','umatan':'umatan'}[typ]
            for table in soup.find_all('table',class_=lambda x:x and cls in x):
                cap=table.find('caption')
                if not cap: continue
                m=re.search(r'(\d{1,2})',' '.join(cap.stripped_strings))
                if not m: continue
                first=int(m.group(1))
                for tr in table.find_all('tr'):
                    th,td=tr.find('th'),tr.find('td')
                    if not th or not td: continue
                    m2=re.search(r'\d{1,2}',' '.join(th.stripped_strings))
                    if not m2: continue
                    second=int(m2.group())
                    if typ=='wide':
                        mn=td.find(class_='min')
                        val=src.num(' '.join(mn.stripped_strings)) if mn else src.num(' '.join(td.stripped_strings).split('-')[0])
                        key=tuple(sorted((first,second)))
                    else:
                        val=src.num(' '.join(td.stripped_strings),0)
                        key=(first,second) if typ=='umatan' else tuple(sorted((first,second)))
                    if val>1: out[key]=val
        elif typ=='trio':
            for table in soup.find_all('table',class_=lambda x:x and 'fuku3' in x):
                cap=' '.join(table.find('caption').stripped_strings) if table.find('caption') else ''
                m=re.search(r'(\d{1,2})-(\d{1,2})',cap)
                if not m: continue
                a,b=map(int,m.groups())
                for tr in table.find_all('tr'):
                    th,td=tr.find('th'),tr.find('td')
                    if not th or not td: continue
                    m3=re.search(r'\d{1,2}',' '.join(th.stripped_strings))
                    if not m3: continue
                    c=int(m3.group()); val=src.num(' '.join(td.stripped_strings),0)
                    if val>1 and len({a,b,c})==3: out[tuple(sorted((a,b,c)))]=val
        else:
            for table in soup.find_all('table',class_=lambda x:x and 'tan3' in x):
                par=table.parent; first=second=None
                if par:
                    for line in par.find_all('div',class_='p_line',recursive=False):
                        txt=' '.join(line.stripped_strings)
                        m1=re.search(r'1着\s*(\d{1,2})',txt); m2=re.search(r'2着\s*(\d{1,2})',txt)
                        if m1: first=int(m1.group(1))
                        if m2: second=int(m2.group(1))
                if first is None or second is None: continue
                for tr in table.find_all('tr'):
                    th,td=tr.find('th'),tr.find('td')
                    if not th or not td: continue
                    m3=re.search(r'\d{1,2}',' '.join(th.stripped_strings))
                    if not m3: continue
                    third=int(m3.group()); val=src.num(' '.join(td.stripped_strings),0)
                    if val>1 and len({first,second,third})==3: out[(first,second,third)]=val
        maps[typ]=out
    return maps

def main():
    finished=[r for r in base.load_finished_rows() if str(r.get('raceDate',''))<='2026-08-02']
    training,stores=base.build_training(finished); model=base.fit_model(training)
    allrows=[]; meta={}; odds_by={}; results={}
    for i,s in enumerate(src.race_specs(),1):
        eh=src.get(s['entryUrl']); rows,m=parse_entry(s,eh)
        rh=src.get(s['resultUrl']); rt=' '.join(BeautifulSoup(rh,'html.parser').stripped_strings)
        mh=re.search(r'天候\s+([^\s]+)\s+(芝|ダート)\s+(良|稍重|重|不良)',rt)
        if mh: m['weather']=mh.group(1); m['trackCondition']=mh.group(3)
        allrows.extend(rows); meta[s['raceId']]=m
        odds_by[s['raceId']]=parse_odds(s); results[s['raceId']]=src.payout_map(rh)
        print(json.dumps({'fetched':i,'raceId':s['raceId'],'weather':m.get('weather'),'condition':m.get('trackCondition'),'oddsCounts':{k:len(v) for k,v in odds_by[s['raceId']].items()}},ensure_ascii=False),flush=True)
    future=base.build_future(allrows,stores); base.attach_predictions(model,future)
    byvenue=defaultdict(list)
    for race in future:
        race.update(meta[race['raceId']]); race['fieldSize']=len(race['runners'])
        byvenue[race['venue']].append((race,src.candidates(race,odds_by[race['raceId']])))
    selected=[]
    for venue,items in byvenue.items():
        print(json.dumps({'venue':venue,'eligiblePreSelect':sum(src.selector.select_race(r,c) is not None for r,c in items)},ensure_ascii=False),flush=True)
        selected.extend(selector.select_venue_day(items))
    selected.sort(key=lambda x:(x['venue'],x['raceNo']))
    report={'modelVersion':'v16','raceDate':'2026-08-08','archiveCutoff':'2026-08-02','trainingRaces':len(training),'selectedRaces':len(selected),'tickets':[],'courses':{}}
    for sel in selected:
        for t in sel['tickets']:
            report['tickets'].append({'raceId':sel['raceId'],'venue':sel['venue'],'raceNo':sel['raceNo'],'betType':t['betType'],'combination':t['combination'],'officialOdds':t['odds'],'uniformScore':t['uniformScore'],'ruleMatchCount':t['ruleMatchCount'],'payoutPer100Yen':results[sel['raceId']].get((t['betType'],t['combination']),0)})
    for course in selector.COURSE_STAKES:
        total_stake=total_return=0; races=[]
        for sel in selected:
            bets=selector.build_course_bets(sel,course); rr=0; detail=[]
            for b in bets:
                pay100=results[sel['raceId']].get((b['betType'],b['combination']),0)
                ret=pay100*(b['stakeYen']//100); total_stake+=b['stakeYen']; total_return+=ret; rr+=ret
                detail.append({**b,'payoutPer100Yen':pay100,'returnYen':ret})
            races.append({'raceId':sel['raceId'],'venue':sel['venue'],'raceNo':sel['raceNo'],'stakeYen':sum(x['stakeYen'] for x in bets),'returnYen':rr,'tickets':detail})
        report['courses'][course]={'totalStakeYen':total_stake,'totalReturnYen':total_return,'profitYen':total_return-total_stake,'roiPct':(100*total_return/total_stake if total_stake else 0),'races':races}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'DONE':True,'selectedRaces':len(selected),'courses':{k:{x:v[x] for x in ('totalStakeYen','totalReturnYen','profitYen','roiPct')} for k,v in report['courses'].items()}},ensure_ascii=False),flush=True)

if __name__=='__main__': main()
