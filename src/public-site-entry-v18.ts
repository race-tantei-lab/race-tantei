import publicSite from "./public-site-entry-v17.js";
import { shell } from "./v1/public-ui.js";
import type { Env } from "./v1/types.js";

function htmlResponse(body:string,version:string):Response{
  return new Response(body,{headers:{
    "content-type":"text/html; charset=utf-8",
    "cache-control":"no-store, max-age=0",
    "x-race-ui-version":version,
    "x-content-type-options":"nosniff",
    "referrer-policy":"no-referrer"
  }});
}

function currentConditionsPage():string{
  const body=`
  <section class="hero">
    <h1>条件詳細</h1>
    <p>「どのレースを買うか」と「そのレースで何を買うか」は別々の段階で決めています。対象レースの結果を見てから選び直すことはせず、発走前までに利用する履歴・出走馬情報・JRA公式オッズから固定します。</p>
  </section>
  <section class="rule-summary">
    <article class="rule-box"><b>各会場5レース</b><span>12レースをそのまま勝率順に並べるのではなく、過去履歴から各レースの「買い目を作りやすい度合い」を計算し、上位5レースを選びます。</span></article>
    <article class="rule-box"><b>馬別勝率は56項目</b><span>馬・騎手・調教師・コース適性・近走など、発走前に確定している56項目から各馬の勝率を推定します。人気順位そのものは勝率モデルへ入れません。</span></article>
    <article class="rule-box"><b>買い目は2点固定</b><span>単勝・ワイド・馬連・馬単・3連複・3連単を全部評価し、異なる2券種から1点ずつ、合計2点に絞ります。</span></article>
    <article class="rule-box"><b>公式オッズのみ</b><span>最終買い目の評価にはJRA公式オッズだけを使用します。合成オッズ・推定オッズでは代用しません。</span></article>
    <article class="rule-box"><b>対象日の結果は不使用</b><span>対象日の着順・払戻はレース選定にも買い目作成にも入れません。確定後に、将来日の履歴へ追加します。</span></article>
    <article class="rule-box"><b>過去成績の意味を分離</b><span>431.7%・的中レース率54.4%は完成ルールを過去10年全体へ適用した後方集計です。完全OOF成績や将来の保証としては扱いません。</span></article>
  </section>

  <div class="section-title"><h2>① 5レースをどう選ぶか</h2><span class="muted">12R → 5R</span></div>
  <section class="card panel condition-flow">
    <ol>
      <li><b>対象日より前の履歴だけで状態を更新</b><br>馬の近走、騎手・調教師成績、過去の券種別・条件別払戻統計などを、前日までの確定履歴から持ちます。対象日の結果はここへ入れません。</li>
      <li><b>各レースで出走馬を履歴評価</b><br>近走着順、速度傾向、騎手・調教師の3着内率、出走経験、直近3走の3着内回数などから順位付けし、レース選定用に上位5頭を残します。</li>
      <li><b>上位5頭から「仮想買い目」を作る</b><br>単勝・ワイド・馬連・馬単・3連複・3連単の組合せを作ります。これは最終公開買い目ではなく、そのレースが過去傾向上どれだけ買いやすいかを測るためのproxyです。</li>
      <li><b>過去ROIを平滑化して仮想買い目を採点</b><br>券種・会場・芝ダート・距離帯・頭数・クラス・馬の履歴特徴などに対応する過去払戻統計を使います。件数の少ない条件だけが偶然高くならないよう、券種全体の基準値を混ぜて平滑化します。</li>
      <li><b>上位3つの仮想買い目からraceScoreを作る</b><br>少なくとも2券種を含む上位3候補のscore平均を、そのレースのraceScoreにします。</li>
      <li><b>会場ごとにraceScore上位5R</b><br>各会場のレースをraceScoreの高い順に並べて5レースを選びます。同点ならレース番号の若い方を先にします。</li>
    </ol>
    <p class="muted"><b>重要:</b> 56項目の勝率モデルが12レースから5レースを直接選んでいるわけではありません。レース選定は、前日までの履歴を使った上記の仮想買い目評価で行います。またレース選定には対象日の最終オッズを使いません。</p>
  </section>

  <div class="section-title"><h2>② 馬ごとの勝率をどう出すか</h2><span class="muted">56項目</span></div>
  <section class="grid2">
    <article class="panel"><h3>レース・コース</h3><p>会場、レース番号、芝・ダート、距離、回り、頭数、月、クラス、天候、馬場状態など。</p></article>
    <article class="panel"><h3>馬</h3><p>馬番・枠番、性齢、馬体重、増減、斤量、出走数、過去勝率・3着内率、休養日数、直近1・3・5走の着順・上がり・速度など。</p></article>
    <article class="panel"><h3>適性</h3><p>同じ芝・ダート、距離帯、会場での出走数・勝率・3着内率、距離変更、芝ダート変更など。</p></article>
    <article class="panel"><h3>人・組み合わせ</h3><p>騎手、調教師、馬×騎手の過去出走数・勝率・3着内率を使用します。</p></article>
  </section>
  <section class="card panel">
    <p>各馬の予測値を出したあと、同じレースの全馬で合計が1になるように正規化して、そのレース内の勝率として扱います。着順・払戻・教師ラベル・人気順位そのものは勝率モデルの入力に含めません。</p>
  </section>

  <div class="section-title"><h2>③ 連系も含めて1点までどう絞るか</h2><span class="muted">全組合せ → 2点</span></div>
  <section class="card panel condition-flow">
    <ol>
      <li><b>6券種の全組合せを作る</b><br>単勝・ワイド・馬連・馬単・3連複・3連単を対象に、取得できたJRA公式オッズの全組合せを候補にします。</li>
      <li><b>着順組合せの確率を計算</b><br>正規化した馬別勝率からPlackett-Luce方式で計算します。馬単・3連単は順序付き、馬連は2順序、3連複は6順序を合算。ワイドはその2頭がともに3着以内へ入る全順序を合算します。</li>
      <li><b>券種ごとにEV上位5候補へ絞る</b><br><b>予測確率 × JRA公式オッズ</b> が高い順に並べ、各券種で上位5候補だけを残します。</li>
      <li><b>上位5候補を再採点して1点へ</b><br><b>ln(予測確率) + 0.4 × ln(JRA公式オッズ)</b> で再評価し、その券種で最も高い1点を残します。</li>
      <li><b>6券種の代表から異なる2券種を選ぶ</b><br>券種ごとの代表1点をscore順に並べ、異なる2券種から1点ずつ選択します。これが公開する2点です。</li>
    </ol>
    <p>連系馬券が1点だけでも、的中組合せを結果から逆算して直接選んでいるのではありません。全組合せを同じ計算で評価したあと、上記の固定ルールで1点まで圧縮しています。</p>
  </section>

  <div class="section-title"><h2>④ 購入額</h2><span class="muted">選ぶ2点は共通</span></div>
  <section class="rule-summary">
    <article class="rule-box"><b>ライト</b><span>1,000円 + 1,000円 = 2,000円</span></article>
    <article class="rule-box"><b>スタンダード</b><span>2,500円 + 2,500円 = 5,000円</span></article>
    <article class="rule-box"><b>プレミアム</b><span>5,000円 + 5,000円 = 10,000円</span></article>
  </section>

  <div class="section-title"><h2>⑤ 431.7%・54.4%はどう読むか</h2><span class="muted">監査上の注意</span></div>
  <section class="card panel condition-flow">
    <p><b>431.7%の回収率と約54.4%の的中レース率は、凍結した過去10年の14,410レースへ完成ルールを適用した全期間の後方集計です。</b></p>
    <p>対象日結果の直接利用、合成オッズ、結果項目を勝率モデルへ入れる処理は監査で確認されていません。一方、この431.7%自体は<b>完全なOOF成績ではありません</b>。完成までの研究ではルール候補の比較も行われているため、「まったく未使用のデータだけで431.7%だった」「将来も431.7%が期待できる」という意味にはしません。</p>
    <p>また、過去買い目のオッズはJRA公式値との整合を監査していますが、14,410レースすべてについて、そのオッズの<b>取得時刻が現在のlive運用の買い目lock時刻と完全に同じ条件だったこと</b>までは、現在の正本記録だけでは独立に証明できません。この点も、過去成績をlive同条件の将来期待値とみなさない理由です。</p>
  </section>

  <div class="section-title"><h2>⑥ 漏洩チェック</h2></div>
  <section class="grid2">
    <article class="panel"><h3>確認済み</h3><p>レース選定で対象日の結果を使わない、レース選定で対象日の最終オッズを使わない、勝率モデルから着順・教師ラベル・人気順位そのものを除外、JRA公式オッズのみ、合成・推定オッズなし。</p></article>
    <article class="panel"><h3>分けて考えること</h3><p>直接的な結果リークが見つからないことと、過去431.7%が無偏な将来期待値であることは別です。研究時のルール選択や過去オッズの取得時刻の同等性は、別の検証上の注意として扱います。</p></article>
  </section>

  <div class="section-title"><h2>公開後の扱い</h2></div>
  <section class="card panel"><p>公開済みの過去買い目は固定します。新しいレース結果は将来日の履歴更新にだけ利用し、過去の買い目や過去成績を後から有利に書き換えることはありません。</p></section>
  <style>.condition-flow ol{margin:0;padding-left:22px}.condition-flow li{margin:0 0 14px;line-height:1.75}.condition-flow li:last-child{margin-bottom:0}.condition-flow p{line-height:1.75}</style>`;
  return shell("条件詳細",body);
}

