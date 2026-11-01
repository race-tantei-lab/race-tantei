import os,json,urllib.request,datetime
API="https://api.cloudflare.com/client/v4/accounts/3c6d1826b573b2e68cb13ec37e9e8ade/d1/database/949b5e8b-d1a4-4c4e-80d1-d031afdc03de/query"
def run(sql,params=()):
    req=urllib.request.Request(API,data=json.dumps({"sql":sql,"params":list(params)}).encode(),method="POST",headers={"Authorization":"Bearer "+os.environ["CLOUDFLARE_API_TOKEN"],"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=40) as x:d=json.load(x)
    if not d.get("success"):raise RuntimeError(d.get("errors"))
    a=d["result"][0]
    return a.get("results") or [], int(a.get("meta",{}).get("rows_read")or 0)
sel,_=run("SELECT r.race_id AS raceId,r.race_date AS raceDate,r.start_time_utc AS startUtc FROM rt_races r WHERE r.race_date='2026-11-01' AND r.start_time_utc IS NOT NULL ORDER BY r.race_no LIMIT 2")
meta,_=run("SELECT key,value FROM rt_ml_feature_meta")
thru=dict((x["key"],x["value"]) for x in meta).get("throughDate","2026-10-29")
print("SAMPLE_METADATA",json.dumps({"throughDate":thru,"races":sel},ensure_ascii=False))
old="""SELECT DISTINCT ra.race_id AS raceId FROM rt_races ra JOIN rt_runners ru ON ru.race_id=ra.race_id
WHERE ra.race_date>? AND (ra.race_date<? OR (ra.race_date=? AND ra.start_time_utc IS NOT NULL AND datetime(ra.start_time_utc)<datetime(?) AND EXISTS (SELECT 1 FROM rt_results rr WHERE rr.race_id=ra.race_id AND rr.finish_position IS NOT NULL)))
AND (ru.horse_name IN (SELECT value FROM json_each(?)) OR COALESCE(ru.jockey,'') IN (SELECT value FROM json_each(?)) OR COALESCE(ru.trainer,'') IN (SELECT value FROM json_each(?)))
ORDER BY ra.race_date,ra.race_id"""
new="""WITH matches AS (
  SELECT race_id FROM rt_runners INDEXED BY rt_idx_runners_horse WHERE horse_name IN (SELECT value FROM json_each(?))
  UNION SELECT race_id FROM rt_runners INDEXED BY rt_idx_runners_jockey WHERE jockey IN (SELECT value FROM json_each(?))
  UNION SELECT race_id FROM rt_runners INDEXED BY rt_idx_runners_jockey WHERE jockey IS NULL AND EXISTS(SELECT 1 FROM json_each(?) WHERE value='')
  UNION SELECT race_id FROM rt_runners INDEXED BY rt_idx_runners_trainer WHERE trainer IN (SELECT value FROM json_each(?))
  UNION SELECT race_id FROM rt_runners INDEXED BY rt_idx_runners_trainer WHERE trainer IS NULL AND EXISTS(SELECT 1 FROM json_each(?) WHERE value='')
)
SELECT ra.race_id AS raceId FROM matches m JOIN rt_races ra ON ra.race_id=m.race_id
WHERE ra.race_date>? AND (ra.race_date<? OR (ra.race_date=? AND ra.start_time_utc IS NOT NULL AND datetime(ra.start_time_utc)<datetime(?) AND EXISTS (SELECT 1 FROM rt_results rr WHERE rr.race_id=ra.race_id AND rr.finish_position IS NOT NULL)))
ORDER BY ra.race_date,ra.race_id"""
for race in sel:
 rows,_=run("SELECT horse_name AS horseName,jockey,trainer FROM rt_runners WHERE race_id=? ORDER BY horse_no",(race["raceId"],))
 horses=json.dumps(list(dict.fromkeys(x["horseName"] for x in rows if x["horseName"])),ensure_ascii=False)
 jockeys=json.dumps(list(dict.fromkeys(x["jockey"] or "" for x in rows)),ensure_ascii=False)
 trainers=json.dumps(list(dict.fromkeys(x["trainer"] or "" for x in rows)),ensure_ascii=False)
 date=race["raceDate"];cutoff=race["startUtc"]
 o,oread=run(old,(thru,date,date,cutoff,horses,jockeys,trainers))
 n,nread=run(new,(horses,jockeys,jockeys,trainers,trainers,thru,date,date,cutoff))
 a=[z["raceId"] for z in o];b=[z["raceId"] for z in n]
 print("FEATURE_PARITY",json.dumps({"race":race["raceId"],"oldCount":len(a),"newCount":len(b),"same":a==b,"oldRowsRead":oread,"newRowsRead":nread,"readReductionPct":round((1-nread/max(oread,1))*100,1),"onlyOld":list(set(a)-set(b))[:5],"onlyNew":list(set(b)-set(a))[:5]},ensure_ascii=False))
 if a!=b:raise RuntimeError("RESULT_MISMATCH")


# The 30-day recency extraction must keep its full-window partitions unchanged:
# the candidate race set is index-driven, scoring query and final ordering are identical.
old_recency="""WITH candidate_races AS (
      SELECT r.race_id
      FROM rt_races r
      WHERE r.race_date BETWEEN ? AND ?
        AND r.start_time_utc IS NOT NULL
        AND datetime(r.start_time_utc) < datetime(?)
        AND (
          (r.venue=? AND COALESCE(r.surface,'')=?)
          OR EXISTS (
            SELECT 1 FROM rt_runners z WHERE z.race_id=r.race_id
              AND COALESCE(z.runner_status,'active')='active'
              AND (z.horse_name IN (SELECT value FROM json_each(?))
                OR COALESCE(z.jockey,'') IN (SELECT value FROM json_each(?))
                OR COALESCE(z.trainer,'') IN (SELECT value FROM json_each(?)))
          )
        )
    ),
    scored AS (
      SELECT r.race_id AS raceId,r.race_date AS raceDate,r.start_time_utc AS startTimeUtc,r.venue,r.surface,
             x.horse_no AS horseNo,x.horse_name AS horseName,x.jockey,x.trainer,
             CAST(y.finish_position AS INTEGER) AS finishPosition,
             CASE WHEN SUM(CASE WHEN CAST(x.win_odds AS REAL)>1.0 THEN 1 ELSE 0 END) OVER (PARTITION BY r.race_id)
                    = COUNT(*) OVER (PARTITION BY r.race_id)
               THEN (1.0 / CAST(x.win_odds AS REAL)) /
                    SUM(1.0 / CAST(x.win_odds AS REAL)) OVER (PARTITION BY r.race_id)
               ELSE 1.0 / COUNT(*) OVER (PARTITION BY r.race_id) END AS marketProbability,
             COUNT(*) OVER (PARTITION BY r.race_id) AS fieldSize
      FROM candidate_races c
      JOIN rt_races r ON r.race_id=c.race_id
      JOIN rt_runners x ON x.race_id=r.race_id
      JOIN rt_results y ON y.race_id=x.race_id AND y.horse_no=x.horse_no
      WHERE COALESCE(x.runner_status,'active')='active'
        AND y.finish_position IS NOT NULL AND CAST(y.finish_position AS INTEGER)>0
    )
    SELECT * FROM scored
    WHERE finishPosition>0 AND (
      horseName IN (SELECT value FROM json_each(?))
      OR COALESCE(jockey,'') IN (SELECT value FROM json_each(?))
      OR COALESCE(trainer,'') IN (SELECT value FROM json_each(?))
      OR (venue=? AND COALESCE(surface,'')=?)
    )
    ORDER BY startTimeUtc,raceId,horseNo"""
new_recency=old_recency.replace(old_recency[old_recency.index("WITH candidate_races AS ("):old_recency.index("    scored AS (")],"""WITH matched_races AS (
      SELECT race_id FROM rt_runners INDEXED BY rt_idx_runners_horse WHERE COALESCE(runner_status,'active')='active' AND horse_name IN (SELECT value FROM json_each(?))
      UNION SELECT race_id FROM rt_runners INDEXED BY rt_idx_runners_jockey WHERE COALESCE(runner_status,'active')='active' AND jockey IN (SELECT value FROM json_each(?))
      UNION SELECT race_id FROM rt_runners INDEXED BY rt_idx_runners_jockey WHERE COALESCE(runner_status,'active')='active' AND jockey IS NULL AND EXISTS(SELECT 1 FROM json_each(?) WHERE value='')
      UNION SELECT race_id FROM rt_runners INDEXED BY rt_idx_runners_trainer WHERE COALESCE(runner_status,'active')='active' AND trainer IN (SELECT value FROM json_each(?))
      UNION SELECT race_id FROM rt_runners INDEXED BY rt_idx_runners_trainer WHERE COALESCE(runner_status,'active')='active' AND trainer IS NULL AND EXISTS(SELECT 1 FROM json_each(?) WHERE value='')
    ),
    candidate_races AS (
      SELECT r.race_id FROM rt_races r
      WHERE r.race_date BETWEEN ? AND ? AND r.start_time_utc IS NOT NULL AND datetime(r.start_time_utc)<datetime(?)
        AND r.venue=? AND COALESCE(r.surface,'')=?
      UNION
      SELECT r.race_id FROM matched_races m JOIN rt_races r ON r.race_id=m.race_id
      WHERE r.race_date BETWEEN ? AND ? AND r.start_time_utc IS NOT NULL AND datetime(r.start_time_utc)<datetime(?)
    ),
""")
from datetime import date,timedelta
for race in sel:
 rows,_=run("SELECT horse_name AS horseName,jockey,trainer FROM rt_runners WHERE race_id=? ORDER BY horse_no",(race["raceId"],))
 horses=json.dumps(list(dict.fromkeys(x["horseName"] for x in rows if x["horseName"])),ensure_ascii=False)
 jockeys=json.dumps(list(dict.fromkeys(x["jockey"] or "" for x in rows)),ensure_ascii=False)
 trainers=json.dumps(list(dict.fromkeys(x["trainer"] or "" for x in rows)),ensure_ascii=False)
 date_=race["raceDate"]
 start=(date.fromisoformat(date_)-timedelta(days=30)).isoformat()
 cutoff=race["startUtc"]
 venue=race["raceId"].split("-")[3]
 v={"tokyo":"東京","kyoto":"京都","hanshin":"阪神","nakayama":"中山","chukyo":"中京"}.get(venue,venue)
 sur=run("SELECT surface FROM rt_races WHERE race_id=?",(race["raceId"],))[0][0]["surface"] or ""
 o,oread=run(old_recency,(start,date_,cutoff,v,sur,horses,jockeys,trainers,horses,jockeys,trainers,v,sur))
 n,nread=run(new_recency,(horses,jockeys,jockeys,trainers,trainers,start,date_,cutoff,v,sur,start,date_,cutoff,horses,jockeys,trainers,v,sur))
 eq=o==n
 print("RECENCY_PARITY",json.dumps({"race":race["raceId"],"oldCount":len(o),"newCount":len(n),"same":eq,"oldRowsRead":oread,"newRowsRead":nread,"readReductionPct":round((1-nread/max(oread,1))*100,1)},ensure_ascii=False))
 if not eq:raise RuntimeError("RECENCY_RESULT_MISMATCH")
