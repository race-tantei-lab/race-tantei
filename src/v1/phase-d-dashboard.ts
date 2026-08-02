import { getCourseMetrics, type CourseMetric } from "./course-db.js";
import { getPhaseCDashboard } from "./phase-c-dashboard.js";
import type { BudgetCourse } from "./types.js";
import { escapeHtml, formatYen } from "./utils.js";
import { getValidationSnapshot, type CourseValidationSummary } from "./validation.js";

const COURSES: Array<{ name: BudgetCourse }> = [
  { name: "ライト" },
  { name: "スタンダード" },
  { name: "プレミアム" }
];

interface DisplayMetric {
  course: BudgetCourse;
  races: number;
  hits: number;
  stake: number;
  returns: number;
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
  return `<a class="metric" href="/performance">
    <div class="metric-head"><b>${escapeHtml(metric.course)}</b></div>
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

  const replacement = `<div class="section-label"><h2>総合成績</h2><span>過去レース＋本番を合算${historicalComplete ? "" : "・過去分集計中"}</span></div>
    <section class="metrics">${cards}</section>`;
  return `${html.slice(0, start)}${replacement}${html.slice(end + "</section>".length)}`;
}

function markSelectedCards(html: string): string {
  let next = html.replace(
    /<a class="race-card" data-race-category="buy"/g,
    '<a class="race-card" data-race-selected="true" data-race-category="buy"'
  );
  next = next.replace(/<a class="race-card" data-race-category="finished"[\s\S]*?<\/a>/g, (card) => {
    const historical = card.includes("フェーズC遡及検証");
    const selected = historical && !card.includes("status skip") && !card.includes("検証計算中");
    if (!selected) return card;
    return card.replace(
      '<a class="race-card" data-race-category="finished"',
      '<a class="race-card" data-race-selected="true" data-race-category="buy finished"'
    );
  });
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
    getValidationSnapshot(db)
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
    .replace("本番成績と遡及検証を分離し、期待値基準未達は見送ります。", "各会場から原則5Rを選出し、過去レースと本番を同じ総合成績に合算します。")
    .replace("各会場から原則5Rを選出し、期待値厳選と会場上位補完を分けて集計します。", "各会場から原則5Rを選出し、過去レースと本番を同じ総合成績に合算します。")
    .replace("<title>レース探偵｜フェーズC</title>", "<title>レース探偵｜会場別5R・総合成績</title>")
    .replace("<title>レース探偵｜会場別5R選出</title>", "<title>レース探偵｜会場別5R・総合成績</title>");
  return injectSelectionCountScript(html);
}
