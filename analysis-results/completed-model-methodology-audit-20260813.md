# 完成モデル 方法論監査 — 2026-08-13

この文書は、現在の完成済み予想ロジックを変更せず、レース選定・買い目選定・過去成績の評価方法をコードと正本成果物から監査した記録である。

## 結論

- 本番のレース選定経路で、対象日の着順・払戻を見て選び直す直接的な結果リークは確認されなかった。
- レース選定はLightGBMが直接5レースを選ぶ方式ではない。予想時点より前の履歴stateから出走馬を評価し、上位5頭を使って6券種のproxy ticketを作り、その過去ROI統計を平滑化したscoreからraceScoreを作り、各会場の上位5レースを選ぶ。
- 最終買い目は56特徴量のLightGBMで馬別勝率を出し、レース内で正規化し、Plackett-Luceで各組合せ確率を計算する。各券種で `predictedProbability × officialJraOdds` 上位5候補を残し、`ln(predictedProbability) + 0.4 × ln(officialJraOdds)` で再評価する。券種ごとの1位から、異なる2券種を1点ずつ選ぶ。
- JRA公式オッズ以外を使う経路、synthetic/estimated odds、対象日結果をレース選定へ混入する経路は完成監査上0件。
- 一方、公開している ROI **431.6505898681471%** と的中レース率約54.4%は、完成監査JSON上 `trainingMode: full frozen archive uniform discovery` の完成ルールを凍結10年アーカイブ全体へ適用した retrospective full-period aggregate である。**431.6505898681471%そのものを完全OOF成績、未使用期間だけの成績、または将来期待値と呼んではいけない。**
- 完成までに日付分割・スライス等のロバスト性確認は存在するが、公開431.65%そのものと別物として扱う。completion audit の5 slicesも、正本だけから各行が必ずその行を除外して再学習された予測だとは証明できない。
- 研究履歴 `acf44ad91c83e30f3a3e0363b43bbc8fb4a51a2c` では race-selection の local-weight を 0.15 / 0.30 / 0.45 / 0.60 で sweep している。したがって少なくともレース選定側には同じ歴史アーカイブを使った研究選択の影響があり、過去集計を無偏な将来推定値として扱うべきではない。
- 最終買い目scoreの係数0.4について、現在の正本は「完成ルールとして0.4を使う」ことを明確に記録しているが、0.4が事前固定だったのか、nested OOF内で選ばれたのかを独立に証明する正本成果物は今回確認できなかった。根拠のない「事前固定だった」という説明はしない。
- 過去買い目で使ったオッズは完成監査上JRA公式ソースとのidentity/horse-set整合が確認され、synthetic oddsは0件。ただし、過去14,410Rで買い目選定に使った各オッズの取得timestampが、現在のlive運用のlock時刻と完全に同等だったことを証明するtimestamp証跡は完成監査JSON単体にはない。そのため431.65%を「現在のlive lockと完全同条件のバックテスト」とも表現しない。

## 1. レース選定の実コード

正本: `scripts/ten-year-production-core.py`

### 1-1. 対象日より前のstateだけを使う

本番はrunner feature stateとrace-selection stateを読み、stateのthroughDateより後かつ対象日より前に確定した日だけを順次反映する。対象日の結果はrace selection実行前にはstateへ入れない。

完成監査:

- `targetDayResultsUsedForSelection: false`
- `historicalFinalOddsUsedForSelection: false`
- `syntheticOddsUsed: false`

### 1-2. 出走馬を履歴stateで順位付け

race-selection側は、主に以下の離散化した事前履歴を使う。

- 近走の着順傾向
- 近走の速度傾向
- 騎手3着内率
- 調教師3着内率
- 馬の出走経験
- 直近3走の3着内回数

`selection_strength` で各馬を順位付けし、proxy ticket生成用に上位5頭だけを残す。この上位5頭は最終買い目を5頭へ限定するためのものではなく、レース自体の買いやすさを測るproxy側の処理である。

### 1-3. 6券種のproxy ticketを作る

上位5頭から以下を生成する。

- 単勝
- 馬連
- ワイド
- 馬単
- 3連複
- 3連単

券種・会場・芝ダート・距離帯・頭数・レース番号帯・クラス・馬の履歴特徴などに対応する、対象日より前までの払戻統計をstateから参照する。

### 1-4. 過去ROIを平滑化してproxy scoreにする

