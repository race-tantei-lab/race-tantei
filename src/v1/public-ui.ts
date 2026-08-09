import { escapeHtml } from "./utils.js";

const STYLE = `
:root{color-scheme:dark;--bg:#07111b;--panel:#101c29;--panel2:#0c1723;--line:#2b3d52;--text:#f2f5f8;--muted:#9baec4;--green:#51d0a5;--green2:#123d35;--red:#ff817c;--warn:#f2d48d;--blue:#87bfff}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:1080px;margin:auto;padding:16px 14px 52px}a{color:inherit;text-decoration:none}.top{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:5px 0 18px;position:sticky;top:0;z-index:20;background:linear-gradient(var(--bg) 76%,transparent)}.brand{font-weight:900;font-size:25px;color:var(--green);white-space:nowrap}.nav{display:flex;gap:7px;overflow:auto}.nav a{white-space:nowrap;padding:8px 11px;border:1px solid var(--line);border-radius:999px;background:var(--panel)}
.hero,.card,.race-card,.panel,.notice,.runner-table,.rule-box{border:1px solid var(--line);background:var(--panel);border-radius:18px}.hero{padding:20px;margin-bottom:16px}.hero h1{margin:0 0 8px;font-size:27px}.hero p{color:var(--muted);line-height:1.75;margin:6px 0}.today-hero{border-color:#2d806c;background:linear-gradient(135deg,#102b27,#101c29)}.today-pill{display:inline-flex;align-items:center;gap:6px;padding:5px 9px;border-radius:999px;background:var(--green2);color:#b9f4df;font-weight:800;font-size:12px}.section-title{display:flex;align-items:end;justify-content:space-between;gap:10px;margin:24px 0 10px}.section-title h2{margin:0;font-size:21px}.muted{color:var(--muted)}
.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.metric{padding:16px}.metric strong{display:block;font-size:34px;color:var(--green);margin:5px 0}.metric small{color:var(--muted);line-height:1.6}.metric summary{cursor:pointer;list-style:none}.metric summary::-webkit-details-marker{display:none}.metric summary:after{content:"月別を見る";display:inline-block;margin-top:9px;font-size:12px;color:var(--blue)}.metric[open] summary:after{content:"月別を閉じる"}.monthly{margin-top:12px;padding-top:11px;border-top:1px solid var(--line);max-height:300px;overflow:auto}.monthly-row{display:grid;grid-template-columns:68px 1fr auto;gap:8px;padding:7px 0;border-bottom:1px solid rgba(43,61,82,.55);font-size:12px}.monthly-row span:nth-child(2){color:var(--muted)}
.navigator{padding:14px}.nav-step{margin:12px 0}.nav-label{font-size:12px;color:var(--muted);margin:0 0 7px}.rail{display:flex;gap:8px;overflow-x:auto;padding:1px 0 7px;scrollbar-width:thin}.chip{flex:0 0 auto;border:1px solid var(--line);background:var(--panel2);color:var(--text);border-radius:999px;padding:9px 13px;font:inherit;cursor:pointer;white-space:nowrap}.chip.active{border-color:var(--green);background:var(--green2);color:#c7f8e5;font-weight:800}.chip.today{box-shadow:inset 0 0 0 1px var(--green)}.race-rail{display:flex;gap:10px;overflow-x:auto;padding:2px 0 10px;min-height:176px}.race-card{flex:0 0 245px;padding:15px;position:relative}.race-card.today{border-color:var(--green)}.race-head{display:flex;align-items:center;justify-content:space-between;gap:8px}.race-no{font-size:24px;font-weight:900}.race-time{font-weight:700;color:var(--muted)}.race-name{margin:9px 0 5px;font-weight:800;min-height:42px}.race-meta{color:var(--muted);font-size:12px}.status{display:inline-flex;margin-top:12px;padding:5px 9px;border-radius:999px;font-size:12px;font-weight:800}.status.buy{background:#15483a;color:#baf4dd}.status.skip{background:#263442;color:#b9c8d8}.status.pending{background:#4a3b1d;color:#f6dda0}.status.none{background:#3a2830;color:#efb9c3}.deadline{font-size:11px;color:var(--warn);margin-top:7px;line-height:1.5}.empty{padding:22px;color:var(--muted)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.panel{padding:17px}.panel h2,.panel h3{margin:0 0 10px}.panel p,.panel li{color:#dbe4ed;line-height:1.75}.panel ul{padding-left:20px}.notice{padding:14px 16px;color:var(--warn);border-color:#6b5730;background:#241f13;line-height:1.7}.course-tabs{display:flex;gap:8px;overflow:auto;margin:12px 0}.course-tab{border:1px solid var(--line);border-radius:999px;background:var(--panel2);padding:9px 12px;color:var(--text);cursor:pointer}.course-tab.active{border-color:var(--green);background:var(--green2)}.bet-table,.runner-table{overflow:auto}.bet-table table,.runner-table table{width:100%;border-collapse:collapse;min-width:620px}.bet-table th,.bet-table td,.runner-table th,.runner-table td{padding:10px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}.bet-table th,.runner-table th{color:var(--muted)}.plus{color:var(--green)}.minus{color:var(--red)}
.back{display:inline-block;margin:0 0 14px;color:var(--blue)}.race-title{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.race-title h1{margin:0}.horse-no{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#1c2a38;font-weight:900}.locked-note{font-size:12px;color:var(--muted);line-height:1.7;margin-top:10px}
.rule-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.rule-box{padding:15px}.rule-box b{display:block;margin-bottom:7px}.rule-box span{color:var(--muted);font-size:13px;line-height:1.6}.rule-group{margin:12px 0;border:1px solid var(--line);border-radius:14px;background:var(--panel2)}.rule-group summary{cursor:pointer;padding:14px;font-weight:800}.rule-list{margin:0;padding:0 16px 14px 37px;max-height:430px;overflow:auto}.rule-list li{padding:6px 0;color:#d7e1eb;line-height:1.55;font-size:13px}
.guide-step{display:grid;grid-template-columns:36px 1fr;gap:12px;align-items:start;margin:12px 0}.step-no{display:grid;place-items:center;width:32px;height:32px;border-radius:50%;background:var(--green2);color:#bdf4df;font-weight:900}.guide-step b{display:block;margin-bottom:4px}.guide-step p{margin:0;color:var(--muted);line-height:1.7}
@media(max-width:760px){.metrics,.grid2,.rule-summary{grid-template-columns:1fr}.wrap{padding:12px 12px 40px}.top{align-items:flex-start}.brand{font-size:23px}.metric strong{font-size:31px}.hero h1{font-size:24px}.race-card{flex-basis:225px}.nav a{font-size:13px}}
`;

