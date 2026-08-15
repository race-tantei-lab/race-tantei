from pathlib import Path


def replace_once(path, old, new):
    p=Path(path); text=p.read_text(encoding='utf-8')
    count=text.count(old)
    if count!=1:
        raise RuntimeError(f'{path}: expected one match, got {count}: {old[:100]!r}')
    p.write_text(text.replace(old,new,1),encoding='utf-8')
    print('patched',path)

replace_once('src/v1/completed-ticket-runtime.ts',
'''  valueProduct: number;\n  score: number;\n}''',
'''  valueProduct: number;\n  score: number;\n  recencyFactor?: number;\n}''')
replace_once('src/v1/completed-ticket-runtime.ts',
'''export function chooseCompletedTwoTickets(horseNos: readonly number[], weights: readonly number[], rows: readonly OfficialOddsRow[]): CompletedTicket[] {''',
'''export function chooseCompletedTwoTickets(\n  horseNos: readonly number[],\n  weights: readonly number[],\n  rows: readonly OfficialOddsRow[],\n  recencyFactor?: (betType: CompletedBetType, officialOdds: number) => number,\n): CompletedTicket[] {''')
replace_once('src/v1/completed-ticket-runtime.ts',
'''      candidates.push({\n        betType,\n        combination,\n        horses: pos.map((index) => horseNos[index]),\n        predictedProbability: probability,\n        officialOdds: odd,\n        valueProduct: probability * odd,\n        score: Number.NaN,\n      });''',
'''      const learnedFactor = recencyFactor ? recencyFactor(betType, odd) : 1;\n      if (!Number.isFinite(learnedFactor) || learnedFactor <= 0) throw new Error(`invalid completed recency factor: ${betType}:${learnedFactor}`);\n      const ticket: CompletedTicket = {\n        betType,\n        combination,\n        horses: pos.map((index) => horseNos[index]),\n        predictedProbability: probability,\n        officialOdds: odd,\n        valueProduct: probability * odd * learnedFactor,\n        score: Number.NaN,\n      };\n      if (recencyFactor) ticket.recencyFactor = learnedFactor;\n      candidates.push(ticket);''')
replace_once('src/v1/completed-ticket-runtime.ts',
'''      score: Math.log(ticket.predictedProbability) + 0.4 * Math.log(ticket.officialOdds),''',
'''      score: Math.log(ticket.predictedProbability) + 0.4 * Math.log(ticket.officialOdds) + Math.log(ticket.recencyFactor ?? 1),''')

replace_once('src/v1/completed-feature-runtime.ts',
'''export async function loadCompletedFeatureStateForRace(db: D1Database, race: RaceRecord, runners: RunnerRecord[]): Promise<CompletedFeatureState> {''',
'''export async function loadCompletedFeatureStateForRace(db: D1Database, race: RaceRecord, runners: RunnerRecord[], cutoffUtc?: string): Promise<CompletedFeatureState> {''')
replace_once('src/v1/completed-feature-runtime.ts',
'''  if (throughDate < race.raceDate) {\n    const raceIds = await db.prepare(\n      "SELECT DISTINCT ra.race_id AS raceId FROM rt_races ra JOIN rt_runners ru ON ru.race_id=ra.race_id WHERE ra.race_date>? AND ra.race_date<? AND (ru.horse_name IN (SELECT value FROM json_each(?)) OR COALESCE(ru.jockey,'') IN (SELECT value FROM json_each(?)) OR COALESCE(ru.trainer,'') IN (SELECT value FROM json_each(?))) ORDER BY ra.race_date,ra.race_id"\n    ).bind(throughDate, race.raceDate, horseJson, jockeyJson, trainerJson).all<{ raceId: string }>();''',
'''  if (throughDate < race.raceDate) {\n    const effectiveCutoff = cutoffUtc ?? race.startTimeUtc ?? new Date().toISOString();\n    const raceIds = await db.prepare(\n      "SELECT DISTINCT ra.race_id AS raceId FROM rt_races ra JOIN rt_runners ru ON ru.race_id=ra.race_id WHERE ra.race_date>? AND (ra.race_date<? OR (ra.race_date=? AND ra.status='finished' AND ra.start_time_utc IS NOT NULL AND datetime(ra.start_time_utc)<datetime(?))) AND (ru.horse_name IN (SELECT value FROM json_each(?)) OR COALESCE(ru.jockey,'') IN (SELECT value FROM json_each(?)) OR COALESCE(ru.trainer,'') IN (SELECT value FROM json_each(?))) ORDER BY ra.race_date,ra.race_id"\n    ).bind(throughDate, race.raceDate, race.raceDate, effectiveCutoff, horseJson, jockeyJson, trainerJson).all<{ raceId: string }>();''')

