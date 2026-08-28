import { safeRaceName } from "./race-display.js";
import { response, shell } from "./public-ui.js";
import { escapeHtml } from "./utils.js";

export const UPCOMING_DETAIL_PATH_VERSION = "upcoming-detail-direct-d1-v1-20260829";

type RaceRow = {
  raceId: string;
  raceDate: string;
  venue: string;
  raceNo: number;
  raceName: string | null;
  startTimeJst: string | null;
  startTimeUtc: string | null;
  surface: string | null;
  distanceM: number | null;
  conditions: string | null;
  direction: string | null;
  weather: string | null;
  trackCondition: string | null;
  status: string;
  selectionValue: string | null;
  previousRaceId: string | null;
  nextRaceId: string | null;
};

type RunnerRow = {
  horseNo: number;
  frameNo: number | null;
  horseName: string;
  sexAge: string | null;
  horseWeight: number | null;
  weightChange: number | null;
  jockey: string | null;
  assignedWeight: number | null;
  trainer: string | null;
  stable: string | null;
  winOdds: number | null;
  popularity: number | null;
  runnerStatus: string;
};

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function selectionState(selectionValue: string | null, raceId: string): { hasSelection: boolean; selected: boolean } {
  if (!selectionValue) return { hasSelection: false, selected: false };
  try {
    const parsed = JSON.parse(selectionValue) as { selected?: Array<{ raceId?: unknown }> };
    if (!Array.isArray(parsed.selected)) return { hasSelection: false, selected: false };
    return {
      hasSelection: true,
      selected: parsed.selected.some((row) => String(row?.raceId ?? "") === raceId),
    };
  } catch {
    return { hasSelection: false, selected: false };
  }
}

function runnerStatusLabel(value: string): string {
  const status = String(value ?? "").toLowerCase();
  if (!status || status === "active" || status === "runner") return "";
  return ` <span class="muted">(${escapeHtml(value)})</span>`;
}

function navHtml(race: RaceRow): string {
  const previous = race.previousRaceId
    ? `<a href="/races/${encodeURIComponent(race.previousRaceId)}">← 前のレース</a>`
    : `<span></span>`;
  const next = race.nextRaceId
    ? `<a href="/races/${encodeURIComponent(race.nextRaceId)}">次のレース →</a>`
    : `<span></span>`;
  return `<nav class="race-detail-tabs"><a href="/">レース一覧</a>${previous}${next}</nav>`;
}

function fastStyles(): string {
  return `<style>
    .race-detail-tabs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin:0 0 12px}.race-detail-tabs a,.race-detail-tabs span{min-height:38px;display:flex;align-items:center;justify-content:center;padding:8px 10px;border:1px solid var(--line);border-radius:11px;background:var(--panel2);font-size:12px;text-align:center}.race-detail-tabs span{visibility:hidden}
    .status.target{background:#15483a;color:#baf4dd;border:1px solid #2d806c}.upcoming-detail-note{font-size:12px;padding:11px 13px}.runner-table td:first-child{white-space:nowrap}.fast-detail-source{margin-top:7px;font-size:9px;color:var(--muted)}
    @media(max-width:760px){.race-detail-tabs{grid-template-columns:1fr 1fr 1fr;gap:5px}.race-detail-tabs a{font-size:10px;padding:7px 4px}.runner-table table{min-width:680px}.hero{padding:14px!important}.hero h1{font-size:22px!important}}
  </style>`;
}

