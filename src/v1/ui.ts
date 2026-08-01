import type { DashboardMetrics } from "./types.js";
import type { RaceDetail, RaceListRow } from "./db.js";
import { escapeHtml, formatYen } from "./utils.js";

const CSS = `
:root{color-scheme:dark;--bg:#0b0f14;--panel:#121923;--panel2:#182231;--line:#293649;--text:#eef3f8;--muted:#9fb0c2;--accent:#4fd1a1;--danger:#ff7b72;--gold:#ffd166}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#091018,#0b0f14 45%);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif;line-height:1.55}
a{color:inherit;text-decoration:none}.wrap{max-width:980px;margin:auto;padding:16px}.top{display:flex;align-items:center;justify-content:space-between;padding:12px 0 18px}.brand{font-weight:900;font-size:22px;letter-spacing:.03em}.brand span{color:var(--accent)}nav{display:flex;gap:8px;overflow:auto;padding-bottom:4px}nav a{white-space:nowrap;padding:8px 11px;background:#111925;border:1px solid var(--line);border-radius:999px;font-size:13px}.hero{padding:20px;background:linear-gradient(135deg,#172638,#10241e);border:1px solid #2b5448;border-radius:20px;margin-bottom:14px}.hero h1{font-size:27px;margin:0 0 7px}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.metric,.card{background:rgba(18,25,35,.94);border:1px solid var(--line);border-radius:16px;padding:15px}.metric b{display:block;font-size:22px;margin-top:4px}.section{margin:22px 0 10px;font-size:18px}.race{display:grid;grid-template-columns:72px 1fr auto;gap:12px;align-items:center;margin-bottom:9px}.race .no{font-weight:900;font-size:18px}.pill{display:inline-block;border-radius:999px;padding:3px 8px;font-size:12px;border:1px solid var(--line);color:var(--muted)}.pill.locked{color:#8df0cc;border-color:#347a65}.pill.finished{color:#ffd89a;border-color:#76613a}.right{text-align:right}.positive{color:var(--accent)}.negative{color:var(--danger)}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:10px 7px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--muted);font-weight:600}.horse-no{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:7px;background:#e8edf2;color:#101820;font-weight:900;margin-right:7px}.buy{border-color:#516d42;background:#162416}.warning{border-color:#6e5730;background:#251e12}.error{border-color:#74403d;background:#271817}.tabs{display:flex;gap:8px;margin:12px 0}.bar{height:7px;border-radius:9px;background:#263242;overflow:hidden;margin-top:5px}.bar i{display:block;height:100%;background:var(--accent)}.footer{font-size:12px;color:var(--muted);padding:32px 4px 50px}.empty{text-align:center;padding:34px 15px;color:var(--muted)}code{word-break:break-all;background:#0b111a;padding:2px 5px;border-radius:5px}.status-dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--accent);margin-right:6px}@media(min-width:700px){.grid{grid-template-columns:repeat(4,1fr)}.wrap{padding:24px}.hero{padding:28px}.race{grid-template-columns:100px 1fr 180px}}
.date-block{margin:20px 0 30px}.date-head{position:sticky;top:0;z-index:3;background:rgba(9,16,24,.94);backdrop-filter:blur(10px);padding:11px 2px 9px;border-bottom:1px solid var(--line)}.date-title{font-size:23px;font-weight:900}.venue-block{margin:15px 0 22px}.venue-head{display:flex;justify-content:space-between;align-items:center;margin:0 3px 9px}.venue-name{font-size:19px;font-weight:900}.race-list{display:grid;gap:8px}.day-nav{display:flex;gap:7px;overflow:auto;padding:2px 0 8px}.day-nav a{white-space:nowrap;border:1px solid var(--line);background:#101925;padding:8px 11px;border-radius:10px;font-size:13px}.result-box{border-color:#76613a;background:#251e12}.detail-status{margin:10px 0}.race-date{font-weight:800;color:var(--accent)}@media(min-width:700px){.race-list{grid-template-columns:repeat(2,minmax(0,1fr))}}
`;

function layout(title: string, body: string): string {
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0b0f14"><title>${escapeHtml(title)}｜レース探偵</title><style>${CSS}</style></head><body><main class="wrap"><div class="top"><a class="brand" href="/"><span>レース</span>探偵</a><nav><a href="/">予想</a><a href="/performance">成績</a><a href="/methodology">予想方法</a><a href="/system">稼働状況</a></nav></div>${body}<footer class="footer">本サイトは独自の統計モデルによる非公式の予想記録サイトで、JRAおよび関係団体とは関係ありません。的中や利益を保証しません。表示する収支は発走前にロックされたモデル買い目を購入したと仮定した成績です。馬券は20歳になってから、無理のない範囲でお楽しみください。</footer></main></body></html>`;
}