function fixHomeYearOrder(html:string):string{
  return html.replace(
    'const years=uniq(calendar.map(x=>x.raceDate.slice(0,4)));',
    'const years=uniq(calendar.map(x=>x.raceDate.slice(0,4))).sort((a,b)=>b.localeCompare(a));'
  );
}

function fixLoseStatusColor(html:string):string{
  return html.replace("</head>",'<style>.status.lose{background:#4a2328!important;color:#ff817c!important}</style></head>');
}

function fixRaceBetLayout(html:string):string{
  let out=html.replace(/<div class="course-tabs">[\s\S]*?<\/div>/g,"");
  out=out.replace(/style="display:none"/g,'style=""');
  const names=["ライト","スタンダード","プレミアム"];
  for(let i=0;i<names.length;i++){
    const marker=new RegExp(`<div class="course-view" data-course="${i}" style="">`,'g');
    out=out.replace(marker,`<div class="course-view" data-course="${i}" style=""><h3 class="course-heading">${names[i]}</h3>`);
  }
  const css=`<style>
  .course-tabs{display:none!important}.course-view{display:block!important;margin:12px 0 18px}.course-heading{margin:0 0 8px;font-size:18px}.bet-table{overflow:visible}.bet-table table{width:100%;min-width:0}
  @media(max-width:760px){
    .bet-table table,.bet-table tbody,.bet-table tr,.bet-table td{display:block;width:100%;min-width:0}.bet-table thead{display:none}.bet-table tr{border:1px solid var(--line);border-radius:14px;background:var(--panel2);padding:10px 12px;margin:8px 0}.bet-table td{border:0;padding:4px 0;font-size:13px;word-break:break-word}.bet-table td:nth-child(1)::before{content:"券種　";color:var(--muted)}.bet-table td:nth-child(2)::before{content:"組合せ　";color:var(--muted)}.bet-table td:nth-child(3)::before{content:"オッズ　";color:var(--muted)}.bet-table td:nth-child(4)::before{content:"購入　";color:var(--muted)}.bet-table td:nth-child(5)::before{content:"払戻　";color:var(--muted)}
  }
  </style>`;
  return out.replace("</head>",`${css}</head>`);
}

export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    const url=new URL(request.url);const path=url.pathname;
    if(path==="/conditions")return htmlResponse(currentConditionsPage(),"ten-year-completed-v18");
    if(!publicSite.fetch)return new Response("NOT_FOUND",{status:404});
    const upstream=await publicSite.fetch(request,env,ctx);
    if(!upstream.ok||!upstream.headers.get("content-type")?.includes("text/html"))return upstream;
    let html=await upstream.text();
    html=fixLoseStatusColor(html);
    if(path==="/")html=fixHomeYearOrder(html);
    if(path.startsWith("/races/"))html=fixRaceBetLayout(html);
    const headers=new Headers(upstream.headers);headers.delete("content-length");headers.set("cache-control","no-store, max-age=0");headers.set("x-race-ui-version","ten-year-completed-v18");
    return new Response(html,{status:upstream.status,headers});
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);}
} satisfies ExportedHandler<Env>;
