import type { DashboardMetrics } from "./types.js";
import type { RaceDetail, RaceListRow } from "./db.js";
import { escapeHtml, formatYen } from "./utils.js";

const CSS = `
:root{color-scheme:dark;--bg:#0b0f14;--panel:#121923;--panel2:#182231;--line:#293649;--text:#eef3f8;--muted:#9fb0c2;--accent:#4fd1a1;--danger:#ff7b72;--gold:#ffd166}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#091018,#0b0f14 45%);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif;line-height:1.55}
a{color:inherit;text-decoration:none}.wrap{max-width:980px;margin:auto;padding:16px}.top{display:flex;align-items:center;justify-content:space-between;padding:12px 0 18px}.brand{font-weight:900;font-size:22px;letter-spacing:.03em}.brand span{color:var(--accent)}nav{display:flex;gap:8px;overflow:auto;padding-bottom:4px}nav a{white-space:nowrap;padding:8px 11px;background:#111925;border:1px solid var(--line);border-radius:999px;font-size:13px}.hero{padding:20px;background:linear-gradient(135deg,#172638,#10241e);border:1px solid #2b5448;border-radius:20px;margin-bottom:14px}.hero h1{font-size:27px;margin:0 0 7px}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.metric,.card{background:rgba(18,25,35,.94);border:1px solid var(--line);border-radius:16px;padding:15px}.metric b{display:block;font-size:22px;margin-top:4px}.section{margin:22px 0 10px;font-size:18px}.race{display:grid;grid-template-columns:72px 1fr auto;gap:12px;align-items:center;margin-bottom:9px}.race .no{font-weight:900;font-size:18px}.pill{display:inline-block;border-radius:999px;padding:3px 8px;font-size:12px;border:1px solid var(--line);color:var(--muted)}.pill.locked{color:#8df0cc;border-color:#347a65}.pill.finished{color:#ffd89a;border-color:#76613a}.right{text-align:right}.positive{color:var(--accent)}.negative{color:var(--danger)}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:10px 7px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--muted);font-weight:600}.horse-no{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:7px;background:#e8edf2;color:#101820;font-weight:900;margin-right:7px}.buy{border-color:#516d42;background:#162416}.warning{border-color:#6e5730;background:#251e12}.error{border-color:#74403d;background:#271817}.tabs{display:flex;gap:8px;margin:12px 0}.bar{height:7px;border-radius:9px;background:#263242;overflow:hidden;margin-top:5px}.bar i{display:block;height:100%;background:var(--accent)}.footer{font-size:12px;color:var(--muted);padding:32px 4px 50px}.empty{text-align:center;padding:34px 15px;color:var(--muted)}code{word-break:break-all;background:#0b111a;padding:2px 5px;border-radius:5px}.status-dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--accent);margin-right:6px}@media(min-width:700px){.grid{grid-template-columns:repeat(4,1fr)}.wrap{padding:24px}.hero{padding:28px}.race{grid-template-columns:100px 1fr 180px}}
`;

function layout(title: string, body: string): string {
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0b0f14"><title>${escapeHtml(title)}｜レース探偵</title><style>${CSS}</style></head><body><main class="wrap"><div class="top"><a class="brand" href="/"><span>レース</span>探偵</a><nav><a href="/">予想</a><a href="/performance">成績</a><a href="/methodology">予想方法</a><a href="/system">稼働状況</a></nav></div>${body}<footer class="footer">本サイトは独自の統計モデルによる非公式の予想記録サイトで、JRAおよび関係団体とは関係ありません。的中や利益を保証しません。表示する収支は発走前にロックされたモデル買い目を購入したと仮定した成績です。馬券は20歳になってから、無理のない範囲でお楽しみください。</footer></main></body></html>`;
}

function pct(value: number | null, digits = 1): string {
  return value === null ? "—" : `${value.toFixed(digits)}%`;
}

