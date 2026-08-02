import { getCourseMetrics, type CourseMetric } from "./course-db.js";
import { getPhaseCDashboard } from "./phase-c-dashboard.js";
import { getThreeMonthValidationSnapshot } from "./three-month-validation.js";
import type { BudgetCourse } from "./types.js";
import { escapeHtml, formatYen } from "./utils.js";
import type { CourseValidationSummary } from "./validation.js";

const COURSES: Array<{ name: BudgetCourse }> = [
  { name: "ライト" },
  { name: "スタンダード" },
  { name: "プレミアム" }
];

const MAX_SELECTED_RACES_PER_VENUE = 5;

interface DisplayMetric {
  course: BudgetCourse;
  races: number;
  hits: number;
  stake: number;
  returns: number;
}

interface RaceCardMatch {
  card: string;
  index: number;
  category: string;
  historical: boolean;
}

function signedYen(value: number): string {
  return `${value >= 0 ? "+" : ""}${formatYen(value)}`;
}

function fromLive(row: CourseMetric): DisplayMetric {
  return {
    course: row.course,
    races: row.settledRaces,
    hits: row.hitRatePct === null ? 0 : Math.round(row.settledRaces * row.hitRatePct / 100),
    stake: row.stakeYen,
    returns: row.returnYen
  };
}

function fromValidation(row: CourseValidationSummary): DisplayMetric {
  return {
    course: row.course,
    races: row.selectedRaces,
    hits: row.hitRaces,
    stake: row.stakeYen,
    returns: row.returnYen
  };
}

function combine(live: DisplayMetric, historical: DisplayMetric): DisplayMetric {
  return {
    course: live.course,
    races: live.races + historical.races,
    hits: live.hits + historical.hits,
    stake: live.stake + historical.stake,
    returns: live.returns + historical.returns
  };
}

function metricCard(metric: DisplayMetric): string {
  const roi = metric.stake > 0 ? metric.returns / metric.stake * 100 : null;
  const profit = metric.returns - metric.stake;
  const averageStake = metric.races > 0 ? Math.round(metric.stake / metric.races) : null;
  return `<a class="metric" href="/performance">
    <div class="metric-head"><b>${escapeHtml(metric.course)}</b><span>${averageStake === null ? "平均購入 —" : `平均購入 ${formatYen(averageStake)}/R`}</span></div>
    <strong>${roi === null ? "—" : `${roi.toFixed(1)}%`}</strong>
    <small>${metric.hits}/${metric.races}R的中　${formatYen(metric.stake)} → ${formatYen(metric.returns)}</small>
    <em class="${profit >= 0 ? "plus" : "minus"}">${signedYen(profit)}</em>
  </a>`;
}

function replaceMetricArea(
  html: string,
  combined: DisplayMetric[],
  historicalComplete: boolean
): string {
  const start = html.indexOf('<div class="section-label">');
  const metricsStart = html.indexOf('<section class="metrics">', start);
  const end = html.indexOf("</section>", metricsStart);
  if (start < 0 || metricsStart < 0 || end < 0) return html;

  const cards = COURSES.map(({ name }) => metricCard(
    combined.find((row) => row.course === name) ?? { course: name, races: 0, hits: 0, stake: 0, returns: 0 }
  )).join("");

  const replacement = `<div class="section-label"><h2>累計回収率</h2><span>過去3ヶ月＋本番を合算${historicalComplete ? "" : "・過去分集計中"}</span></div>
    <section class="metrics">${cards}</section>`;
  return `${html.slice(0, start)}${replacement}${html.slice(end + "</section>".length)}`;
}

function categoryTokens(category: string): string[] {
  return category.split(/\s+/).filter(Boolean);
}

function isHistoricalCard(card: string): boolean {
  return card.includes('class="retro"') || card.includes("遡及検証");
}

function hasSettledCourseResult(card: string): boolean {
  return card.includes('class="course-result')
    && !card.includes("status skip")
    && !card.includes("検証計算中")
    && !card.includes("結果反映中");
}

function markCardSelected(card: string): string {
  let next = card.replace(/\sdata-race-selected="true"/g, "");
  const category = next.match(/data-race-category="([^"]+)"/)?.[1] ?? "other";
  const tokens = categoryTokens(category);
  if (!tokens.includes("buy")) tokens.unshift("buy");
  next = next.replace(/data-race-category="[^"]+"/, `data-race-category="${tokens.join(" ")}"`);
  return next.replace(
    '<a class="race-card"',
    '<a class="race-card" data-race-selected="true"'
  );
}

function cleanUnselectedCard(card: string, historical: boolean): string {
  let next = card.replace(/\sdata-race-selected="true"/g, "");
  if (!historical) return next;
  const category = next.match(/data-race-category="([^"]+)"/)?.[1];
  if (!category) return next;
  const tokens = categoryTokens(category).filter((token) => token !== "buy");
  return next.replace(
    /data-race-category="[^"]+"/,
    `data-race-category="${tokens.length > 0 ? tokens.join(" ") : "finished"}"`
  );
}

