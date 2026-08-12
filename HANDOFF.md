# レース探偵 — 正本引継ぎ

> **次スレッドで「引き継いで」と言われたら、最初にこのファイルと `config/canonical-production-manifest.json` を読むこと。**
>
> 保存会話・古いREADME・研究ブランチ・旧 `public-site-entry-v*`・旧 `run-auto-final-live.py` から現行仕様を推測しない。

## 0. 現在地

- repository: `race-tantei-lab/race-tantei`
- production branch: `main`
- completed model: `ten-year-completed-model`
- status: **completed / production active**
- production site: `https://race-tantei-phase0.race-tantei.workers.dev`
- Worker: `race-tantei-phase0`
- current UI entry: **必ず `wrangler.jsonc.main` を読む**
  - 現時点: `src/public-site-entry-v18.ts`
  - deploy revision: `ten-year-completed-public-v18-20260812`
- D1: `race-tantei-phase0`
- D1 database ID: `949b5e8b-d1a4-4c4e-80d1-d031afdc03de`
- Worker version IDは固定しない。`analysis-results/production-deployment.log` の `Current Version ID:` を読む。
- canonical verifier: `scripts/verify-canonical-handoff.py`
- workflow: `.github/workflows/verify-canonical-handoff.yml`
- success marker: **`CANONICAL_HANDOFF_OK`**

この引継ぎ文書の更新はモデル変更ではない。完成済みモデル・state・過去公開買い目は固定する。

## 1. 次スレッドの開始順

1. `HANDOFF.md`
2. `config/canonical-production-manifest.json`
3. `config/ten-year-completed-model.json`
4. `analysis-results/ten-year-model-completion-20260812.json`
5. **`analysis-results/completed-model-methodology-audit-20260813.md`**
6. `wrangler.jsonc` でcurrent entry確認
7. `scripts/run-ten-year-auto-final-live.py` でproduction runner確認
8. `scripts/verify-canonical-handoff.py` / workflowのcurrent main成功確認
9. 依頼された具体作業へ進む。モデル探索からやり直さない。

## 2. 完成モデルの正本

### ファイル

- config: `config/ten-year-completed-model.json`
- weights: `models/ten-year-completed-model.txt`
- completion audit: `analysis-results/ten-year-model-completion-20260812.json`
- methodology audit: `analysis-results/completed-model-methodology-audit-20260813.md`
- state manifest: `models/ten-year-production-state-manifest.json`
- runner state: `models/ten-year-runner-feature-state.json.gz`
- selection state: `models/ten-year-race-selection-state.json.gz`

### weights

SHA256:

`63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5`

LightGBM 4.6.0 binary classifier、56 features、target `labelWin`。

### archive

- 2016-08-10 ～ 2026-08-09
- universe 34,566R
- selected 14,410R
- venue-days 2,882
- 各会場・各開催日ちょうど5R

### probability model

除外:

- raw `raceId`
- raw `raceDate`
- `finishPosition`
- `labelWin`
- `labelTop3`
- `marketPopularity`

canonical params:

- n_estimators 500
- learning_rate 0.04
- num_leaves 127
- min_child_samples 30
- reg_lambda 4
- reg_alpha 0.2
- colsample_bytree 0.9
- random_state 20260812

### race selection — 実処理

レース選定はLightGBMで12Rを直接順位付けする方式ではない。`scripts/ten-year-production-core.py` のprior-only selection stateを使う。

1. 対象日より前の確定履歴だけでselection stateを更新。
2. 各レースの出走馬を、近走form/speed、騎手・調教師3着内率、経験、直近3走top3回数等から順位付け。
3. proxy ticket用に上位5頭を残す。
4. 単勝 / 馬連 / ワイド / 馬単 / 3連複 / 3連単のproxy候補を生成。
5. 対象日より前の券種・条件別払戻ROI統計をpriorで平滑化してscore化。
6. score上位3 proxy ticketsを取り、最低2券種を含ませる。
7. 3点の平均scoreをraceScoreとする。
8. 会場ごとraceScore上位5Rを選ぶ。

canonical selection constants:

- TOP_HORSES 5
- MIN_N 500
- KEY_PRIOR 2000
- BET_PRIOR 5000
- PRIOR_ROI 0.80
- TOP_COMPONENTS 8
- TICKETS_PER_RACE 3
- LOCAL_WEIGHT 0.60

完成監査:

- targetDayResultsUsedForSelection false
- historicalFinalOddsUsedForSelection false
- syntheticOddsUsed false

### final tickets — 実処理

