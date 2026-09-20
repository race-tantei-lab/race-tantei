import { saveResultBundle } from "./db.js";
import { extractResultLinks, fetchJraPage, pageLooksLikeResult, parseEntryPage, parseResultPage, toResultUrl } from "./jra.js";
import { parseJraPayoutsFromHtml } from "./jra-payout-fallback.js";
import type { Env } from "./types.js";

const MAX_CANDIDATES_PER_TICK = 15;
const RESULT_GRACE_MS = 4 * 60 * 1000;
const UNORDERED = new Set(["ワイド", "馬連", "3連複"]);

type Candidate = {
  raceId: string;
  raceDate: string;
  entryUrl: string;
  resultUrl: string | null;
  startTimeUtc: string;
};

type PublicBet = {
  id: number;
  betType: string;
  combination: string;
  stakeYen: number;
};

type PayoutRow = {
  betType: string;
  combination: string;
  payoutYen: number;
};

export type BoundedSettlementAudit = {
  checkedAt: string;
  candidates: string[];
  resultSavedRaceIds: string[];
  settledRaceIds: string[];
  settledRows: number;
  waitingRaceIds: string[];
  errors: Array<{ raceId: string; error: string }>;
};

function errorText(error: unknown): string {
  return error instanceof Error ? `${error.name}:${error.message}` : String(error);
}

function jstDate(now: Date, offsetDays = 0): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000 + offsetDays * 86400_000).toISOString().slice(0, 10);
}

function canonical(betType: string, combination: string): string {
  const nums = (String(combination).match(/\d{1,2}/g) ?? []).map(Number);
  if (UNORDERED.has(betType)) nums.sort((a, b) => a - b);
  return nums.join("-");
}

function jraRaceKey(url: string): string | null {
  try {
    const cname = decodeURIComponent(new URL(url).searchParams.get("CNAME") ?? "");
    const match = cname.match(/(?:pw|sw)01(?:dde01|sde01|sde10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})\//i);
    return match ? match.slice(1, 7).join(":") : null;
  } catch {
    return null;
  }
}

