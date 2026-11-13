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

print("JRA_RESULT_ODDS_LINK_DETAILS")
for u in ["https://sp.jra.jp/JRADB/accessS.html?CNAME=sw01sde1006202604050720260919%2FC2",
 "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0106202604050120260919/18",
 "https://race.netkeiba.com/odds/index.html?race_id=202606040507",
 "https://race.sp.netkeiba.com/odds/index.html?race_id=202606040507"]:
 try:
  req=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0 Safari/537.36","Accept-Language":"ja-JP,ja;q=0.9"})
  with urllib.request.urlopen(req,timeout=13) as f:raw=f.read()
  decoded=raw.decode("cp932","replace") if "jra.jp" in u else raw.decode("utf-8","replace")
  soup=BeautifulSoup(decoded,"html.parser")
  oddslinks=[(a.get("href") or "",a.get_text(" ",strip=True)[:80]) for a in soup.find_all("a")
           if any(x in (a.get("href") or "").lower() for x in ("ou","odd","accesso"))]
  cmatches=re.findall(r".{0,120}(?:151ou|ODDS|単勝オッズ|オッズ).{0,170}",decoded,re.I)
  trs=[[c.get_text(" ",strip=True) for c in tr.find_all(["td","th"])] for tr in soup.find_all("tr")]
  print("SEP19_DETAIL",json.dumps({"url":u,"bytes":len(raw),"oddsLinks":oddslinks[:30],
    "cnameMatches":cmatches[:10],"table":trs[:8],
    "body":soup.get_text(" ",strip=True)[:350]},ensure_ascii=False),flush=True)
 except Exception as ex:print("SEP19_DETAIL",json.dumps({"url":u,"error":str(ex)[:200]}),flush=True)

for u in ["https://sp.jra.jp/JRADB/accessS.html?CNAME=sw01sde1006202604050720260919%2F00",
 "https://sp.jra.jp/JRADB/accessS.html?CNAME=sw01sde1006202604050720260919",
 "https://sp.jra.jp/JRADB/accessS.html?CNAME=sw01sde1006202604050820260919%2F00",
 "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0106202604050820260919/00",
 "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0106202604050420260919/7B"]:
 try:
  req=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0","Accept-Language":"ja-JP"})
  with urllib.request.urlopen(req,timeout=12) as r:raw=r.read()
  txt=raw.decode("cp932","replace")
  soup=BeautifulSoup(txt,"html.parser")
  cmatches=re.findall(r"(?:pw|sw)151ou(?:10|S3)\\d{20}Z/[0-9A-Fa-f]{2}",txt,re.I)
  bod=soup.get_text(" ",strip=True)
  print("JRA_SUFFIX_PROBE",json.dumps({"u":u,"bytes":len(raw),"oddsCnames":cmatches[:5],
   "hasRace7":("第7レース" in bod or "7R" in bod),"hasSep19":"2026年9月19日" in bod,
   "title":soup.title.get_text(" ",strip=True) if soup.title else "", "snippet":bod[-240:]},ensure_ascii=False),flush=True)
 except Exception as e:print("JRA_SUFFIX_PROBE",json.dumps({"u":u,"error":str(e)[:160]},ensure_ascii=False),flush=True)
