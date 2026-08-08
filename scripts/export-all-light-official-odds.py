import concurrent.futures,gzip,http.cookiejar,itertools,json,os,random,re,time,urllib.error,urllib.parse,urllib.request
from pathlib import Path
from bs4 import BeautifulSoup
TOKEN=os.environ['CLOUDFLARE_API_TOKEN'];ACCOUNT=os.environ['CLOUDFLARE_ACCOUNT_ID'];DATABASE=os.environ['CLOUDFLARE_D1_DATABASE_ID'];ENDPOINT=f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1/database/{DATABASE}/query'
SHARD_COUNT=int(os.environ.get('SHARD_COUNT','1'));SHARD_INDEX=int(os.environ.get('SHARD_INDEX','0'));WORKERS=int(os.environ.get('WORKERS','12'))
OUT=Path('artifacts')/f'all-light-official-odds-shard-{SHARD_INDEX}.jsonl.gz';META=Path('artifacts')/f'all-light-official-odds-meta-shard-{SHARD_INDEX}.json'
def d1(sql,params):
 body=json.dumps({'sql':sql,'params':params}).encode();req=urllib.request.Request(ENDPOINT,data=body,headers={'Authorization':f'Bearer {TOKEN}','Content-Type':'application/json'},method='POST')
 with urllib.request.urlopen(req,timeout=90) as r:p=json.loads(r.read().decode())
 if not p.get('success'):raise RuntimeError(p.get('errors'))
 return p.get('result',[{}])[0].get('results',[])
def opn(op,req,attempts=7):
 last=None
 for a in range(attempts):
  try:
   with op.open(req,timeout=60) as r:return r.read(),r.geturl()
  except urllib.error.HTTPError as e:
   last=e
   if e.code not in {429,500,502,503,504}:raise
  except Exception as e:last=e
  time.sleep(min(12,.6*(2**a))+random.random()*.3)
 raise last
def post(op,host,cname,referer):
 data=urllib.parse.urlencode({'cname':cname}).encode('ascii');req=urllib.request.Request(host+'/JRADB/accessO.html',data=data,headers={'User-Agent':'Mozilla/5.0','Accept-Language':'ja','Referer':referer,'Content-Type':'application/x-www-form-urlencoded'},method='POST');raw,u=opn(op,req);return raw.decode('cp932','replace'),u
def of(x):
 try:return float(str(x).replace(',','').strip())
 except:return None
def parse_win(s):
 out={}
 for t in s.find_all('table'):
  rows=t.find_all('tr')
  if not rows:continue
  head=[' '.join(x.stripped_strings) for x in rows[0].find_all(['th','td'])]
  if '馬番' not in head or '単勝' not in head:continue
  for tr in rows[1:]:
   cells=[' '.join(x.stripped_strings) for x in tr.find_all(['th','td'])];nums=[i for i,c in enumerate(cells[:3]) if c.isdigit() and 1<=int(c)<=20]
   if not nums:continue
   i=nums[-1];h=int(cells[i]);j=i+2
   if j<len(cells):
    v=of(cells[j])
    if v and v>0:out[h]=v
  if out:return out
 return out
def parse_desktop_pair(s,cls,wide=False):
 out={}
 for t in s.find_all('table'):
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
    mm=re.match(r'\s*([0-9,.]+)\s*-\s*([0-9,.]+)',c[1]);v=[of(mm.group(1)),of(mm.group(2))] if mm else None
   else:v=of(c[1])
   if v is not None and (not wide or None not in v):out[tuple(sorted((a,b)))]=v
 return out
def parse_mobile_pair(s,wide=False):
 text=' '.join(s.stripped_strings);out={}
 if wide:
  pat=re.compile(r'(?<!\d)(\d{1,2})-(\d{1,2})\s+([0-9,.]+)\s*-\s*([0-9,.]+)')
  for a,b,lo,hi in pat.findall(text):out[tuple(sorted((int(a),int(b))))]=[of(lo),of(hi)]
 else:
  pat=re.compile(r'(?<!\d)(\d{1,2})-(\d{1,2})\s+(票数なし|[0-9,.]+)')
  for a,b,v in pat.findall(text):
   x=of(v)
   if x is not None:out[tuple(sorted((int(a),int(b))))]=x
 return out