1. 56 features → runner raw probability
2. race内で合計1へ正規化
3. Plackett-Luceで全6券種の全組合せ確率を計算
4. 各券種を `predictedProbability × officialJraOdds` で順位付けし上位5候補
5. 上位5を `ln(predictedProbability) + 0.4 × ln(officialJraOdds)` で再評価
6. 各券種の1位を残す
7. 異なる2券種の上位を1点ずつ選び、合計2点固定

対象券種:

- 単勝
- ワイド
- 馬連
- 馬単
- 3連複
- 3連単

stakes:

- ライト 1,000 + 1,000 = 2,000円
- スタンダード 2,500 + 2,500 = 5,000円
- プレミアム 5,000 + 5,000 = 10,000円

JRA公式オッズのみ。synthetic oddsは禁止。

## 3. 過去成績の読み方 — 2026-08-13監査で固定

完成監査の14,410R:

- ROI **431.6505898681471%**（表示通常431.7%）
- hitRacePct 54.406662040249834%
- top1% race return除外・stake維持 ROI 342.88272021835996%
- top1% ticket payout除外・stake維持 ROI 316.2602358973746%

**重要:** completion auditは probability model を `trainingMode: full frozen archive uniform discovery` と記録している。したがって公開431.6505898681471%は、完成ルールを凍結10年アーカイブ全体へ適用したfull-period retrospective aggregateとして扱う。

以下の表現は禁止:

- 「431.7%は完全OOF」
- 「431.7%は未使用期間だけの成績」
- 「431.7%がそのまま将来期待回収率」
- 「過去14,410Rは現在のlive lockと完全同条件」と、timestamp証跡なしに断定すること

完成までに日付分割・スライス等のロバスト性検証はあるが、公開full aggregateと混同しない。

研究commit `acf44ad91c83e30f3a3e0363b43bbc8fb4a51a2c` はrace-selection local weightを 0.15 / 0.30 / 0.45 / 0.60 でsweepしている。少なくともレース選定側には研究選択が存在するので、full archive成績を無偏なforward estimateと扱わない。

final ticket coefficient 0.4はcanonical completed ruleとして確定している。一方、0.4が事前固定・nested OOF選定だったことを独立に証明する正本成果物は2026-08-13監査では確認できていない。未確認部分を都合よく補完しない。

historical oddsはcompletion audit上、JRA公式source identity / horse-set整合が取れ、synthetic/estimated oddsは0。ただし各過去レースのodds snapshot timestampが現在live lockと完全同等である証跡はcompletion audit JSON単体にはない。これもfull-period ROIをlive-equivalentと断定しない理由。

詳細: `analysis-results/completed-model-methodology-audit-20260813.md`

## 4. production stateと来歴

`models/ten-year-production-state-manifest.json` が正本。

- throughDate 2026-08-09
- sourceHistoryArtifactId 9056288221
- canonicalFeatureArtifactId 9087261097
- canonicalDemandArtifactId 9074033903

SHA256:

- runner feature state: `86f8fdf6ee82d4465efec50ff36198010a20044bc1187f4b8c8ded912f640f3f`
- race selection state: `b27775dbc645ce326348cf60c6f139f8689db779a7fbd86c19d1b26eb5691ca8`

state manifestに存在しない `featureRows` / `demandRows` / `historyRaces` をchecker都合で追加しない。

## 5. 本番自動予想

workflow:

`.github/workflows/auto-final-live-bets.yml`

production entry:

**`scripts/run-ten-year-auto-final-live.py`**

関連:

- `scripts/ten-year-production-core.py`
- `scripts/generate-ten-year-preday-selection.py`
- `scripts/generate-ten-year-live-bets.py`
- `scripts/collect-current-jra-official-odds-live.py`
- `scripts/collect-current-jra-official-odds-fast.py`

旧 `scripts/run-auto-final-live.py` 単体はcurrent modelではない。時間管理等のshellとしてimportされても、選定・買い目生成・checkはten-year wrapperへ差し替わる。旧316ルールをcurrent truthにしない。

D1重要table:

- rt_races
- rt_runners
- rt_results
- rt_payouts
- rt_public_bets
- rt_system_state

## 6. 公開サイト

**current entry判定は `wrangler.jsonc.main`。**

現時点 `src/public-site-entry-v18.ts`。

公開条件詳細は、次を具体的に表示する。

- 12R→selection-side上位5頭→6券種proxy→上位3→raceScore→会場5R
- 56 features→normalized runner probabilities
- Plackett-Luce combination probabilities
- 各券種EV上位5→`ln(p)+0.4ln(odds)`→券種代表1点
- 異なる2券種から2点
- 431.7% / 54.4%はfull-period retrospective aggregateで、完全OOFではない
- historical odds timestampのlive-lock同等性は未証明なら断定しない
- 公開済み買い目は不変

