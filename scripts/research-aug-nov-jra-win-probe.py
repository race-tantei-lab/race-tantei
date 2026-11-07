#!/usr/bin/env python3
import importlib.util, sys, re, urllib.parse, http.cookiejar, urllib.request
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/"scripts/research-enrich-official-history-odds.py"
spec=importlib.util.spec_from_file_location("historical_jra_odds",p)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
url="https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1007202602070120260815/56"
c=m.http.cookiejar.CookieJar();op=m.urllib.request.build_opener(m.urllib.request.HTTPCookieProcessor(c))
req=m.urllib.request.Request(url,headers={"User-Agent":m.USER_AGENT,"Accept-Language":"ja"})
raw,_=m.open_retry(op,req,attempts=2)
text=raw.decode("cp932","replace")
print("JRA_PROBE_RESULT_PAGE",len(text),re.findall("pw151ou[^\\\"'&<> ]+",text,re.I)[:3],flush=True)
marker="1007202602070120260815"
found=m.extract_odds_cnames(text,"pw151ou",marker)
print("JRA_PROBE_ODDS_LINKS",found[:5],flush=True)
if not found:raise RuntimeError("JRA_WIN_ODDS_LINK_UNAVAILABLE")
win_html,_=m.post_odds(op,found[0],url)
parsed=m.parse_win(BeautifulSoup(win_html,"html.parser"))
print("JRA_PROBE_WIN_ODDS",dict(list(parsed.items())[:12]),"horses",len(parsed),flush=True)
if len(parsed)<3:raise RuntimeError("JRA_WIN_ODDS_EMPTY")
