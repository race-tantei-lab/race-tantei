#!/usr/bin/env python3
import collections
import datetime as dt
import math

HISTORY_DAYS = 30
HALF_LIFE_DAYS = 7.0
DATE_MULTIPLIERS = {0: 6.0, 1: 4.0}
DAYS_2_TO_7_MULTIPLIER = 2.0
OLDER_MULTIPLIER = 1.0
RUNNER_FACTOR_MIN = 0.50
RUNNER_FACTOR_MAX = 2.00
BET_FACTOR_MIN = 0.70
BET_FACTOR_MAX = 1.35
BET_ROI_CAP = 8.0
ODDS_EDGES = (2,3,5,7,10,15,20,30,50,75,100,150,300,500,800,1200,2000)


def clamp(value, low, high):
    return max(low, min(high, value))


def parse_utc(value):
    text=str(value or '').strip()
    if not text: return None
    text=text.replace('Z','+00:00')
    try:
        parsed=dt.datetime.fromisoformat(text)
    except ValueError:
        try: parsed=dt.datetime.strptime(text,'%Y-%m-%d %H:%M:%S').replace(tzinfo=dt.timezone.utc)
        except ValueError: return None
    if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def recency_weight(event_time_utc, event_date, cutoff_utc, target_date):
    event=parse_utc(event_time_utc); cutoff=parse_utc(cutoff_utc)
    if event is None or cutoff is None or event >= cutoff: return 0.0
    age_days=max(0.0,(cutoff-event).total_seconds()/86400.0)
    if age_days>HISTORY_DAYS+1: return 0.0
    try:
        day_diff=(dt.date.fromisoformat(str(target_date))-dt.date.fromisoformat(str(event_date))).days
    except ValueError:
        day_diff=int(age_days)
    if day_diff<0: return 0.0
    if day_diff in DATE_MULTIPLIERS: multiplier=DATE_MULTIPLIERS[day_diff]
    elif day_diff<=7: multiplier=DAYS_2_TO_7_MULTIPLIER
    else: multiplier=OLDER_MULTIPLIER
    return multiplier*(0.5**(age_days/HALF_LIFE_DAYS))


def odds_bin(value):
    try: odds=float(value)
    except (TypeError,ValueError): return None
    if not math.isfinite(odds) or odds<=1.0: return None
    i=0
    while i<len(ODDS_EDGES) and odds>=ODDS_EDGES[i]: i+=1
    return i


def load_recent_runner_rows(collector,target_date,cutoff_utc):
    start=(dt.date.fromisoformat(target_date)-dt.timedelta(days=HISTORY_DAYS)).isoformat()
    return collector.d1_query('''
        SELECT r.race_id AS raceId,r.race_date AS raceDate,r.start_time_utc AS startTimeUtc,
               r.venue,r.surface,r.distance_m AS distanceM,
               x.horse_no AS horseNo,x.horse_name AS horseName,x.jockey,x.trainer,x.win_odds AS winOdds,
               y.finish_position AS finishPosition
        FROM rt_races r
        JOIN rt_runners x ON x.race_id=r.race_id
        JOIN rt_results y ON y.race_id=x.race_id AND y.horse_no=x.horse_no
        WHERE r.race_date BETWEEN ? AND ?
          AND r.start_time_utc IS NOT NULL
          AND datetime(r.start_time_utc) < datetime(?)
          AND y.finish_position IS NOT NULL
          AND CAST(y.finish_position AS INTEGER)>0
          AND COALESCE(x.runner_status,'active')='active'
        ORDER BY r.start_time_utc,r.race_id,x.horse_no
    ''',[start,target_date,cutoff_utc])


def load_recent_bet_rows(collector,target_date,cutoff_utc):
    start=(dt.date.fromisoformat(target_date)-dt.timedelta(days=HISTORY_DAYS)).isoformat()
    return collector.d1_query('''
        SELECT b.race_id AS raceId,b.bet_type AS betType,b.stake_yen AS stakeYen,
               COALESCE(b.return_yen,0) AS returnYen,b.assumed_odds AS assumedOdds,
               r.race_date AS raceDate,r.start_time_utc AS startTimeUtc,r.venue
        FROM rt_public_bets b
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE r.race_date BETWEEN ? AND ?
          AND r.start_time_utc IS NOT NULL
          AND datetime(r.start_time_utc) < datetime(?)
          AND b.source_prediction_id=-2
          AND b.course='ライト'
          AND b.settlement_status='settled'
        ORDER BY r.start_time_utc,b.race_id,b.id
    ''',[start,target_date,cutoff_utc])


