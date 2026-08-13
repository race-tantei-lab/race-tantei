import publicSite from "./public-site-entry-v18.js";
import { response as baseResponse, shell } from "./v1/public-ui.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v19-product-copy-20260813";

function timingBlock(): string {
  return `
  <details class="data-timing">
    <summary><b>データ更新のタイミング</b><span>日本時間</span></summary>
    <div class="data-timing-body">
      <p><b>開催情報</b><span>バックグラウンド同期は5分ごと。新しい開催の探索は木〜日曜は90分ごと、土日の8:00〜20:59は20分ごとに行います。</span></p>
      <p><b>出馬情報</b><span>発走24時間より前は3時間ごと、24〜3時間前は1時間ごと、3時間〜45分前は15分ごと、45分前以降は5分ごとに更新します。</span></p>
      <p><b>買い目</b><span>土・日・月の8:00〜19:00に10分ごとに確認。対象レースは発走45〜15分前のJRA公式オッズで買い目を確定します。</span></p>
      <p><b>結果・払戻</b><span>発走約4分後から結果を確認します。未確定の場合は再取得し、払戻が出たら公開済みの買い目と自動で照合します。</span></p>
    </div>
  </details>`;
}

function conditionsBody(): string {
  return `
  <section class="hero">
    <h1>予想ロジック</h1>
    <p>レース探偵は、まず「買うレース」を選び、そのあとに「何を買うか」を決めます。使うのは発走前までに取得できる情報だけ。レース後の結果を見て予想を選び直すことはありません。</p>
  </section>

  <section class="rule-summary">
    <article class="rule-box"><b>各会場5レース</b><span>その日の12Rから、過去データ上で買い目の期待値が出やすい5Rを選びます。</span></article>
    <article class="rule-box"><b>1レース2点</b><span>6券種をすべて比較し、異なる2券種から1点ずつ選びます。</span></article>
    <article class="rule-box"><b>56項目で勝率予測</b><span>馬・騎手・調教師・コース適性・近走など、発走前に分かる情報から各馬の勝率を推定します。</span></article>
    <article class="rule-box"><b>JRA公式オッズ</b><span>買い目の評価にはJRA公式オッズを使用します。合成オッズや推定オッズには置き換えません。</span></article>
    <article class="rule-box"><b>結果は予想に使わない</b><span>対象日の着順や払戻は、レース選びにも買い目作成にも使いません。</span></article>
    <article class="rule-box"><b>過去成績は参考値</b><span>回収率431.7%・的中レース率54.4%は過去10年の検証結果です。将来の成績を保証する数字ではありません。</span></article>
  </section>

  ${timingBlock()}

  <div class="section-title"><h2>1. 買うレースを選ぶ</h2><span class="muted">12R → 5R</span></div>
  <section class="card panel condition-flow">
    <ol>
      <li><b>前日までのデータを更新</b><br>近走成績、騎手・調教師成績、券種や条件ごとの過去払戻などを、前日までの確定データから更新します。</li>
      <li><b>各レースの注目馬を上位5頭に絞る</b><br>近走の着順や速度傾向、騎手・調教師の3着内率、出走経験などから、レース選定用に上位5頭を選びます。</li>
      <li><b>上位5頭から選定用の仮買い目を作る</b><br>単勝・ワイド・馬連・馬単・3連複・3連単の候補を作り、そのレースが過去データ上でどれだけ狙いやすいかを比べます。</li>
      <li><b>過去の払戻傾向でレースを点数化</b><br>券種、会場、芝・ダート、距離、頭数、クラスなど条件の近い過去データを使います。サンプルが少ない条件だけが極端に高くならないよう補正も入れています。</li>
      <li><b>各会場の上位5Rを採用</b><br>レースごとの評価を高い順に並べ、各会場から5レースを購入対象にします。同点ならレース番号の若い方を優先します。</li>
    </ol>
    <p class="muted">レース選びには、対象日の結果や対象日の最終オッズを使いません。</p>
  </section>

  <div class="section-title"><h2>2. 各馬の勝率を出す</h2><span class="muted">56項目</span></div>
  <section class="grid2">
    <article class="panel"><h3>レース条件</h3><p>会場、レース番号、芝・ダート、距離、回り、頭数、月、クラス、天候、馬場状態など。</p></article>
    <article class="panel"><h3>馬の状態</h3><p>馬番・枠番、性齢、馬体重、増減、斤量、出走数、過去勝率・3着内率、休養日数、直近1・3・5走の着順・上がり・速度など。</p></article>
    <article class="panel"><h3>コース適性</h3><p>芝・ダート、距離帯、会場ごとの出走数・勝率・3着内率、距離変更、芝ダート変更など。</p></article>
    <article class="panel"><h3>騎手・調教師</h3><p>騎手、調教師、馬と騎手の組み合わせごとの出走数・勝率・3着内率を使います。</p></article>
  </section>
  <section class="card panel">
    <p>56項目から各馬の予測値を出したあと、同じレースの全馬で合計100%になるよう勝率へ変換します。着順・払戻・学習用の正解ラベル・人気順位そのものは、この勝率予測の入力には使いません。</p>
  </section>

  <div class="section-title"><h2>3. 買い目を2点に絞る</h2><span class="muted">全組合せ → 2点</span></div>
  <section class="card panel condition-flow">
    <ol>
      <li><b>6券種の全組合せを比較</b><br>単勝・ワイド・馬連・馬単・3連複・3連単について、JRA公式オッズが取得できた組合せをすべて候補にします。</li>
      <li><b>組合せごとの確率を計算</b><br>馬別勝率からPlackett-Luce法で着順の組合せ確率を計算します。馬単・3連単は着順どおり、馬連・3連複・ワイドは該当する並びを合算します。</li>
      <li><b>期待値の高い候補を残す</b><br><b>予測確率 × JRA公式オッズ</b> の高い順に、各券種で上位5候補まで絞ります。</li>
      <li><b>券種ごとに1点を選ぶ</b><br>残った候補を最終スコアで比較し、各券種から最も評価の高い1点だけを残します。</li>
      <li><b>異なる2券種から1点ずつ</b><br>6券種の代表候補を比べ、異なる2券種から1点ずつ選びます。これが公開する2点です。</li>
    </ol>
    <p>連系馬券も、当たった組合せを後から選んでいるわけではありません。全組合せを同じ手順で比較した結果、最も評価の高い1点だけが残ります。</p>
    <details class="formula-note"><summary>最終スコアの計算式</summary><p><b>ln(予測確率) + 0.4 × ln(JRA公式オッズ)</b></p></details>
  </section>

  <div class="section-title"><h2>4. 購入額</h2><span class="muted">買い目は3コース共通</span></div>
  <section class="rule-summary">
    <article class="rule-box"><b>ライト</b><span>1,000円 + 1,000円 = 2,000円</span></article>
    <article class="rule-box"><b>スタンダード</b><span>2,500円 + 2,500円 = 5,000円</span></article>
    <article class="rule-box"><b>プレミアム</b><span>5,000円 + 5,000円 = 10,000円</span></article>
  </section>

  <div class="section-title"><h2>5. 過去成績の読み方</h2><span class="muted">2016/8/10〜2026/8/9</span></div>
  <section class="card panel condition-flow">
    <p><b>回収率431.7%・的中レース率54.4%は、過去10年の14,410レースに現在のルールを適用した集計です。</b></p>
    <p>この数字は、未使用データだけで検証した成績ではありません。ルール作成の過程でも同じ10年データを参照しているため、実際の将来成績より良く見えている可能性があります。将来の回収率や的中率を示す数字としては扱いません。</p>
    <p>過去検証で使ったオッズはJRA公式値ですが、14,410レースすべてで、現在の買い目確定時刻と同じ取得タイミングだったことまでは確認できていません。</p>
  </section>

  <div class="section-title"><h2>6. データの扱い</h2></div>
  <section class="grid2">
    <article class="panel"><h3>予想前に使うデータ</h3><p>前日までの確定履歴、当日の出馬情報、買い目確定時に取得したJRA公式オッズを使います。</p></article>
    <article class="panel"><h3>予想に使わないデータ</h3><p>対象日の着順・払戻は予想に使いません。勝率モデルには人気順位そのものも入れません。</p></article>
  </section>

  <div class="section-title"><h2>予想履歴について</h2></div>
  <section class="card panel"><p>公開した買い目と結果は後から変更しません。新しいレース結果は、その後のレースで使う履歴データとして追加します。</p></section>

  <style>
    .condition-flow ol{margin:0;padding-left:22px}.condition-flow li{margin:0 0 14px;line-height:1.75}.condition-flow li:last-child{margin-bottom:0}.condition-flow p{line-height:1.75}
    .data-timing{margin:12px 0 4px;border:1px solid var(--line);border-radius:12px;background:var(--panel);overflow:hidden}
    .data-timing summary{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;cursor:pointer;list-style:none}.data-timing summary::-webkit-details-marker{display:none}.data-timing summary b{font-size:13px}.data-timing summary span{font-size:10px;color:var(--muted)}
    .data-timing-body{padding:0 12px 10px;border-top:1px solid var(--line)}.data-timing-body p{display:grid;grid-template-columns:90px minmax(0,1fr);gap:10px;margin:0;padding:8px 0;border-bottom:1px solid rgba(43,61,82,.45);font-size:11px;line-height:1.55}.data-timing-body p:last-child{border-bottom:0}.data-timing-body p>span{color:var(--muted)}
    .formula-note{margin-top:12px;border-top:1px solid var(--line);padding-top:10px}.formula-note summary{cursor:pointer;color:var(--blue);font-size:12px}.formula-note p{margin:8px 0 0!important;font-size:12px;color:var(--muted)}
    @media(max-width:760px){.data-timing summary{padding:9px 10px}.data-timing-body{padding:0 10px 8px}.data-timing-body p{grid-template-columns:72px minmax(0,1fr);gap:8px;font-size:10px}}
  </style>`;
}