export function response(body: string, status = 200): Response {
  return new Response(body, { status, headers: {
    "content-type": "text/html; charset=utf-8", "cache-control": "no-store, max-age=0",
    "x-content-type-options": "nosniff", "referrer-policy": "no-referrer",
    "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
  }});
}

export function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: {
    "content-type": "application/json; charset=utf-8", "cache-control": "no-store, max-age=0",
    "x-content-type-options": "nosniff", "x-robots-tag": "noindex, nofollow"
  }});
}

export function redirect(path: string): Response {
  return new Response(null, { status: 302, headers: { location: path, "cache-control": "no-store" } });
}

export function shell(title: string, body: string, script = ""): string {
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#07111b"><title>${escapeHtml(title)}｜レース探偵</title><style>${STYLE}</style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><nav class="nav"><a href="/">レース</a><a href="/conditions">条件詳細</a><a href="/guide">見方</a></nav></header>${body}</main>${script ? `<script>${script}</script>` : ""}</body></html>`;
}

export function conditionsPage(): string {
  const groups: Array<[string,string[]]> = [
    ["券種",["単勝","馬連","ワイド","馬単","3連複","3連単"]],
    ["距離",["1200m以下","1300〜1500m","1600〜1800m","1900〜2200m","2300〜2600m","2700m以上"]],
    ["JRA実オッズ",["1〜2倍","2〜3倍","3〜5倍","5〜7倍","7〜10倍","10〜15倍","15〜20倍","20〜30倍","30〜50倍","50〜75倍","75〜100倍","100〜150倍","150〜300倍","300〜500倍","500〜800倍","800〜1200倍","1200〜2000倍","2000倍以上"]],
    ["レース環境",["10会場","芝・ダート・障害","馬場：良・稍重・重・不良","天候：晴・曇・雨系・雪系","頭数：8頭以下／9〜11／12〜13／14〜16／17頭以上","レース番号：1〜3R／4〜6R／7〜9R／10〜12R","季節：冬・春・夏・秋","方向：右・左・直線"]],
    ["人気・市場",["市場評価順位：1位〜251位以下まで9帯","組合せ内の最上位人気：1番人気〜9番人気以下","組合せ内の最低人気：1〜2番人気〜15番人気以下","人気順位合計：3以下〜41以上","1番人気馬の含有数：0〜3頭","市場との乖離：0.55未満〜1.70以上の9帯"]],
    ["過去実績",["近走好走馬の数：0〜3頭以上","最高近走評価：履歴なし／低め／中程度／良好／非常に良好","最高速度評価：履歴なし／低め／中程度／良好／非常に良好","最高騎手実績：15%未満〜45%以上","最高厩舎実績：15%未満〜45%以上","条件経験馬の数：0〜3頭以上","直近好走回数の合計：0〜7回以上"]],
    ["クラス",["新馬","未勝利","1勝クラス","2勝クラス","3勝クラス","OP/L","G3","G2","G1","その他"]]
  ];
  const details = groups.map(([title,items]) => `<details class="rule-group"><summary>${title}</summary><ul class="rule-list">${items.map((item)=>`<li>${escapeHtml(item)}</li>`).join("")}</ul></details>`).join("");
  const body = `<section class="hero"><h1>条件詳細</h1><p>現在の買い目は、予想時点で取得できる情報だけに同じ判定ルールを適用して決めます。結果を見たあとに過去の買い目を書き換えることはありません。</p></section>
  <section class="rule-summary"><article class="rule-box"><b>対象レース</b><span>各会場・各開催日から5レース。条件に合う買い目を持つレースを強さ順で選び、同点はレース番号順で決めます。</span></article><article class="rule-box"><b>1レースの買い目</b><span>3〜10点。最上位の条件一致スコアに対して85%以上の候補を残し、3点未満なら強い順から3点を採用します。</span></article><article class="rule-box"><b>購入額</b><span>ライト2,000円、スタンダード5,000円、プレミアム10,000円。100円単位で、そのレースの予算を固定ルールで配分します。</span></article><article class="rule-box"><b>集中しすぎない</b><span>1つの買い目にはレース予算の35%まで。高オッズほど配分を抑え、100倍を基準に1.5乗で段階的に比重を下げます。</span></article><article class="rule-box"><b>使う情報</b><span>会場、コース、距離、JRA実オッズ、人気構成、市場との乖離、クラス、馬・騎手・厩舎の過去実績まで、下に全項目と区分を掲載します。</span></article><article class="rule-box"><b>時系列を厳守</b><span>そのレースの結果は予想に使いません。履歴は予想時点より前のレースだけで作り、終了後に将来の改善材料へ追加します。</span></article></section>
  <div class="section-title"><h2>判定に使う全項目</h2><span class="muted">日本語で整理</span></div><div class="notice">内部の番号やファイル名は表示しません。下記の区分を券種ごとに組み合わせて、全レースへ同じ判定手順を適用します。</div>${details}`;
  return shell("条件詳細", body);
}