export function renderHome(metrics: DashboardMetrics, races: RaceListRow[]): string {
  const raceCards = races.map((race) => `
    <a class="card race" href="/races/${encodeURIComponent(race.raceId)}">
      <div><div class="muted">${escapeHtml(race.venue)}</div><div class="no">${race.raceNo}R</div><div class="muted">${escapeHtml(race.startTimeJst ?? "")}</div></div>
      <div><b>${escapeHtml(race.raceName)}</b><div class="muted">${race.topHorseNo ? `予想1位 ${race.topHorseNo} ${escapeHtml(race.topHorseName)}` : "予想計算待ち"}</div></div>
      <div class="right"><span class="pill ${race.predictionStatus === "locked" ? "locked" : race.status === "finished" ? "finished" : ""}">${race.predictionStatus === "locked" ? "発走前固定済み" : race.status === "finished" ? "結果確定" : race.predictionStatus === "draft" ? "暫定" : "待機"}</span><div class="muted">買い目 ${race.betCount}</div></div>
    </a>`).join("");
  return layout("本日の予想", `
    <section class="hero"><div class="muted"><span class="status-dot"></span>全自動・公開予想記録</div><h1>回収率100％超を、全履歴で検証する。</h1><div class="muted">出馬表取得、確率計算、発走前ロック、結果・払戻、回収率集計まで自動処理します。</div></section>
    <section class="grid">
      <div class="metric"><span class="muted">累計回収率</span><b class="${(metrics.roiPct ?? 0) >= 100 ? "positive" : ""}">${pct(metrics.roiPct)}</b></div>
      <div class="metric"><span class="muted">モデル収支</span><b class="${metrics.profitYen >= 0 ? "positive" : "negative"}">${metrics.profitYen >= 0 ? "+" : ""}${formatYen(metrics.profitYen)}</b></div>
      <div class="metric"><span class="muted">購入／払戻</span><b>${formatYen(metrics.totalStakeYen)}</b><small class="muted">払戻 ${formatYen(metrics.totalReturnYen)}</small></div>
      <div class="metric"><span class="muted">固定予想</span><b>${metrics.predictionCount}R</b><small class="muted">的中率 ${pct(metrics.hitRatePct)}</small></div>
    </section>
    <h2 class="section">レース一覧</h2>
    ${raceCards || '<div class="card empty">データ取得後にレースが表示されます。システムは定期実行中です。</div>'}
  `);
}

export function renderRace(detail: RaceDetail): string {
  const { race, runners, prediction, predictedRunners, bets } = detail;
  const predMap = new Map(predictedRunners.map((runner) => [runner.horseNo, runner]));
  const runnerRows = runners.map((runner) => {
    const pred = predMap.get(runner.horseNo);
    return `<tr><td><span class="horse-no">${runner.horseNo}</span>${escapeHtml(runner.horseName)}${runner.runnerStatus !== "active" ? ` <span class="pill">${escapeHtml(runner.runnerStatus)}</span>` : ""}</td><td>${pred ? `${(pred.winProbability * 100).toFixed(1)}%<div class="bar"><i style="width:${Math.min(100, pred.winProbability * 250)}%"></i></div>` : "—"}</td><td>${runner.winOdds ?? "—"}</td><td>${pred?.fairOdds.toFixed(2) ?? "—"}</td><td>${pred?.expectedValuePct ? pred.expectedValuePct.toFixed(1) + "%" : "—"}</td><td>${runner.finishPosition ?? "—"}</td></tr>`;
  }).join("");
  const betCards = bets.map((bet) => `<div class="card buy"><b>${escapeHtml(bet.betType)} ${escapeHtml(bet.combination)}</b><div>モデル金額 ${formatYen(bet.stakeYen)} ／ 想定オッズ ${bet.assumedOdds.toFixed(1)}</div><div class="muted">推定期待値 ${bet.expectedValuePct.toFixed(1)}%　${bet.settlementStatus === "settled" ? `払戻 ${formatYen(bet.returnYen ?? 0)}` : "発走前公開"}</div></div>`).join("");
  const explanations = predictedRunners.slice(0, 5).map((pred) => `<div class="card"><b>${pred.predictedOrder}位　${pred.horseNo} ${escapeHtml(pred.horseName)}</b><div class="muted">${escapeHtml(pred.explanation)}</div></div>`).join("");
  return layout(`${race.venue}${race.raceNo}R`, `
    <section class="hero"><div class="muted">${escapeHtml(race.raceDate)} ${escapeHtml(race.venue)} ${race.raceNo}R　${escapeHtml(race.startTimeJst ?? "")}</div><h1>${escapeHtml(race.raceName)}</h1><div>${escapeHtml(race.conditions ?? "")}　${escapeHtml(race.surface ?? "")}${race.distanceM ?? ""}m ${escapeHtml(race.direction ?? "")}</div><div class="tabs"><span class="pill ${prediction?.status === "locked" ? "locked" : ""}">${prediction?.status === "locked" ? "発走前固定済み" : prediction?.status === "draft" ? "暫定予想" : "予想待ち"}</span><span class="pill">モデル ${escapeHtml(prediction?.modelVersion ?? "—")}</span></div></section>
    <h2 class="section">買い目</h2>${betCards || '<div class="card empty">期待値基準を満たす推奨馬券はありません。</div>'}
    <h2 class="section">各馬の推定値</h2><div class="card" style="overflow:auto"><table><thead><tr><th>馬</th><th>勝率</th><th>オッズ</th><th>適正</th><th>期待値</th><th>着順</th></tr></thead><tbody>${runnerRows}</tbody></table></div>
    <h2 class="section">予想根拠</h2>${explanations || '<div class="card empty">予想計算待ちです。</div>'}
  `);
}

