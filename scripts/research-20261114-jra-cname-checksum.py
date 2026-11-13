#!/usr/bin/env python3
import urllib.request, concurrent.futures,json,re
from bs4 import BeautifulSoup
def test(no):
  suffix=(0x63+0xB5*no)%256
  urls=[]
  for prefix in ("pw01sde01","pw01sde10"):
    code=f"{prefix}0620260405{no:02d}20260919/{suffix:02X}"
    url="https://www.jra.go.jp/JRADB/accessS.html?CNAME="+code
    try:
      r=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept-Language":"ja-JP"})
      with urllib.request.urlopen(r,timeout=13) as f:raw=f.read()
      text=raw.decode("cp932","replace")
      body=BeautifulSoup(text,"html.parser").get_text(" ",strip=True)
      os=re.findall(r"(?:pw|sw)151ou(?:10|S3)\\d{20}Z/[0-9A-Fa-f]{2}",text,re.I)
      urls.append({"prefix":prefix,"url":url,"valid":bool(os),"oddsCode":os[:2],
        "htmlBytes":len(raw),"title":BeautifulSoup(text,"html.parser").title.get_text(" ",strip=True)[:90]})
    except Exception as ex:urls.append({"url":url,"err":str(ex)[:100]})
  return {"raceNo":no,"cases":urls}
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
 for x in ex.map(test,range(1,13)):
   print("JRA_CHECKSUM_RACE",json.dumps(x,ensure_ascii=False),flush=True)
