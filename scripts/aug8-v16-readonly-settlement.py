import importlib.util, itertools, json, math, re, sys
from collections import defaultdict
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec); sys.modules[name]=m; spec.loader.exec_module(m); return m
base=load('aug8_base',ROOT/'scripts'/'publish-nonlinear-v4-production.py')
selector=load('aug8_v16',ROOT/'scripts'/'v16-uniform-rule-selector.py')
prob=load('aug8_prob',ROOT/'scripts'/'final-course-policy.py')
OUT=ROOT/'artifacts'/'aug8-v16-settlement'; OUT.mkdir(parents=True,exist_ok=True)

SAPP={1:0xC5,2:0x7A,3:0x2F,4:0xE4,5:0x99,6:0x4E,7:0x03,8:0xB8,9:0x6D,10:0x62,11:0x17,12:0xCC}
SPECS={'01':('札幌','sapporo','01',0),'04':('新潟','niigata','02',0x0F),'07':('中京','chukyo','02',0x0F-0x22)}
ADDS={'umaren':('pw154ouS3',47,'Z/'),'wide':('pw155ouS3',179,'Z/'),'umatan':('pw156ouS3',55,'Z/'),'trio':('pw157ouS3',29,'Z99/'),'trifecta':('pw158ouS3',63,'Z/')}
JP={'umaren':'馬連','wide':'ワイド','umatan':'馬単','trio':'3連複','trifecta':'3連単'}
sess=requests.Session(); sess.headers.update({'User-Agent':'Mozilla/5.0 (compatible; RaceTanteiAug8Settlement/1.0; +https://www.jra.go.jp/)','Accept-Language':'ja'})

def get(url):
    r=sess.get(url,timeout=60); r.encoding='cp932'; r.raise_for_status(); return r.text

def post(cname):
    r=sess.post('https://www.jra.go.jp/JRADB/accessO.html',data={'cname':cname},timeout=60); r.encoding='cp932'; r.raise_for_status(); return r.text

def num(s,default=0.0):
    try:return float(str(s).replace(',','').strip())
    except:return default

def race_specs():
    rows=[]
    for vc,(jp,en,meeting,off) in SPECS.items():
        for rno in range(1,13):
            es=(SAPP[rno]+off)%256; rs=(es-0x44)%256; body=f'{vc}2026{meeting}05{rno:02d}20260808'
            rows.append({'raceId':f'2026-08-08-{en}-{rno:02d}','raceDate':'2026-08-08','venue':jp,'raceNo':rno,'entrySuffix':es,'body':body,'entryCname':f'pw01dde01{body}/{es:02X}','entryUrl':f'https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde01{body}/{es:02X}','resultUrl':f'https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde01{body}/{rs:02X}'})
    return rows

def parse_entry(spec,html):
    soup=BeautifulSoup(html,'html.parser'); text=' '.join(soup.stripped_strings)
    if not all(x in text for x in ['2026年8月8日',spec['venue'],f"{spec['raceNo']}レース"]): raise RuntimeError('ENTRY_MISMATCH:'+spec['raceId'])
    md=re.search(r'コース：\s*([0-9,]+)\s*メートル\s*（(芝|ダート)',text); distance=int(md.group(1).replace(',','')) if md else 0; surface=md.group(2) if md else ''
    mc=re.search(r'(芝|ダート)\s+(良|稍重|重|不良)',text); condition=mc.group(2) if mc else ''
    mw=re.search(r'天候\s+([^\s]+)',text); weather=mw.group(1) if mw else ''
    rows=[]
    for tr in soup.select('table.basic tr'):
        tdnum=tr.find('td',class_='num'); horse=tr.find('td',class_='horse'); jockey=tr.find('td',class_='jockey'); waku=tr.find('td',class_='waku')
        if not tdnum or not horse or not jockey: continue
        hno_txt=' '.join(tdnum.stripped_strings)
        if not re.fullmatch(r'\d{1,2}',hno_txt): continue
        hno=int(hno_txt); ht=' '.join(horse.stripped_strings); jt=' '.join(jockey.stripped_strings)
        mo=re.match(r'(.+?)\s+([0-9]+\.[0-9]+)\s*\((\d+)\s*番人気\s*\)\s+(\d+)kg\s*\(([+\-]?\d+)\)',ht)
        if not mo: continue
        horse_name,odds,pop,weight,change=mo.groups()
        # trainer is the name immediately before (美浦)/(栗東)
        mt=re.search(r'([^\s]+\s+[^\s]+|[^\s]+)\s*\((美浦|栗東)\)',ht); trainer=mt.group(1) if mt else ''
        mj=re.match(r'([^\s]+)[^\s]*/[^\s]+\s+([0-9]+(?:\.[0-9]+)?)\s*kg\s+(.+)$',jt)
        sexage=jt.split('/')[0] if '/' in jt else ''; assigned=num(mj.group(2)) if mj else 0; jockey_name=mj.group(3).strip() if mj else ''
        img=waku.find('img') if waku else None; mf=re.search(r'枠(\d+)',img.get('alt','')) if img else None; frame=int(mf.group(1)) if mf else 0
        rows.append({'raceId':spec['raceId'],'raceDate':'2026-08-08','venue':spec['venue'],'raceNo':spec['raceNo'],'surface':surface,'distanceM':distance,'trackCondition':condition,'startTimeUtc':'2026-08-08T00:00:00Z','horseNo':hno,'frameNo':frame,'horseName':horse_name.strip(),'sexAge':sexage,'horseWeight':int(weight),'weightChange':int(change),'jockey':jockey_name,'assignedWeight':assigned,'trainer':trainer,'stable':trainer,'winOdds':float(odds),'popularity':int(pop),'runnerStatus':'active'})
    if len(rows)<5: raise RuntimeError(f'ENTRY_RUNNERS_TOO_SMALL:{spec["raceId"]}:{len(rows)}')
    return rows, {'surface':surface,'distanceM':distance,'trackCondition':condition,'weather':weather,'fieldSize':len(rows)}