function renderRace(race: RaceRow, runners: RunnerRow[]): Response {
  const selection = selectionState(race.selectionValue, race.raceId);
  const state = selection.selected
    ? { code: "target", label: "買い目対象", message: "最終計算前です。「買い目確定」と表示されるまでは確定買い目ではありません。" }
    : selection.hasSelection
      ? { code: "skip", label: "見送り", message: "このレースは今回の購入対象に選ばれていません。" }
      : { code: "pending", label: "判定中", message: "購入対象レースの判定前です。" };

  const raceName = safeRaceName(race.raceName, Number(race.raceNo), race.conditions);
  const meta = [
    race.raceDate.replaceAll("-", "/"), race.venue, `${race.raceNo}R`,
    race.startTimeJst ? `${race.startTimeJst}発走` : null,
    race.surface, race.distanceM ? `${race.distanceM}m` : null,
    race.trackCondition,
  ].filter(Boolean).join("　");

  const runnerRows = runners.map((r) => `<tr>
    <td><span class="horse-no">${Number(r.horseNo)}</span>${runnerStatusLabel(r.runnerStatus)}</td>
    <td><b>${escapeHtml(r.horseName)}</b></td>
    <td>${escapeHtml(r.sexAge ?? "—")}</td>
    <td>${escapeHtml(r.jockey ?? "—")}${r.assignedWeight === null ? "" : `<br><span class="muted">${Number(r.assignedWeight)}kg</span>`}</td>
    <td>${escapeHtml(r.trainer ?? "—")}</td>
    <td>${r.horseWeight === null ? "—" : `${Number(r.horseWeight)}kg${r.weightChange === null ? "" : ` (${Number(r.weightChange) >= 0 ? "+" : ""}${Number(r.weightChange)})`}`}</td>
    <td>${r.winOdds === null ? "—" : `${Number(r.winOdds)}倍`}</td>
    <td>${r.popularity === null ? "—" : `${Number(r.popularity)}番人気`}</td>
  </tr>`).join("");

  const body = `${navHtml(race)}
    <section class="hero"><div class="race-title"><span class="race-no">${Number(race.raceNo)}R</span><h1>${escapeHtml(raceName)}</h1><span class="status ${state.code}">${state.label}</span></div><p>${escapeHtml(meta)}</p>${race.conditions ? `<p>${escapeHtml(race.conditions)}</p>` : ""}</section>
    <div class="section-title"><h2>予想（確定前）</h2><span class="status ${state.code}">${state.label}</span></div><div class="notice upcoming-detail-note">${escapeHtml(state.message)}</div>
    <div class="section-title"><h2>出走馬</h2><span class="muted">${runners.length}頭</span></div><div class="runner-table"><table><thead><tr><th>馬番</th><th>馬名</th><th>性齢</th><th>騎手</th><th>調教師</th><th>馬体重</th><th>単勝</th><th>人気</th></tr></thead><tbody>${runnerRows}</tbody></table></div>
    <div class="fast-detail-source">表示データ: 正本D1（未来レース高速読込）</div>`;

  let html = shell(`${race.venue}${race.raceNo}R`, body);
  html = html.replace("</head>", `${fastStyles()}</head>`);
  const out = response(html);
  const headers = new Headers(out.headers);
  headers.set("x-race-upcoming-detail-path", UPCOMING_DETAIL_PATH_VERSION);
  return new Response(out.body, { status: out.status, statusText: out.statusText, headers });
}

export async function fastUpcomingRaceDetailResponse(db: D1Database, raceId: string, now = new Date()): Promise<Response | null> {
  const raceDate = raceId.slice(0, 10);
  if (!/^20\d{2}-\d{2}-\d{2}$/.test(raceDate) || raceDate <= jstDate(now)) return null;

  const [race, runners] = await Promise.all([
    db.prepare(`
      SELECT r.race_id AS raceId,r.race_date AS raceDate,r.venue,r.race_no AS raceNo,r.race_name AS raceName,
             r.start_time_jst AS startTimeJst,r.start_time_utc AS startTimeUtc,r.surface,r.distance_m AS distanceM,
             r.conditions,r.direction,r.weather,r.track_condition AS trackCondition,r.status,
             (SELECT state_value FROM rt_system_state s WHERE s.state_key='final_daily_selection:'||r.race_date LIMIT 1) AS selectionValue,
             (SELECT p.race_id FROM rt_races p WHERE p.race_date=r.race_date AND p.venue=r.venue AND p.race_no<r.race_no ORDER BY p.race_no DESC LIMIT 1) AS previousRaceId,
             (SELECT n.race_id FROM rt_races n WHERE n.race_date=r.race_date AND n.venue=r.venue AND n.race_no>r.race_no ORDER BY n.race_no ASC LIMIT 1) AS nextRaceId
      FROM rt_races r WHERE r.race_id=? LIMIT 1
    `).bind(raceId).first<RaceRow>(),
    db.prepare(`
      SELECT horse_no AS horseNo,frame_no AS frameNo,horse_name AS horseName,sex_age AS sexAge,
             horse_weight AS horseWeight,weight_change AS weightChange,jockey,assigned_weight AS assignedWeight,
             trainer,stable,win_odds AS winOdds,popularity,runner_status AS runnerStatus
      FROM rt_runners WHERE race_id=? ORDER BY horse_no
    `).bind(raceId).all<RunnerRow>(),
  ]);

  if (!race) return null;
  race.raceNo = Number(race.raceNo);
  race.distanceM = race.distanceM === null ? null : Number(race.distanceM);
  const normalizedRunners = runners.results.map((row) => ({
    ...row,
    horseNo: Number(row.horseNo),
    frameNo: row.frameNo === null ? null : Number(row.frameNo),
    horseWeight: row.horseWeight === null ? null : Number(row.horseWeight),
    weightChange: row.weightChange === null ? null : Number(row.weightChange),
    assignedWeight: row.assignedWeight === null ? null : Number(row.assignedWeight),
    winOdds: row.winOdds === null ? null : Number(row.winOdds),
    popularity: row.popularity === null ? null : Number(row.popularity),
  }));
  return renderRace(race, normalizedRunners);
}
