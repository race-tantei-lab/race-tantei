export interface Phase1Env {
  DB: D1Database;
  JRA_ENTRY_PROBE_URL: string;
  JRA_RESULT_PROBE_URL: string;
}

export interface RaceHeader {
  raceId: string;
  raceDate: string;
  venue: string;
  meetingNo: number;
  meetingDay: number;
  raceNo: number;
  raceName: string;
  conditions: string | null;
  surface: string | null;
  distanceM: number | null;
  direction: string | null;
  startTimeJst: string | null;
}

export interface RunnerRecord {
  horseNo: number;
  frameNo: number | null;
  horseName: string;
  sexAge: string | null;
  coatColor: string | null;
  horseWeight: number | null;
  weightChange: number | null;
  jockey: string | null;
  assignedWeight: number | null;
  trainer: string | null;
  stable: string | null;
  finalOdds: number | null;
  popularity: number | null;
  runnerStatus: string;
}

export interface ResultRecord {
  horseNo: number;
  finishPosition: number | null;
  resultStatus: string;
  timeText: string | null;
  marginText: string | null;
  final3f: number | null;
}

export interface PayoutRecord {
  betType: string;
  combination: string;
  payoutYen: number;
  popularity: number | null;
}

export interface ParsedRaceBundle {
  race: RaceHeader;
  runners: RunnerRecord[];
  results: ResultRecord[];
  payouts: PayoutRecord[];
}

export interface Phase1PilotResult {
  ok: boolean;
  raceId: string | null;
  runners: number;
  results: number;
  payouts: number;
  error: string | null;
}

const VENUE_SLUG: Record<string, string> = {
  札幌: "sapporo",
  函館: "hakodate",
  福島: "fukushima",
  新潟: "niigata",
  東京: "tokyo",
  中山: "nakayama",
  中京: "chukyo",
  京都: "kyoto",
  阪神: "hanshin",
  小倉: "kokura"
};

const BET_TYPES = ["単勝", "複勝", "枠連", "馬連", "馬単", "ワイド", "3連複", "3連単"] as const;

function decodeEntities(value: string): string {
  const named: Record<string, string> = {
    amp: "&",
    lt: "<",
    gt: ">",
    quot: '"',
    apos: "'",
    nbsp: " "
  };
  return value.replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (_match, entity: string) => {
    if (entity.startsWith("#x") || entity.startsWith("#X")) {
      const code = Number.parseInt(entity.slice(2), 16);
      return Number.isFinite(code) ? String.fromCodePoint(code) : "";
    }
    if (entity.startsWith("#")) {
      const code = Number.parseInt(entity.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : "";
    }
    return named[entity.toLowerCase()] ?? "";
  });
}

export function htmlToLines(html: string): string[] {
  const withBreaks = html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "")
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\/(?:td|th|tr|li|p|div|section|article|h[1-6]|dt|dd|ul|ol|table)>/gi, "\n")
    .replace(/<[^>]+>/g, " ");

  return decodeEntities(withBreaks)
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.replace(/[\t\u00a0 ]+/g, " ").trim())
    .filter((line) => line.length > 0);
}

