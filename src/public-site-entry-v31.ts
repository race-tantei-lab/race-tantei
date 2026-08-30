import publicSite from "./public-site-entry-v30.js";
import { shell } from "./v1/public-ui.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v31-next-bet-until-post-20260830";

type RaceRow = {
  raceId: string;
  venue: string;
  raceNo: number;
  startTimeUtc: string | null;
  startTimeJst: string | null;
};

type StableNextBet = {
  raceId: string;
  venue: string;
  raceNo: number;
  startTimeJst: string | null;
  deadlineJst: string | null;
  locked: boolean;
};

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function jstClock(value: string | null | undefined): string | null {
  if (!value) return null;
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return /^\d{1,2}:\d{2}$/.test(value) ? value.padStart(5, "0") : null;
  return new Date(time + 9 * 60 * 60 * 1000).toISOString().slice(11, 16);
}

function deadlineClock(startTimeUtc: string | null): string | null {
  if (!startTimeUtc) return null;
  const time = Date.parse(startTimeUtc);
  if (!Number.isFinite(time)) return null;
  return new Date(time - 15 * 60 * 1000 + 9 * 60 * 60 * 1000).toISOString().slice(11, 16);
}

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch] ?? ch));
}

function docNav(html: string, path: string): string {
  const raceCurrent = path === "/" ? ' aria-current="page"' : "";
  const win5Current = path === "/win5" ? ' aria-current="page"' : "";
  const moreCurrent = path === "/conditions" || path === "/guide" ? " current" : "";
  const nav = `<nav class="nav compact-nav"><a href="/"${raceCurrent}>レース</a><a href="/win5"${win5Current}>WIN5</a><details class="nav-more${moreCurrent}"><summary>その他</summary><div class="nav-more-menu"><a href="/conditions"${path === "/conditions" ? ' aria-current="page"' : ""}>予想のしくみ</a><a href="/guide"${path === "/guide" ? ' aria-current="page"' : ""}>使い方</a></div></details></nav>`;
  return html.replace(/<nav class="nav">[\s\S]*?<\/nav>/, nav).replace(
    "</head>",
    `<style>
      .compact-nav{overflow:visible!important;align-items:center}.compact-nav>a[aria-current="page"]{border-color:var(--green);background:var(--green2);color:#c7f8e5;font-weight:900}
      .nav-more{position:relative;flex:0 0 auto}.nav-more>summary{list-style:none;cursor:pointer;white-space:nowrap;padding:8px 11px;border:1px solid var(--line);border-radius:999px;background:var(--panel);font-size:13px}.nav-more>summary::-webkit-details-marker{display:none}.nav-more.current>summary{border-color:var(--green);background:var(--green2);color:#c7f8e5;font-weight:900}.nav-more-menu{position:absolute;right:0;top:calc(100% + 6px);z-index:80;display:grid;min-width:145px;padding:6px;border:1px solid var(--line);border-radius:12px;background:var(--panel);box-shadow:0 12px 28px rgba(0,0,0,.35)}.nav-more-menu a{border:0!important;border-radius:8px!important;background:transparent!important;padding:9px 10px!important;font-size:12px!important}.nav-more-menu a[aria-current="page"],.nav-more-menu a:hover{background:var(--panel2)!important;color:#c7f8e5}
      .method-flow ol{margin:0;padding-left:22px}.method-flow li{margin:0 0 14px;line-height:1.78}.method-flow li:last-child{margin-bottom:0}.method-flow p{line-height:1.78}.method-emphasis{border-color:#2d806c;background:linear-gradient(135deg,#102b27,#101c29)}.method-warning{border-color:#80652d;background:#2a2414}.method-loop{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}.method-loop article{padding:14px;border:1px solid var(--line);border-radius:14px;background:var(--panel2)}.method-loop b{display:block;color:var(--green);margin-bottom:5px}.method-loop span{font-size:12px;line-height:1.65;color:var(--muted)}.guide-status{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.guide-status article{padding:14px;border:1px solid var(--line);border-radius:14px;background:var(--panel2)}.guide-status b{display:block;margin-bottom:5px}.guide-status span{color:var(--muted);font-size:12px;line-height:1.6}
      @media(max-width:760px){.nav-more>summary{padding:7px 9px;font-size:12px}.method-loop,.guide-status{grid-template-columns:1fr 1fr}}
      @media(max-width:520px){.method-loop,.guide-status{grid-template-columns:1fr}}
    </style></head>`,
  );
}