def load_recent_learning_rows(collector,target_date,cutoff_utc):
    return load_recent_runner_rows(collector,target_date,cutoff_utc),load_recent_bet_rows(collector,target_date,cutoff_utc)


def _add_signal(stats,key,weight,residual,same_day):
    item=stats.setdefault(key,[0.0,0.0,0,0])
    item[0]+=weight*residual; item[1]+=weight; item[2]+=1; item[3]+=int(same_day)


def _signal(stats,key,prior_mass):
    item=stats.get(key)
    if not item: return 0.0,0,0,0.0
    return item[0]/(item[1]+prior_mass),item[2],item[3],item[1]


def _draw_bucket(horse_no,field):
    try: pct=(int(horse_no)-0.5)/max(1,int(field))
    except (TypeError,ValueError): return 1
    return 0 if pct<1/3 else (1 if pct<2/3 else 2)


def build_runner_learning(rows,target_race,current_runners,cutoff_utc,target_date):
    by_race=collections.defaultdict(list)
    for row in rows: by_race[str(row.get('raceId') or '')].append(row)
    stats={}; used_races=set(); same_day=set(); previous_day=set(); last7=set()
    for race_id,race_rows in by_race.items():
        valid=[]
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
        first=valid[0][0]
        weight=recency_weight(first.get('startTimeUtc'),first.get('raceDate'),cutoff_utc,target_date)
        if weight<=0: continue
        day_diff=(dt.date.fromisoformat(target_date)-dt.date.fromisoformat(str(first.get('raceDate')))).days
        used_races.add(race_id)
        if day_diff==0: same_day.add(race_id)
        if day_diff==1: previous_day.add(race_id)
        if 0<=day_diff<=7: last7.add(race_id)
        field=len(valid)
        venue=str(first.get('venue') or ''); surface=str(first.get('surface') or '')
        for row,odd,pos in valid:
            expected=((1.0/odd)/denom) if use_market else (1.0/field)
            residual=(1.0 if pos==1 else 0.0)-expected
            is_same=day_diff==0
            name=str(row.get('horseName') or '').strip(); jockey=str(row.get('jockey') or '').strip(); trainer=str(row.get('trainer') or '').strip()
            if name: _add_signal(stats,('horse',name),weight,residual,is_same)
            if jockey: _add_signal(stats,('jockey',jockey),weight,residual,is_same)
            if trainer: _add_signal(stats,('trainer',trainer),weight,residual,is_same)
            bucket=_draw_bucket(row.get('horseNo'),field)
            _add_signal(stats,('draw',venue,surface,bucket),weight,residual,is_same)
    venue=str(target_race.get('venue') or '');surface=str(target_race.get('surface') or '');field=len(current_runners)
    factors=[]; details=[]
    for runner in current_runners:
        horse_sig,horse_n,horse_same,horse_eff=_signal(stats,('horse',str(runner.get('horseName') or '').strip()),2.0)
        jockey_sig,jockey_n,jockey_same,jockey_eff=_signal(stats,('jockey',str(runner.get('jockey') or '').strip()),10.0)
        trainer_sig,trainer_n,trainer_same,trainer_eff=_signal(stats,('trainer',str(runner.get('trainer') or '').strip()),14.0)
        bucket=_draw_bucket(runner.get('horseNo'),field)
        draw_sig,draw_n,draw_same,draw_eff=_signal(stats,('draw',venue,surface,bucket),10.0)
        log_adjust=0.90*horse_sig+1.20*jockey_sig+0.75*trainer_sig+1.00*draw_sig
        factor=clamp(math.exp(log_adjust),RUNNER_FACTOR_MIN,RUNNER_FACTOR_MAX)
        factors.append(factor)
        details.append({'horseNo':int(runner.get('horseNo') or 0),'factor':round(factor,8),'signals':{
            'horse':round(horse_sig,8),'jockey':round(jockey_sig,8),'trainer':round(trainer_sig,8),'sameVenueSurfaceDraw':round(draw_sig,8)},
            'samples':{'horse':horse_n,'jockey':jockey_n,'trainer':trainer_n,'sameVenueSurfaceDraw':draw_n},
            'sameDaySamples':{'horse':horse_same,'jockey':jockey_same,'trainer':trainer_same,'sameVenueSurfaceDraw':draw_same},
            'effectiveWeight':{'horse':round(horse_eff,6),'jockey':round(jockey_eff,6),'trainer':round(trainer_eff,6),'sameVenueSurfaceDraw':round(draw_eff,6)}})
    audit={'runnerHistoryRaces':len(used_races),'sameDayFinishedRaces':len(same_day),'previousDayFinishedRaces':len(previous_day),'last7DaysFinishedRaces':len(last7)}
    return factors,details,audit