function guideBody(): string {
  return `
  <section class="hero">
    <h1>レース探偵の使い方</h1>
    <p>見る順番はシンプルです。開催日と会場を選び、購入対象のレースを開けば、買い目・購入額・結果まで確認できます。</p>
  </section>
  <section class="card panel">
    <div class="guide-step"><span class="step-no">1</span><div><b>開催日と会場を選ぶ</b><p>トップページで年・月・開催日・会場を選ぶと、その日のレース一覧が表示されます。</p></div></div>
    <div class="guide-step"><span class="step-no">2</span><div><b>ステータスを見る</b><p>購入対象は買い目を表示します。終了後は「的中」「不的中」、購入対象外は「見送り」と表示します。</p></div></div>
    <div class="guide-step"><span class="step-no">3</span><div><b>レースを開く</b><p>レース詳細では、2点の買い目、JRA公式オッズ、購入額、出走馬情報を確認できます。</p></div></div>
    <div class="guide-step"><span class="step-no">4</span><div><b>予算コースを選ぶ</b><p>ライト2,000円、スタンダード5,000円、プレミアム10,000円。選ぶ2点は同じで、購入額だけが変わります。</p></div></div>
    <div class="guide-step"><span class="step-no">5</span><div><b>結果を確認する</b><p>レース後はJRAの払戻と自動照合し、払戻額と回収率へ反映します。公開済みの買い目は後から変更しません。</p></div></div>
  </section>
  <div class="section-title"><h2>表示について</h2></div>
  <section class="grid2">
    <article class="panel"><h3>的中 / 不的中</h3><p>公開した買い目のうち、1点でも払戻があれば「的中」、どちらも払戻0円なら「不的中」です。</p></article>
    <article class="panel"><h3>見送り</h3><p>その日の購入対象5レースに入らなかったレースです。結果を見て後から対象へ変更することはありません。</p></article>
  </section>
  <div class="section-title"><h2>予想方法を詳しく見る</h2></div>
  <section class="card panel"><p>レースの選び方、馬別勝率、2点への絞り込み、データ更新のタイミングは「予想ロジック」にまとめています。</p><p><a class="back" href="/conditions">予想ロジックを見る →</a></p></section>`;
}