replace_once('src/v1/completed-worker-live-lock.ts',
'''import { loadCompletedModelRuntime, type CompletedModelRuntime } from "./completed-model-runtime";''',
'''import { loadCompletedModelRuntime, type CompletedModelRuntime } from "./completed-model-runtime";\nimport { completedRecencyBetFactor, loadCompletedRecencyLearning, neutralCompletedRecencyLearning, type CompletedRecencyAudit, type CompletedRunnerRecencyDetail } from "./completed-recency-learning";''')
replace_once('src/v1/completed-worker-live-lock.ts',
'''const FINALIZE_OPEN_MS = 16 * 60 * 1000;\nconst DEADLINE_MS = 15 * 60 * 1000;''',
'''const DEADLINE_MS = 15 * 60 * 1000;\nconst FINALIZE_OPEN_MS = DEADLINE_MS;''')
replace_once('src/v1/completed-worker-live-lock.ts',
'''  oddsSnapshotSha256: string;\n  tickets: CompletedTicket[];\n  courseBets: CompletedCourseBet[];''',
'''  oddsSnapshotSha256: string;\n  onlineLearning?: CompletedRecencyAudit;\n  runnerRecencyFactors?: CompletedRunnerRecencyDetail[];\n  tickets: CompletedTicket[];\n  courseBets: CompletedCourseBet[];''')
replace_once('src/v1/completed-worker-live-lock.ts',
'''  const state = await loadCompletedFeatureStateForRace(db, refreshed.race, refreshed.runners);\n  const vectors = refreshed.runners.map((runner) => completedFeatureVector(state, refreshed.race, runner, refreshed.runners.length));\n  const raw = vectors.map((vector) => model.predict(vector));\n  const weights = normalizeCompletedWeights(raw);\n  const fetched = await fetchFastJraOfficialOddsForRace(refreshed.race.entryUrl, { raceDate: refreshed.race.raceDate, venue: refreshed.race.venue, raceNo: refreshed.race.raceNo });\n  const oddsFetchedAt = iso();\n  const tickets = chooseCompletedTwoTickets(refreshed.runners.map((runner) => Number(runner.horseNo)), weights, fetched.rows);''',
'''  const learningCutoff = iso(now);\n  const state = await loadCompletedFeatureStateForRace(db, refreshed.race, refreshed.runners, learningCutoff);\n  const vectors = refreshed.runners.map((runner) => completedFeatureVector(state, refreshed.race, runner, refreshed.runners.length));\n  const raw = vectors.map((vector) => model.predict(vector));\n  const baseWeights = normalizeCompletedWeights(raw);\n  let learning;\n  try {\n    learning = await loadCompletedRecencyLearning(db, refreshed.race, refreshed.runners, learningCutoff);\n  } catch (error) {\n    learning = neutralCompletedRecencyLearning(refreshed.runners, learningCutoff, errorText(error));\n  }\n  const weights = normalizeCompletedWeights(baseWeights.map((value, index) => value * learning.runnerFactors[index]));\n  const fetched = await fetchFastJraOfficialOddsForRace(refreshed.race.entryUrl, { raceDate: refreshed.race.raceDate, venue: refreshed.race.venue, raceNo: refreshed.race.raceNo });\n  const oddsFetchedAt = iso();\n  const tickets = chooseCompletedTwoTickets(\n    refreshed.runners.map((runner) => Number(runner.horseNo)),\n    weights,\n    fetched.rows,\n    (betType, odds) => completedRecencyBetFactor(learning, betType, refreshed.race.venue, odds),\n  );''')
replace_once('src/v1/completed-worker-live-lock.ts',
'''    oddsSource: fetched.source,\n    oddsSnapshotSha256: await sha256Hex(canonicalOddsRows(fetched.rows)),\n    tickets,''',
'''    oddsSource: fetched.source,\n    oddsSnapshotSha256: await sha256Hex(canonicalOddsRows(fetched.rows)),\n    onlineLearning: learning.audit,\n    runnerRecencyFactors: learning.runnerDetails,\n    tickets,''')
replace_once('src/v1/completed-worker-live-lock.ts',
'''    oddsSnapshotSha256: snapshot.oddsSnapshotSha256,\n    tickets: snapshot.tickets,''',
'''    oddsSnapshotSha256: snapshot.oddsSnapshotSha256,\n    onlineLearning: snapshot.onlineLearning ?? null,\n    runnerRecencyFactors: snapshot.runnerRecencyFactors ?? null,\n    tickets: snapshot.tickets,''')
replace_once('src/v1/completed-worker-live-lock.ts',
'''      // At/after T-15 there is no new network dependency. Promote the best\n      // already-generated candidate, preferring one that used official bodyweight.\n      if (remaining <= DEADLINE_MS) {\n        const fallback = await latestOfficialBodyWeightPreview(env.DB, raceId) ?? await latestPreview(env.DB, raceId);\n        if (!fallback) throw new Error(`WORKER_DEADLINE_PREVIEW_MISSING:${raceId}`);\n        if (!snapshotHasOfficialBodyWeight(fallback)) bodyWeightBreachRaceIds.add(raceId);\n        await commitSnapshot(env.DB, raceId, fallback, now, "deadline_watchdog");\n        lockedByWorker.push(raceId);\n        finalizedFromFallbackRaceIds.push(raceId);\n        latePromotedRaceIds.push(raceId);\n        continue;\n      }''',
'''      // T-15 is the immutable boundary. First try one last fresh score using\n      // every result settled up to this instant and the freshest official odds.\n      // If any acquisition fails, promote the last good preview so learning can\n      // never become a reason for a missing bet.\n      if (remaining <= DEADLINE_MS) {\n        let deadlineFresh: PreviewSnapshot | null = null;\n        try {\n          model ??= await loadWorkerModel(env.DB);\n          deadlineFresh = await generatePreview(env.DB, model, raceId, now);\n          refreshedPreviewRaceIds.push(raceId);\n        } catch (error) {\n          errors.push({ raceId, error: `T15_FRESH_FALLBACK:${errorText(error)}` });\n        }\n        const fallback = deadlineFresh ?? await latestOfficialBodyWeightPreview(env.DB, raceId) ?? await latestPreview(env.DB, raceId);\n        if (!fallback) throw new Error(`WORKER_DEADLINE_PREVIEW_MISSING:${raceId}`);\n        if (!snapshotHasOfficialBodyWeight(fallback)) bodyWeightBreachRaceIds.add(raceId);\n        await commitSnapshot(env.DB, raceId, fallback, new Date(), deadlineFresh ? "fresh" : "deadline_watchdog");\n        lockedByWorker.push(raceId);\n        if (deadlineFresh) finalizedFromFreshRaceIds.push(raceId);\n        else { finalizedFromFallbackRaceIds.push(raceId); latePromotedRaceIds.push(raceId); }\n        continue;\n      }''')

