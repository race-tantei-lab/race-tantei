#!/usr/bin/env python3
"""Read-only exact JRA CNAME identity audit 2026 Sep19/Sep21/Sep22."""
import importlib.util,json,re,sys,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def helper():
    s=importlib.util.spec_from_file_location("sep19_d1_read",ROOT/"scripts/postaug-support-aug-nov-frozen-policy-recheck.py")
    m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);return m
def main():
    d1=helper()
    dates=["2026-08-09","2026-09-19","2026-09-21","2026-09-22"]
    for day in dates:
        rows=d1.d1_query("""SELECT race_id raceId,race_date raceDate,venue,
                  race_no raceNo,meeting_no meetingNo,meeting_day meetingDay,
                  result_url resultUrl,status
                  FROM rt_races WHERE race_date=? ORDER BY venue,race_no LIMIT 60""",[day])
        items=[]
        for r in rows:
            if day=="2026-08-09" and r.get("raceNo") not in (9,10,11,12):continue
            url=urllib.parse.unquote(str(r.get("resultUrl") or ""))
            m=re.search(r"(?:pw|sw)01sde(?:10|01)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})",url,re.I)
            items.append({"raceId":r["raceId"],"venue":r["venue"],"number":r["raceNo"],"status":r["status"],
                "meeting":r["meetingNo"],"meetingDay":r["meetingDay"],
                "resultCnameDate":m.group(6) if m else None,
                "resultCnameRace":m.group(5) if m else None,
                "cname":m.group(0) if m else None,
                "urlPrefix":url[:145]})
        print("EXACT_RACE_IDENTITY_DIAGNOSTIC",json.dumps({"date":day,"count":len(items),"races":items},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
