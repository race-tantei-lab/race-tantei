from pathlib import Path


def replace_once(path, old, new):
    p=Path(path); text=p.read_text(encoding='utf-8')
    count=text.count(old)
    if count!=1:
        raise RuntimeError(f'{path}: expected one match, got {count}: {old[:120]!r}')
    p.write_text(text.replace(old,new,1),encoding='utf-8')
    print('market-fallback',path)

replace_once('scripts/live-recency-learning.py',
'''        valid=[]
        for row in race_rows:
            try: odd=float(row.get('winOdds')); pos=int(row.get('finishPosition'))
            except (TypeError,ValueError): continue
            if not math.isfinite(odd) or odd<=1.0 or pos<=0: continue
            valid.append((row,odd,pos))
        if len(valid)<3: continue
        denom=sum(1.0/odd for _,odd,_ in valid)
        if denom<=0: continue
        first=valid[0][0]''',
'''        valid=[]
        for row in race_rows:
            try: pos=int(row.get('finishPosition'))
            except (TypeError,ValueError): continue
            if pos<=0: continue
            try: odd=float(row.get('winOdds'))
            except (TypeError,ValueError): odd=None
            if odd is not None and (not math.isfinite(odd) or odd<=1.0): odd=None
            valid.append((row,odd,pos))
        if len(valid)<3: continue
        priced=[odd for _,odd,_ in valid if odd is not None]
        denom=sum(1.0/odd for odd in priced) if len(priced)==len(valid) else 0.0
        use_market=denom>0.0 and len(priced)==len(valid)
        first=valid[0][0]''')
replace_once('scripts/live-recency-learning.py',
'''        for row,odd,pos in valid:
            expected=(1.0/odd)/denom; residual=(1.0 if pos==1 else 0.0)-expected''',
'''        for row,odd,pos in valid:
            expected=((1.0/odd)/denom) if use_market else (1.0/field)
            residual=(1.0 if pos==1 else 0.0)-expected''')

replace_once('src/v1/completed-recency-learning.ts',
'''  finishPosition: number; marketProbability: number; fieldSize: number;''',
'''  finishPosition: number; marketProbability: number | null; fieldSize: number;''')
replace_once('src/v1/completed-recency-learning.ts',
'''             CAST(y.finish_position AS INTEGER) AS finishPosition,
             (1.0 / CAST(x.win_odds AS REAL)) /
               SUM(1.0 / CAST(x.win_odds AS REAL)) OVER (PARTITION BY r.race_id) AS marketProbability,
             COUNT(*) OVER (PARTITION BY r.race_id) AS fieldSize
      FROM rt_races r
      JOIN rt_runners x ON x.race_id=r.race_id
      LEFT JOIN rt_results y ON y.race_id=x.race_id AND y.horse_no=x.horse_no
      WHERE r.race_date BETWEEN ? AND ?
        AND r.start_time_utc IS NOT NULL
        AND datetime(r.start_time_utc) < datetime(?)
        AND COALESCE(x.runner_status,'active')='active'
        AND CAST(x.win_odds AS REAL)>1.0''',
'''             CAST(y.finish_position AS INTEGER) AS finishPosition,
             CASE
               WHEN SUM(CASE WHEN CAST(x.win_odds AS REAL)>1.0 THEN 1 ELSE 0 END) OVER (PARTITION BY r.race_id)
                    = COUNT(*) OVER (PARTITION BY r.race_id)
               THEN (1.0 / CAST(x.win_odds AS REAL)) /
                    SUM(1.0 / CAST(x.win_odds AS REAL)) OVER (PARTITION BY r.race_id)
               ELSE 1.0 / COUNT(*) OVER (PARTITION BY r.race_id)
             END AS marketProbability,
             COUNT(*) OVER (PARTITION BY r.race_id) AS fieldSize
      FROM rt_races r
      JOIN rt_runners x ON x.race_id=r.race_id
      JOIN rt_results y ON y.race_id=x.race_id AND y.horse_no=x.horse_no
      WHERE r.race_date BETWEEN ? AND ?
        AND r.start_time_utc IS NOT NULL
        AND datetime(r.start_time_utc) < datetime(?)
        AND COALESCE(x.runner_status,'active')='active'
        AND y.finish_position IS NOT NULL
        AND CAST(y.finish_position AS INTEGER)>0''')

print('CANONICAL_MARKET_FALLBACK_APPLIED')
