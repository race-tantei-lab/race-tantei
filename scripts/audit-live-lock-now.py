#!/usr/bin/env python3
import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta

ACCOUNT_ID=os.environ['CLOUDFLARE_ACCOUNT_ID']
DATABASE_ID=os.environ['CLOUDFLARE_D1_DATABASE_ID']
TOKEN=os.environ['CLOUDFLARE_API_TOKEN']
URL=f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query'
DATE=os.environ.get('AUDIT_RACE_DATE','2026-08-16')

def q(sql,params=None):
    req=urllib.request.Request(URL,data=json.dumps({'sql':sql,'params':params or []},ensure_ascii=False).encode(),method='POST',headers={'Authorization':f'Bearer {TOKEN}','Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=120) as r: body=json.loads(r.read().decode())
    if not body.get('success'): raise RuntimeError(body)
    result=body.get('result') or []
    return (result[0].get('results') or []) if result else []

sel=q('SELECT state_value AS value,updated_at AS updatedAt FROM rt_system_state WHERE state_key=? LIMIT 1',[f'final_daily_selection:{DATE}'])
if not sel: raise SystemExit('SELECTION_MISSING')
payload=json.loads(sel[0]['value'])
ids=[str(x.get('raceId') or '') for x in payload.get('selected',[]) if x.get('raceId')]
if not ids: raise SystemExit('SELECTION_EMPTY')
ph=','.join('?' for _ in ids)
races=q(f'''SELECT r.race_id AS raceId,r.venue,r.race_no AS raceNo,r.start_time_jst AS startTimeJst,r.start_time_utc AS startTimeUtc,r.entry_url AS entryUrl,
COUNT(b.id) AS betRows,COUNT(DISTINCT b.course) AS courses,COUNT(DISTINCT b.bet_type) AS betTypes,MIN(b.locked_at) AS firstLockedAt,MAX(b.locked_at) AS lastLockedAt
FROM rt_races r LEFT JOIN rt_public_bets b ON b.race_id=r.race_id
WHERE r.race_id IN ({ph}) GROUP BY r.race_id ORDER BY datetime(r.start_time_utc),r.race_id''',ids)
now=datetime.now(timezone.utc)
for r in races:
    start=datetime.fromisoformat(str(r['startTimeUtc']).replace('Z','+00:00'))
    r['secondsToStart']=int((start-now).total_seconds())
    r['canonicalEntryUrl']=('/JRADB/accessD.html?CNAME=' in str(r.get('entryUrl') or ''))
    r['completeSixRows']=(int(r.get('betRows') or 0)==6 and int(r.get('courses') or 0)==3 and int(r.get('betTypes') or 0)==2)

states=q("SELECT state_key AS stateKey,state_value AS value,updated_at AS updatedAt FROM rt_system_state WHERE state_key LIKE 'worker_live_%' AND (state_key=? OR state_key LIKE ?) ORDER BY state_key",[f'worker_live_lock:{DATE}','worker_live_preview:%'])
worker_audit=None
preview=[]
for row in states:
    key=str(row['stateKey'])
    try: value=json.loads(row['value'])
    except Exception: value=row['value']
    if key==f'worker_live_lock:{DATE}': worker_audit={'updatedAt':row['updatedAt'],'value':value}
    elif key.startswith('worker_live_preview:'):
        rid=key.split(':',1)[1]
        if rid in ids:
            snaps=value.get('snapshots',[]) if isinstance(value,dict) else []
            preview.append({'raceId':rid,'updatedAt':row['updatedAt'],'snapshots':len(snaps),'latestGeneratedAt':snaps[0].get('generatedAt') if snaps else None,'latestOddsFetchedAt':snaps[0].get('oddsFetchedAt') if snaps else None})

out={'checkedAtUtc':now.isoformat(),'checkedAtJst':now.astimezone(timezone(timedelta(hours=9))).isoformat(),'date':DATE,'selectionUpdatedAt':sel[0]['updatedAt'],'selectedRaceCount':len(ids),'races':races,'workerAudit':worker_audit,'previews':preview}
print(json.dumps(out,ensure_ascii=False,indent=2))

future=[r for r in races if r['secondsToStart']>0]
overdue=[r for r in future if r['secondsToStart']<=15*60 and not r['completeSixRows']]
print('LIVE_LOCK_AUDIT_SUMMARY',json.dumps({'future':len(future),'overdueMissing':[r['raceId'] for r in overdue],'completeRaces':[r['raceId'] for r in races if r['completeSixRows']],'previewRaces':[r['raceId'] for r in preview]},ensure_ascii=False))