def parse_odds(spec):
    maps={}
    # win from entry rows is attached separately
    for typ,(prefix,add,mid) in ADDS.items():
        cd=(spec['entrySuffix']+add)%256; html=post(prefix+spec['body']+mid+f'{cd:02X}'); text=' '.join(BeautifulSoup(html,'html.parser').stripped_strings)
        out={}
        if typ=='wide':
            for a,b,lo,hi in re.findall(r'(?<!\d)(\d{1,2})-(\d{1,2})\s+([0-9,.]+)\s*-\s*([0-9,.]+)',text): out[tuple(sorted((int(a),int(b))))]=num(lo)
        elif typ in ('umaren','umatan'):
            for a,b,v in re.findall(r'(?<!\d)(\d{1,2})-(\d{1,2})\s+([0-9,.]+)',text):
                key=(int(a),int(b)) if typ=='umatan' else tuple(sorted((int(a),int(b)))); out[key]=num(v)
        else:
            for a,b,c,v in re.findall(r'(?<!\d)(\d{1,2})-(\d{1,2})-(\d{1,2})\s+([0-9,.]+)',text):
                vals=(int(a),int(b),int(c)); key=vals if typ=='trifecta' else tuple(sorted(vals)); out[key]=num(v)
        maps[typ]=out
    return maps

def payout_map(result_html):
    text=' '.join(BeautifulSoup(result_html,'html.parser').stripped_strings); tail=text[text.rfind('払戻金'):]
    out={}
    pats=[('単勝','単勝',r'単勝\s+(\d{1,2})\s+([0-9,]+)\s*円'),('馬連','馬連',r'馬連\s+(\d{1,2})-(\d{1,2})\s+([0-9,]+)\s*円'),('馬単','馬単',r'馬単\s+(\d{1,2})-(\d{1,2})\s+([0-9,]+)\s*円'),('3連複','3連複',r'3連複\s+(\d{1,2})-(\d{1,2})-(\d{1,2})\s+([0-9,]+)\s*円'),('3連単','3連単',r'3連単\s+(\d{1,2})-(\d{1,2})-(\d{1,2})\s+([0-9,]+)\s*円')]
    for typ,_,pat in pats:
        for m in re.finditer(pat,tail):
            vals=list(m.groups()); pay=int(vals.pop().replace(',','')); horses=tuple(map(int,vals)); horses=tuple(sorted(horses)) if typ in ('馬連','3連複') else horses; out[(typ,'-'.join(map(str,horses)))]=pay
    # wide has up to 3 winning combinations
    for a,b,v in re.findall(r'(\d{1,2})-(\d{1,2})\s+([0-9,]+)\s*円\s+\d+\s*番人気',tail[tail.find('ワイド'):tail.find('馬連') if '馬連' in tail else None]):
        hs=tuple(sorted((int(a),int(b)))); out[('ワイド','-'.join(map(str,hs)))]=int(v.replace(',',''))
    return out

def market_event(bet_type,horses,market):
    if bet_type=='単勝': return market.get(horses[0],0.0)
    if bet_type=='ワイド': return prob.wide_probability(horses[0],horses[1],market)
    if bet_type=='馬連': return prob.unordered_top_two(horses[0],horses[1],market)
    if bet_type=='馬単': return prob.ordered_probability(horses[:2],market)
    if bet_type=='3連複': return prob.unordered_top_three(horses[:3],market)
    return prob.ordered_probability(horses[:3],market)