export function guidePage(): string {
  const steps = [
    ["レースを探す","トップは「年 → 月 → 日付 → 会場 → レース」の順です。各段を横にスワイプして選びます。今日の開催日は「今日」と表示します。"],
    ["買い目対象を確認","「買い目あり」は購入対象、「見送り」は条件非該当です。開催前でまだ判定が終わっていないレースは「判定中」と表示します。"],
    ["買い目が出る時間","必要な情報がそろえば早めに確定します。遅くとも買い目対象になったレースは発走15分前までに固定し、固定後は変更しません。"],
    ["レース情報の更新","開催情報・出走馬・単勝オッズなどは自動取得します。通常は数十分〜数時間単位、発走が近づくと5〜15分程度の間隔で更新します。結果も確定後に自動反映します。"],
    ["レース詳細を見る","レースカードをタップすると、出走馬一覧、確定済みの買い目、購入額、結果、条件に当てはまった理由を確認できます。"],
    ["過去の買い目","結果が出たあとも、当時固定した買い目と購入額はそのまま残します。後から当たりやすい形へ書き換えることはありません。"],
    ["新しい結果の使い方","終了したレースは次の改善材料に追加します。改善した条件を将来に採用しても、過去に固定した買い目・払戻・回収率の元データは変更しません。"]
  ];
  const body = `<section class="hero"><h1>レース探偵の見方</h1><p>初めて見る人向けに、レースの探し方から買い目の確定・結果反映までをまとめています。</p></section><section class="panel">${steps.map((s,i)=>`<div class="guide-step"><div class="step-no">${i+1}</div><div><b>${s[0]}</b><p>${s[1]}</p></div></div>`).join("")}</section><div class="section-title"><h2>表示の意味</h2></div><section class="grid2"><article class="panel"><span class="status buy">買い目あり</span><p>購入対象。レース詳細でコースごとの買い目を確認できます。</p><span class="status skip">見送り</span><p>その日の選定対象外、または購入条件に届かなかったレースです。</p></article><article class="panel"><span class="status pending">判定中</span><p>開催前でデータ更新・条件照合中です。対象になった場合は表示されている期限までに買い目を固定します。</p><span class="status none">買い目記録なし</span><p>過去データに、固定済み買い目として保存された記録がないレースです。</p></article></section>`;
  return shell("見方", body);
}
