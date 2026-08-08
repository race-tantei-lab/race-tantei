import concurrent.futures, gzip, http.cookiejar, itertools, json, os, random, re, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from bs4 import BeautifulSoup
TOKEN=os.environ['CLOUDFLARE_API_TOKEN']; ACCOUNT=os.environ['CLOUDFLARE_ACCOUNT_ID']; DATABASE=os.environ['CLOUDFLARE_D1_DATABASE_ID']
ROOT=Path(__file__).resolve().parents[1]; SELECTION=ROOT/'analysis-results/fixed-oos-five-races-per-venue-day.json'; OUT=ROOT/'artifacts/selected-historical-official-light-odds.jsonl.gz'; META=ROOT/'artifacts/selected-historical-official-light-odds-meta.json'; WORKERS=int(os.environ.get('ODDS_WORKERS','12'))
ENDPOINT=f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query'
def d1(sql,params=None):
 b=json.dumps({'sql':sql,'params':params or []}).encode();q=urllib.request.Request(ENDPOINT,data=b,headers={'Authorization':f'Bearer {TOKEN}','Content-Type':'application/json'},method='POST')
 with urllib.request.urlopen(q,timeout=90) as r:p=json.loads(r.read().decode())
 if not p.get('success'):raise RuntimeError(p.get('errors'))
 return p.get('result',[{}])[0].get('results',[])
def open_retry(opener,req,attempts=6):
 last=None
 for a in range(attempts):
  try:
   with opener.open(req,timeout=60) as r:return r.read(),r.geturl()
  except urllib.error.HTTPError as e:
   last=e
   if e.code not in {429,500,502,503,504}:raise
  except Exception as e:last=e
  time.sleep(min(8,.4*(2**a))+random.random()*.25)
 raise last or RuntimeError('fetch failed')
def post(opener,cname,referer):
 q=urllib.request.Request('https://www.jra.go.jp/JRADB/accessO.html',data=urllib.parse.urlencode({'cname':cname}).encode('ascii'),headers={'User-Agent':'Mozilla/5.0 (compatible; RaceTanteiHistoricalOdds/1.1; +https://www.jra.go.jp/)','Accept-Language':'ja','Referer':referer,'Content-Type':'application/x-www-form-urlencoded'},method='POST');raw,url=open_retry(opener,q);return raw.decode('cp932','replace'),url
def ofloat(x):
 try:return float(str(x).strip().replace(',',''))
 except:return None
def parse_win(soup):
 for t in soup.find_all('table',class_=lambda x:x and 'basic' in x):
  rows=t.find_all('tr');head=[' '.join(x.stripped_strings) for x in rows[0].find_all(['th','td'])] if rows else []
  if '馬番' not in head or '単勝' not in head:continue
  out={}
  for tr in rows[1:]:
   c=[' '.join(x.stripped_strings) for x in tr.find_all(['th','td'])];nums=[i for i,v in enumerate(c[:3]) if v.isdigit()]
   if not nums:continue
   i=nums[-1];h=int(c[i]);o=ofloat(c[i+2]) if i+2<len(c) else None
   if o and o>0:out[h]=o
  return out
 return {}
def parse_pair(soup,cls,wide=False):
 out={}
 for t in soup.find_all('table'):
  if cls not in (t.get('class') or []):continue
  li=t.find_parent('li');text=' '.join(li.stripped_strings) if li else '';m=re.match(r'\s*(\d+)\b',text)
  if not m:continue
  a=int(m.group(1))
  for tr in t.find_all('tr'):
   c=[' '.join(x.stripped_strings) for x in tr.find_all(['th','td'])]
   if len(c)<2 or not c[0].isdigit():continue
   b=int(c[0]);
   if a==b:continue
   if wide:
    mm=re.match(r'\s*([0-9,.]+)\s*-\s*([0-9,.]+)',c[1]);v=[ofloat(mm.group(1)),ofloat(mm.group(2))] if mm else None
    if not v or None in v:continue
   else:
    v=ofloat(c[1]);
    if not v:continue
   out[tuple(sorted((a,b)))]=v
 return out
