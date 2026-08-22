import { WIN5_PAGE_URL, WIN5_VERSION, type Win5Target, type Win5TargetCache } from "./completed-win5";
import { decodeJraHtml, jraPageText } from "./jra-official-odds";

const TARGET_PREFIX = "win5:targets:";
const TARGET_CACHE_MS = 10 * 60 * 1000;
const USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136 Safari/537.36";
const VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉";

type StateRow = { value: string };
type RaceTimeRow = { raceId: string; raceName: string | null; startTimeUtc: string | null };

export type Win5TargetIdentity = {
  leg: 1 | 2 | 3 | 4 | 5;
  raceDate: string;
  venue: string;
  raceNo: number;
};

function stateKey(date: string): string { return `${TARGET_PREFIX}${date}`; }

function startTimeJstFromUtc(value: string): string {
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) throw new Error(`WIN5_TARGET_START_TIME_INVALID:${value}`);
  return new Date(ms + 9 * 60 * 60 * 1000).toISOString().slice(11, 16);
}

function cacheHasFiveHydratedTargets(value: Win5TargetCache | null, date: string): value is Win5TargetCache {
  return Boolean(value
    && value.version === 1
    && value.date === date
    && value.targets.length === 5
    && value.targets.every((row, index) =>
      row.leg === index + 1
      && row.raceDate === date
      && Number.isInteger(row.raceNo)
      && row.raceNo >= 1
      && row.raceNo <= 12
      && Number.isFinite(Date.parse(row.startTimeUtc))));
}

function cacheFresh(value: Win5TargetCache | null, date: string, now: Date): value is Win5TargetCache {
  return cacheHasFiveHydratedTargets(value, date)
    && Number.isFinite(Date.parse(value.fetchedAt))
    && now.getTime() - Date.parse(value.fetchedAt) < TARGET_CACHE_MS;
}

async function loadCache(db: D1Database, date: string): Promise<Win5TargetCache | null> {
  const row = await db.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
    .bind(stateKey(date)).first<StateRow>();
  if (!row?.value) return null;
  try { return JSON.parse(row.value) as Win5TargetCache; } catch { return null; }
}

async function saveCache(db: D1Database, date: string, value: Win5TargetCache): Promise<void> {
  await db.prepare(`
    INSERT INTO rt_system_state(state_key,state_value,updated_at)
    VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
  `).bind(stateKey(date), JSON.stringify(value)).run();
}

export function parseWin5TargetIdentitiesFromHtml(pageHtml: string, date: string): Win5TargetIdentity[] {
  if (!/^20\d{2}-\d{2}-\d{2}$/.test(date)) return [];
  const month = Number(date.slice(5, 7));
  const day = Number(date.slice(8, 10));
  const marker = `${month}月${day}日`;
  const text = jraPageText(pageHtml);
  const markerIndex = text.indexOf(marker);
  if (markerIndex < 0) return [];

  const afterMarker = text.slice(markerIndex + marker.length);
  const nextDateIndex = afterMarker.search(/\d{1,2}月\d{1,2}日/);
  const section = nextDateIndex < 0
    ? text.slice(markerIndex, Math.min(text.length, markerIndex + 2500))
    : text.slice(markerIndex, markerIndex + marker.length + nextDateIndex);

  const pattern = new RegExp(`(${VENUES})\\s*(\\d{1,2})\\s*[RＲ]`, "g");
  const found: Win5TargetIdentity[] = [];
  const seen = new Set<string>();
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(section)) !== null && found.length < 5) {
    const venue = match[1];
    const raceNo = Number(match[2]);
    if (!Number.isInteger(raceNo) || raceNo < 1 || raceNo > 12) continue;
    const signature = `${venue}:${raceNo}`;
    if (seen.has(signature)) continue;
    seen.add(signature);
    found.push({
      leg: (found.length + 1) as 1 | 2 | 3 | 4 | 5,
      raceDate: date,
      venue,
      raceNo,
    });
  }
  return found.length === 5 ? found : [];
}

async function fetchOfficialIdentities(date: string): Promise<{ sourceUrl: string; identities: Win5TargetIdentity[] }> {
  const response = await fetch(WIN5_PAGE_URL, {
    headers: {
      "User-Agent": USER_AGENT,
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "ja-JP,ja;q=0.9",
      "Cache-Control": "no-cache",
      "Referer": "https://www.jra.go.jp/",
    },
    redirect: "follow",
  });
  if (!response.ok) throw new Error(`WIN5_TARGET_IDENTITY_HTTP_${response.status}`);
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength > 4_000_000) throw new Error("WIN5_TARGET_IDENTITY_BODY_TOO_LARGE");
  const html = decodeJraHtml(bytes, response.headers.get("content-type"));
  return {
    sourceUrl: response.url || WIN5_PAGE_URL,
    identities: parseWin5TargetIdentitiesFromHtml(html, date),
  };
}

async function hydrateFromRaceTable(db: D1Database, identities: Win5TargetIdentity[]): Promise<Win5Target[]> {
  const targets: Win5Target[] = [];
  for (const identity of identities) {
    const row = await db.prepare(`
      SELECT race_id AS raceId,race_name AS raceName,start_time_utc AS startTimeUtc
      FROM rt_races
      WHERE race_date=? AND venue=? AND race_no=?
      LIMIT 1
    `).bind(identity.raceDate, identity.venue, identity.raceNo).first<RaceTimeRow>();
    const startTimeUtc = String(row?.startTimeUtc || "");
    if (!row?.raceId || !Number.isFinite(Date.parse(startTimeUtc))) {
      throw new Error(`WIN5_TARGET_RACE_TIME_MISSING:${identity.raceDate}:${identity.venue}:${identity.raceNo}`);
    }
    targets.push({
      ...identity,
      startTimeJst: startTimeJstFromUtc(startTimeUtc),
      startTimeUtc,
      raceId: row.raceId,
      raceName: row.raceName || `${identity.raceNo}R`,
    });
  }
  return targets;
}

export async function ensureWin5OfficialTargetCache(
  db: D1Database,
  date: string,
  now = new Date(),
  forceRefresh = false,
): Promise<Win5TargetCache | null> {
  const cached = await loadCache(db, date);
  if (!forceRefresh && cacheFresh(cached, date, now)) return cached;

  try {
    const official = await fetchOfficialIdentities(date);
    // No row for this date means JRA has no published WIN5 target set. Keep the
    // worker quiet on genuine non-WIN5 days; Sunday readiness separately makes
    // a missing published row a hard operational failure once the morning gate opens.
    if (official.identities.length === 0) return cacheHasFiveHydratedTargets(cached, date) ? cached : null;
    const targets = await hydrateFromRaceTable(db, official.identities);
    const next: Win5TargetCache = {
      version: WIN5_VERSION,
      date,
      fetchedAt: now.toISOString(),
      sourceUrl: official.sourceUrl,
      targets,
    };
    await saveCache(db, date, next);
    return next;
  } catch (error) {
    if (cacheHasFiveHydratedTargets(cached, date)) {
      console.error("WIN5_TARGET_REPAIR_REFRESH_FAILED_USING_CACHE", date, error);
      return cached;
    }
    throw error;
  }
}
