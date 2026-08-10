#!/usr/bin/env python3
import html
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; RaceTanteiResearch/1.0; +https://www.jra.go.jp/)"
ODDS_URL = "https://www.jra.go.jp/JRADB/accessO.html"
TARGETS = [
    ("2026-08-01-chukyo-03", "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1007202602030320260801%2F33"),
    ("2026-08-02-chukyo-02", "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0107202602040220260802%2FCF"),
    ("2026-08-09-chukyo-01-control", "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0107202602060120260809%2F9E"),
]


def decode(raw, content_type):
    for enc in ("cp932", "shift_jis", "utf-8"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", "replace")


def request(opener, url, cname=None, referer=None):
    data = urllib.parse.urlencode({"cname": cname}).encode("ascii") if cname else None
    headers = {"User-Agent": UA, "Accept-Language": "ja-JP,ja;q=0.9", "Referer": referer or "https://www.jra.go.jp/"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with opener.open(req, timeout=40) as resp:
        raw = resp.read()
        return decode(raw, resp.headers.get("content-type")), resp.geturl()


def cnames(text):
    clean = html.unescape(text).replace("\\u0026", "&").replace("\\/", "/")
    found = []
    for pattern in (r"(?:CNAME=|cname=)([^\"'&<>\s)]+)", r"((?:pw|sw)15[0-9A-Za-z]+[^\"'<>\s,)]+)"):
        for m in re.finditer(pattern, clean, re.I):
            value = urllib.parse.unquote(m.group(1)).strip()
            if value.lower().startswith(("pw15", "sw15")):
                found.append(value)
    return list(dict.fromkeys(found))


def summary(text):
    values = cnames(text)
    return {
        "bytes": len(text),
        "oddsCnames": [v for v in values if re.match(r"^(?:pw|sw)15[1-8]ou", v, re.I)][:40],
        "all15Cnames": values[:80],
        "hasDate0801": "20260801" in text,
        "hasDate0802": "20260802" in text,
        "hasDate0809": "20260809" in text,
    }


rows = []
for name, result_url in TARGETS:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    result_html, result_final = request(opener, result_url)
    odds_index_html, odds_index_final = request(opener, ODDS_URL, cname="pw15oli00/6D", referer=result_url)
    rows.append({
        "name": name,
        "result": summary(result_html),
        "oddsIndex": summary(odds_index_html),
        "cookies": [{"name": c.name, "domain": c.domain, "path": c.path} for c in jar],
        "resultFinal": result_final,
        "oddsIndexFinal": odds_index_final,
    })

print(json.dumps({
    "purpose": "research_only_session_aware_jra_odds_diagnostic",
    "rows": rows,
    "syntheticOddsUsed": False,
    "productionDatabaseWritten": False,
    "productionModelChanged": False,
}, ensure_ascii=False, indent=2))
