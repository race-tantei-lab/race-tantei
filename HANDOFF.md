# レース探偵 — 正本引継ぎ

> **次スレッドで「引き継いで」と言われたら、最初にこのファイルと `config/canonical-production-manifest.json` を読むこと。**
>
> 保存会話・古いREADME・研究ブランチ・旧 `public-site-entry-v*`・旧 `run-auto-final-live.py` から現行仕様を推測しない。現行仕様はこのファイル、canonical manifest、`config/ten-year-completed-model.json`、`wrangler.jsonc`、`scripts/run-ten-year-auto-final-live.py` を正本とする。

## 0. 現在地

- リポジトリ: `race-tantei-lab/race-tantei`
- 本番ブランチ: `main`
- 完成モデル: `ten-year-completed-model`
- モデル状態: **completed / production active**
- 公開サイト: `https://race-tantei-phase0.race-tantei.workers.dev`
- 本番Worker: `race-tantei-phase0`
- 現在のUI入口: **`wrangler.jsonc` の `main` を必ず見ること**
  - 引継ぎ作成時点: `src/public-site-entry-v18.ts`
  - revision: `ten-year-completed-public-v18-20260812`
- 検証済み本番ベースラインcommit: `8f07a9eca0c7494d902aa6873a9149121896ccde`
- 検証済みWorker version ID: `3e2e4c51-056d-4dfe-812b-4c4b8245792d`
- D1: `race-tantei-phase0`
- D1 database ID: `949b5e8b-d1a4-4c4e-80d1-d031afdc03de`

このHANDOFF/manifest/audit/README追加は引継ぎ整理であり、上記ベースラインの予想ロジックを変更するものではない。

---

## 1. 次スレッドの開始手順

「引き継いで」と言われたら、順番を変えずに以下を行う。

1. `HANDOFF.md` を読む。
2. `config/canonical-production-manifest.json` を読む。
3. `config/ten-year-completed-model.json` を読む。
4. `wrangler.jsonc` を読み、**その時点の `main` が本番UI入口であることを確認**する。
5. `scripts/run-ten-year-auto-final-live.py` を読み、現在の本番自動予想入口を確認する。
6. 必要な作業にだけ進む。モデル探索・再学習・再検証から始めない。

### 会話上の進め方

このユーザーとのツール作業では、**ツールを1回使ったら必ず画面に進捗を返す**。長時間無言で複数ツールを連続実行しない。「細かく区切る」はタスクを分割する意味ではなく、**同じタスクの途中でも返信を細かく挟む**という意味。

---

## 2. 完成モデルの正本

### 正本ファイル

- 仕様: `config/ten-year-completed-model.json`
- 学習済み重み: `models/ten-year-completed-model.txt`
- 完成監査: `analysis-results/ten-year-model-completion-20260812.json`
- state manifest: `models/ten-year-production-state-manifest.json`
- runner feature state: `models/ten-year-runner-feature-state.json.gz`
- race selection state: `models/ten-year-race-selection-state.json.gz`

### モデル重み

SHA256:

`63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5`

LightGBM 4.6.0 binary classifier。feature countは56。

### 対象期間とレース選定

- frozen archive: 2016-08-10 ～ 2026-08-09
- universe: 34,566R
- selected: 14,410R
- venue-days: 2,882
- **各会場・各開催日ちょうど5R**
- 選定は予想時点の過去履歴から作る `raceScore`
- 対象日の結果は選定に使わない
- レース選定にhistorical final oddsを使わない
- synthetic oddsは禁止

### 馬別勝率モデル

- target: `labelWin`
- 56特徴量
- `marketPopularity` は勝率モデルから除外
- post-result field、raw raceId/date、教師ラベル等を入力に使わない
- canonical params:
  - n_estimators: 500
  - learning_rate: 0.04
  - num_leaves: 127
  - min_child_samples: 30
  - reg_lambda: 4
  - reg_alpha: 0.2
  - colsample_bytree: 0.9
  - random_state: 20260812

### 買い目

対象券種:

- 単勝
- ワイド
- 馬連
- 馬単
- 3連複
- 3連単

組合せ確率は馬別勝率を正規化し、Plackett-Luceで計算。

各券種で `predictedProbability × officialJraOdds` の上位5候補を残し、最終評価は:

`ln(predictedProbability) + 0.4 × ln(officialJraOdds)`

最終的に**異なる2券種から1点ずつ、合計2点固定**。

### コース購入額

