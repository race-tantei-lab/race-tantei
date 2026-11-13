#!/usr/bin/env python3
import urllib.request,json,re
from bs4 import BeautifulSoup
urls=[
 "https://keibalab.jp/db/race/202609190607/odds.html",
 "https://keibalab.jp/db/race/202609190601/odds.html",
 "https://tospo-keiba.jp/race/202606040507/win-odds",
 "https://sports.yahoo.co.jp/keiba/race/odds/win/2606040507",
 "https://sp.jra.jp/JRADB/accessS.html?CNAME=sw01sde1006202604050720260919%2FC2"
]
for u in urls:
 try:
  req=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36","Accept-Language":"ja-JP,ja;q=0.9"})
  with urllib.request.urlopen(req,timeout=16) as r:raw=r.read();status=r.status
  soup=BeautifulSoup(raw.decode("utf-8","replace"),"html.parser")
  trs=[]
  for tr in soup.find_all("tr"):
   texts=[td.get_text(" ",strip=True) for td in tr.find_all(["th","td"])]
   if len(texts)>2:trs.append(texts)
  print("SEP19_ODDS_PROVIDER_PROBE",json.dumps({"url":u,"status":status,"bytes":len(raw),"title":soup.title.get_text(" ",strip=True)[:150] if soup.title else "",
   "tables":trs[:12],"text":soup.get_text(" ",strip=True)[:550]},ensure_ascii=False),flush=True)
 except Exception as e:print("SEP19_ODDS_PROVIDER_PROBE",json.dumps({"url":u,"error":str(e)[:240]}),flush=True)