function docsResponse(title: string, body: string, path: string): Response {
  return new Response(docNav(shell(title, body), path), {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-race-ui-version": UI_VERSION,
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
    },
  });
}

function currentConditionsBody(): string {
  return `
  <section class="hero method-emphasis">
    <h1>予想のしくみ</h1>
    <p>レース探偵は、完成済みのベースモデルを土台にしながら、当日を含む直近の確定結果を次の予想へ継続的に反映します。買い目はJRA公式オッズだけで評価し、発走15分前までに確定した後は変更しません。</p>
  </section>

  <section class="rule-summary">
    <article class="rule-box"><b>完成モデル＋継続学習</b><span>完成済みベースモデルの重みは固定。その上に、直近30日と同じ日の終了済みレースを反映する学習レイヤーを重ねます。</span></article>
    <article class="rule-box"><b>当日結果も次レースへ反映</b><span>予想時刻より前に終了し結果が確定したレースは、その日の後続レースの予想へ順次反映します。対象レース自身や未来の結果は使いません。</span></article>
    <article class="rule-box"><b>JRA公式オッズだけ</b><span>買い目評価と最終確定に使う市場オッズはJRA公式値のみ。合成オッズ・推定オッズ・確率から作った代替オッズは使いません。</span></article>
    <article class="rule-box"><b>発走15分前までに確定</b><span>45分前から予想プレビューを更新し、発走15分前時点では買い目が固定済みになるよう安全余裕を持って確定します。</span></article>
    <article class="rule-box"><b>確定後は変更不可</b><span>公開買い目と確定状態はデータベース側でも更新を拒否します。結果を見てから組合せやオッズを書き換えることはできません。</span></article>
    <article class="rule-box"><b>公式オッズが無ければ代用しない</b><span>JRA公式オッズ付きの保存済み予想が無い場合、偽のオッズで穴埋めせず確定しません。</span></article>
  </section>

  <div class="section-title"><h2>当日の予想はこう更新されます</h2><span class="muted">終了 → 学習 → 次の予想</span></div>
  <section class="method-loop">
    <article><b>1. レース終了</b><span>着順・払戻を取得し、公開済み買い目を精算します。</span></article>
    <article><b>2. 継続学習へ追加</b><span>終了済みレースと精算済み買い目を、次の予想時刻より前の履歴として追加します。</span></article>
    <article><b>3. 次レースを再評価</b><span>完成モデルの出力に直近学習の補正をかけ、最新のJRA公式オッズで買い目候補を評価します。</span></article>
    <article><b>4. 15分前までに固定</b><span>保存済みの公式オッズ付き予想を確定し、それ以降は再計算・差し替えをしません。</span></article>
  </section>

  <div class="section-title"><h2>① その日の対象5レースを選ぶ</h2><span class="muted">各会場 12R → 5R</span></div>
  <section class="card panel method-flow">
    <ol>
      <li><b>対象レース選定は先に固定</b><br>各会場の12レースから5レースを選ぶ段階では、対象日の結果を使いません。対象日より前の確定履歴だけからraceScoreを作ります。</li>
      <li><b>レース選定用に上位5頭を評価</b><br>近走form・speed、騎手・調教師の3着内率、経験、直近3走の好走回数などから出走馬を順位付けします。</li>
      <li><b>6券種の選定用proxyを作る</b><br>単勝・ワイド・馬連・馬単・3連複・3連単の候補を作り、過去の券種・条件別払戻ROIをpriorで平滑化して採点します。</li>
      <li><b>上位3候補の平均をraceScoreにする</b><br>最低2券種を含む上位3つの選定用候補からraceScoreを作り、会場ごとに上位5レースを固定します。</li>
    </ol>
    <p class="muted"><b>ここだけは当日中も動かしません。</b> 継続学習で変わるのは後続レースの馬別評価・買い目評価であり、その日に選ばれた5レース自体を結果を見て入れ替えることはありません。</p>
  </section>

  <div class="section-title"><h2>② 完成済みベースモデル</h2><span class="muted">LightGBM・56項目</span></div>
  <section class="grid2">
    <article class="panel"><h3>レース・コース</h3><p>会場、レース番号、芝・ダート、距離、回り、頭数、月、クラス、天候、馬場状態など。</p></article>
    <article class="panel"><h3>馬</h3><p>馬番・枠番、性齢、馬体重、増減、斤量、出走数、過去勝率・3着内率、休養日数、直近1・3・5走の着順・上がり・速度など。</p></article>
    <article class="panel"><h3>適性</h3><p>同じ芝・ダート、距離帯、会場での出走数・勝率・3着内率、距離変更、芝ダート変更など。</p></article>
    <article class="panel"><h3>人・組み合わせ</h3><p>騎手、調教師、馬×騎手の過去出走数・勝率・3着内率などを使います。</p></article>
  </section>
  <section class="card panel"><p>56項目から各馬の値を出し、同一レース内で合計1になるよう正規化して1着確率として扱います。完成済みベースモデルの重み自体は日中に再学習しません。</p></section>

  <div class="section-title"><h2>③ 継続学習レイヤー</h2><span class="muted">直近30日＋当日終了レース</span></div>
  <section class="card panel method-flow">
    <p><b>ここが現在のライブ運用で追加されている学習部分です。</b> 予想を作るたびに、その予想時刻より前に終了・確定した履歴だけを読み直します。</p>
    <ol>
      <li><b>未来の結果は遮断</b><br>開始時刻が予想時刻以降のレースは学習対象に入りません。対象レース自身の結果も当然入りません。</li>
      <li><b>同じ日の終了済みレースを強く反映</b><br>直近30日を使い、同日を6倍、前日を4倍、2〜7日前を2倍、それ以前を1倍の基礎重みとして、さらに7日半減で新しい結果ほど強く反映します。</li>
      <li><b>馬・騎手・調教師・枠傾向を補正</b><br>直近結果が市場評価に対して上振れ・下振れしているかを見て、ベースモデルの馬別確率へ補正をかけます。</li>
      <li><b>実際に公開した買い目の成績も反映</b><br>精算済みのライトコース買い目から、券種・会場・オッズ帯ごとの直近ROIを学習し、買い目評価へ補正をかけます。</li>
    </ol>
    <p class="muted">つまり「毎レースLightGBMを一から再学習する」のではなく、<b>凍結した完成モデル＋終了レースを順次取り込む直近学習</b>という構成です。</p>
  </section>

  <div class="section-title"><h2>④ JRA公式オッズで2点へ絞る</h2><span class="muted">全6券種 → 2点</span></div>
  <section class="card panel method-flow">
    <ol>
      <li><b>JRA公式オッズを取得</b><br>単勝・ワイド・馬連・馬単・3連複・3連単の公式オッズを取得します。最終状態として許可している取得元はJRA公式経路だけです。</li>
      <li><b>組合せ確率を計算</b><br>直近学習を反映した馬別1着確率からPlackett-Luce方式で各組合せの推定確率を計算します。</li>
      <li><b>券種ごとにEV上位5候補</b><br><b>推定確率 × JRA公式オッズ</b> が高い順に各券種の上位5候補へ絞ります。</li>
      <li><b>評価点で券種代表を決定</b><br><b>ln(予測確率) + 0.4 × ln(JRA公式オッズ)</b> を基本に、直近の券種成績補正も加えて各券種の代表1点を決めます。</li>
      <li><b>異なる2券種から1点ずつ</b><br>6券種の代表を比較し、異なる2券種から1点ずつ、合計2点を公開買い目にします。</li>
    </ol>
  </section>

  <div class="section-title"><h2>⑤ 発走15分前までに確定</h2><span class="muted">確定後は不変</span></div>
  <section class="card panel method-flow method-warning">
    <ol>
      <li><b>発走45分前からプレビュー更新</b><br>完成モデル、継続学習、取得できた公式馬体重、JRA公式オッズを使って保存済み予想を更新します。</li>
      <li><b>発走16分前以内で確定対象に入れる</b><br>Cloudflareの1分ごとの実行が数秒ずれることを考慮し、15分前を過ぎないよう1分早い安全余裕を持たせています。</li>
      <li><b>発走15分前以降は再計算しない</b><br>この境界以降はJRAへの新規アクセス、モデル再計算、継続学習の再計算、オッズ更新を行わず、事前に保存したJRA公式オッズ付き予想だけを確定対象にします。</li>
      <li><b>JRA公式オッズが無ければfail closed</b><br>公式オッズ付き予想が無い場合は、推定・合成オッズでは代用しません。偽の数字で買い目を作るより未確定を選びます。</li>
      <li><b>確定後はDBでも変更不可</b><br>公開買い目の組合せ・金額・オッズと、locked済み最終状態はデータベースの保護ルールで更新を拒否します。</li>
    </ol>
  </section>

  <div class="section-title"><h2>⑥ 購入額</h2><span class="muted">選ぶ2点は共通</span></div>
  <section class="rule-summary">
    <article class="rule-box"><b>ライト</b><span>1,000円 + 1,000円 = 2,000円</span></article>
    <article class="rule-box"><b>スタンダード</b><span>2,500円 + 2,500円 = 5,000円</span></article>
    <article class="rule-box"><b>プレミアム</b><span>5,000円 + 5,000円 = 10,000円</span></article>
  </section>

  <div class="section-title"><h2>⑦ 過去成績の見方</h2><span class="muted">431.7%・54.4%</span></div>
  <section class="card panel method-flow">
    <p><b>431.7%の回収率と約54.4%の的中レース率は、凍結した過去10年の14,410レースへ完成ルールを適用した全期間の後方集計です。</b></p>
    <p>これは完全OOF成績や将来収益の保証ではありません。現在のライブ運用では、ここで説明した継続学習・JRA公式オッズ限定・発走15分前までの確定・確定後不変というルールで実績を積み上げます。</p>
  </section>`;
}

