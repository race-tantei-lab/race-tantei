import type { RaceListRow } from "./db.js";
import type { CourseMetric } from "./course-db.js";
import { escapeHtml, formatYen } from "./utils.js";

function pct(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}%`;
}

function dateLabel(date: string): string {
  const match = date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return date;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const dayOfMonth = Number(match[3]);
  const weekday = new Date(Date.UTC(year, month - 1, dayOfMonth)).getUTCDay();
  const day = ["日", "月", "火", "水", "木", "金", "土"][weekday] ?? "";
  return `${month}月${dayOfMonth}日（${day}）`;
}

export function renderCourseHome(metrics: CourseMetric[], races: RaceListRow[]): string {
  const courseOrder = ["ライト", "スタンダード", "プレミアム"];
  const budgets: Record<string, string> = { ライト: "2,000円", スタンダード: "5,000円", プレミアム: "10,000円" };
  const metricByCourse = new Map(metrics.map((row) => [row.course, row]));
  const courseCards = courseOrder.map((course) => {
    const row = metricByCourse.get(course as CourseMetric["course"]);
    const stake = row?.stakeYen ?? 0;
    const returns = row?.returnYen ?? 0;
    const profit = row?.profitYen ?? 0;
    const roi = row?.roiPct ?? null;
    return `<section class="course-card"><div class="course-title"><div><span>${escapeHtml(course)}コース</span><b>${budgets[course]}</b></div><strong class="${roi !== null && roi >= 100 ? "plus" : "minus"}">${pct(roi)}</strong></div><div class="course-stats"><div><small>累計購入</small><b>${formatYen(stake)}</b></div><div><small>累計払戻</small><b>${formatYen(returns)}</b></div><div><small>累計収支</small><b class="${profit >= 0 ? "plus" : "minus"}">${profit >= 0 ? "+" : ""}${formatYen(profit)}</b></div><div><small>精算レース</small><b>${row?.settledRaces ?? 0}R</b></div></div></section>`;
  }).join("");

  const grouped = new Map<string, Map<string, RaceListRow[]>>();
  for (const race of [...races].sort((a, b) => a.raceDate.localeCompare(b.raceDate) || a.venue.localeCompare(b.venue, "ja") || a.raceNo - b.raceNo)) {
    const venues = grouped.get(race.raceDate) ?? new Map<string, RaceListRow[]>();
    const rows = venues.get(race.venue) ?? [];
    rows.push(race);
    venues.set(race.venue, rows);
    grouped.set(race.raceDate, venues);
  }

  const dates = [...grouped.keys()];
  const dayNav = dates.map((date) => `<a href="#date-${date}">${escapeHtml(dateLabel(date))}</a>`).join("");
  const raceSections = dates.map((date) => {
    const venues = grouped.get(date)!;
    const venueHtml = [...venues.entries()].map(([venue, rows]) => {
      const cards = rows.map((race) => {
        const finished = race.status === "finished";
        const state = finished ? "結果確定" : race.predictionStatus === "locked" ? "予想公開" : race.predictionStatus === "draft" ? "暫定予想" : "予想待ち";
        const summary = finished ? "着順・コース別払戻を確認" : race.topHorseNo ? `◎ ${race.topHorseNo} ${escapeHtml(race.topHorseName)}` : "予想データ準備中";
        return `<a class="race-card" href="/races/${encodeURIComponent(race.raceId)}"><div><strong>${race.raceNo}R</strong><small>${escapeHtml(race.startTimeJst ?? "時刻未定")}</small></div><div><b>${escapeHtml(race.raceName)}</b><small>${summary}</small></div><span>${state}</span></a>`;
      }).join("");
      return `<section class="venue"><div class="venue-head"><h3>${escapeHtml(venue)}競馬場</h3><span>${rows.length}レース</span></div>${cards}</section>`;
    }).join("");
    return `<section class="date" id="date-${date}"><h2>${escapeHtml(dateLabel(date))}</h2><p>${escapeHtml(date)} ／ ${[...venues.values()].reduce((sum, rows) => sum + rows.length, 0)}レース</p>${venueHtml}</section>`;
  }).join("");

  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0b0f14"><title>予想一覧｜レース探偵</title><style>
  :root{color-scheme:dark;--bg:#0b0f14;--panel:#121923;--line:#293649;--text:#eef3f8;--muted:#9fb0c2;--green:#4fd1a1;--red:#ff7b72}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#091018,#0b0f14);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:980px;margin:auto;padding:16px}a{color:inherit;text-decoration:none}.top{display:flex;justify-content:space-between;align-items:center;padding:12px 0 20px}.brand{font-size:22px;font-weight:900}.brand span{color:var(--green)}nav{display:flex;gap:8px;overflow:auto}nav a{white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:8px 11px;background:#111925;font-size:13px}.hero{padding:22px;background:linear-gradient(135deg,#172638,#10241e);border:1px solid #2b5448;border-radius:20px}.hero h1{font-size:28px;margin:8px 0}.hero p{margin:0;color:var(--muted)}.course-grid{display:grid;gap:12px;margin:16px 0 26px}.course-card{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:16px}.course-title{display:flex;justify-content:space-between;align-items:center}.course-title span{display:block;color:var(--muted)}.course-title b{font-size:20px}.course-title strong{font-size:29px}.course-stats{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:14px}.course-stats div{background:#0d141d;border-radius:11px;padding:10px}.course-stats small{display:block;color:var(--muted)}.course-stats b{display:block;margin-top:3px}.plus{color:var(--green)}.minus{color:var(--red)}.day-nav{display:flex;gap:8px;overflow:auto;margin:10px 0 18px}.day-nav a{white-space:nowrap;border:1px solid var(--line);border-radius:10px;padding:9px 12px;background:#101925}.date{margin:28px 0}.date>h2{margin:0;font-size:27px}.date>p{margin:3px 0 15px;color:var(--muted)}.venue{margin:16px 0 24px}.venue-head{display:flex;justify-content:space-between;align-items:center}.venue-head h3{font-size:20px}.venue-head span{color:var(--muted)}.race-card{display:grid;grid-template-columns:70px 1fr auto;gap:11px;align-items:center;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:13px;margin:8px 0}.race-card strong{font-size:19px;color:var(--green)}.race-card small{display:block;color:var(--muted)}.race-card>span{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:4px 8px}.footer{color:var(--muted);font-size:12px;padding:30px 3px 50px}@media(min-width:760px){.course-grid{grid-template-columns:repeat(3,1fr)}.course-stats{grid-template-columns:1fr 1fr}.wrap{padding:24px}}@media(max-width:620px){.race-card{grid-template-columns:62px 1fr}.race-card>span{grid-column:2;justify-self:start}}
  </style></head><body><main class="wrap"><div class="top"><a class="brand" href="/"><span>レース</span>探偵</a><nav><a href="/">予想</a><a href="/performance">成績</a><a href="/methodology">予想方法</a><a href="/system">稼働状況</a></nav></div><section class="hero"><p>● 全自動・公開予想記録</p><h1>日付と競馬場からレースを選ぶ。</h1><p>回収率・購入・払戻・収支は、3つの予算コースを混ぜずに表示します。</p></section><div class="course-grid">${courseCards}</div>${dayNav ? `<h2>開催日</h2><div class="day-nav">${dayNav}</div>` : ""}${raceSections || "<p>レースデータを取得中です。</p>"}<footer class="footer">本サイトは非公式の予想記録サイトです。的中や利益を保証しません。</footer></main></body></html>`;
}
