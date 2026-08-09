import { FROZEN_RULE_COUNT, FROZEN_RULE_DESCRIPTIONS } from "./frozen-rule-descriptions.js";
import { shell } from "./public-ui.js";
import { escapeHtml } from "./utils.js";

const BET_TYPES = ["単勝", "馬連", "ワイド", "馬単", "3連複", "3連単"] as const;

export function renderPublicConditions(): string {
  const ruleGroups = BET_TYPES.map((betType) => {
    const rows = FROZEN_RULE_DESCRIPTIONS[betType] ?? [];
    return `<details class="rule-group"><summary>${escapeHtml(betType)}　${rows.length}条件</summary><ol class="rule-list">${rows.map((row) => `<li>${escapeHtml(row)}</li>`).join("")}</ol></details>`;
  }).join("");

  const body = `<section class="hero"><h1>条件詳細</h1><p>買い目は、予想時点までに取得できた情報だけを使い、下記の条件と共通ルールを同じ手順で全レースに適用して決めます。結果が出たあとに、そのレースの買い目や購入額を書き換えることはありません。</p></section>
  <section class="rule-summary">
    <article class="rule-box"><b>対象レース</b><span>各会場・各開催日から5レースを選びます。条件に合う買い目の強さで順位を付け、同じ強さならレース番号が若い方を優先します。</span></article>
    <article class="rule-box"><b>1レースの買い目</b><span>3〜10点です。最も強い条件一致に対して85%以上の候補を残し、3点に満たない場合は条件に合う候補から強い順に3点まで採用します。</span></article>
    <article class="rule-box"><b>購入額</b><span>ライト2,000円、スタンダード5,000円、プレミアム10,000円。どのコースも1レースの予算を100円単位で配分します。</span></article>
    <article class="rule-box"><b>1点への集中上限</b><span>1つの買い目に配分できるのは、そのレース予算の35%までです。1点だけに大きく集中する買い方はしません。</span></article>
    <article class="rule-box"><b>高オッズの配分</b><span>高オッズになるほど購入額の比重を段階的に抑えます。100倍を基準に、オッズが高くなるほどリスクを小さくする共通配分です。</span></article>
    <article class="rule-box"><b>過去情報の扱い</b><span>馬・騎手・厩舎・近走などの履歴は、そのレースより前の情報だけを使用します。終了したレースは将来の改善材料になりますが、過去の記録は変更しません。</span></article>
  </section>
  <div class="section-title"><h2>実際に使う全条件</h2><span class="muted">全${FROZEN_RULE_COUNT}条件</span></div>
  <div class="notice" style="color:#d7e1eb;border-color:#2b3d52;background:#0c1723;box-shadow:inset 3px 0 0 #2d806c">下の各項目は「その券種で買い目候補になる組合せの条件」です。会場・距離・JRA実オッズ・馬場・人気構成・市場との乖離・近走・騎手・厩舎など、記載された条件をすべて満たした候補を同じ手順で判定します。</div>
  ${ruleGroups}`;

  return shell("条件詳細", body);
}