その他UI要件:

- home累計/月別/会場別は10年canonical metrics
- 14,410R表示
- 年は2026→…→2016
- 終了済み: 的中 / 不的中 / 見送り
- 不的中は赤、見送りと区別
- 「公開後の扱い」は通常の紺panel、黄色notice禁止
- 過去詳細: 着順、枠、馬番、馬名、性齢、斤量、騎手、調教師、馬体重、人気
- 過去確定買い目を横スライド中心にしない
- ライト / スタンダード / プレミアム縦表示
- mobileは1券ずつcard型

public summary:

- `src/v1/ten-year-public-summary.ts`
- selected 14,410
- ROI 431.6505898681471%
- 121 months
- 10 venues

history:

- loader `src/v1/ten-year-history.ts`
- assets `src/v1/ten-year-history-data/`
- 34,566R / canonical tickets 14,410R

runner archive:

- `data/ten-year-runners/manifest.json`
- 34,566R / 480,441 runner rows / 121 months

## 7. 再生成の正本

- public history builder: `scripts/build-ten-year-public-history-assets.py`
- public history workflow: `.github/workflows/promote-ten-year-public-history.yml`
- runner builder: `scripts/build-ten-year-runner-assets.py`
- runner workflow: `.github/workflows/promote-ten-year-runner-assets.yml`
- production state: `.github/workflows/promote-ten-year-production-state.yml`
- completed model assets: `.github/workflows/promote-ten-year-completed-model-assets.yml`

再生成はcanonical artifact IDs / SHA / completion auditと一致させ、新モデル探索として扱わない。

## 8. 絶対にしないこと

- 完成モデルを勝手に再探索・再選定しない。
- completed modelをcandidateへ戻さない。
- 明示指示なしに新モデル再学習・再検証を始めない。
- 過去結果から買い目を後付け変更しない。
- synthetic oddsを使わない。
- 過去公開買い目を変更しない。
- 10年全履歴をD1へmass writeする方式へ戻さない。
- 黄色noticeを戻さない。
- 不的中を見送りと同色にしない。
- 買い目UIを横スライド中心へ戻さない。
- 正本にないmetadataをchecker通過目的で捏造しない。
- Worker version IDをHANDOFF/manifestへ固定しない。
- validationの種類を根拠なくOOFと呼ばない。
- exact odds timestampを証拠なしにlive-equivalentと呼ばない。
- workflow失敗中に「完成」と言わない。

## 9. 検証

script:

`scripts/verify-canonical-handoff.py`

workflow:

`.github/workflows/verify-canonical-handoff.yml`

success:

**`CANONICAL_HANDOFF_OK`**

検証は少なくとも:

- completed identity / productionChanged
- model SHA
- state date / artifact IDs / state SHA
- completion audit gates / 34,566 / 14,410
- methodology auditの存在とperformance interpretation
- `wrangler.jsonc.main` / revision / model / D1
- live workflow / canonical runner接続
- public summary / runner archive
- conditions pageの具体的selection/ticket説明とOOF注意
- deployment log URL/revision/model/D1/current Worker version
- README/HANDOFF入口

を確認する。

過去の `production state featureRows mismatch` はchecker側が実在しないfieldを要求したことが原因。checkerを正本へ合わせ、正本に架空fieldを足さない。

## 10. 会話上の進め方

ツール作業では進捗を細かく表示する。「細かく区切る」は承認待ちを増やす意味ではない。同一タスク内で、実行可能な次工程へ進みながら進捗を返す。ユーザーが「完成させて」と言った作業は、実装・検証・本番確認まで進める。

## 11. 一番短い引継ぎ認識

- 完成モデルはproduction active。
- 14,410R / ROI 431.6505898681471% / hit 54.4%。ただしfull-period retrospective aggregateで完全OOFとは呼ばない。
- 各会場5R、1R2点、異なる2券種。
- race selectionはLightGBM直選択ではなくproxy-ticket raceScore。
- final ticketsは56-feature LightGBM + Plackett-Luce + official odds。
- weights SHA `63e359...453a5`。
- production runner `run-ten-year-auto-final-live.py`。
- UIは `wrangler.jsonc.main`。
- methodology auditを読む。
- old research/316 rule/old UIをcurrent truthにしない。
- current mainで `verify-canonical-handoff.py` が `CANONICAL_HANDOFF_OK` になるまで完成扱いしない。