function decodeHref(value: string): string {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&#38;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

function matchingResultUrl(entryHtml: string, entryUrl: string): string | null {
  const targetKey = jraRaceKey(entryUrl);
  if (!targetKey) return null;
  const matches: string[] = [];
  for (const match of entryHtml.matchAll(/href=["']([^"']*accessS\.html[^"']*)["']/gi)) {
    try {
      const href = new URL(decodeHref(match[1] ?? ""), entryUrl).href;
      const cname = decodeURIComponent(new URL(href).searchParams.get("CNAME") ?? "");
      if (/(?:pw|sw)01sde(?:01|10)/i.test(cname) && jraRaceKey(href) === targetKey) matches.push(href);
    } catch {
      // Ignore unrelated or malformed JRA links and keep searching this page.
    }
  }
  if (!matches.length) return null;
  return matches.find((url) => /(?:pw|sw)01sde01/i.test(decodeURIComponent(new URL(url).searchParams.get("CNAME") ?? "")))
    ?? matches[0]
    ?? null;
}

async function pendingCandidates(db: D1Database, now: Date): Promise<Candidate[]> {
  const fromDate = jstDate(now, -1);
  const throughDate = jstDate(now);
  const dueBefore = new Date(now.getTime() - RESULT_GRACE_MS).toISOString();
  const result = await db.prepare(`
    SELECT r.race_id AS raceId,r.race_date AS raceDate,r.entry_url AS entryUrl,r.result_url AS resultUrl,r.start_time_utc AS startTimeUtc
    FROM rt_public_bets b
    JOIN rt_races r ON r.race_id=b.race_id
    WHERE b.source_prediction_id=-2
      AND b.settlement_status='pending'
      AND r.race_date>=? AND r.race_date<=?
      AND r.entry_url IS NOT NULL AND LENGTH(TRIM(r.entry_url))>0
      AND r.start_time_utc IS NOT NULL
      AND datetime(r.start_time_utc)<=datetime(?)
    GROUP BY r.race_id,r.race_date,r.entry_url,r.start_time_utc
    ORDER BY r.start_time_utc,r.race_id
    LIMIT ?
  `).bind(fromDate, throughDate, dueBefore, MAX_CANDIDATES_PER_TICK).all<Candidate>();
  return result.results ?? [];
}

async function settlePublicRows(db: D1Database, raceId: string, refundHorseNos: number[]): Promise<number> {
  const [betResult, payoutResult] = await db.batch([
    db.prepare(`
      SELECT id,bet_type AS betType,combination,stake_yen AS stakeYen
      FROM rt_public_bets
      WHERE race_id=? AND source_prediction_id=-2 AND settlement_status='pending'
      ORDER BY id
    `).bind(raceId),
    db.prepare(`
      SELECT bet_type AS betType,combination,payout_yen AS payoutYen
      FROM rt_payouts WHERE race_id=?
    `).bind(raceId),
  ]);

  const bets = (betResult.results ?? []) as unknown as PublicBet[];
  if (!bets.length) return 0;
  const payouts = (payoutResult.results ?? []) as unknown as PayoutRow[];
  if (!payouts.length) return 0;

  const payoutTypes = new Set(payouts.map((row) => String(row.betType)));
  const payoutMap = new Map(
    payouts.map((row) => [
      `${row.betType}:${canonical(row.betType, row.combination)}`,
      Number(row.payoutYen),
    ]),
  );
  const refunds = new Set(refundHorseNos.map(Number).filter(Number.isInteger));
  const updates: D1PreparedStatement[] = [];

  for (const bet of bets) {
    const horses = (String(bet.combination).match(/\d{1,2}/g) ?? []).map(Number);
    let returnYen: number;
    if (horses.some((horseNo) => refunds.has(horseNo))) {
      returnYen = Number(bet.stakeYen);
    } else {
      if (!payoutTypes.has(String(bet.betType))) continue;
      const payout = payoutMap.get(`${bet.betType}:${canonical(bet.betType, bet.combination)}`) ?? 0;
      returnYen = Math.round(Number(bet.stakeYen) / 100 * payout);
    }
    updates.push(
      db.prepare("UPDATE rt_public_bets SET settlement_status='settled',return_yen=? WHERE id=?")
        .bind(returnYen, Number(bet.id)),
    );
  }
  if (updates.length) await db.batch(updates);
  return updates.length;
}

export async function runBoundedResultSettlement(env: Env, now = new Date()): Promise<BoundedSettlementAudit> {
  const audit: BoundedSettlementAudit = {
    checkedAt: now.toISOString(),
    candidates: [],
    resultSavedRaceIds: [],
    settledRaceIds: [],
    settledRows: 0,
    waitingRaceIds: [],
    errors: [],
  };

  const candidates = await pendingCandidates(env.DB, now);
  audit.candidates = candidates.map((race) => race.raceId);

  for (const race of candidates) {
    try {
      const entry = await fetchJraPage(race.entryUrl);
      const resultUrls: string[] = [];
      const seen = new Set<string>();
      const addResultUrl = (value: string | null | undefined) => {
        if (!value || seen.has(value)) return;
        seen.add(value);
        resultUrls.push(value);
      };

      // Prefer an already persisted official result URL, then use every official
      // link advertised by the entry page, the parsed entry result URL, the
      // legacy same-race matcher, and finally the deterministic JRA conversion.
      // This mirrors the quota-free result renderer and avoids leaving a race
      // pending just because one CNAME/link shape changed after race day.
      addResultUrl(race.resultUrl);
      for (const value of extractResultLinks(entry.html, entry.url)) addResultUrl(value);
      try { addResultUrl(parseEntryPage(entry.html, entry.url).race.resultUrl); } catch { /* keep other candidates */ }
      addResultUrl(matchingResultUrl(entry.html, entry.url));
      addResultUrl(toResultUrl(race.entryUrl));

      let page: Awaited<ReturnType<typeof fetchJraPage>> | null = null;
      let bundle: ReturnType<typeof parseResultPage> | null = null;
      for (const candidate of resultUrls) {
        try {
          const fetched = await fetchJraPage(candidate);
          if (!pageLooksLikeResult(fetched.html)) continue;
          const parsed = parseResultPage(fetched.html, fetched.url);
          if (parsed.race.raceId !== race.raceId || parsed.results.length < 3) continue;

          const payoutMap = new Map<string, (typeof parsed.payouts)[number]>();
          for (const payout of [...parsed.payouts, ...parseJraPayoutsFromHtml(fetched.html)]) {
            const key = `${payout.betType}:${canonical(payout.betType, payout.combination)}`;
            payoutMap.set(key, { ...payout, combination: canonical(payout.betType, payout.combination) });
          }
          const payouts = [...payoutMap.values()];
          if (!payouts.length) continue;

          page = fetched;
          bundle = { ...parsed, payouts };
          break;
        } catch {
          // One stale official candidate must not block the other valid JRA URLs.
        }
      }
      if (!page || !bundle) {
        audit.waitingRaceIds.push(race.raceId);
        continue;
      }

      await saveResultBundle(env.DB, bundle);
      await env.DB.batch([
        env.DB.prepare(`
          UPDATE rt_races
          SET result_url=?,result_updated_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
          WHERE race_id=?
        `).bind(page.url, race.raceId),
        env.DB.prepare(`
          UPDATE rt_race_sources
          SET result_url=?,status='complete',last_result_fetch_at=CURRENT_TIMESTAMP,
              last_error=NULL,updated_at=CURRENT_TIMESTAMP
          WHERE race_id=? AND entry_url=?
        `).bind(page.url, race.raceId, race.entryUrl),
      ]);
      audit.resultSavedRaceIds.push(race.raceId);

      const settled = await settlePublicRows(env.DB, race.raceId, bundle.refundHorseNos ?? []);
      if (settled > 0) {
        audit.settledRaceIds.push(race.raceId);
        audit.settledRows += settled;
      } else {
        audit.waitingRaceIds.push(race.raceId);
      }
    } catch (error) {
      audit.errors.push({ raceId: race.raceId, error: errorText(error) });
    }
  }

  return audit;
}