過去件数が少ない条件をそのまま高評価しないため、券種全体priorと条件別priorで平滑化する。canonical production coreでは `MIN_N=500`, `KEY_PRIOR=2000`, `BET_PRIOR=5000`, `PRIOR_ROI=0.80`, `TOP_COMPONENTS=8`, `LOCAL_WEIGHT=0.60` を使う。

各レースでscore上位3 proxy ticketsを取り、少なくとも2券種を含ませる。その3点のscore平均がraceScoreとなる。

### 1-5. 各会場でraceScore上位5R

同一会場のレースをraceScore降順、同点時はレース番号順に並べ、上位5Rを選ぶ。

したがって、公開ページでは「LightGBMが12Rから5Rを直接選ぶ」と説明してはいけない。

## 2. 最終買い目の実コード

正本: `scripts/generate-ten-year-live-bets.py`, `scripts/ten-year-production-core.py`

### 2-1. 56特徴量から馬別勝率

LightGBM binary classifierが各出走馬のraw probabilityを出す。対象レース内で合計1になるよう正規化する。`marketPopularity`, `finishPosition`, `labelWin`, `labelTop3`, raw `raceId`, raw `raceDate` は勝率モデル入力から除外されている。

### 2-2. Plackett-Luceで組合せ確率

- 単勝: その馬の正規化勝率
- 馬単: A→Bの順序付き確率
- 馬連: A→BとB→Aを合算
- 3連単: A→B→Cの順序付き確率
- 3連複: 3頭の6順列を合算
- ワイド: 2頭がともに3着以内へ入る全順序を第三馬ごとに合算

全組合せを列挙するため、連系馬券が1点になるのは「結果を知ってその1点を選んだ」からではなく、候補生成後に1候補まで圧縮するルールによる。

### 2-3. 券種ごとに1点へ圧縮

各券種で全候補を `predictedProbability × officialJraOdds` で並べ、上位5だけ残す。その5候補を

`ln(predictedProbability) + 0.4 × ln(officialJraOdds)`

で再評価し、その券種の1位を残す。

### 2-4. 6券種から異なる2券種

券種ごとの1位をscore順に並べ、異なる2券種を1つずつ選ぶ。よって1レース2点固定。

- ライト: 1,000円 + 1,000円
- スタンダード: 2,500円 + 2,500円
- プレミアム: 5,000円 + 5,000円

コース差は購入額だけで、選ぶ2点は同じ。

## 3. 431.65% / 54.4%の正しい読み方

完成監査 `analysis-results/ten-year-model-completion-20260812.json` のfull集計:

- selected races: 14,410
- ROI: 431.6505899903346%（コース精算値 431.6505898681471%）
- hitRacePct: 54.406662040249834%
- top 1% race return除外・stake維持: 342.88272021835996%
- top 1% ticket payout除外・stake維持: 316.2602358973746%

これらは完成ルールの過去10年full-period retrospective aggregateである。高い数値自体は正本に記録されているが、そのまま完全OOF・live-equivalent・将来期待値とは解釈しない。

年別hitRacePctは2016年67.82%から2024年47.85%、2025年48.19%、2026年48.67%へ低下しており、全期間平均54.4%だけを現在の的中率期待として使うのも適切ではない。

## 4. 漏洩・来歴チェック

完成監査で確認済み:

- official odds only: true
- actual JRA payouts only: true
- post-result fields excluded from buy features: true
- raw date/year features excluded: true
- target-day results in race selection: false
- historical final odds in race selection: false
- synthetic/estimated odds: 0
- odds source/result identity mismatch: 0
- horse-set mismatch: 0

ただし「直接的な結果リークが見つからない」ことと「過去ROIが無偏な将来推定値である」ことは別。研究時のルール選択、フルアーカイブ学習、historical odds timingの同等性は別のバイアス論点として表示上も区別する。

## 5. 公開・引継ぎルール

- 公開条件詳細では、上記のレース選定と買い目圧縮工程を具体的に説明する。
- 431.7% / 54.4%は「過去10年の完成ルールfull集計」と明記し、完全OOFや将来保証と書かない。
- historical official oddsのexact live-lock timestamp同等性を新しい証跡なしに断定しない。
- 完成モデル、重み、state、過去公開買い目はこの監査のために変更しない。
- 過去買い目・成績は結果を見て書き換えない。

この監査は透明性のための文書化であり、モデル再探索・再学習・再選定ではない。