function selectVenueCards(panel: string): string {
  const cardPattern = /<a class="race-card"[^>]*data-race-category="([^"]+)"[^>]*>[\s\S]*?<\/a>/g;
  const cards: RaceCardMatch[] = [...panel.matchAll(cardPattern)].map((match) => ({
    card: match[0],
    index: match.index ?? 0,
    category: match[1] ?? "other",
    historical: isHistoricalCard(match[0])
  }));
  if (cards.length === 0) return panel;

  const selected = new Set<number>();
  const liveCandidates = cards.filter((item) => {
    if (item.historical) return false;
    const tokens = categoryTokens(item.category);
    return tokens.includes("buy") || (tokens.includes("finished") && hasSettledCourseResult(item.card));
  });
  const historicalCandidates = cards.filter((item) => item.historical && hasSettledCourseResult(item.card));

  for (const candidate of liveCandidates) {
    if (selected.size >= MAX_SELECTED_RACES_PER_VENUE) break;
    selected.add(candidate.index);
  }
  for (const candidate of historicalCandidates) {
    if (selected.size >= MAX_SELECTED_RACES_PER_VENUE) break;
    selected.add(candidate.index);
  }

  let result = "";
  let cursor = 0;
  for (const item of cards) {
    result += panel.slice(cursor, item.index);
    result += selected.has(item.index)
      ? markCardSelected(item.card)
      : cleanUnselectedCard(item.card, item.historical);
    cursor = item.index + item.card.length;
  }
  return result + panel.slice(cursor);
}

export function markSelectedCards(html: string): string {
  const venuePattern = /<section class="venue-panel"[^>]*data-venue-panel="[^"]+"[^>]*>[\s\S]*?<\/section>/g;
  const next = html.replace(venuePattern, (panel) => selectVenueCards(panel));
  return next.replace(
    "card.dataset.raceCategory!==filter",
    "!card.dataset.raceCategory.split(' ').includes(filter)"
  );
}

function injectSelectionCountScript(html: string): string {
  const script = `<script>(()=>{
    const update=()=>{
      document.querySelectorAll('[data-day-panel]').forEach(panel=>{
        const cards=[...panel.querySelectorAll('.race-card')];
        const selected=cards.filter(card=>card.dataset.raceSelected==='true');
        const finished=cards.filter(card=>(card.dataset.raceCategory||'').split(' ').includes('finished'));
        panel.dataset.defaultFilter=selected.length>0?'buy':'all';
        const summary=panel.querySelector('.day-summary p');
        if(summary)summary.textContent='選出レース '+selected.length+'R　終了 '+finished.length+'R';
        const buyButton=panel.querySelector('[data-filter="buy"]');
        if(buyButton){
          const span=buyButton.querySelector('span');
          if(span)span.textContent=String(selected.length);
          const first=buyButton.firstChild;
          if(first)first.textContent='選出レース ';
        }
        panel.querySelectorAll('[data-venue-tab]').forEach(tab=>{
          const venue=tab.dataset.venueTab||'';
          const venuePanel=[...panel.querySelectorAll('[data-venue-panel]')].find(item=>item.dataset.venuePanel===venue);
          const count=venuePanel?[...venuePanel.querySelectorAll('[data-race-selected="true"]')].length:0;
          tab.dataset.buyCount=String(count);
          let badge=tab.querySelector('span');
          if(count>0){if(!badge){badge=document.createElement('span');tab.appendChild(badge)}badge.textContent=String(count)}
          else if(badge)badge.remove();
        });
      });
      const active=document.querySelector('[data-day-tab].active');
      if(active instanceof HTMLElement)active.click();
    };
    update();
  })();</script>`;
  return html.replace("</body>", `${script}</body>`);
}

export async function getPhaseDDashboard(db: D1Database, liveModel: string): Promise<string> {
  let html = await getPhaseCDashboard(db, liveModel);
  const [liveRows, historicalSnapshot] = await Promise.all([
    getCourseMetrics(db, liveModel),
    getThreeMonthValidationSnapshot(db)
  ]);
  const live = COURSES.map(({ name }) => fromLive(
    liveRows.find((row) => row.course === name) ?? {
      course: name,
      settledRaces: 0,
      betCount: 0,
      stakeYen: 0,
      returnYen: 0,
      profitYen: 0,
      roiPct: null,
      hitRatePct: null
    }
  ));
  const historical = COURSES.map(({ name }) => fromValidation(
    historicalSnapshot.combined.find((row) => row.course === name) ?? {
      course: name,
      processedRaces: 0,
      selectedRaces: 0,
      skippedRaces: 0,
      hitRaces: 0,
      tickets: 0,
      pendingTickets: 0,
      stakeYen: 0,
      returnYen: 0,
      profitYen: 0,
      expectedReturnYen: 0,
      roiPct: null,
      expectedRoiPct: null,
      hitRatePct: null,
      byTicketType: []
    }
  ));
  const combined = COURSES.map(({ name }) => combine(
    live.find((row) => row.course === name)!,
    historical.find((row) => row.course === name)!
  ));

  html = replaceMetricArea(html, combined, historicalSnapshot.complete);
  html = markSelectedCards(html)
    .replace(/買い目あり/g, "選出レース")
    .replace("本番成績と遡及検証を分離し、期待値基準未達は見送ります。", "各会場から原則5Rを選出し、過去3ヶ月と本番を同じ総合成績に合算します。")
    .replace("各会場から原則5Rを選出し、期待値厳選と会場上位補完を分けて集計します。", "各会場から原則5Rを選出し、過去3ヶ月と本番を同じ総合成績に合算します。")
    .replace("各会場から原則5Rを選出し、過去レースと本番を同じ総合成績に合算します。", "各会場から原則5Rを選出し、過去3ヶ月と本番を同じ総合成績に合算します。")
    .replace("<title>レース探偵｜フェーズC</title>", "<title>レース探偵｜会場別5R・累計回収率</title>")
    .replace("<title>レース探偵｜会場別5R選出</title>", "<title>レース探偵｜会場別5R・累計回収率</title>")
    .replace("<title>レース探偵｜会場別5R・総合成績</title>", "<title>レース探偵｜会場別5R・累計回収率</title>");
  return injectSelectionCountScript(html);
}