function currentGuideBody(): string {
  return `
  <section class="hero method-emphasis">
    <h1>使い方</h1>
    <p>見るポイントは「対象レース」「次の買い目」「確定買い目」「結果」の4つです。予想は開催中も終了レースを取り込みながら更新されます。</p>
  </section>

  <section class="card panel">
    <div class="guide-step"><span class="step-no">1</span><div><b>当日の対象レースを確認</b><p>各会場5レースが対象です。その日に選ばれた5レースは途中の結果を見て入れ替えません。</p></div></div>
    <div class="guide-step"><span class="step-no">2</span><div><b>「次の買い目」を確認</b><p>ホームには次の未発走対象レースを表示します。まだ確定前なら公開期限、確定済みなら「公開済み」と表示します。</p></div></div>
    <div class="guide-step"><span class="step-no">3</span><div><b>開催中も予想は更新</b><p>前のレースが終了して結果・払戻が確定すると、その情報を継続学習へ追加し、後続レースの馬別評価と買い目評価へ反映します。</p></div></div>
    <div class="guide-step"><span class="step-no">4</span><div><b>発走15分前までに確定</b><p>JRA公式オッズだけを使った保存済み予想を確定します。確定後の買い目は変更しません。</p></div></div>
    <div class="guide-step"><span class="step-no">5</span><div><b>買い目の理由を見る</b><p>対象レースでは、各買い目の推定確率、JRA公式オッズ、確率×オッズ、買い目の評価点を確認できます。直近結果の反映状況も表示します。</p></div></div>
    <div class="guide-step"><span class="step-no">6</span><div><b>レース後に結果を精算</b><p>的中・不的中・返還を確定し、その精算結果は後続レースや次開催の直近学習へ利用します。公開済みの過去買い目は書き換えません。</p></div></div>
  </section>

  <div class="section-title"><h2>表示の意味</h2></div>
  <section class="guide-status">
    <article><b>買い目対象</b><span>その日の固定5レースに選ばれ、まだ買い目確定前です。</span></article>
    <article><b>買い目あり</b><span>買い目が確定済みです。発走前でも「次の買い目」には残ります。</span></article>
    <article><b>見送り</b><span>その日の固定5レースには選ばれていません。</span></article>
    <article><b>的中</b><span>公開買い目のうち返還ではない払戻が発生しました。</span></article>
    <article><b>不的中</b><span>公開買い目の精算が完了し、払戻がありませんでした。</span></article>
    <article><b>返還</b><span>出走取消などにより対象買い目の返還が発生しました。</span></article>
  </section>

  <div class="section-title"><h2>継続学習について</h2></div>
  <section class="card panel method-flow">
    <p><b>「継続学習」は、完成モデル自体を毎レース作り直す意味ではありません。</b> 完成済みベースモデルは固定したまま、予想時点より前に確定した直近30日の結果、特に同じ日の終了レースを強く反映する補正レイヤーを更新します。</p>
    <p>そのため、朝の最初の予想と夕方の予想では、同じ完成モデルを使っていても、その日ここまでの実際の結果が後続レースへ反映されます。</p>
  </section>

  <div class="section-title"><h2>オッズと確定ルール</h2></div>
  <section class="card panel method-flow method-warning">
    <p>市場オッズはJRA公式値だけを使用します。JRA公式オッズを取得できない場合、合成オッズや推定オッズで代用して確定することはありません。</p>
    <p>発走15分前までに確定した買い目は、その後のオッズ変動や結果に関係なく固定されます。</p>
  </section>`;
}