function findRaceHeader(lines: string[]): RaceHeader {
  const text = lines.join("\n");
  const event = text.match(/(\d{4})年(\d{1,2})月(\d{1,2})日[^\n]*?(\d+)回(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)(\d+)日/);
  if (!event) throw new Error("PHASE1_RACE_HEADER_NOT_FOUND");

  const year = Number(event[1]);
  const month = Number(event[2]);
  const day = Number(event[3]);
  const meetingNo = Number(event[4]);
  const venue = event[5] ?? "";
  const meetingDay = Number(event[6]);
  const afterEvent = text.slice((event.index ?? 0) + event[0].length);
  const race = afterEvent.match(/(?:^|\n)\s*(\d{1,2})R\s+([^\n]+)/);
  if (!race) throw new Error("PHASE1_RACE_NUMBER_NOT_FOUND");

  const raceNo = Number(race[1]);
  const raceName = (race[2] ?? "").trim();
  const course = afterEvent.match(/コース\s*(\d+)m\s*(芝|ダート|障害)(?:[・\s]*(左|右|直線))?\s*発走(\d{1,2}):(\d{2})/);
  const conditionsMatch = afterEvent.match(new RegExp(`${raceNo}R\\s+[^\\n]+\\n([^\\n]+)\\nコース`));
  const raceDate = `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const slug = VENUE_SLUG[venue];
  if (!slug) throw new Error("PHASE1_UNKNOWN_VENUE");

  return {
    raceId: `${raceDate.replaceAll("-", "")}-${slug}-${String(raceNo).padStart(2, "0")}`,
    raceDate,
    venue,
    meetingNo,
    meetingDay,
    raceNo,
    raceName,
    conditions: conditionsMatch?.[1]?.trim() ?? null,
    surface: course?.[2] ?? null,
    distanceM: course?.[1] ? Number(course[1]) : null,
    direction: course?.[3] ?? null,
    startTimeJst: course?.[4] && course[5] ? `${course[4].padStart(2, "0")}:${course[5]}` : null
  };
}

function parseWeight(line: string): { sexAge: string | null; coatColor: string | null; weight: number | null; change: number | null } | null {
  const match = line.match(/([牡牝セ]\d+)\s*[／/]\s*([^\s／/]+)\s*(\d+)kg(?:\(([^)]+)\))?/);
  if (!match) return null;
  const changeText = match[4] ?? "";
  const changeMatch = changeText.match(/([+-]?\d+)/);
  return {
    sexAge: match[1] ?? null,
    coatColor: match[2] ?? null,
    weight: match[3] ? Number(match[3]) : null,
    change: changeMatch?.[1] ? Number(changeMatch[1]) : null
  };
}

function findPreviousIntegers(lines: string[], start: number, limit = 10): number[] {
  const values: number[] = [];
  for (let index = start; index >= 0 && start - index < limit; index -= 1) {
    const line = lines[index];
    if (line && /^\d{1,2}$/.test(line)) values.unshift(Number(line));
  }
  return values;
}

function nameAndOdds(lines: string[], weightIndex: number): { name: string; nameIndex: number; odds: number | null; popularity: number | null; status: string } | null {
  for (let index = weightIndex - 1; index >= 0 && weightIndex - index <= 8; index -= 1) {
    const line = lines[index] ?? "";
    const normal = line.match(/^(.+?)\s+(\d+(?:\.\d+)?)\s*\((\d+)番人気\)$/);
    if (normal) {
      return {
        name: (normal[1] ?? "").trim(),
        nameIndex: index,
        odds: Number(normal[2]),
        popularity: Number(normal[3]),
        status: "active"
      };
    }
    const excluded = line.match(/^(.+?)\s+(除外|取消)$/);
    if (excluded) {
      return {
        name: (excluded[1] ?? "").trim(),
        nameIndex: index,
        odds: null,
        popularity: null,
        status: excluded[2] === "除外" ? "excluded" : "scratched"
      };
    }
  }
  return null;
}

function parsePeople(lines: string[], start: number, end: number): { jockey: string | null; assignedWeight: number | null; trainer: string | null; stable: string | null } {
  const joined = lines.slice(start, end).join(" ");
  const match = joined.match(/([▲△☆★]?[ぁ-んァ-ヶ一-龠々ー・]{2,16})\s*\((\d+(?:\.\d+)?)\)\s*([ぁ-んァ-ヶ一-龠々ー・]{2,16})\s*\((美浦|栗東)\)/);
  return {
    jockey: match?.[1]?.replace(/^[▲△☆★]/, "") ?? null,
    assignedWeight: match?.[2] ? Number(match[2]) : null,
    trainer: match?.[3] ?? null,
    stable: match?.[4] ?? null
  };
}

export function parseEntryPage(html: string): { race: RaceHeader; runners: RunnerRecord[] } {
  const lines = htmlToLines(html);
  const race = findRaceHeader(lines);
  const runners: RunnerRecord[] = [];
  const seen = new Set<number>();

  for (let index = 0; index < lines.length; index += 1) {
    const weightInfo = parseWeight(lines[index] ?? "");
    if (!weightInfo) continue;
    const identity = nameAndOdds(lines, index);
    if (!identity) continue;
    const integers = findPreviousIntegers(lines, identity.nameIndex - 1);
    if (integers.length === 0) continue;
    const horseNo = integers.at(-1) ?? 0;
    const frameNo = integers.length >= 2 ? integers.at(-2) ?? null : null;
    if (horseNo < 1 || horseNo > 18 || seen.has(horseNo)) continue;
    const nextWeightIndex = lines.findIndex((line, candidate) => candidate > index && parseWeight(line) !== null);
    const peopleEnd = nextWeightIndex === -1 ? Math.min(lines.length, index + 15) : nextWeightIndex;
    const people = parsePeople(lines, index + 1, peopleEnd);

    runners.push({
      horseNo,
      frameNo,
      horseName: identity.name,
      sexAge: weightInfo.sexAge,
      coatColor: weightInfo.coatColor,
      horseWeight: weightInfo.weight,
      weightChange: weightInfo.change,
      jockey: people.jockey,
      assignedWeight: people.assignedWeight,
      trainer: people.trainer,
      stable: people.stable,
      finalOdds: identity.odds,
      popularity: identity.popularity,
      runnerStatus: identity.status
    });
    seen.add(horseNo);
  }

  if (runners.length < 5) throw new Error(`PHASE1_RUNNERS_TOO_FEW:${runners.length}`);
  return { race, runners: runners.sort((a, b) => a.horseNo - b.horseNo) };
}

function findResultForRunner(lines: string[], runner: RunnerRecord): ResultRecord | null {
  const index = lines.findIndex((line) => line === runner.horseName || line.startsWith(`${runner.horseName} `));
  if (index < 0) return runner.runnerStatus === "active" ? null : {
    horseNo: runner.horseNo,
    finishPosition: null,
    resultStatus: runner.runnerStatus,
    timeText: null,
    marginText: null,
    final3f: null
  };

  const previous = lines.slice(Math.max(0, index - 8), index);
  const statuses = previous.filter((line) => /^(?:除外|取消|中止|失格|\d{1,2})$/.test(line));
  const horseNoIndex = statuses.map((line) => Number(line)).lastIndexOf(runner.horseNo);
  let finishText: string | null = null;
  if (horseNoIndex >= 2) finishText = statuses[horseNoIndex - 2] ?? null;
  if (horseNoIndex === 1 && /^(?:除外|取消|中止|失格)$/.test(statuses[0] ?? "")) finishText = statuses[0] ?? null;

  const nextNames = lines
    .map((line, candidate) => ({ line, candidate }))
    .filter(({ line, candidate }) => candidate > index && line !== runner.horseName && /^[ぁ-んァ-ヶ一-龠々ー・A-Za-z0-9]+(?:\s+\d+番人気)?$/.test(line))
    .map(({ candidate }) => candidate);
  const end = nextNames[0] ?? Math.min(lines.length, index + 12);
  const after = lines.slice(index, end).join(" ");
  const time = after.match(/(\d+:\d{2}\.\d)/);
  const afterTime = time?.index !== undefined ? after.slice(time.index + time[0].length) : "";
  const margin = afterTime.match(/^\s*\(([^)]+)\)/);
  const final3fMatches = [...afterTime.matchAll(/(?:^|\s)(\d{2}\.\d)(?:\s|$)/g)];
  const final3fText = final3fMatches.at(-1)?.[1];
  const finishPosition = finishText && /^\d+$/.test(finishText) ? Number(finishText) : null;
  const resultStatus = finishPosition !== null ? "finished" : (finishText ?? runner.runnerStatus);

  return {
    horseNo: runner.horseNo,
    finishPosition,
    resultStatus,
    timeText: time?.[1] ?? null,
    marginText: finishPosition === null ? null : (margin?.[1] ?? null),
    final3f: final3fText ? Number(final3fText) : null
  };
}

function parsePayoutLines(lines: string[]): PayoutRecord[] {
  const payouts: PayoutRecord[] = [];
  let currentType: string | null = null;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    if ((BET_TYPES as readonly string[]).includes(line)) {
      currentType = line;
      continue;
    }
    if (!currentType) continue;

    const combined = line.match(/^([0-9]+(?:-[0-9]+){0,2})\s+([\d,]+)円(?:\s+(\d+)番人気)?$/);
    if (combined) {
      payouts.push({
        betType: currentType,
        combination: combined[1] ?? "",
        payoutYen: Number((combined[2] ?? "0").replaceAll(",", "")),
        popularity: combined[3] ? Number(combined[3]) : null
      });
      continue;
    }

    const amount = line.match(/^([\d,]+)円$/);
    if (!amount || index === 0) continue;
    const combination = lines[index - 1] ?? "";
    if (!/^[0-9]+(?:-[0-9]+){0,2}$/.test(combination)) continue;
    const popularityLine = lines[index + 1] ?? "";
    const popularity = popularityLine.match(/^(\d+)番人気$/);
    payouts.push({
      betType: currentType,
      combination,
      payoutYen: Number((amount[1] ?? "0").replaceAll(",", "")),
      popularity: popularity?.[1] ? Number(popularity[1]) : null
    });
  }
  return payouts;
}

export function parseResultPage(html: string, runners: RunnerRecord[]): { results: ResultRecord[]; payouts: PayoutRecord[] } {
  const lines = htmlToLines(html);
  const resultStart = lines.findIndex((line) => line.includes("レース結果"));
  const payoutStart = lines.findIndex((line) => line === "払戻金");
  if (resultStart < 0 || payoutStart < 0) throw new Error("PHASE1_RESULT_SECTION_NOT_FOUND");
  const resultLines = lines.slice(resultStart, payoutStart);
  const results = runners
    .map((runner) => findResultForRunner(resultLines, runner))
    .filter((result): result is ResultRecord => result !== null);

  const payoutEnd = lines.findIndex((line, index) => index > payoutStart && (line === "勝馬の紹介" || line.startsWith("・勝馬投票")));
  const payoutLines = lines.slice(payoutStart, payoutEnd > payoutStart ? payoutEnd : undefined);
  const payouts = parsePayoutLines(payoutLines);

  if (results.filter((result) => result.finishPosition !== null).length < 3) {
    throw new Error(`PHASE1_RESULTS_TOO_FEW:${results.length}`);
  }
  if (payouts.length < 3) throw new Error(`PHASE1_PAYOUTS_TOO_FEW:${payouts.length}`);
  return { results, payouts };
}

export async function ensurePhase1Schema(db: D1Database): Promise<void> {
  const statements = [
    `CREATE TABLE IF NOT EXISTS races (
      race_id TEXT PRIMARY KEY,
      race_date TEXT NOT NULL,
      venue TEXT NOT NULL,
      meeting_no INTEGER NOT NULL,
      meeting_day INTEGER NOT NULL,
      race_no INTEGER NOT NULL,
      race_name TEXT NOT NULL,
      conditions TEXT,
      surface TEXT,
      distance_m INTEGER,
      direction TEXT,
      start_time_jst TEXT,
      entry_url TEXT NOT NULL,
      result_url TEXT NOT NULL,
      race_status TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`,
    `CREATE TABLE IF NOT EXISTS runners (
      race_id TEXT NOT NULL,
      horse_no INTEGER NOT NULL,
      frame_no INTEGER,
      horse_name TEXT NOT NULL,
      sex_age TEXT,
      coat_color TEXT,
      horse_weight INTEGER,
      weight_change INTEGER,
      jockey TEXT,
      assigned_weight REAL,
      trainer TEXT,
      stable TEXT,
      final_odds REAL,
      popularity INTEGER,
      runner_status TEXT NOT NULL,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (race_id, horse_no)
    )`,
    `CREATE TABLE IF NOT EXISTS race_results (
      race_id TEXT NOT NULL,
      horse_no INTEGER NOT NULL,
      finish_position INTEGER,
      result_status TEXT NOT NULL,
      time_text TEXT,
      margin_text TEXT,
      final_3f REAL,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (race_id, horse_no)
    )`,
    `CREATE TABLE IF NOT EXISTS payouts (
      race_id TEXT NOT NULL,
      bet_type TEXT NOT NULL,
      combination TEXT NOT NULL,
      payout_yen INTEGER NOT NULL,
      popularity INTEGER,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (race_id, bet_type, combination)
    )`,
    `CREATE TABLE IF NOT EXISTS phase1_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      started_at TEXT NOT NULL,
      completed_at TEXT NOT NULL,
      ok INTEGER NOT NULL,
      race_id TEXT,
      runners_count INTEGER NOT NULL,
      results_count INTEGER NOT NULL,
      payouts_count INTEGER NOT NULL,
      error_message TEXT
    )`,
    `CREATE INDEX IF NOT EXISTS idx_races_date ON races(race_date DESC, venue, race_no)`,
    `CREATE INDEX IF NOT EXISTS idx_phase1_runs_started ON phase1_runs(started_at DESC)`
  ];
  for (const statement of statements) await db.prepare(statement).run();
}

async function fetchJraHtml(source: string): Promise<string> {
  const url = new URL(source);
  if (!(url.hostname === "jra.go.jp" || url.hostname.endsWith(".jra.go.jp"))) {
    throw new Error("PHASE1_NON_JRA_HOST");
  }
  const response = await fetch(url.toString(), {
    redirect: "manual",
    headers: { "accept": "text/html,application/xhtml+xml" }
  });
  if (response.status >= 300 && response.status < 400) throw new Error(`PHASE1_REDIRECT:${response.status}`);
  if (!response.ok) throw new Error(`PHASE1_HTTP:${response.status}`);
  const type = response.headers.get("content-type") ?? "";
  if (!type.includes("text/html")) throw new Error(`PHASE1_CONTENT_TYPE:${type}`);
  const declaredLength = Number(response.headers.get("content-length") ?? "0");
  if (declaredLength > 2_000_000) throw new Error("PHASE1_BODY_TOO_LARGE");
  const html = await response.text();
  if (html.length > 2_000_000) throw new Error("PHASE1_BODY_TOO_LARGE");
  return html;
}

async function upsertRace(db: D1Database, bundle: ParsedRaceBundle, entryUrl: string, resultUrl: string): Promise<void> {
  const race = bundle.race;
  await db.prepare(`INSERT INTO races (
    race_id, race_date, venue, meeting_no, meeting_day, race_no, race_name,
    conditions, surface, distance_m, direction, start_time_jst,
    entry_url, result_url, race_status, updated_at
  ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'result_confirmed', CURRENT_TIMESTAMP)
  ON CONFLICT(race_id) DO UPDATE SET
    race_date=excluded.race_date, venue=excluded.venue, meeting_no=excluded.meeting_no,
    meeting_day=excluded.meeting_day, race_no=excluded.race_no, race_name=excluded.race_name,
    conditions=excluded.conditions, surface=excluded.surface, distance_m=excluded.distance_m,
    direction=excluded.direction, start_time_jst=excluded.start_time_jst,
    entry_url=excluded.entry_url, result_url=excluded.result_url,
    race_status=excluded.race_status, updated_at=CURRENT_TIMESTAMP`).bind(
      race.raceId, race.raceDate, race.venue, race.meetingNo, race.meetingDay,
      race.raceNo, race.raceName, race.conditions, race.surface, race.distanceM,
      race.direction, race.startTimeJst, entryUrl, resultUrl
    ).run();

  for (const runner of bundle.runners) {
    await db.prepare(`INSERT INTO runners (
      race_id, horse_no, frame_no, horse_name, sex_age, coat_color, horse_weight,
      weight_change, jockey, assigned_weight, trainer, stable, final_odds,
      popularity, runner_status, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(race_id, horse_no) DO UPDATE SET
      frame_no=excluded.frame_no, horse_name=excluded.horse_name, sex_age=excluded.sex_age,
      coat_color=excluded.coat_color, horse_weight=excluded.horse_weight,
      weight_change=excluded.weight_change, jockey=excluded.jockey,
      assigned_weight=excluded.assigned_weight, trainer=excluded.trainer,
      stable=excluded.stable, final_odds=excluded.final_odds,
      popularity=excluded.popularity, runner_status=excluded.runner_status,
      updated_at=CURRENT_TIMESTAMP`).bind(
        race.raceId, runner.horseNo, runner.frameNo, runner.horseName, runner.sexAge,
        runner.coatColor, runner.horseWeight, runner.weightChange, runner.jockey,
        runner.assignedWeight, runner.trainer, runner.stable, runner.finalOdds,
        runner.popularity, runner.runnerStatus
      ).run();
  }

  for (const result of bundle.results) {
    await db.prepare(`INSERT INTO race_results (
      race_id, horse_no, finish_position, result_status, time_text, margin_text,
      final_3f, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(race_id, horse_no) DO UPDATE SET
      finish_position=excluded.finish_position, result_status=excluded.result_status,
      time_text=excluded.time_text, margin_text=excluded.margin_text,
      final_3f=excluded.final_3f, updated_at=CURRENT_TIMESTAMP`).bind(
        race.raceId, result.horseNo, result.finishPosition, result.resultStatus,
        result.timeText, result.marginText, result.final3f
      ).run();
  }

  for (const payout of bundle.payouts) {
    await db.prepare(`INSERT INTO payouts (
      race_id, bet_type, combination, payout_yen, popularity, updated_at
    ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(race_id, bet_type, combination) DO UPDATE SET
      payout_yen=excluded.payout_yen, popularity=excluded.popularity,
      updated_at=CURRENT_TIMESTAMP`).bind(
        race.raceId, payout.betType, payout.combination, payout.payoutYen, payout.popularity
      ).run();
  }
}

async function recordPhase1Run(db: D1Database, startedAt: string, result: Phase1PilotResult): Promise<void> {
  await db.prepare(`INSERT INTO phase1_runs (
    started_at, completed_at, ok, race_id, runners_count, results_count,
    payouts_count, error_message
  ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`).bind(
    startedAt, new Date().toISOString(), result.ok ? 1 : 0, result.raceId,
    result.runners, result.results, result.payouts, result.error
  ).run();
}

export async function runPhase1Pilot(env: Phase1Env): Promise<Phase1PilotResult> {
  const startedAt = new Date().toISOString();
  await ensurePhase1Schema(env.DB);
  try {
    const [entryHtml, resultHtml] = await Promise.all([
      fetchJraHtml(env.JRA_ENTRY_PROBE_URL),
      fetchJraHtml(env.JRA_RESULT_PROBE_URL)
    ]);
    const entry = parseEntryPage(entryHtml);
    const result = parseResultPage(resultHtml, entry.runners);
    const bundle: ParsedRaceBundle = {
      race: entry.race,
      runners: entry.runners,
      results: result.results,
      payouts: result.payouts
    };
    await upsertRace(env.DB, bundle, env.JRA_ENTRY_PROBE_URL, env.JRA_RESULT_PROBE_URL);
    const output: Phase1PilotResult = {
      ok: true,
      raceId: entry.race.raceId,
      runners: entry.runners.length,
      results: result.results.length,
      payouts: result.payouts.length,
      error: null
    };
    await recordPhase1Run(env.DB, startedAt, output);
    return output;
  } catch (error) {
    const output: Phase1PilotResult = {
      ok: false,
      raceId: null,
      runners: 0,
      results: 0,
      payouts: 0,
      error: error instanceof Error ? error.message : String(error)
    };
    await recordPhase1Run(env.DB, startedAt, output);
    return output;
  }
}

export async function getPhase1Status(db: D1Database): Promise<unknown> {
  await ensurePhase1Schema(db);
  const [races, runners, results, payouts, latestRuns, latestRaces] = await Promise.all([
    db.prepare("SELECT COUNT(*) AS count FROM races").first<{ count: number }>(),
    db.prepare("SELECT COUNT(*) AS count FROM runners").first<{ count: number }>(),
    db.prepare("SELECT COUNT(*) AS count FROM race_results").first<{ count: number }>(),
    db.prepare("SELECT COUNT(*) AS count FROM payouts").first<{ count: number }>(),
    db.prepare(`SELECT started_at AS startedAt, completed_at AS completedAt, ok,
      race_id AS raceId, runners_count AS runners, results_count AS results,
      payouts_count AS payouts, error_message AS error
      FROM phase1_runs ORDER BY id DESC LIMIT 10`).all(),
    db.prepare(`SELECT race_id AS raceId, race_date AS raceDate, venue, race_no AS raceNo,
      race_name AS raceName, surface, distance_m AS distanceM,
      start_time_jst AS startTimeJst, race_status AS raceStatus
      FROM races ORDER BY race_date DESC, venue, race_no LIMIT 20`).all()
  ]);
  return {
    ok: true,
    phase: 1,
    counts: {
      races: races?.count ?? 0,
      runners: runners?.count ?? 0,
      results: results?.count ?? 0,
      payouts: payouts?.count ?? 0
    },
    latestRuns: latestRuns.results,
    races: latestRaces.results,
    now: new Date().toISOString()
  };
}

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export async function renderDashboard(db: D1Database, phase0Status: unknown): Promise<string> {
  const phase1 = await getPhase1Status(db) as {
    counts: { races: number; runners: number; results: number; payouts: number };
    latestRuns: Array<Record<string, unknown>>;
    races: Array<Record<string, unknown>>;
  };
  const raceCards = phase1.races.length === 0
    ? '<div class="empty">Phase 1の自動取得結果を待っています。</div>'
    : phase1.races.map((race) => `<article class="race-card">
        <div class="race-meta">${escapeHtml(race.raceDate)}　${escapeHtml(race.venue)} ${escapeHtml(race.raceNo)}R</div>
        <h2>${escapeHtml(race.raceName)}</h2>
        <div>${escapeHtml(race.surface)} ${escapeHtml(race.distanceM)}m　発走 ${escapeHtml(race.startTimeJst)}</div>
        <div class="status">${escapeHtml(race.raceStatus)}</div>
      </article>`).join("");
  const latest = phase1.latestRuns[0];
  const pilotMessage = latest
    ? `${Number(latest.ok) === 1 ? "取得成功" : "取得失敗"}：${escapeHtml(latest.raceId ?? latest.error)}`
    : "未実行";

  return `<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>レース探偵</title><style>
:root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#111827;background:#f5f7fb}
*{box-sizing:border-box}body{margin:0}.wrap{max-width:860px;margin:auto;padding:20px 16px 56px}
header{padding:14px 0 22px}h1{font-size:28px;margin:0 0 6px}.sub{color:#64748b}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:14px 0 24px}
.metric,.race-card,.panel,.empty{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:16px;box-shadow:0 4px 16px rgba(15,23,42,.04)}
.metric strong{display:block;font-size:26px;margin-top:4px}.label,.race-meta{font-size:13px;color:#64748b}
.panel{margin-bottom:18px}.panel h2,.race-card h2{font-size:18px;margin:5px 0 10px}.status{display:inline-block;margin-top:10px;padding:5px 9px;border-radius:999px;background:#eef2ff;color:#3730a3;font-size:12px}
.races{display:grid;gap:12px}.empty{color:#64748b}code{white-space:pre-wrap;word-break:break-word;font-size:11px;color:#475569}
@media(min-width:700px){.grid{grid-template-columns:repeat(4,minmax(0,1fr))}.races{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style></head><body><main class="wrap">
<header><h1>レース探偵</h1><div class="sub">自動競馬予想・成績共有サイト／開発中</div></header>
<section class="grid">
<div class="metric"><span class="label">登録レース</span><strong>${phase1.counts.races}</strong></div>
<div class="metric"><span class="label">出走馬</span><strong>${phase1.counts.runners}</strong></div>
<div class="metric"><span class="label">着順データ</span><strong>${phase1.counts.results}</strong></div>
<div class="metric"><span class="label">払戻データ</span><strong>${phase1.counts.payouts}</strong></div>
</section>
<section class="panel"><div class="label">Phase 1 パイロット</div><h2>${pilotMessage}</h2><div class="sub">出馬表・結果・払戻を手入力なしで保存する検証です。</div></section>
<section><h2>取得済みレース</h2><div class="races">${raceCards}</div></section>
<details class="panel" style="margin-top:20px"><summary>Phase 0 技術情報</summary><code>${escapeHtml(JSON.stringify(phase0Status, null, 2))}</code></details>
</main></body></html>`;
}