def candidates(race,odds):
    ranked=sorted(race['runners'],key=lambda x:-float(x['probability'])); by={int(x['horseNo']):x for x in ranked}
    for i,x in enumerate(ranked,1): x['predictedOrder']=i
    win={int(x['horseNo']):float(x['probability']) for x in ranked}; sw=sum(win.values()); win={k:v/sw for k,v in win.items()}
    market={int(x['horseNo']):float(x['market']) for x in ranked}; sm=sum(market.values()); market={k:v/sm for k,v in market.items()}
    allc=[]
    def add(bt,hs,odd):
        hs=tuple(sorted(hs)) if bt in ('ワイド','馬連','3連複') else tuple(hs); mp=prob.event_probability(bt,hs,win,win); mkp=market_event(bt,hs,market)
        if odd and odd>1 and mp>0 and mkp>0: allc.append({'betType':bt,'combination':'-'.join(map(str,hs)),'odds':float(odd),'oddsSource':'jra_official','predProb':mp,'marketProb':mkp,'residRatio':mp/mkp,'rank':sum(by[h]['predictedOrder'] for h in hs),'expectedEV':mp*float(odd)})
    hs=list(by)
    for h in hs: add('単勝',(h,),float(by[h]['winOdds']))
    for a,b in itertools.combinations(hs,2):
        add('ワイド',(a,b),odds['wide'].get(tuple(sorted((a,b))))); add('馬連',(a,b),odds['umaren'].get(tuple(sorted((a,b))))); add('馬単',(a,b),odds['umatan'].get((a,b))); add('馬単',(b,a),odds['umatan'].get((b,a)))
    for comb in itertools.combinations(hs,3):
        add('3連複',comb,odds['trio'].get(tuple(sorted(comb))))
        for order in itertools.permutations(comb): add('3連単',order,odds['trifecta'].get(order))
    out=[]
    for bt in ('単勝','ワイド','馬連','馬単','3連複','3連単'):
        xs=[x for x in allc if x['betType']==bt]; xs.sort(key=lambda x:(-x['expectedEV'],x['rank'],x['odds'])); out.extend(xs[:5])
    return out

def main():
    # Train only through 2026-08-02, the frozen archive endpoint. Aug 8 outcomes are never training input.
    finished=[r for r in base.load_finished_rows() if str(r.get('raceDate',''))<='2026-08-02']
    training,stores=base.build_training(finished); model=base.fit_model(training)
    specs=race_specs(); allrows=[]; meta={}; odds_by={}; results={}
    for i,s in enumerate(specs,1):
        eh=get(s['entryUrl']); rows,m=parse_entry(s,eh); allrows.extend(rows); meta[s['raceId']]=m; odds_by[s['raceId']]=parse_odds(s); results[s['raceId']]=payout_map(get(s['resultUrl'])); print(json.dumps({'fetched':i,'raceId':s['raceId']},ensure_ascii=False),flush=True)
    future=base.build_future(allrows,stores); base.attach_predictions(model,future)
    byvenue=defaultdict(list)
    for race in future:
        m=meta[race['raceId']]; race.update(m); race['fieldSize']=len(race['runners']); byvenue[race['venue']].append((race,candidates(race,odds_by[race['raceId']])))
    selected=[]
    for venue,items in byvenue.items(): selected.extend(selector.select_venue_day(items))
    selected.sort(key=lambda x:(x['venue'],x['raceNo']))
    report={'modelVersion':'v16','raceDate':'2026-08-08','archiveCutoff':'2026-08-02','trainingRaces':len(training),'selectedRaces':len(selected),'tickets':[],'courses':{}}
    for sel in selected:
        for t in sel['tickets']:
            pay100=results[sel['raceId']].get((t['betType'],t['combination']),0); report['tickets'].append({'raceId':sel['raceId'],'venue':sel['venue'],'raceNo':sel['raceNo'],'betType':t['betType'],'combination':t['combination'],'officialOdds':t['odds'],'rank':t['rank'],'uniformScore':t['uniformScore'],'ruleMatchCount':t['ruleMatchCount'],'payoutPer100Yen':pay100})
    for course,stakes in selector.COURSE_STAKES.items():
        total_stake=0; total_return=0; rows=[]
        for sel in selected:
            bets=selector.build_course_bets(sel,course); rr=0
            for b in bets:
                pay=results[sel['raceId']].get((b['betType'],b['combination']),0); ret=pay*(b['stakeYen']//100); total_stake+=b['stakeYen']; total_return+=ret; rr+=ret
            rows.append({'raceId':sel['raceId'],'venue':sel['venue'],'raceNo':sel['raceNo'],'stakeYen':sum(x['stakeYen'] for x in bets),'returnYen':rr})
        report['courses'][course]={'totalStakeYen':total_stake,'totalReturnYen':total_return,'roiPct':total_return/total_stake*100 if total_stake else 0,'profitYen':total_return-total_stake,'races':rows}
    (OUT/'settlement.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
