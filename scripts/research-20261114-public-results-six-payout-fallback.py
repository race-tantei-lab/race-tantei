#!/usr/bin/env python3
"""2026 JRA result cash supplement from public race-result archive (read-only).

Required six JRA markets are reconstructed from independently hosted
race-result pages. Every payout agrees with an existing D1 number where
present; conflicts fail closed. This is a third-party confirmation, not
equivalent to an authenticated JRA payout ledger.
"""
from __future__ import annotations
import collections, json, re, urllib.request, time, sys
from bs4 import BeautifulSoup
TYPES=("単勝","ワイド","馬連","馬単","3連複","3連単")
UNORDERED={"ワイド","馬連","3連複"}
SLUG={"札幌":"sapporo","函館":"hakodate","福島":"fukushima",
  "新潟":"niigata","東京":"tokyo","中山":"nakayama","中京":"chukyo",
  "京都":"kyoto","阪神":"hanshin","小倉":"kokura"}
def result_url(race):
    venue=str(race.get("venue") or "")
    if venue not in SLUG:
        raise RuntimeError("NON_JRA_VENUE_IN_PUBLIC_SOURCE:"+venue)
    date=str(race.get("raceDate") or "")
    no=int(race["raceNo"])
    if not re.fullmatch(r"2026-(0[89]|1[01])-\d\d",date) or not 1<=no<=12:
        raise RuntimeError("RACE_IDENTITY_OUTSIDE_PUBLIC_SOURCE")
    return "https://data.keiba-intelligence.jp/jra/results/"+date.replace("-","/")+"/"+SLUG[venue]+"/"+str(no)+"/"
def num(s):
    a=re.findall(r"\d+",str(s).replace(",",""))
    return tuple(map(int,a))
def to_jra_type(s):
    return str(s).replace("三連","3連").strip()
def parse_public(html,race):
    soup=BeautifulSoup(html,"html.parser")
    date=str(race["raceDate"])
    venue=str(race["venue"])
    no=int(race["raceNo"])
    header=soup.find("h1")
    label=header.get_text(" ",strip=True) if header else ""
    page=soup.get_text(" ",strip=True)
    jdate=f"{date[:4]}年{date[5:7]}月{date[8:10]}日"
    if jdate not in page or venue+"競馬" not in page or f"第{no}R" not in page:
        raise RuntimeError("PUBLIC_RACE_DATE_VENUE_NUMBER_MISMATCH:"+label[:100])
    try:
        section=page.split("💰 払戻金",1)[1].split("全券種の払戻金を見る",1)[0]
    except IndexError:
        raise RuntimeError("PUBLIC_WIN_EXACTA_TRIFECTA_SECTION_MISSING")
    data={k:{} for k in TYPES}
    groups=[
        ("単勝", r"単勝\s*(\d+)番\s*([\d,]+)円"),
        ("馬単", r"馬単\s*(\d+)-(\d+)\s*([\d,]+)円"),
        ("3連単", r"(?:三連単|3連単)\s*(\d+)-(\d+)-(\d+)\s*([\d,]+)円"),
    ]
    for typ,pat in groups:
        match=re.search(pat,section)
        if not match:raise RuntimeError("PUBLIC_TOP_PAYOUT_NOT_FOUND:"+typ+":"+section[:220])
        nums=tuple(int(x) for x in match.groups()[:-1])
        yen=int(match.group(match.lastindex).replace(",",""))
        if yen<100 or yen%10:raise RuntimeError("INVALID_PUBLIC_TOP_PAYOUT")
        data[typ][nums]=yen
    table=None
    for t in soup.find_all("table"):
        row=t.find("tr")
        if not row:continue
        head=" ".join(x.get_text(" ",strip=True) for x in row.find_all(["th","td"]))
        if "券種" in head and "組番" in head and "払戻金" in head:
            table=t;break
    if table is None:raise RuntimeError("PUBLIC_PAYBACK_TABLE_NOT_FOUND")
    for tr in table.find_all("tr")[1:]:
        cells=[c.get_text(" ",strip=True) for c in tr.find_all(["td","th"])]
        if len(cells)<3:continue
        typ=to_jra_type(cells[0])
        if typ not in TYPES:continue
        combo=num(cells[1]); n=1 if typ=="単勝" else 3 if typ in ("3連複","3連単") else 2
        if len(combo)!=n:raise RuntimeError("INVALID_PUBLIC_PAYOUT_COMBINATION:"+typ)
        if typ in UNORDERED:combo=tuple(sorted(combo))
        yen_digits=re.findall(r"\d+",cells[2].replace(",",""))
        if not yen_digits:raise RuntimeError("INVALID_PUBLIC_PAYOUT_AMOUNT")
        yen=int(yen_digits[0])
        if yen<100 or yen%10:raise RuntimeError("INVALID_PUBLIC_PAYOUT_VALUE")
        old=data[typ].get(combo)
        if old is not None and old!=yen:raise RuntimeError("INCONSISTENT_PAYOUT_IN_PUBLIC_PAGE")
        data[typ][combo]=yen
    if any(not x for x in data.values()):
        raise RuntimeError("PUBLIC_MISSING_SIX_SETTLEMENT_TYPES")
    return data
