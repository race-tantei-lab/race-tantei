#!/usr/bin/env python3
"""Read-only archived JRA final win odds coverage (NOT T15)."""
import gzip,glob,json,math
from collections import Counter
for year in (2023,2024,2025,2026):
    total=valid=0
    races=full=0
    months=Counter()
    for path in sorted(glob.glob(f"data/ten-year-runners/{year}-*.json.gz")):
        with gzip.open(path,"rt",encoding="utf-8") as fh:
            rows=json.load(fh)
        for rid,rs in rows:
            good=0
            for row in rs:
                val=row[10]
                try:
                    odds=float(val)
                    is_good=math.isfinite(odds) and 1<=odds<=1000
                except (TypeError,ValueError):
                    is_good=False
                good+=int(is_good);valid+=int(is_good);total+=1
            races+=1
            full+=int(good==len(rs))
            months[path.split("/")[-1][:7]]+=1
    if not total:continue
    print("HISTORICAL_FINAL_ODDS_COVERAGE_NOT_T15",
      json.dumps({"year":year,"runners":total,"validRunners":valid,
        "validRunnerPct":round(100*valid/total,2),
        "races":races,"fullRaces":full,"fullRacePct":round(100*full/races,2),
        "months":dict(months)},ensure_ascii=False),flush=True)
