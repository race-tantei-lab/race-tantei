#!/usr/bin/env python3
"""Read-only D1 and public source payout-gap inventory, no writes."""
import collections, datetime as dt, importlib.util, json, sys, urllib.request
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-six-market-payout-gap-diagnostic.json"
def helper():
    s=importlib.util.spec_from_file_location("gaps_2026_helper",ROOT/"scripts/postaug-support-aug-nov-frozen-policy-recheck.py")
    m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);return m
def scrape(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept-Language":"ja,en;q=0.9"})
    try:
        with urllib.request.urlopen(req,timeout=18) as f:
            html=f.read().decode("utf8","replace")
        soup=BeautifulSoup(html,"html.parser")
        tables=[]
        for table in soup.find_all("table"):
            tables.append([[" ".join(e.stripped_strings) for e in tr.find_all(["th","td"])] for tr in table.find_all("tr")][:16])
        return {"status":"OK","htmlLength":len(html),"tables":tables[:4],"heading":" ".join(soup.stripped_strings)[:550]}
    except Exception as e:return {"status":"ERROR","error":str(e)[:320]}
def main():
    live=helper();live.START="2026-08-01";live.END="2026-11-14";live.MONTHS=("2026-08","2026-09","2026-10","2026-11")
    bydate,mc=live.d1_bundles()
    status_bydate=collections.Counter()
    lacking_url=collections.Counter()
    rows=[]
    for day,bs in bydate.items():
      for b in bs:
        r=b["race"]
        status_bydate[(day,str(r.get("venue")),str(r.get("status")))]+=1
        if not r.get("resultUrl"):lacking_url[(day,str(r.get("status")))]+=1
        rows.append(r)
    pays=collections.defaultdict(set)
    for month in live.MONTHS:
        n=(dt.date.fromisoformat(month+"-01")+dt.timedelta(days=35)).replace(day=1).isoformat()[:7]
        a=live.paged("SELECT race_id raceId,bet_type betType FROM rt_payouts WHERE race_id>=? AND race_id<? ORDER BY race_id",[month+"-",n+"-"])
        for r in a:pays[r["raceId"]].add(r["betType"])
    six={"単勝","ワイド","馬連","馬単","3連複","3連単"}
    missing=[]
    for r in rows:
      found=pays.get(r["raceId"],set()); lacks=sorted(six-found)
      if lacks:missing.append({"raceId":r["raceId"],"day":r["raceDate"],"venue":r["venue"],"raceNo":r["raceNo"],
                "status":r["status"],"missing":lacks,"resultUrlPresent":bool(r.get("resultUrl")),"runners":len(next((b["runners"] for b in bydate[r["raceDate"]] if b["race"]["raceId"]==r["raceId"]),[]))})
    bydate_missing=collections.Counter(x["day"] for x in missing if x["status"]=="finished")
    test_urls=[
      "https://data.keiba-intelligence.jp/jra/results/2026/08/08/chukyo/3/",
      "https://data.keiba-intelligence.jp/jra/results/2026/08/08/niigata/3/",
      "https://data.keiba-intelligence.jp/jra/results/2026/09/19/nakayama/7/",
      "https://data.keiba-intelligence.jp/jra/results/2026/09/19/hanshin/7/"
    ]
    sample={u:scrape(u) for u in test_urls}
    report={"statusesByDate":[{"date":d,"venue":v,"status":status,"n":n} for (d,v,status),n in sorted(status_bydate.items())],
      "withoutResultUrl":str(lacking_url),"missingPayoutCount":len(missing),
      "missingForFinishedByDate":dict(bydate_missing.most_common()),
      "examplesMissing":missing[:60],
      "publicSiteProbes":sample,
      "sourceMonthCounts":mc}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("AUG_NOV_DIAGNOSTIC_SUMMARY",json.dumps({
       "missingPaidRows":len(missing),"missingFinishedByDate":dict(bydate_missing.most_common(10)),
       "publicProbeStatus":{u:x["status"] for u,x in sample.items()},
       "noResultUrls":str(lacking_url)},ensure_ascii=False),flush=True)
    for u,x in sample.items():print("AUG_NOV_PUBLIC_SOURCE_PROBE",json.dumps({"url":u,**x},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