async function loadStableNextBet(env: Env, now = new Date()): Promise<{ selectionExists: boolean | null; nextBet: StableNextBet | null }> {
  const date = jstDate(now);
  try {
    const [selection, races, locked] = await Promise.all([
      env.DB.prepare("SELECT state_value AS value FROM rt_system_state WHERE state_key=? LIMIT 1")
        .bind(`final_daily_selection:${date}`).first<{ value: string | null }>(),
      env.DB.prepare(`
        SELECT race_id AS raceId,venue,race_no AS raceNo,start_time_utc AS startTimeUtc,start_time_jst AS startTimeJst
        FROM rt_races
        WHERE race_date=?
        ORDER BY start_time_utc,race_no,race_id
      `).bind(date).all<RaceRow>(),
      env.DB.prepare(`
        SELECT DISTINCT b.race_id AS raceId
        FROM rt_public_bets b
        JOIN rt_races r ON r.race_id=b.race_id
        WHERE r.race_date=? AND b.source_prediction_id=-2
      `).bind(date).all<{ raceId: string }>(),
    ]);

    if (!selection?.value) return { selectionExists: false, nextBet: null };

    const selectedIds = new Set<string>();
    try {
      const parsed = JSON.parse(selection.value) as { selected?: Array<{ raceId?: unknown }> };
      for (const row of parsed.selected ?? []) {
        const raceId = String(row?.raceId ?? "");
        if (raceId) selectedIds.add(raceId);
      }
    } catch {
      return { selectionExists: true, nextBet: null };
    }

    const lockedIds = new Set(locked.results.map((row) => String(row.raceId)));
    const nowMs = now.getTime();
    const next = races.results
      .filter((row) => selectedIds.has(String(row.raceId)))
      .map((row) => ({ row, startMs: Date.parse(String(row.startTimeUtc ?? "")) }))
      .filter((item) => Number.isFinite(item.startMs) && item.startMs > nowMs)
      .sort((a, b) => a.startMs - b.startMs)[0];

    if (!next) return { selectionExists: true, nextBet: null };
    return {
      selectionExists: true,
      nextBet: {
        raceId: String(next.row.raceId),
        venue: String(next.row.venue),
        raceNo: Number(next.row.raceNo),
        startTimeJst: jstClock(next.row.startTimeUtc) ?? next.row.startTimeJst,
        deadlineJst: deadlineClock(next.row.startTimeUtc),
        locked: lockedIds.has(String(next.row.raceId)),
      },
    };
  } catch (error) {
    console.error("HOME_NEXT_BET_LOAD_FAILED", error);
    return { selectionExists: null, nextBet: null };
  }
}