function pct(value: number | null, digits = 1): string {
  return value === null ? "—" : `${value.toFixed(digits)}%`;
}

export function renderHome(metrics: DashboardMetrics, races: RaceListRow[]): string {
  const dateLabel = (date: string): string => {
    const parsed = new Date(`${date}T00:00:00+09:00`);
    if (Number.isNaN(parsed.getTime())) return date;
    const day = ["日", "月", "火", "水", "木", "金", "土"][parsed.getDay()] ?? "";
    return `${parsed.getMonth() + 1}月${parsed.getDate()}日（${day}）`;
  };
  const grouped = new Map<string, Map<string, RaceListRow[]>>();
  for (const race of [...races].sort((a,b) => a.raceDate.localeCompare(b.raceDate) || a.venue.localeCompare(b.venue, "ja") || a.raceNo-b.raceNo)) {
    const venues = grouped.get(race.raceDate) ?? new Map<string, RaceListRow[]>();
    const rows = venues.get(race.venue) ?? [];
    rows.push(race); venues.set(race.venue, rows); grouped.set(race.raceDate, venues);
  }
  const dates=[...grouped.keys()];
  const nav=dates.map(date=>`<a href="#date-${date}">${escapeHtml(dateLabel(date))}</a>`).join("");
  const sections=dates.map(date=>{
    const venues=grouped.get(date)!;
    const venueHtml=[...venues.entries()].map(([venue,rows])=>{
      const cards=rows.map(race=>{
        const finished=race.status==="finished";
        const state=finished ? "結果確定" : race.predictionStatus==="locked" ? "予想公開" : race.predictionStatus==="draft" ? "暫定予想" : "予想待ち";
        const cls=finished ? "finished" : race.predictionStatus==="locked" ? "locked" : "";
        const summary=finished ? "着順・払戻を確認" : race.topHorseNo ? `◎ ${race.topHorseNo} ${escapeHtml(race.topHorseName)}` : "予想データ準備中";
        return `<a class="card race" href="/races/${encodeURIComponent(race.raceId)}"><div><div class="race-date">${race.raceNo}R</div><div class="muted">${escapeHtml(race.startTimeJst ?? "時刻未定")}</div></div><div><b>${escapeHtml(race.raceName)}</b><div class="muted">${summary}</div></div><div class="right"><span class="pill ${cls}">${state}</span><div class="muted">買い目 ${race.betCount}</div></div></a>`;
      }).join("");
      return `<section class="venue-block"><div class="venue-head"><div class="venue-name">${escapeHtml(venue)}競馬場</div><div class="muted">${rows.length}レース</div></div><div class="race-list">${cards}</div></section>`;
    }).join("");
    return `<section class="date-block" id="date-${date}"><div class="date-head"><div class="date-title">${escapeHtml(dateLabel(date))}</div><div class="muted">${escapeHtml(date)} ／ ${[...venues.values()].reduce((n,v)=>n+v.length,0)}レース</div></div>${venueHtml}</section>`;
  }).join("");
  return layout("予想一覧", `<section class="hero"><div class="muted"><span class="status-dot"></span>全自動・公開予想記録</div><h1>日付と競馬場からレースを選ぶ。</h1><div class="muted">予想、買い目、結果、払戻を各レースの詳細画面で確認できます。</div></section><section class="grid"><div class="metric"><span class="muted">累計回収率</span><b class="${(metrics.roiPct ?? 0)>=100 ? "positive":""}">${pct(metrics.roiPct)}</b></div><div class="metric"><span class="muted">モデル収支</span><b class="${metrics.profitYen>=0?"positive":"negative"}">${metrics.profitYen>=0?"+":""}${formatYen(metrics.profitYen)}</b></div><div class="metric"><span class="muted">購入／払戻</span><b>${formatYen(metrics.totalStakeYen)}</b><small class="muted">払戻 ${formatYen(metrics.totalReturnYen)}</small></div><div class="metric"><span class="muted">固定予想</span><b>${metrics.predictionCount}R</b><small class="muted">的中率 ${pct(metrics.hitRatePct)}</small></div></section>${nav?`<h2 class="section">開催日</h2><div class="day-nav">${nav}</div>`:""}${sections||'<div class="card empty">レースデータを取得中です。</div>'}`);
}

