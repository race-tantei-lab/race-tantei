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
    <p>現在の予想は、対象レースの結果を使わず、発走前までに取得できる履歴・出走馬情報・JRA公式オッズだけでレース選定から買い目まで一貫して決めます。過去に公開した買い目はあとから変更しません。</p>
  </section>
  <section class="rule-summary">
    <article class="rule-box"><b>対象レース</b><span>JRA開催を対象に、各会場・各開催日から5レースを選びます。選定は過去履歴から作るレーススコアで行い、その日の結果は使いません。</span></article>
    <article class="rule-box"><b>馬ごとの勝率</b><span>馬・騎手・調教師・コース適性・近走など、発走前に確定している56項目から勝率を推定します。人気順位そのものは勝率モデルへ入れません。</span></article>
    <article class="rule-box"><b>買い目は2点固定</b><span>1レースにつき必ず2点。しかも同じ券種から2点ではなく、異なる2券種から1点ずつ選びます。</span></article>
    <article class="rule-box"><b>購入額</b><span>ライトは1点1,000円、スタンダードは1点2,500円、プレミアムは1点5,000円。どのコースも2点を50%ずつ購入します。</span></article>
    <article class="rule-box"><b>公式オッズのみ</b><span>買い目の評価にはJRA公式オッズだけを使用します。合成オッズや推定オッズで代用しません。</span></article>
    <article class="rule-box"><b>時系列を厳守</b><span>対象レースの着順・払戻・対象日後の情報は予想に使いません。確定後の結果は、次回以降に使う履歴へだけ追加します。</span></article>
  </section>
  <div class="section-title"><h2>レース選定</h2><span class="muted">各会場5R</span></div>
  <section class="card panel">
    <p>過去のレース結果から更新した馬・騎手・調教師などの履歴状態を使ってレーススコアを計算し、各会場・各開催日の上位5レースを買い目候補にします。対象日の結果を見てからレースを選び直すことはありません。</p>
  </section>
  <div class="section-title"><h2>勝率推定に使う主な情報</h2><span class="muted">発走前情報のみ</span></div>
  <section class="grid2">
    <article class="panel"><h3>レース・コース</h3><p>会場、レース番号、芝・ダート、距離、回り、頭数、月、クラス、天候、馬場状態など。</p></article>
    <article class="panel"><h3>馬</h3><p>馬番・枠番、性齢、馬体重、増減、斤量、出走数、勝率・3着内率、休養日数、直近1・3・5走の着順・上がり・速度など。</p></article>
    <article class="panel"><h3>適性</h3><p>同じ芝・ダート、距離帯、会場での出走数・勝率・3着内率、距離変更、芝ダート変更など。</p></article>
    <article class="panel"><h3>人・組み合わせ</h3><p>騎手、調教師、馬×騎手の過去出走数・勝率・3着内率を使用します。</p></article>
  </section>
  <div class="section-title"><h2>買い目の決め方</h2><span class="muted">6券種から2点</span></div>
  <section class="card panel">
    <p>対象券種は <b>単勝・ワイド・馬連・馬単・3連複・3連単</b> の6種類です。馬ごとの勝率から着順組み合わせの確率を計算し、各券種で「予測確率 × JRA公式オッズ」が高い上位5候補を残します。</p>
    <p>その後、各候補を <b>ln(予測確率) + 0.4 × ln(JRA公式オッズ)</b> で評価し、最終的にスコアが高い <b>異なる2券種</b> から1点ずつ選びます。</p>
  </section>
  <div class="section-title"><h2>公開後の扱い</h2></div>
  <section class="card panel"><p>公開済みの過去買い目は固定します。新しいレース結果は将来日の履歴更新にだけ利用し、過去の買い目や過去成績を後から有利に書き換えることはありません。</p></section>`;
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