def fetch(row):
 cj=http.cookiejar.CookieJar();op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj));hdr={'User-Agent':'Mozilla/5.0 (compatible; RaceTanteiHistoricalOdds/1.1; +https://www.jra.go.jp/)','Accept-Language':'ja'}
 raw,_=open_retry(op,urllib.request.Request(row['resultUrl'],headers=hdr));html=raw.decode('cp932','replace')
 m=re.search(r"doAction\('/JRADB/accessO\.html'\s*,\s*'(pw151ou[^']+)'\)",html)
 if not m:raise RuntimeError('FIRST_ODDS_CNAME_MISS')
 h151,u151=post(op,m.group(1),row['resultUrl']);s151=BeautifulSoup(h151,'html.parser');tabs={}
 for tag in s151.find_all(onclick=True):
  mm=re.search(r"doAction\('/JRADB/accessO\.html'\s*,\s*'(pw15(4|5)ou[^']+)'\)",tag.get('onclick',''))
  if mm:tabs['15'+mm.group(2)]=mm.group(1)
 if '154' not in tabs or '155' not in tabs:raise RuntimeError('LIGHT_TAB_CNAME_MISS')
 h154,_=post(op,tabs['154'],u151);h155,_=post(op,tabs['155'],u151);win=parse_win(s151);um=parse_pair(BeautifulSoup(h154,'html.parser'),'umaren');wi=parse_pair(BeautifulSoup(h155,'html.parser'),'wide',True);horses=sorted(win);pairs=list(itertools.combinations(horses,2))
 rec={'raceId':row['raceId'],'raceDate':row['raceDate'],'venue':row['venue'],'raceNo':int(row['raceNo']),'horses':horses,'win':[win.get(h) for h in horses],'umaren':[um.get(tuple(sorted(p))) for p in pairs],'wide':[wi.get(tuple(sorted(p))) for p in pairs],'source':'jra_historical_official_odds'}
 rec['expected']={'win':len(horses),'umaren':len(pairs),'wide':len(pairs)};rec['present']={'win':sum(x is not None for x in rec['win']),'umaren':sum(x is not None for x in rec['umaren']),'wide':sum(x is not None for x in rec['wide'])};return rec
sel=set(json.loads(SELECTION.read_text(encoding='utf-8'))['races']);rows=d1("SELECT race_id raceId,race_date raceDate,venue,race_no raceNo,result_url resultUrl FROM rt_races WHERE race_date>=? AND race_date<? AND status='finished' ORDER BY race_date,venue,race_no",['2024-05-04','2026-08-03']);rows=[r for r in rows if r['raceId'] in sel]
if len(rows)!=len(sel):raise RuntimeError(f'SELECTION_MISMATCH:{len(rows)}:{len(sel)}')
OUT.parent.mkdir(exist_ok=True);ok=0;fail=[];exp={k:0 for k in ['win','umaren','wide']};pre={k:0 for k in exp};t=time.time()
with gzip.open(OUT,'wt',encoding='utf-8',compresslevel=5) as f, concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
 fm={pool.submit(fetch,r):r for r in rows}
 for i,fu in enumerate(concurrent.futures.as_completed(fm),1):
  r=fm[fu]
  try:
   x=fu.result();f.write(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n');ok+=1
   for k in exp:exp[k]+=x['expected'][k];pre[k]+=x['present'][k]
  except Exception as e:fail.append({'raceId':r['raceId'],'error':f'{type(e).__name__}:{e}'})
  if i%100==0:print(json.dumps({'done':i,'ok':ok,'fail':len(fail),'sec':round(time.time()-t,1)}),flush=True)
cov=ok/len(rows) if rows else 0;meta={'selectedRaces':len(rows),'successRaces':ok,'failedRaces':len(fail),'raceCoveragePct':100*cov,'expectedTotals':exp,'presentTotals':pre,'combinationCoveragePct':{k:(100*pre[k]/exp[k] if exp[k] else 0) for k in exp},'failures':fail[:300],'source':'JRA official historical odds pages','syntheticOddsUsed':False,'estimatedOddsUsed':False,'workers':WORKERS};META.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(meta,ensure_ascii=False),flush=True)
if cov<.98:raise RuntimeError(f'LIGHT_ODDS_COVERAGE_TOO_LOW:{cov:.6f}')
