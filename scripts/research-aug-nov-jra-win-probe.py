#!/usr/bin/env python3
import importlib.util,sys,urllib.request,urllib.parse,urllib.error,http.cookiejar,re
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/"scripts/research-enrich-official-history-odds.py"
spec=importlib.util.spec_from_file_location("historical_jra_odds",p)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
examples=[
 ("aug_desktop","https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1007202602070120260815/56","pw151ou","1007202602070120260815"),
 ("sep_mobile","https://app.jra.jp/JRADB/accessS.html?CNAME=sw01sde0101202602050620260905/0C","sw151ou","1001202602050620260905"),
 ("oct_desktop","https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0108202604010120261003/DD","pw151ou","1008202604010120261003"),
 ("oct31_mobile","https://www.jra.go.jp/JRADB/accessS.html?CNAME=sw01sde0108202604100120261031/9B","sw151ou","1008202604100120261031"),
 ("nov01_sp","https://sp.jra.jp/JRADB/accessS.html?CNAME=sw01sde0105202604110120261101/9D","sw151ou","1005202604110120261101"),
 ("nov07_desktop","https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0105202605010120261107/9F","pw151ou","1005202605010120261107"),
]
for title,url,prefix,marker in examples:
 try:
  cj=m.http.cookiejar.CookieJar()
  op=m.urllib.request.build_opener(m.urllib.request.HTTPCookieProcessor(cj))
  req=m.urllib.request.Request(url,headers={"User-Agent":m.USER_AGENT,"Accept-Language":"ja"})
  raw,_=m.open_retry(op,req,attempts=2)
  page=raw.decode("cp932","replace")
  values=m.extract_odds_cnames(page,prefix,marker)
  print("JRA_PROBE_PAGE",title,"size",len(page),"odds",values[:3],
    "all_151_links",re.findall(r"(?:pw|sw)151ou[^\\\"'&<>\\s)]+",page,re.I)[:12],
    "accessO",len(re.findall("accessO",page,re.I)),flush=True)
  if not values:
   for token in ("オッズ","accessO","CNAME=","151ou"):
    at=page.find(token)
    print("JRA_PROBE_HTML_TOKEN",title,token,at,repr(page[max(0,at-250):at+450]) if at>=0 else "",flush=True)
  if not values:continue
  from urllib.parse import urlencode
  for host in ["https://www.jra.go.jp/JRADB/accessO.html","https://app.jra.jp/JRADB/accessO.html"]:
   try:
    original=m.ODDS_URL;m.ODDS_URL=host
    html,_=m.post_odds(op,values[0],url)
    win=m.parse_win(BeautifulSoup(html,"html.parser"))
    print("JRA_PROBE_WIN_ODDS",title,host,len(win),list(win.items())[:6],flush=True)
    if not win:
     soup=BeautifulSoup(html,"html.parser")
     print("JRA_PROBE_MOBILE_HTML",title,host,"htmlBytes",len(html),
           "tableClasses",[x.get("class") for x in soup.find_all("table")[:8]],
           "text",soup.get_text(" ",strip=True)[:1700],flush=True)
     print("JRA_PROBE_MOBILE_TR_EXAMPLES",title,[str(tr)[:1400] for tr in soup.find_all("tr")[:7]],flush=True)
    if win:break
   except Exception as e:
    print("JRA_PROBE_HOST_ERROR",title,host,type(e).__name__,str(e)[:300],flush=True)
   finally:m.ODDS_URL=original
 except Exception as e:
  print("JRA_PROBE_PAGE_ERROR",title,type(e).__name__,str(e)[:300],flush=True)
