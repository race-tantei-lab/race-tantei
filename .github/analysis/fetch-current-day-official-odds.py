#!/usr/bin/env python3
import gzip, importlib.util, itertools, json, os, pathlib, sys, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[2]
SOURCE=ROOT/"scripts"/"collect-current-jra-official-odds-live.py"
spec=importlib.util.spec_from_file_location("live_current_odds",SOURCE)
if spec is None or spec.loader is None: raise RuntimeError("IMPORT_FAILED")
live=importlib.util.module_from_spec(spec);sys.modules[spec.name]=live;spec.loader.exec_module(live)
fast=live.base; runtime=fast.runtime; base=runtime.base
A=os.environ["CLOUDFLARE_ACCOUNT_ID"];D=os.environ["CLOUDFLARE_D1_DATABASE_ID"];T=os.environ["CLOUDFLARE_API_TOKEN"]
U=f"https://api.cloudflare.com/client/v4/accounts/{A}/d1/database/{D}/query"
OUT=ROOT/"artifacts"/"current-day-selected-official-odds.jsonl.gz"

def q(sql,p=None):
    req=urllib.request.Request(U,data=json.dumps({"sql":sql,"params":p or []}).encode(),method="POST",
      headers={"Authorization":f"Bearer {T}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r:x=json.loads(r.read().decode())
    if not x.get("success"):raise RuntimeError(x)
    return (x.get("result") or [{}])[0].get("results") or []

def val(low,high):
    lo=float(low);hi=float(high)
    return lo if abs(lo-hi)<1e-12 else [lo,hi]

def parse_combo_rows(rows):
    out={}
    for combo,lo,hi in rows: out[str(combo)]=val(lo,hi)
    return out

sel=q("SELECT state_value v FROM rt_system_state WHERE state_key='final_daily_selection:2026-10-12' LIMIT 1")
ids=[str(x["raceId"]) for x in json.loads(sel[0]["v"]).get("selected",[])]
assert len(ids)==10,ids
ph=",".join("?" for _ in ids)
races=q(f"SELECT race_id raceId,race_date raceDate,venue,race_no raceNo,start_time_utc startTimeUtc,entry_url entryUrl FROM rt_races WHERE race_id IN ({ph}) ORDER BY race_id",ids)
assert len(races)==10,len(races)
records=[];errors=[]
for race in races:
    rid=race["raceId"]; entry=race.get("entryUrl")
    try:
        if not entry: raise RuntimeError("ENTRY_URL_MISSING")
        race_date_digits=str(race["raceDate"]).replace("-",""); race_no=int(race["raceNo"])
        entry_html=runtime.fetch_url(entry)
        actions=[c for c,_ in base.action_links(entry_html) if fast.same_race_link(c,race_date_digits,race_no)]
        seeds=[c for c in actions if c.startswith(fast.TYPE_PREFIX["単勝"])]
        if not seeds: raise RuntimeError("WIN_CNAME_NOT_FOUND")
        win_cname=seeds[0]
        win_page=runtime.fetch_url(base.JRA_ODDS_URL,cname=win_cname,referer=entry)
        horses,win_rows=fast.parse_win(win_page)
        active_rows=q("SELECT horse_no horseNo FROM rt_runners WHERE race_id=? AND COALESCE(runner_status,'active')='active' ORDER BY horse_no",[rid])
        active_horses={int(x["horseNo"]) for x in active_rows}
        horses=[int(h) for h in horses if int(h) in active_horses]
        win_rows=[row for row in win_rows if int(row[0]) in active_horses]
        type_cnames=fast.find_type_cnames(win_page,race_date_digits,race_no)
        maps={"単勝":{str(c):val(lo,hi) for c,lo,hi in win_rows}}
        for bt in ["馬連","ワイド","馬単","3連複","3連単"]:
            cname=type_cnames.get(bt)
            if not cname: raise RuntimeError(f"{bt}_CNAME_NOT_FOUND")
            page=runtime.fetch_url(base.JRA_ODDS_URL,cname=cname,referer=base.JRA_ODDS_URL)
            rows=runtime.parse_odds_rows(page,bt)
            if not rows: raise RuntimeError(f"{bt}_NO_ROWS")
            maps[bt]=parse_combo_rows(rows)
        horses=sorted(int(h) for h in horses)
        pairs=list(itertools.combinations(horses,2)); exactas=list(itertools.permutations(horses,2))
        trios=list(itertools.combinations(horses,3)); tris=list(itertools.permutations(horses,3))
        rec={"raceId":rid,"raceDate":race["raceDate"],"venue":race["venue"],"raceNo":int(race["raceNo"]),"horses":horses,
          "win":[maps["単勝"].get(str(h)) for h in horses],
          "umaren":[maps["馬連"].get("-".join(map(str,sorted(p)))) for p in pairs],
          "wide":[maps["ワイド"].get("-".join(map(str,sorted(p)))) for p in pairs],
          "umatan":[maps["馬単"].get("-".join(map(str,p))) for p in exactas],
          "trio":[maps["3連複"].get("-".join(map(str,sorted(p)))) for p in trios],
          "trifecta":[maps["3連単"].get("-".join(map(str,p))) for p in tris],
          "source":"jra_current_official_odds_after_race"}
        required={"win":len(horses),"umaren":len(pairs),"wide":len(pairs),"umatan":len(exactas),"trio":len(trios),"trifecta":len(tris)}
        present={k:sum(v is not None for v in rec[k]) for k in required}
        rec["expected"]=required;rec["present"]=present
        for k in ("win","umaren","wide"):
            if present[k]!=required[k]:raise RuntimeError(f"INCOMPLETE:{k}:{present[k]}/{required[k]}")
        records.append(rec)
    except Exception as e:
        errors.append({"raceId":rid,"error":f"{type(e).__name__}:{e}"})
OUT.parent.mkdir(exist_ok=True)
with gzip.open(OUT,"wt",encoding="utf-8") as fh:
    for x in records: fh.write(json.dumps(x,ensure_ascii=False,separators=(",",":"))+"\n")
print(json.dumps({"currentDayRequested":10,"success":len(records),"errors":errors,
 "coverage":len(records)/10*100},ensure_ascii=False))
if len(records)!=10: raise RuntimeError(f"CURRENT_DAY_ODDS_INCOMPLETE:{len(records)}/10")