function liveReasonBlock(): string {
  return `<section class="prediction-reasons"><div class="prediction-reasons-head"><h2>買い目の選び方</h2><span>このレース</span></div><p class="prediction-reason-copy">馬別の予測勝率とJRA公式オッズから6券種の全候補を比較し、最終評価の高い異なる2券種を1点ずつ選んでいます。</p></section>`;
}

function polishCommonCopy(html: string): string {
  let out = html
    .replace('<a href="/conditions">条件詳細</a>', '<a href="/conditions">予想ロジック</a>')
    .replace('<a href="/guide">見方</a>', '<a href="/guide">使い方</a>')
    .replaceAll("このレースは完成モデルの買い目対象ではありません。", "このレースは購入対象外です。")
    .replaceAll("固定済み", "買い目確定");

  if (out.includes('class="prediction-reasons"')) {
    out = out.replace(/<section class="prediction-reasons">[\s\S]*?<\/section>/, liveReasonBlock());
    const css = `<style>.prediction-reason-copy{margin:0;color:var(--muted);font-size:12px;line-height:1.7}</style>`;
    out = out.replace("</head>", `${css}</head>`);
  }
  return out;
}

function productPage(title: string, body: string): Response {
  const base = baseResponse(polishCommonCopy(shell(title, body)));
  const headers = new Headers(base.headers);
  headers.set("x-race-ui-version", UI_VERSION);
  return new Response(base.body, { status: base.status, headers });
}

function streamingNavCopy(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("x-race-ui-version", UI_VERSION);
  const source = new Response(response.body, { status: response.status, headers });
  return new HTMLRewriter()
    .on('.nav a[href="/conditions"]', { element(element) { element.setInnerContent("予想ロジック"); } })
    .on('.nav a[href="/guide"]', { element(element) { element.setInnerContent("使い方"); } })
    .transform(source);
}

async function polishResponse(response: Response, path: string): Promise<Response> {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  if (!path.startsWith("/races/")) return streamingNavCopy(response);
  try {
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("cache-control", "no-store, max-age=0");
    headers.set("x-race-ui-version", UI_VERSION);
    return new Response(polishCommonCopy(await response.text()), { status: response.status, headers });
  } catch {
    return response;
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const path = new URL(request.url).pathname;
    if (path === "/conditions") return productPage("予想ロジック", conditionsBody());
    if (path === "/guide") return productPage("使い方", guideBody());
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    return polishResponse(await publicSite.fetch(request, env, ctx), path);
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
