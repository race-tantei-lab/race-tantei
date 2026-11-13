#!/usr/bin/env python3
"""Read-only diagnostic: verify full-field JRA OFFICIAL final win odds can fill D1 gaps."""
from __future__ import annotations
import concurrent.futures, importlib.util, json, re, urllib.parse
from pathlib import Path
from collections import Counter
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-official-final-odds-fetch-probe.json"
def imp(path,name):
    s=importlib.util.spec_from_file_location(name,ROOT/path)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def get_odds(row,historic,live):
    url=row["resultUrl"]
    if not url:return {"error":"NO_OFFICIAL_JRA_RESULT_URL"}
    decoded=urllib.parse.unquote(url)
    match=re.search(r"(?:pw|sw)01sde(?:10|01)(\\d{2})(\\d{4})(\\d{2})(\\d{2})(\\d{2})(\\d{8})",decoded,re.I)
    if not match:return {"error":"UNRECOGNIZED_JRA_RESULT_CNAME","url":url[:120]}
    venue,year,meeting,day,rno,ymd=match.groups()
    if ymd!=row["raceDate"].replace("-","") or int(rno)!=int(row["raceNo"]):
        return {"error":"JRA_IDENTITY_MISMATCH","url":url[:120]}
    if re.search("CNAME=sw01",url,re.I):
        parsed=urllib.parse.urlsplit(url);url=urllib.parse.urlunsplit(parsed._replace(netloc="sp.jra.jp"))
    jar=historic.http.cookiejar.CookieJar()
    opener=historic.urllib.request.build_opener(historic.urllib.request.HTTPCookieProcessor(jar))
    req=historic.urllib.request.Request(url,headers={"User-Agent":historic.USER_AGENT,"Accept-Language":"ja-JP,ja;q=0.9"})
    raw,_=historic.open_retry(opener,req,attempts=2,timeout=12)
    page=raw.decode("cp932","replace")
    core=venue+year+meeting+day+rno+ymd
    found=sorted(set(re.findall(r"(?:pw|sw)151ou(?:10|S3)"+re.escape(core)+r"Z/[0-9A-Fa-f]{2}",page,re.I)))
    if len(found)!=1:return {"error":"OFFICIAL_WIN_LINK_COUNT_"+str(len(found)),"url":url[:120],"htmlBytes":len(raw)}
    cname=found[0]
    html,source=historic.post_odds(opener,cname,url)
    quotes=live.parse_mobile_win_odds(html) if cname.lower().startswith("sw") else historic.parse_win(BeautifulSoup(html,"html.parser"))
    return {"odds":quotes,"quoteCount":len(quotes),"cname":cname,"source":source}
def main():
    live=imp("scripts/postaug-support-aug-nov-frozen-policy-recheck.py","diag_d1_reader")
    historic=imp("scripts/research-enrich-official-history-odds.py","diag_official")
    live.START="2026-08-01";live.END="2026-11-14";live.MONTHS=("2026-08","2026-09","2026-10","2026-11")
    byday,counts=live.d1_bundles()
    allr=[b for day in sorted(byday) for b in byday[day] if b["race"].get("status")=="finished"]
    missing=[b for b in allr if sum(x.get("winOdds") not in (None,"","0","-") for x in b["runners"])<10]
    print("OFFICIAL_DIAGNOSTIC_MISSING_D1_ODDS",json.dumps({"finished":len(allr),"missingOdds":len(missing),"withoutResultUrl":sum(not b["race"].get("resultUrl") for b in missing)}),flush=True)
    chosen=missing[:18]
    def work(b):
        row=b["race"]
        try:
            res=get_odds(row,historic,live)
            res.update({"raceId":row["raceId"],"date":row["raceDate"],
                        "runnerCount":len(b["runners"])})
            return res
        except Exception as e:return {"raceId":row["raceId"],"error":type(e).__name__+":"+str(e)[:260]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(work,chosen))
    summary=Counter("OK" if x.get("quoteCount",0)>=10 else str(x.get("error") or "FEWER_10_QUOTES") for x in results)
    for r in results: print("OFFICIAL_FINAL_ODDS_SAMPLE",json.dumps({k:v for k,v in r.items() if k!="odds"},ensure_ascii=False),flush=True)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({"counts":counts,"diagnosis":dict(summary),"results":results},ensure_ascii=False,indent=2)+"\n")
    print("OFFICIAL_FINAL_ODDS_PROBE_FINISHED",json.dumps({"finished":len(allr),"missingD1Odds":len(missing),"sample":len(chosen),"diagnosis":dict(summary)},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