function stableNextBetHtml(state: { selectionExists: boolean | null; nextBet: StableNextBet | null }): string {
  if (state.nextBet) {
    const next = state.nextBet;
    return `<section class="home-next-release${next.locked ? " home-next-release-locked" : ""}" aria-label="次の買い目">
      <span>次の買い目</span>
      <a href="/races/${encodeURIComponent(next.raceId)}"><b>${esc(next.venue)} ${next.raceNo}R</b><strong>${next.locked ? "公開済み" : `${esc(next.deadlineJst ?? "--:--")}までに公開`}</strong></a>
      <small>${esc(next.startTimeJst ?? "--:--")}発走</small>
    </section>`;
  }
  if (state.selectionExists === true) {
    return `<section class="home-next-release home-next-release-empty" aria-label="次の買い目">
      <span>次の買い目</span>
      <div class="home-next-release-copy"><b>本日の対象買い目は終了</b></div>
      <small>次回は次の開催日の対象決定後に表示</small>
    </section>`;
  }
  if (state.selectionExists === false) {
    return `<section class="home-next-release home-next-release-empty" aria-label="次の買い目">
      <span>次の買い目</span>
      <div class="home-next-release-copy"><b>対象レース決定後に表示</b></div>
      <small>当日8:00以降に対象レースを決定</small>
    </section>`;
  }
  return `<section class="home-next-release home-next-release-empty" aria-label="次の買い目">
    <span>次の買い目</span>
    <div class="home-next-release-copy"><b>次の買い目を確認中</b></div>
    <small>ページを再読み込みすると更新されます</small>
  </section>`;
}

