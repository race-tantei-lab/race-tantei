from pathlib import Path

p=Path('src/v1/completed-recency-learning.ts')
text=p.read_text(encoding='utf-8')
old="""      OR (raceDate=? AND venue=? AND COALESCE(surface,'')=?)
    )
    ORDER BY startTimeUtc,raceId,horseNo
  `).bind(startDate(race.raceDate), race.raceDate, cutoffUtc, JSON.stringify(horses), JSON.stringify(jockeys), JSON.stringify(trainers), race.raceDate, race.venue, String(race.surface || \"\")).all<RunnerHistoryRow>();"""
new="""      OR (venue=? AND COALESCE(surface,'')=?)
    )
    ORDER BY startTimeUtc,raceId,horseNo
  `).bind(startDate(race.raceDate), race.raceDate, cutoffUtc, JSON.stringify(horses), JSON.stringify(jockeys), JSON.stringify(trainers), race.venue, String(race.surface || \"\")).all<RunnerHistoryRow>();"""
if text.count(old)!=1:
    raise RuntimeError(f'expected exact Worker draw-scope block once, got {text.count(old)}')
p.write_text(text.replace(old,new,1),encoding='utf-8')
print('WORKER_DRAW_RECENCY_30D_PARITY_APPLIED')
