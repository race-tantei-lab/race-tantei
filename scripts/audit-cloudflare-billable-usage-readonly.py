#!/usr/bin/env python3
"""One-off READ ONLY Cloudflare billing-metric audit. No D1 SQL, no writes.
Query only Cloudflare public API metadata (GET) and GraphQL Analytics aggregates.
No token / raw responses / personally identifying account details are printed.
"""
import os,json,urllib.request,datetime,sys
API="https://api.cloudflare.com/client/v4"
token=os.getenv("CLOUDFLARE_API_TOKEN")
account=os.getenv("CLOUDFLARE_ACCOUNT_ID")
if not token or not account:
    print("CF_BILLING_AUDIT_ERROR",json.dumps({"error":"MISSING_TOKEN_OR_ACCOUNT"}));sys.exit(1)
def get(url,data=None):
    req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,
      "Content-Type":"application/json","Accept":"application/json"},
      data=json.dumps(data).encode("utf8") if data is not None else None)
    try:
      with urllib.request.urlopen(req,timeout=45) as resp:return json.load(resp)
    except Exception as e:
      return {"errors":[{"message":type(e).__name__,"http":getattr(e,"code",None)}]}
def gql(query,vars):
    return get(API+"/graphql",{"query":query,"variables":vars})
def errmsg(payload):
    return [str(x.get("message","unknown"))[:200] for x in payload.get("errors",[])][:3]
start="2026-11-01"
today=datetime.datetime.now(datetime.timezone.utc).date().isoformat()
result={"start":start,"through":today,"mode":"cloudflare_metadata_and_analytics_read_only",
        "billingInvoiceChecked":False}
# 1) D1 read/write rows account-wide. Date grouped, no raw private query text.
query="""query($accountTag: string!, $start: Date, $end: Date) {
  viewer { accounts(filter: {accountTag: $accountTag}) {
    d1AnalyticsAdaptiveGroups(limit: 3000,
      filter: {date_geq:$start, date_leq:$end},orderBy:[date_DESC]) {
      dimensions {databaseId date}
      sum {rowsRead rowsWritten readQueries writeQueries}
    }
  } }
}"""
r=gql(query,{"accountTag":account,"start":start,"end":today})
if r.get("errors"):result["d1Error"]=errmsg(r)
else:
  accounts=r.get("data",{}).get("viewer",{}).get("accounts",[]) or []
  groups=[g for a in accounts for g in a.get("d1AnalyticsAdaptiveGroups",[]) or []]
  bydb={}
  for g in groups:
    d=g.get("dimensions") or {}; s=g.get("sum") or {}
    db=d.get("databaseId","unknown")
    obj=bydb.setdefault(db,{"rowsRead":0,"rowsWritten":0,"readQueries":0,"writeQueries":0,"days":0})
    for key in ("rowsRead","rowsWritten","readQueries","writeQueries"):
      obj[key]+=int(s.get(key) or 0)
    obj["days"]+=1
  # No raw D1 database UUIDs printed: identify the targeted race-tantei
  # DB by a stable "race_tantei" indicator, other dbs aggregated as "other".
  target=os.getenv("CLOUDFLARE_D1_DATABASE_ID","")
  tot={k:sum(o[k] for o in bydb.values()) for k in ("rowsRead","rowsWritten","readQueries","writeQueries")}
  result.update(d1GroupCount=len(groups),d1Totals=tot,
      raceD1=bydb.get(target),otherDatabaseCount=sum(db!=target for db in bydb))
# 2) D1 storage from read-only REST database metadata; do not run SQL.
data=get(API+"/accounts/"+account+"/d1/database?per_page=100")
if data.get("errors"):
   result["d1StorageError"]=errmsg(data)
else:
   databases=data.get("result",[]) or []
   sizes=[int(d.get("file_size") or 0) for d in databases]
   result["d1Storage"]={"dbs":len(databases),"totalBytes":sum(sizes),
        "targetBytes":next((int(d.get("file_size") or 0) for d in databases
              if d.get("uuid")==os.getenv("CLOUDFLARE_D1_DATABASE_ID")),None),
        "allSizesReported":all("file_size" in d for d in databases)}
# 3) Worker request counts account-wide, no script names printed.
qworker="""query($accountTag:string!,$from:Time!,$to:Time!){
 viewer{accounts(filter:{accountTag:$accountTag}){
 workersInvocationsAdaptive(limit:10000,
   filter:{datetime_geq:$from,datetime_leq:$to}){
      sum{requests errors}
   }
 }}
}"""
w=gql(qworker,{"accountTag":account,
      "from":start+"T00:00:00Z","to":today+"T23:59:59Z"})
if w.get("errors"):result["workersError"]=errmsg(w)
else:
    vals=[g.get("sum",{}) for a in w.get("data",{}).get("viewer",{}).get("accounts",[]) or []
            for g in a.get("workersInvocationsAdaptive",[]) or []]
    result["workersTotals"]={"rows":len(vals),
         "requests":sum(int(o.get("requests") or 0) for o in vals),
         "errors":sum(int(o.get("errors") or 0) for o in vals),
         "mayBeTruncated":len(vals)>=10000}
print("CLOUDFLARE_BILLABLE_USAGE_AUDIT",json.dumps(result,ensure_ascii=False,sort_keys=True),flush=True)