- ライト: 1,000円 + 1,000円 = 2,000円
- スタンダード: 2,500円 + 2,500円 = 5,000円
- プレミアム: 5,000円 + 5,000円 = 10,000円

公式JRAオッズのみ使用する。

### 完成成績

完成監査の14,410Rで3コースともROI:

**431.6505898681471%**

表示上は通常 `431.7%`。

### 完成監査JSONの注意

`analysis-results/ten-year-model-completion-20260812.json` 内の

- `productionModelChanged:false`
- `productionDatabaseWritten:false`

は**完成監査を記録した時点の歴史的事実**。その後本番昇格が完了しているため、現在のproduction statusをこの2フィールドから判定してはいけない。

現在の本番状態は以下で判断する:

- `config/ten-year-completed-model.json` の `productionChanged:true`
- canonical production code
- `wrangler.jsonc`
- deployment log

---

## 3. 正本stateとデータ来歴

`models/ten-year-production-state-manifest.json` を正本とする。

- throughDate: 2026-08-09
- source history artifact ID: `9056288221`
- canonical runner feature artifact ID: `9087261097`
- canonical demand artifact ID: `9074033903`

state SHA256:

- `models/ten-year-runner-feature-state.json.gz`
  - `86f8fdf6ee82d4465efec50ff36198010a20044bc1187f4b8c8ded912f640f3f`
- `models/ten-year-race-selection-state.json.gz`
  - `b27775dbc645ce326348cf60c6f139f8689db779a7fbd86c19d1b26eb5691ca8`

stateは2026-08-09終了時点までの履歴状態。未来日の本番では、それ以降に確定した過去結果だけを順次反映して使う。

---

## 4. 本番自動予想の正本

### 本番workflow

`.github/workflows/auto-final-live-bets.yml`

### 本番ランナー

**`scripts/run-ten-year-auto-final-live.py`**

これが現行production entry。

関連正本:

- `scripts/ten-year-production-core.py`
- `scripts/generate-ten-year-preday-selection.py`
- `scripts/generate-ten-year-live-bets.py`
- `scripts/collect-current-jra-official-odds-live.py`
- `scripts/collect-current-jra-official-odds-fast.py`

### 重要: 旧ランナーの扱い

`scripts/run-auto-final-live.py` は直接実行してはいけない。

現在の `run-ten-year-auto-final-live.py` は、旧ランナーを**時間管理・ロック・既存運用シェルとして内部importする場合がある**が、以下を完成モデル実装へ差し替える:

- レース選定
- 買い目生成
- 検証/check-only

したがって旧 `run-auto-final-live.py` の316ルール等を見て「今の本番モデル」と判断してはいけない。

### 本番D1の重要テーブル

- `rt_races`
- `rt_runners`
- `rt_results`
- `rt_payouts`
- `rt_public_bets`
- `rt_system_state`

canonical check-onlyではモデルSHA、56特徴量、state SHA/date、必要テーブル等を検証する。

確定買い目は1Rにつき2点、異なる2券種、コース予算をちょうど使い切る。

---

## 5. 公開サイトの正本

### 本番入口

**`wrangler.jsonc.main` が唯一の正しい判定方法。**

引継ぎ作成時点:

`src/public-site-entry-v18.ts`

下位の `v17`, `v16`, `v15` 等はv18からtransitiveに利用される場合がある。**古いから削除してよい、あるいは個別に現行仕様だと判断してはいけない。**

### 現行UI要件

以下はユーザー確定要件として維持する。

- ホームの累計・月別・会場別は10年完成モデルの正本集計を表示する。
- 14,410Rを正本成績として表示する。
- 年は**新しい順: 2026 → … → 2016**。
- 月・日付は現在の順序を維持。
- 終了済みレースは `的中 / 不的中 / 見送り`。
- **不的中は赤色**。
- 見送りは不的中と混同しない。
- 条件詳細ページは完成モデルの説明を表示する。
- **条件詳細ページの「公開後の扱い」に黄色いnoticeを使わない。通常の紺パネルにする。**
- 過去レース詳細に出走馬・結果を表示する。
- 表示項目: 着順、枠、馬番、馬名、性齢、斤量、騎手、調教師、馬体重、人気。
- 過去レースの確定買い目は横スライド形式にしない。
- ライト・スタンダード・プレミアムを縦に表示する。
- スマホでは買い目を1券ずつカード型で読める形にする。
- 過去の公開買い目と成績を後から書き換えない。

### 公開集計

`src/v1/ten-year-public-summary.ts`

- selected races: 14,410
- ROI: 431.6505898681471%
- monthly: 121か月
- venue: 10会場