function normalizeCurrentOperationalCopy(input: string): string {
  const replacements: Array<[string, string]> = [
    ["最近30日間のレース結果を反映：", "直近30日＋当日終了レースを継続反映："],
    ["最近30日間のレース結果を反映", "直近30日＋当日終了レースを継続反映"],
    ["各レースの1着予想と、最近の結果の反映状況", "各レースの1着予想と、当日を含む直近結果の反映状況"],
    ["最近のレース結果の反映", "当日を含む直近結果の反映"],
    ["最近の結果の反映状況", "当日を含む直近結果の反映状況"],
    ["通常と異なる方法で買い目を確定", "保存済みのJRA公式オッズ付き予想で買い目を確定"],
    ["JRA公式オッズを取得できなかったため、発走15分前の時点で利用できた予測データを使って買い目を確定しました。この買い目も通常どおり成績に集計します。", "JRA公式オッズを取得できない場合は、推定・合成オッズで代用せず買い目を確定しません。"],
    ["JRA公式オッズを取得できなかったため、発走15分前の時点で利用できた予測データから2種類の買い目を選びました。取得できていないオッズは表示していません。", "JRA公式オッズを取得できない場合は、推定・合成オッズで代用せず買い目を確定しません。"],
    ["フォールバック", "保存済み予想"],
  ];
  return replacements.reduce((html, [from, to]) => html.split(from).join(to), input);
}

function homeLiveLearningHtml(): string {
  return `<section class="home-live-learning" aria-label="当日の予想更新">
    <b>予想は当日も継続更新</b>
    <span>終了したレースと確定した払戻を次の予想へ反映 → JRA公式オッズだけで評価 → 発走15分前までに確定後は変更しません。</span>
    <a href="/conditions">しくみを見る</a>
  </section>`;
}

async function rewritePublicHtml(response: Response, env: Env, path: string): Promise<Response> {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;

  let html = normalizeCurrentOperationalCopy(await response.text());
  if (path === "/") {
    const state = await loadStableNextBet(env);
    const slot = stableNextBetHtml(state);
    if (html.includes('class="home-next-release')) {
      html = html.replace(/<section class="home-next-release[\s\S]*?<\/section>/, slot);
    } else if (html.includes('<details class="home-publish-flow home-publish-details">')) {
      html = html.replace('<details class="home-publish-flow home-publish-details">', `${slot}<details class="home-publish-flow home-publish-details">`);
    } else {
      html = html.replace(/(<div class="section-title"><h2>累計回収率<\/h2>)/, `${slot}$1`);
    }
    if (!html.includes('class="home-live-learning"')) {
      const strip = homeLiveLearningHtml();
      if (html.includes('class="home-next-release')) {
        html = html.replace(/(<section class="home-next-release[\s\S]*?<\/section>)/, `$1${strip}`);
      } else {
        html = html.replace(/(<div class="section-title"><h2>累計回収率<\/h2>)/, `${strip}$1`);
      }
    }
  }

  html = html.replace(
    "</head>",
    `<style>
      .home-next-release-empty{border-color:var(--line);background:var(--panel)}.home-next-release-copy{display:flex;align-items:baseline;min-width:0}.home-next-release-empty b{font-size:14px;color:var(--text)}.home-next-release-locked strong{color:var(--green)}
      .home-live-learning{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:9px;align-items:center;margin:0 0 10px;padding:10px 12px;border:1px solid var(--line);border-radius:13px;background:var(--panel2)}.home-live-learning b{font-size:12px;color:var(--green);white-space:nowrap}.home-live-learning span{font-size:11px;color:var(--muted);line-height:1.55}.home-live-learning a{font-size:11px;color:var(--blue);white-space:nowrap}
      @media(max-width:760px){.home-next-release-copy{grid-column:2}.home-next-release-empty small{grid-column:2}.home-live-learning{grid-template-columns:1fr}.home-live-learning b,.home-live-learning a{white-space:normal}}
    </style></head>`,
  );

  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("x-race-ui-version", UI_VERSION);
  headers.set("cache-control", "no-store, max-age=0");
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const path = new URL(request.url).pathname;
    if (path === "/conditions") return docsResponse("予想のしくみ", currentConditionsBody(), path);
    if (path === "/guide") return docsResponse("使い方", currentGuideBody(), path);
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    return rewritePublicHtml(response, env, path);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