def _bet_key_rows(rows,cutoff_utc,target_date):
    buckets=collections.defaultdict(lambda:[0.0,0.0,0,0])
    races=set();same=set();prev=set();last7=set()
    for row in rows:
        try: stake=float(row.get('stakeYen')); returned=float(row.get('returnYen')); odd=float(row.get('assumedOdds'))
        except (TypeError,ValueError): continue
        if stake<=0 or not math.isfinite(returned): continue
        weight=recency_weight(row.get('startTimeUtc'),row.get('raceDate'),cutoff_utc,target_date)
        if weight<=0: continue
        day_diff=(dt.date.fromisoformat(target_date)-dt.date.fromisoformat(str(row.get('raceDate')))).days
        rid=str(row.get('raceId') or '');races.add(rid)
        if day_diff==0:same.add(rid)
        if day_diff==1:prev.add(rid)
        if 0<=day_diff<=7:last7.add(rid)
        bt=str(row.get('betType') or '');venue=str(row.get('venue') or '');obin=odds_bin(odd)
        roi=clamp(returned/stake,0.0,BET_ROI_CAP)
        keys=[('bt',bt),('btv',bt,venue)]
        if obin is not None: keys += [('bto',bt,obin),('btvo',bt,venue,obin)]
        for key in keys:
            item=buckets[key];item[0]+=weight*roi;item[1]+=weight;item[2]+=1;item[3]+=int(day_diff==0)
    audit={'betHistoryRaces':len(races),'sameDaySettledBetRaces':len(same),'previousDaySettledBetRaces':len(prev),'last7DaysSettledBetRaces':len(last7)}
    return buckets,audit


def _posterior_factor(buckets,key,prior_mass):
    item=buckets.get(key)
    if not item:return None
    mean=(item[0]+prior_mass)/(item[1]+prior_mass)
    return clamp(math.sqrt(max(0.01,mean)),BET_FACTOR_MIN,BET_FACTOR_MAX)


def build_bet_learning(rows,cutoff_utc,target_date):
    buckets,audit=_bet_key_rows(rows,cutoff_utc,target_date)
    return {'buckets':buckets,'audit':audit}


def bet_factor(state,bet_type,venue,odds):
    buckets=state.get('buckets',{});obin=odds_bin(odds);parts=[]
    specs=[(('bt',bet_type),20.0),(('btv',bet_type,venue),12.0)]
    if obin is not None: specs.extend([(('bto',bet_type,obin),12.0),(('btvo',bet_type,venue,obin),8.0)])
    for key,prior in specs:
        factor=_posterior_factor(buckets,key,prior)
        if factor is not None:parts.append(factor)
    if not parts:return 1.0
    return clamp(math.exp(sum(math.log(x) for x in parts)/len(parts)),BET_FACTOR_MIN,BET_FACTOR_MAX)


def learning_policy():
    return {'version':'canonical-recency-v1','historyDays':HISTORY_DAYS,'halfLifeDays':HALF_LIFE_DAYS,
            'dateMultipliers':{'sameDay':DATE_MULTIPLIERS[0],'previousDay':DATE_MULTIPLIERS[1],'days2To7':DAYS_2_TO_7_MULTIPLIER,'days8To30':OLDER_MULTIPLIER},
            'runnerFactorRange':[RUNNER_FACTOR_MIN,RUNNER_FACTOR_MAX],'betFactorRange':[BET_FACTOR_MIN,BET_FACTOR_MAX],
            'futureResultsAllowed':False,'sameDayFinishedResultsAllowed':True}