### 10年レース履歴

loader:

`src/v1/ten-year-history.ts`

generated data:

`src/v1/ten-year-history-data/`

- 2016-08-10 ～ 2026-08-09
- 34,566R
- canonical買い目付き: 14,410R

### 馬情報archive

`data/ten-year-runners/`

manifest:

`data/ten-year-runners/manifest.json`

- 34,566R
- 480,441 runner rows
- 2016-08 ～ 2026-08
- 121か月

過去レース詳細では月別gzipを必要時に読み込む。

---

## 6. データ再生成の正本

### 公開10年履歴

- builder: `scripts/build-ten-year-public-history-assets.py`
- workflow: `.github/workflows/promote-ten-year-public-history.yml`

### 過去馬情報

- builder: `scripts/build-ten-year-runner-assets.py`
- workflow: `.github/workflows/promote-ten-year-runner-assets.yml`

### production state

`.github/workflows/promote-ten-year-production-state.yml`

### completed model assets

`.github/workflows/promote-ten-year-completed-model-assets.yml`

再生成するときも、canonical artifact IDs / SHA / completion auditと一致することを前提にする。新しいモデル探索として扱わない。

---

## 7. 旧物・研究物の扱い

リポジトリには大量の過去研究workflow、旧本番workflow、旧UI versionが残っている。**存在することと現行正本であることは別。**

### 正本ではないもの

- research branch全般
- `research-*` scripts / workflows
- 旧rule-based / ROI200 / v3 / v4 / v5等の過去production実験
- `approved-production-model*` 等の旧production config
- `scripts/run-auto-final-live.py` 単体
- `src/public-site-entry-v17.ts` 以下を単独で「現行UI」とみなすこと
- 古いREADME記述

これらは削除禁止とは限らないが、**現行仕様の判断根拠には使わない**。

### UI versionの判断

ファイル名の数字で推測しない。必ず `wrangler.jsonc.main` を読む。

### production runnerの判断

workflow `.github/workflows/auto-final-live-bets.yml` が呼ぶ正本ラッパーを読む。旧スクリプトの名前だけで判断しない。

---

## 8. 絶対にしないこと

- 完成モデルを勝手に再探索・再選定しない。
- 完成モデルを「候補」に戻さない。
- ユーザーから明示的にモデル変更指示がない限り、再学習・再検証を新モデル探索として始めない。
- 過去結果から買い目を後付け変更しない。
- synthetic oddsを使わない。
- 過去の公開買い目を変更しない。
- D1へ10年全履歴を大量writeして無料枠を消費する方式へ戻さない。公開10年履歴はrepo内圧縮archiveを利用する。
- 条件詳細に黄色いnoticeを戻さない。
- 不的中を見送りと同色に戻さない。
- レース詳細の確定買い目を横スライド中心のUIへ戻さない。

---

## 9. 変更するときの確認順

### モデル/予想ロジック

1. `config/ten-year-completed-model.json`
2. `config/canonical-production-manifest.json`
3. `scripts/run-ten-year-auto-final-live.py`
4. production core/generator
5. check-only
6. workflow run

### サイト/UI

1. `wrangler.jsonc`
2. `wrangler.jsonc.main` のentry
3. 必要な下位wrapper
4. Typecheck
5. Cloudflare deploy
6. 実サイト確認workflow/HTTP確認

### 10年公開履歴

1. `src/v1/ten-year-history.ts`
2. `src/v1/ten-year-history-data/`
3. `src/v1/ten-year-public-summary.ts`
4. `data/ten-year-runners/manifest.json`

---

## 10. 一番短い引継ぎ回答

次スレッドでユーザーが「レース探偵を引き継いで」とだけ言った場合、まずrepo正本を確認した上で、最低限こう認識すること:

- 10年完成モデルは完成済み・本番active。
- 14,410R、ROI 431.65%、各会場5R、2券固定、異なる2券種。
- LightGBM重みSHAは `63e359...453a5`。
- 本番予想入口は `run-ten-year-auto-final-live.py`。
- UI入口は `wrangler.jsonc.main`。
- 現在はv18系UI、10年履歴・runner archiveまで本番表示済み。
- 旧研究・旧316ルール・古いUI固定値を拾って現行仕様を上書きしない。
- 具体作業を始める前にこのHANDOFFとmanifestを読み込む。

このファイル自体に矛盾が疑われた場合は、**機械判定は `config/canonical-production-manifest.json`、実際のcurrent entryは `wrangler.jsonc` とproduction workflowを優先して確認する。**
