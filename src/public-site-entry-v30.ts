import publicSite from "./public-site-entry-v29.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v30-clear-language-20260816";

function replaceExact(html: string, from: string, to: string): string {
  return html.split(from).join(to);
}

function removeTodayHomeHero(input: string): string {
  return input.replace(
    '<section class="hero today-hero"><span class="today-pill">TODAY</span><h1>今日のレース</h1><p>年 → 月 → 日付 → 会場 → レースの順に選ぶだけで、全レースを確認できます。買い目対象・見送り・判定中も同じ画面で分かります。</p></section>',
    "",
  );
}

function clarifyCommonLanguage(input: string): string {
  let html = input;

  const exact: Array<[string, string]> = [
    ["非常用T-15確定", "通常と異なる方法で買い目を確定"],
    ["JRA公式オッズ取得失敗のため、モデル確率優先のフォールバックで買い目を固定しました。成績集計には通常どおり含めます。", "JRA公式オッズを取得できなかったため、発走15分前の時点で利用できた予測データを使って買い目を確定しました。この買い目も通常どおり成績に集計します。"],
    ["取得失敗・確率優先", "取得できませんでした"],
    ["非常用選定", "買い目の決め方"],
    ["モデル確率優先", "予測した当たりやすさを優先"],
    ["JRA公式オッズの取得に失敗したため、買い目未生成を防ぐ非常用経路で確定しました。利用可能なモデル確率と直近学習を優先して2券種を選定しています。オッズは捏造せず表示しません。", "JRA公式オッズを取得できなかったため、発走15分前の時点で利用できた予測データから2種類の買い目を選びました。取得できていないオッズは表示していません。"],
    ["組合せ予測確率", "この組合せが当たる推定確率"],
    ["確率 × オッズ", "推定確率 × 公式オッズ"],
    ["最終スコア", "買い目の評価点"],
    ["各券種で「予測確率 × JRA公式オッズ」上位5候補 → 最終スコアで券種代表 → 異なる2券種から最終2点、の順で絞っています。", "まず各券種で「推定確率 × JRA公式オッズ」が高い5候補に絞り、評価点で各券種から1つを選びます。その後、異なる券種から最終的に2点を採用します。"],
    ["この券種の全組合せの中で「予測確率 × 公式オッズ」の上位5候補に残り、その5候補を最終スコアで比べて券種代表になりました。6券種の代表から異なる2券種を選ぶ最終選考でも残ったため、この買い目を採用しています。", "この券種の全組合せから「推定確率 × JRA公式オッズ」が高い5候補に絞り、その中で評価点が最も高かったため採用候補になりました。最後に6券種の候補を比較し、異なる2券種の中で評価が高かったため、この買い目を採用しています。"],
    [">根拠<", ">買い目の理由<"],
    [">馬一覧<", ">出走馬<"],
    ["直近30日学習：", "最近30日間のレース結果を反映："],
    ["直近30日学習", "最近30日間のレース結果を反映"],
    ["直近学習", "最近のレース結果の反映"],
    ["学習情報", "最近の結果の反映状況"],
    ["モデル1着確率", "1着になる推定確率"],
    ["1着確率を見る", "1着になる推定確率を見る"],
    ["1着確率", "1着になる推定確率"],
    ["馬体重反映済", "最新の馬体重を反映済み"],
    ["7日内", "過去7日"],
    ["対象5R取得済み", "対象5レースを取得済み"],
    ["JRA対象5レースは取得済み", "JRA公式サイトから対象5レースを取得済み"],
    ["JRA公式を再確認中", "JRA公式サイトから対象レースを確認しています"],
    ["JRA公式ページを再取得します", "JRA公式サイトから対象レースを確認しています"],
    ["5R通過確率", "5レースすべて的中する推定確率"],
    ["5R通過", "5レースすべて的中（推定）"],
    ["広めに押さえて通過率を優先", "選ぶ馬を広めにして、5レースすべて当たる可能性を優先"],
    ["点数と通過率のバランス型", "購入点数と、5レースすべて当たる可能性のバランス型"],
    ["カバー ", "選んだ馬が1着になる合計確率 "],
    ["条件一致スコア", "買い目の評価点"],
    ["市場との乖離", "人気・オッズと予測の差"],
    ["市場評価順位", "オッズから見た人気順位"],
    ["直近好走回数", "最近の好走回数"],
  ];

  for (const [from, to] of exact) html = replaceExact(html, from, to);

  html = html
    .replace(/T[-–](\d+)/g, (_match, minutes) => `発走${minutes}分前`)
    .replace(/(\d{2}:\d{2}) JST/g, "$1（日本時間）")
    .replace(/>予想ロジック</g, ">予想のしくみ<")
    .replace(/>条件詳細</g, ">予想のしくみ<")
    .replace(/>見方</g, ">使い方<");

  return html;
}

function clarifyWin5Language(input: string): string {
  let html = input;
  const exact: Array<[string, string]> = [
    ["T-15で固定済み", "最初の対象レースの発走15分前に確定済み"],
    ["T-15まで更新", "最初の対象レースの発走15分前まで更新"],
    ["最終確定", "買い目の確定時刻"],
    ["最終更新", "予想の更新時刻"],
    ["予測更新", "予想の更新時刻"],
    ["上から順にWIN1 → WIN5", "上から順に1レース目 → 5レース目"],
    ["更新時刻・1着確率・直近学習の詳細", "予想の更新時刻・各馬が1着になる推定確率・最近のレース結果の反映状況"],
    ["各レースの1着確率・学習情報", "各レースの1着予想と、最近の結果の反映状況"],
    ["10年モデル＋直近・当日学習で5レースの1着確率を算出し、予算内で通過確率が最大になる組み合わせを自動構成。", "過去10年のデータに加えて、最近と当日のレース結果も反映して各馬が1着になる可能性を予測し、予算内で5レースすべてが当たる可能性が高くなる組み合わせを選びます。"],
    ["まず買い目を見て、必要なときだけ確率や学習情報を開ける構成にしています。", "最初に買い目を表示します。詳しい1着予想や、最近のレース結果の反映状況は「その他」で確認できます。"],
  ];
  for (const [from, to] of exact) html = replaceExact(html, from, to);

  // Keep the production smoke marker without showing an English product label.
  if (html.includes("WIN5 PREDICTION")) {
    html = replaceExact(html, "WIN5 PREDICTION", "WIN5予想");
    html = html.replace("</body>", "<!-- WIN5 PREDICTION --></body>");
  }
  return html;
}

async function clarifyHtmlResponse(response: Response, path: string): Promise<Response> {
  if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
  let html = await response.text();
  if (path === "/win5") html = clarifyWin5Language(html);
  html = clarifyCommonLanguage(html);
  if (path === "/") html = removeTodayHomeHero(html);
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("x-race-ui-version", UI_VERSION);
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    return clarifyHtmlResponse(response, new URL(request.url).pathname);
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