def fetch_public(race,attempts=2):
    url=result_url(race)
    err=None
    for k in range(attempts):
        try:
            req=urllib.request.Request(url,headers={
               "User-Agent":"Mozilla/5.0 (compatible; RaceTanteiResearch/1.0)",
               "Accept":"text/html","Accept-Language":"ja-JP,ja;q=0.9"})
            with urllib.request.urlopen(req,timeout=18) as f:
                html=f.read().decode("utf-8","replace")
            payouts=parse_public(html,race)
            return payouts,{"url":url,"source":"third-party public results site","htmlBytes":len(html)}
        except Exception as ex:
            err=ex
            if k+1<attempts:time.sleep(.5)
    raise RuntimeError("PUBLIC_RESULT_FETCH_FAILED:"+str(err)[:170])
def integrate(d1_payment_lists,public_lists,rid):
    if len(d1_payment_lists)!=6:raise RuntimeError("D1_MARKET_ALIGNMENT_BROKEN")
    merged=[]
    for m,typ in enumerate(TYPES):
        old=d1_payment_lists[m].copy()
        for combo,amount in public_lists[typ].items():
            if combo in old and old[combo]!=amount:
                raise RuntimeError("PAYOUT_SOURCE_CONFLICT_"+str(rid)+"_"+typ+"_"+str(combo))
            old[combo]=amount
        if not old:raise RuntimeError("SIX_PAYOUT_TYPES_STILL_MISSING_"+str(rid)+"_"+typ)
        merged.append(old)
    return merged
def self_test():
    html="""<html><h1>2026年08月08日 中京競馬 第3R</h1><h2>💰 払戻金</h2>
    <p>単勝 2番 210円（2番人気）</p><p>馬単 2-8 640円</p><p>三連単 2-8-10 8,730円</p>
    <h3>全券種の払戻金を見る</h3>
    <table><tr><th>券種</th><th>組番</th><th>払戻金</th></tr>
    <tr><td>馬連</td><td>2-8</td><td>510円</td></tr>
    <tr><td>ワイド</td><td>2-8</td><td>200円</td></tr>
    <tr><td>三連複</td><td>2-8-10</td><td>1200円</td></tr></table></html>"""
    x=parse_public(html,{"raceDate":"2026-08-08","venue":"中京","raceNo":3})
    assert x["単勝"][(2,)]==210 and x["3連単"][(2,8,10)]==8730
    assert x["馬連"][(2,8)]==510
    assert integrate([{} for _ in TYPES],x,"test")[0][(2,)]==210
    print("PUBLIC_SIX_PAYOUT_FALLBACK_SELFTEST_OK",flush=True)
if __name__=="__main__":
    self_test()
    if "--live-probe" in sys.argv:
        for day,venue,no in (("2026-08-08","中京",3),
                             ("2026-08-08","新潟",3),
                             ("2026-09-19","中山",7)):
            d,source=fetch_public({"raceDate":day,"venue":venue,"raceNo":no})
            print("PUBLIC_SIX_MARKET_REAL_RESULT_PROBE",json.dumps({
                "date":day,"venue":venue,"raceNo":no,
                "marketCount":sum(bool(z) for z in d.values()),
                "markets":{k:len(v) for k,v in d.items()},
                "amounts":{k:list(v.values())[:1] for k,v in d.items()},
                "sourceUrl":source["url"]},ensure_ascii=False),flush=True)
            assert all(d.values())
