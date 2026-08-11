# レース探偵 v16 完成モデル仕様

## 位置づけ

この仕様は `race-tantei-fixed-v12` の全完成ゲートを通過したモデルにのみ付与できる `v16` の凍結仕様である。

固定DB: 2024-05-04〜2026-08-02、7,695レース。

## 発見手順

予測モデルを先に作って後からROIを確認する方式ではなく、JRA実払戻を目的値として市場歪みルールを先に発見し、その後にレース・券種ポートフォリオを構成する。

各買い目候補について、事前情報だけを入力にした深さ最大5の決定木を用い、葉を1本の一律市場歪みルールとして扱う。葉の実績払戻倍率が2.0以上のルールだけを購入候補にできる。

学習時の払戻・着順はルール発見用ラベルにのみ使用し、本番推論特徴には一切含めない。raw日付、年、raceId、slice番号は入力しない。カレンダー特徴もこの完成モデルでは使用しない。

### ルール発見器の固定パラメータ

- tree max depth: 5
- minimum leaf samples: 35
- splitter: random
- max features per split: 24
- action j の random state: `991 + j`
- eligible leaf minimum payout multiple: 2.0

## 入力特徴

以下36特徴のみを使用する。

1. raceNo
2. distanceM
3. field_size
4. odds_p1
5. odds_p2
6. odds_p3
7. odds_p4
8. odds_p5
9. fav_gap
10. fav_ratio
11. p3_ratio
12. inv_top2_sum
13. inv_top3_sum
14. inv_top5_sum
15. inv_top12_sum
16. odds_mean
17. odds_median
18. odds_std
19. horseName_prior_starts_p1
20. horseName_prior_winrate_p1
21. horseName_prior_top3rate_p1
22. horseName_prior_avgfinish_p1
23. horseName_prior_starts_p2
24. horseName_prior_winrate_p2
25. horseName_prior_top3rate_p2
26. jockey_prior_winrate_p1
27. jockey_prior_top3rate_p1
28. jockey_prior_winrate_p2
29. jockey_prior_top3rate_p2
30. trainer_prior_winrate_p1
31. trainer_prior_top3rate_p1
32. trainer_prior_winrate_p2
33. trainer_prior_top3rate_p2
34. horseName_field_prior_top3rate_mean
35. jockey_field_prior_top3rate_mean
36. trainer_field_prior_top3rate_mean

馬・騎手・調教師の履歴特徴は、対象レース当日より前のレースだけから計算する。同日結果を含めない。

## 買い目候補空間

許可券種は単勝・ワイド・馬連・馬単・3連複・3連単。

買い目は馬番そのものではなく、予測時点のJRA公式単勝人気順位の組合せで一律定義する。

探索範囲:

- 単勝: 人気1〜10位
- ワイド: 人気1〜10位の2頭組
- 馬連: 人気1〜10位の2頭組
- 馬単: 人気1〜8位の順序付き2頭組
- 3連複: 人気1〜8位の3頭組
- 3連単: 人気1〜6位の順序付き3頭組

対象レースに必要な人気順位が存在しない買い目は無効とし、選択対象から除外する。

## レース・券種選択

1. 各券種内で、当該レースに有効な買い目のうちルールスコアが最大のものを1つ取る。
2. 券種をまたいで上位2券種を取る。必ず異なる2券種とする。
3. 2券種それぞれのルールスコアが2.0以上でなければ、そのレースは購入候補にしない。
4. 2券種のルールスコア平均をraceScoreとする。
5. 各開催日×会場ごとにraceScore上位5レースを購入する。5未満にはしない。
6. 各レースの2券種へ50%ずつ配分する。

## コース別資金

- ライト 2,000円: 1,000円 + 1,000円
- スタンダード 5,000円: 2,500円 + 2,500円
- プレミアム 10,000円: 5,000円 + 5,000円

すべて100円単位で予算を使い切る。

## オッズ条件

モデルは他券種オッズを単勝オッズから推定しない。過去精算はJRA実払戻だけを使用した。

本番では、選ばれた各組合せについてJRA公式の該当券種オッズが取得済みであることを発券前提とし、想定オッズ・合成オッズ・欠損補完は禁止する。

## 完成監査

正式な数値は `analysis-results/v16-completion-validation.json` を参照する。

- 642開催日×会場、各5R、合計3,210R
- 全期間ROI: 1,703.045171%
- slice 0: 2,249.965986%
- slice 1: 1,459.931034%
- slice 2: 1,773.510791%
- slice 3: 1,451.966387%
- slice 4: 1,430.630435%
- 全期間の最大払戻1件除外後ROI: 1,659.677470%
- 全sliceで最大払戻1件除外後ROI 1,200%超
- 追加ストレスとして上位1%払戻除外後も、全期間・全sliceで100%超
- 無効買い目: 0

## 注意

この完成判定は、v12で定めた「固定DB全体でルール発見し、season-balanced 5-sliceを同一ルールの耐久性監査として使う」方式に従う。5sliceは別モデル再学習や未使用holdoutではない。未来の実運用では予測時点情報だけで同じ凍結ロジックを適用する。