export function renderPerformance(metrics: DashboardMetrics, rows: Array<{ label: string; bets: number; stake: number; returns: number; roi: number | null }>): string {
  const bodyRows = rows.map((row) => `<tr><td>${escapeHtml(row.label)}</td><td>${row.bets}</td><td>${formatYen(row.stake)}</td><td>${formatYen(row.returns)}</td><td class="${(row.roi ?? 0) >= 100 ? "positive" : ""}">${pct(row.roi)}</td></tr>`).join("");
  return layout("成績", `<section class="hero"><h1>公開予想成績</h1><div class="muted">外れを含む、発走前に固定した全買い目を集計します。</div></section><section class="grid"><div class="metric"><span class="muted">累計回収率</span><b>${pct(metrics.roiPct)}</b></div><div class="metric"><span class="muted">累計収支</span><b>${formatYen(metrics.profitYen)}</b></div><div class="metric"><span class="muted">買い目数</span><b>${metrics.settledBetCount}</b></div><div class="metric"><span class="muted">的中率</span><b>${pct(metrics.hitRatePct)}</b></div></section><h2 class="section">月別</h2><div class="card" style="overflow:auto"><table><thead><tr><th>月</th><th>買い目</th><th>購入</th><th>払戻</th><th>回収率</th></tr></thead><tbody>${bodyRows || '<tr><td colspan="5">確定データ待ち</td></tr>'}</tbody></table></div>`);
}

export function renderMethodology(): string {
  return layout("予想方法", `<section class="hero"><h1>予想方法</h1><div class="muted">主観的なS・A・Bランクは使わず、確率・適正オッズ・期待値で公開します。</div></section><div class="card"><h2>1．推定勝率</h2><p>単勝オッズを市場の基準確率として正規化し、サイト内に蓄積した馬・騎手・調教師・同条件成績を縮小推定で補正します。データが少ない段階では市場比率を強く残し、過学習を抑えます。</p><h2>2．発走前固定</h2><p>発走15分前を目安に予想順位、推定確率、使用オッズ、買い目、モデル金額を固定します。発走後は上書きしません。</p><h2>3．買い目</h2><p>初期モデルは、事前オッズを無料で安定取得できる単勝だけを対象にします。推定期待値が設定基準を超えた場合のみ、抑制した分数Kelly方式で100円単位の金額を計算します。組合せ馬券は事前オッズの安定取得が確認できるまで無理に推奨しません。</p><h2>4．成績</h2><p>表示する回収率は、固定済みモデル買い目をすべて購入したと仮定した成績です。外れたレースも削除せず、返還・除外も機械的に処理します。</p></div>`);
}

export function renderSystem(snapshot: unknown): string {
  return layout("稼働状況", `<section class="hero"><h1>システム稼働状況</h1><div class="muted"><span class="status-dot"></span>Cloudflare Workers + D1／競馬専用環境</div></section><div class="card"><pre style="white-space:pre-wrap;word-break:break-word;margin:0">${escapeHtml(JSON.stringify(snapshot, null, 2))}</pre></div>`);
}

export function renderNotFound(): string {
  return layout("見つかりません", `<div class="card empty">ページが見つかりません。</div>`);
}
