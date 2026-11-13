#!/usr/bin/env python3
"""Read-only JRA Sep21 cancellation Sep22 replacement data audit."""
import os,json,urllib.request
URL=("https://api.cloudflare.com/client/v4/accounts/"+os.environ["CLOUDFLARE_ACCOUNT_ID"]+
     "/d1/database/"+os.environ["CLOUDFLARE_D1_DATABASE_ID"]+"/query")
def query(sql,parameters=None):
 req=urllib.request.Request(URL,data=json.dumps({"sql":sql,"params":parameters or []}).encode(),
   headers={"Authorization":"Bearer "+os.environ["CLOUDFLARE_API_TOKEN"],"Content-Type":"application/json"},method="POST")
 with urllib.request.urlopen(req,timeout=30) as r:x=json.loads(r.read())
 if not x.get("success"):raise RuntimeError(str(x.get("errors")))
 return x["result"][0]["results"]
def main():
 rows=query("SELECT race_date, venue, status, count(*) n FROM rt_races WHERE race_date>=? AND race_date<=? GROUP BY race_date,venue,status ORDER BY race_date,venue,status",["2026-09-19","2026-09-23"])
 print("JRA_SEP21_CANCEL_22_REPLACEMENT_ROWS",json.dumps(rows,ensure_ascii=False),flush=True)
 meta=query("SELECT race_id,race_date,venue,race_no,status,result_url FROM rt_races WHERE race_date>=? AND race_date<=? AND venue='中山' ORDER BY race_date,race_no LIMIT 60",["2026-09-21","2026-09-22"])
 print("JRA_SEP21_SEP22_RACES",json.dumps(meta,ensure_ascii=False),flush=True)
 results=query("SELECT substr(race_id,1,10) racePrefix,count(*) n FROM rt_payouts WHERE race_id LIKE '2026-09-2%' GROUP BY racePrefix ORDER BY racePrefix")
 print("JRA_SEP21_SEP22_EXISTING_PAYOUTS",json.dumps(results,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