replace_once('scripts/generate-ten-year-live-bets.py',
'''COLLECTOR_PATH=ROOT/'scripts'/'collect-jra-official-odds.py'\nCOURSE_STAKES''',
'''COLLECTOR_PATH=ROOT/'scripts'/'collect-jra-official-odds.py'\nLEARNING_PATH=ROOT/'scripts'/'live-recency-learning.py'\nCOURSE_STAKES''')
replace_once('scripts/generate-ten-year-live-bets.py',
'''def choose_two(core,rid,runners,w,odds):''',
'''def choose_two(core,learning,rid,runners,w,odds,bet_learning,venue):''')
replace_once('scripts/generate-ten-year-live-bets.py',
'''            candidates.append({'betType':bt,'combination':combo,'horses':[horse_nos[i] for i in pos],'predictedProbability':p,'officialOdds':odd,'valueProduct':p*odd})''',
'''            learned_factor=float(learning.bet_factor(bet_learning,bt,venue,odd))\n            candidates.append({'betType':bt,'combination':combo,'horses':[horse_nos[i] for i in pos],'predictedProbability':p,'officialOdds':odd,'recencyFactor':learned_factor,'valueProduct':p*odd*learned_factor})''')
replace_once('scripts/generate-ten-year-live-bets.py',
'''        for x in retained:x['score']=math.log(x['predictedProbability'])+0.4*math.log(x['officialOdds'])''',
'''        for x in retained:x['score']=math.log(x['predictedProbability'])+0.4*math.log(x['officialOdds'])+math.log(x.get('recencyFactor',1.0))''')
replace_once('scripts/generate-ten-year-live-bets.py',
'''    core=load(CORE_PATH,'ten_year_production_core_bets');collector=load(COLLECTOR_PATH,'ten_year_bets_collector');cfg=core.load_config()''',
'''    core=load(CORE_PATH,'ten_year_production_core_bets');collector=load(COLLECTOR_PATH,'ten_year_bets_collector');learning=load(LEARNING_PATH,'live_recency_learning');cfg=core.load_config()''')
replace_once('scripts/generate-ten-year-live-bets.py',
'''    state=core.load_feature_state();delta=core.delta_bundles(collector,state['throughDate'],a.date);core.advance_feature_state(state,delta)\n    target_map={str(b['race']['raceId']):b for b in core.target_bundles(collector,a.date)}\n    booster=lgb.Booster(model_file=str(core.MODEL_PATH));features=list(cfg['runnerProbabilityModel']['features'])\n    if booster.num_feature()!=len(features):raise RuntimeError(f'MODEL_FEATURE_COUNT_INVALID:{booster.num_feature()}/{len(features)}')\n    generated_at=dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z');out=[]''',
'''    generated_at=dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')\n    state=core.load_feature_state();delta=core.delta_bundles(collector,state['throughDate'],a.date);core.advance_feature_state(state,delta)\n    same_day=core.bundles_from_d1(collector,"race_date=? AND status='finished' AND start_time_utc IS NOT NULL AND datetime(start_time_utc)<datetime(?)",[a.date,generated_at])\n    if same_day: core.update_feature_state_for_date(state,same_day)\n    target_map={str(b['race']['raceId']):b for b in core.target_bundles(collector,a.date)}\n    booster=lgb.Booster(model_file=str(core.MODEL_PATH));features=list(cfg['runnerProbabilityModel']['features'])\n    if booster.num_feature()!=len(features):raise RuntimeError(f'MODEL_FEATURE_COUNT_INVALID:{booster.num_feature()}/{len(features)}')\n    try:\n        runner_learning_rows,bet_learning_rows=learning.load_recent_learning_rows(collector,a.date,generated_at)\n        bet_learning=learning.build_bet_learning(bet_learning_rows,generated_at,a.date)\n        learning_error=None\n    except Exception as exc:\n        runner_learning_rows=[];bet_learning={'buckets':{},'audit':{'betHistoryRaces':0,'sameDaySettledBetRaces':0,'previousDaySettledBetRaces':0,'last7DaysSettledBetRaces':0}};learning_error=f'{type(exc).__name__}:{exc}'\n    out=[]''')
replace_once('scripts/generate-ten-year-live-bets.py',
'''        w=raw/raw.sum();chosen=choose_two(core,rid,runners,w,odds)''',
'''        base_w=raw/raw.sum()\n        factors,runner_learning_detail,runner_learning_audit=learning.build_runner_learning(runner_learning_rows,b['race'],runners,generated_at,a.date) if runner_learning_rows else ([1.0]*len(runners),[{'horseNo':int(r['horseNo']),'factor':1.0} for r in runners],{'runnerHistoryRaces':0,'sameDayFinishedRaces':0,'previousDayFinishedRaces':0,'last7DaysFinishedRaces':0})\n        adjusted=np.asarray([base_w[i]*float(factors[i]) for i in range(len(runners))],dtype=np.float64);w=adjusted/adjusted.sum()\n        chosen=choose_two(core,learning,rid,runners,w,odds,bet_learning,str(b['race'].get('venue') or ''))''')
replace_once('scripts/generate-ten-year-live-bets.py',
'''        out.append({'raceId':rid,'raceDate':a.date,'venue':b['race'].get('venue'),'raceNo':b['race'].get('raceNo'),'sourceModel':'ten-year-completed-model','runnerProbabilities':[{'horseNo':int(runners[i]['horseNo']),'probability':float(w[i])} for i in range(len(runners))],'tickets':chosen,'courseBets':course_bets})''',
'''        online_learning={**learning.learning_policy(),**runner_learning_audit,**bet_learning.get('audit',{}),'cutoffUtc':generated_at,'status':'neutral_fallback' if learning_error else 'applied','error':learning_error,'sameDayFeatureStateRaces':len(same_day)}\n        out.append({'raceId':rid,'raceDate':a.date,'venue':b['race'].get('venue'),'raceNo':b['race'].get('raceNo'),'sourceModel':'ten-year-completed-model','runnerProbabilities':[{'horseNo':int(runners[i]['horseNo']),'baseProbability':float(base_w[i]),'recencyFactor':float(factors[i]),'probability':float(w[i])} for i in range(len(runners))],'runnerRecencyFactors':runner_learning_detail,'onlineLearning':online_learning,'tickets':chosen,'courseBets':course_bets})''')
replace_once('scripts/generate-ten-year-live-bets.py',
'''    artifact={'generatedAt':generated_at,'date':a.date,'sourceModel':'ten-year-completed-model','ticketsPerRace':2,'resultDataUsedForTargetDay':False,'officialOddsOnly':True,'races':out}''',
'''    artifact={'generatedAt':generated_at,'date':a.date,'sourceModel':'ten-year-completed-model','ticketsPerRace':2,'resultDataUsedForTargetDay':False,'targetRaceResultUsed':False,'priorSameDayResultDataUsedForLiveLearning':any((r.get('onlineLearning') or {}).get('sameDayFinishedRaces',0)>0 for r in out),'officialOddsOnly':True,'onlineLearningPolicy':learning.learning_policy(),'races':out}''')

replace_once('.github/workflows/auto-final-live-bets.yml',
'''      - "scripts/generate-ten-year-live-bets.py"\n      - "scripts/collect-jra-official-odds.py"''',
'''      - "scripts/generate-ten-year-live-bets.py"\n      - "scripts/live-recency-learning.py"\n      - "scripts/collect-jra-official-odds.py"''')
replace_once('.github/workflows/auto-final-live-bets.yml',
'''            scripts/generate-ten-year-live-bets.py \\\n            scripts/collect-current-jra-official-odds-live.py''',
'''            scripts/generate-ten-year-live-bets.py \\\n            scripts/live-recency-learning.py \\\n            scripts/collect-current-jra-official-odds-live.py''')

replace_once('package.json',
'''node dist-test/tests/walk-forward-tests.js",''',
'''node dist-test/tests/walk-forward-tests.js && node dist-test/tests/completed-recency-learning-tests.js",''')

print('ALL_PATCHES_APPLIED')