def vec(hs,win,q,w):
 pairs=list(itertools.combinations(hs,2));return {'horses':hs,'win':[win.get(h) for h in hs],'umaren':[q.get(tuple(sorted(x))) for x in pairs],'wide':[w.get(tuple(sorted(x))) for x in pairs]}
def fetch(row):
 url=row['resultUrl'];mobile='sp.jra.jp' in url or 'CNAME=sw' in urllib.parse.unquote(url);host='https://sp.jra.jp' if mobile else 'https://www.jra.go.jp';prefix='sw' if mobile else 'pw'
 cj=http.cookiejar.CookieJar();op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj));raw,_=opn(op,urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept-Language':'ja'}));html=raw.decode('cp932','replace')
 m=re.search(r'('+prefix+r'151ou[0-9A-Za-z_/.-]+)',html)
 if not m:raise RuntimeError('FIRST_CNAME_MISS')
 first=m.group(1);marker=first.split('Z',1)[0].replace(prefix+'151ou','',1);h151,u151=post(op,host,first,url);s151=BeautifulSoup(h151,'html.parser');tokens=sorted(set(re.findall(prefix+r'15[45][A-Za-z0-9_/.-]+',h151)))
 tabs={}
 for k in ['154','155']:
  cs=[x for x in tokens if x.startswith(prefix+k+'ou') and marker in x]
  if not cs:raise RuntimeError('TAB_MISS:'+k)
  tabs[k]=min(cs,key=len)
 h154,_=post(op,host,tabs['154'],u151);h155,_=post(op,host,tabs['155'],u151)
 win=parse_win(s151);q=parse_mobile_pair(BeautifulSoup(h154,'html.parser')) if mobile else parse_desktop_pair(BeautifulSoup(h154,'html.parser'),'umaren');w=parse_mobile_pair(BeautifulSoup(h155,'html.parser'),True) if mobile else parse_desktop_pair(BeautifulSoup(h155,'html.parser'),'wide',True)
 hs=sorted(win);v=vec(hs,win,q,w);exp=len(hs)*(len(hs)-1)//2;present={'win':sum(x is not None for x in v['win']),'umaren':sum(x is not None for x in v['umaren']),'wide':sum(x is not None for x in v['wide'])}
 return {'raceId':row['raceId'],'raceDate':row['raceDate'],'venue':row['venue'],'raceNo':int(row['raceNo']),**v,'expected':{'win':len(hs),'umaren':exp,'wide':exp},'present':present,'source':'jra_historical_official_odds'}
rows=d1("SELECT race_id raceId,race_date raceDate,venue,race_no raceNo,result_url resultUrl FROM rt_races WHERE race_date>=? AND race_date<? AND status='finished' ORDER BY race_date,venue,race_no",['2024-05-04','2026-08-03']);rows=[r for i,r in enumerate(rows) if i%SHARD_COUNT==SHARD_INDEX]
OUT.parent.mkdir(exist_ok=True);ok=0;fail=[];pt={k:0 for k in ['win','umaren','wide']};et={k:0 for k in pt}
with gzip.open(OUT,'wt',encoding='utf-8') as f,concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
 fm={pool.submit(fetch,r):r for r in rows}
 for i,fu in enumerate(concurrent.futures.as_completed(fm),1):
  r=fm[fu]
  try:
   x=fu.result();f.write(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n');ok+=1
   for k in pt:pt[k]+=x['present'][k];et[k]+=x['expected'][k]
  except Exception as e:fail.append({'raceId':r['raceId'],'error':type(e).__name__+':'+str(e)})
  if i%100==0:print(json.dumps({'shard':SHARD_INDEX,'done':i,'ok':ok,'fail':len(fail)}),flush=True)
meta={'shard':SHARD_INDEX,'rows':len(rows),'success':ok,'failed':len(fail),'raceCoveragePct':100*ok/len(rows),'combinationCoveragePct':{k:100*pt[k]/et[k] if et[k] else 0 for k in pt},'failures':fail,'syntheticOddsUsed':False,'estimatedOddsUsed':False};META.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n');print(json.dumps(meta,ensure_ascii=False))
if ok/len(rows)<.99:raise RuntimeError('COVERAGE_TOO_LOW')