export function renderRace(detail: RaceDetail): string {
  const { race, runners, prediction, predictedRunners, bets } = detail;
  const predMap=new Map(predictedRunners.map(r=>[r.horseNo,r]));
  const finished=race.status==="finished";
  const finishers=[...runners].filter(r=>r.finishPosition!==null).sort((a,b)=>(a.finishPosition??99)-(b.finishPosition??99));
  const stake=bets.reduce((n,b)=>n+b.stakeYen,0), returns=bets.reduce((n,b)=>n+(b.returnYen??0),0), profit=returns-stake;
  const marks=["◎","○","▲"];
  const predictionBox=prediction ? `<div class="card detail-status"><b>${prediction.status==="locked"?"発走前固定予想":"暫定予想"}</b><div class="tabs">${predictedRunners.slice(0,3).map((p,i)=>`<span class="pill ${i===0?"locked":""}">${marks[i]} ${p.horseNo} ${escapeHtml(p.horseName)}</span>`).join("")}</div><div class="muted">生成 ${escapeHtml(prediction.generatedAt)}${prediction.lockedAt?` ／ 固定 ${escapeHtml(prediction.lockedAt)}`:""}</div></div>` : '<div class="card warning"><b>予想はまだ公開されていません</b><div class="muted">出走馬とオッズ取得後に自動生成します。</div></div>';
  const resultBox=finished ? `<div class="card result-box"><b>レース結果</b><div class="tabs">${finishers.slice(0,3).map(r=>`<span class="pill finished">${r.finishPosition}着 ${r.horseNo} ${escapeHtml(r.horseName)}</span>`).join("")||'<span class="muted">着順取得中</span>'}</div>${bets.length?`<div>購入 ${formatYen(stake)} ／ 払戻 ${formatYen(returns)} ／ <strong class="${profit>=0?"positive":"negative"}">${profit>=0?"+":""}${formatYen(profit)}</strong></div>`:'<div class="muted">固定買い目なし</div>'}</div>` : '<div class="card"><b>結果待ち</b><div class="muted">終了後に着順、払戻、収支を自動反映します。</div></div>';
  const rows=runners.map(r=>{const p=predMap.get(r.horseNo);return `<tr><td><span class="horse-no">${r.horseNo}</span>${escapeHtml(r.horseName)}<div class="muted">${escapeHtml(r.jockey??"")}</div></td><td>${p?`${p.predictedOrder}位<br>${(p.winProbability*100).toFixed(1)}%`:"—"}</td><td>${r.winOdds??"—"}</td><td>${p?.fairOdds.toFixed(2)??"—"}</td><td>${p?.expectedValuePct!=null?p.expectedValuePct.toFixed(1)+"%":"—"}</td><td>${r.finishPosition??"—"}</td></tr>`}).join("");
  const betCards=bets.map(b=>`<div class="card buy"><b>${escapeHtml(b.betType)} ${escapeHtml(b.combination)}</b><div>購入想定 ${formatYen(b.stakeYen)} ／ 使用オッズ ${b.assumedOdds.toFixed(1)}</div><div class="muted">期待値 ${b.expectedValuePct.toFixed(1)}% ／ ${b.settlementStatus==="settled"?`払戻 ${formatYen(b.returnYen??0)}`:"発走前固定済み"}</div></div>`).join("");
  const reasons=predictedRunners.slice(0,5).map(p=>`<div class="card"><b>${p.predictedOrder}位 ${p.horseNo} ${escapeHtml(p.horseName)}</b><div class="muted">${escapeHtml(p.explanation)}</div></div>`).join("");
  return layout(`${race.raceDate} ${race.venue}${race.raceNo}R`, `<section class="hero"><div class="muted">${escapeHtml(race.raceDate)} ／ ${escapeHtml(race.venue)}競馬場</div><h1>${race.raceNo}R ${escapeHtml(race.raceName)}</h1><div><b>${escapeHtml(race.startTimeJst??"時刻未定")} 発走</b>　${escapeHtml(race.conditions??"")} ${escapeHtml(race.surface??"")}${race.distanceM??""}m</div><div class="tabs"><span class="pill ${finished?"finished":prediction?.status==="locked"?"locked":""}">${finished?"結果確定":prediction?.status==="locked"?"予想公開中":prediction?"暫定予想":"予想待ち"}</span></div></section>${predictionBox}${resultBox}<h2 class="section">買い目</h2>${betCards||'<div class="card empty">固定された買い目はありません。</div>'}<h2 class="section">出走馬・予想・結果</h2><div class="card" style="overflow:auto"><table><thead><tr><th>馬</th><th>予想</th><th>単勝</th><th>適正</th><th>期待値</th><th>着順</th></tr></thead><tbody>${rows||'<tr><td colspan="6">取得中</td></tr>'}</tbody></table></div><h2 class="section">予想根拠</h2>${reasons||'<div class="card empty">予想生成後に表示されます。</div>'}`);
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
