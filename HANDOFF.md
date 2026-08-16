# レース探偵 — 正本引継ぎ

> **次スレッドで「レース探偵を引き継いで」「最終状態から再開」と言われたら、最初にこのファイルと `FINAL_STATE_20260816.md` を読むこと。**
>
> 保存会話・古いREADME・研究ブランチ・旧 `public-site-entry-v*`・旧monitorから現行仕様を推測しない。
> current runtimeは必ず `main` / `wrangler.jsonc` / GitHub Actions / 必要なら本番D1を直接確認する。

## 0. 現在地

- repository: `race-tantei-lab/race-tantei`
- production branch: `main`
- status: **completed model / production active**
- handoff version: **4**
- production site: `https://race-tantei-phase0.race-tantei.workers.dev`
- Worker: `race-tantei-phase0`
- D1: `race-tantei-phase0`
- D1 database ID: `949b5e8b-d1a4-4c4e-80d1-d031afdc03de`
- current UI entry: **固定値で覚えず必ず `wrangler.jsonc.main` を読む**
- current deploy revision: **必ず `wrangler.jsonc.vars.DEPLOY_REVISION` を読む**
- Worker version IDも固定しない。必要なら本番deploymentを直接確認する。

### 2026-08-16 17:29 JSTの最終基準

live-lock / T-15 / JRA公式オッズ / DB防衛線の最終状態は:

**`FINAL_STATE_20260816.md`**

を正本とする。

この時点では:

- `wrangler.jsonc.main = src/public-site-entry-v30.ts`
- deploy revision = `ten-year-completed-public-v30-clear-language-20260816`
- Worker cron = 毎分 (`* * * * *`)
- final safety implementation baseline = `6c96994f250fc6e91a33ff7e8a5b26a6c565a8a7`
- Phase 0 checks run `31936304428` / job `95138668577` は全step success

以後コードが進んだ場合はこの固定値より現行mainを優先するが、**安全要件を後退させてはいけない**。

## 1. 次スレッドの開始順

1. `HANDOFF.md`
2. `FINAL_STATE_20260816.md`
3. `config/canonical-production-manifest.json`
4. `config/ten-year-completed-model.json`
5. `analysis-results/ten-year-model-completion-20260812.json`
6. `analysis-results/completed-model-methodology-audit-20260813.md`
7. `wrangler.jsonc` でcurrent entry / cron / build / revision確認
8. live-lock safetyを確認
   - `src/v1/completed-worker-deadline-guard.ts`
   - `src/v1/completed-worker-live-lock.ts`
   - `src/v1/completed-final-invariants.ts`
   - `.github/workflows/auto-final-live-bets.yml`
   - `scripts/run-stored-preview-deadline-backup.py`
9. 最新mainのPhase 0 checks / production checks確認
10. 必要なら本番D1で対象レースのfinal state / locked_at / oddsSourceを確認
11. 依頼された具体作業へ進む。モデル探索からやり直さない。

## 2. 完成モデルの正本

- model: `ten-year-completed-model`
- config: `config/ten-year-completed-model.json`
- weights: `models/ten-year-completed-model.txt`
- completion audit: `analysis-results/ten-year-model-completion-20260812.json`
- methodology audit: `analysis-results/completed-model-methodology-audit-20260813.md`
- state manifest: `models/ten-year-production-state-manifest.json`
- runner state: `models/ten-year-runner-feature-state.json.gz`
- selection state: `models/ten-year-race-selection-state.json.gz`
- canonical ten-year generation wrapper: `scripts/run-ten-year-auto-final-live.py`
  - これはcompleted modelのpreday/live生成wrapperとして保持する。
  - **現行T-15自動backupはこのrunnerを呼ばず、stored-preview-onlyで動く。両者を混同しない。**

weights SHA256:

`63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5`

LightGBM 4.6.0 binary classifier、56 features、target `labelWin`。

### archive

- 2016-08-10 ～ 2026-08-09
- universe 34,566R
- selected 14,410R
- venue-days 2,882
- 各会場・各開催日5R

### race selection

レース選定はLightGBMで12Rを直接順位付けする方式ではない。`scripts/ten-year-production-core.py` のprior-only selection stateを使う。

- 対象日より前の確定履歴だけでselection state更新
- 出走馬のprior featuresからproxy ticket候補を構築
- 6券種のproxy候補をprior ROIでscore化
- raceScore上位を使い会場ごと5R選定

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

### final tickets

1. 56 features → runner raw probability
2. race内で正規化
3. Plackett-Luceで6券種の組合せ確率
4. `predictedProbability × officialJraOdds` 上位候補
5. `ln(predictedProbability) + 0.4 × ln(officialJraOdds)` で再評価
6. 各券種代表から異なる2券種を1点ずつ、合計2点

対象券種:

- 単勝
- ワイド
- 馬連
- 馬単
- 3連複
- 3連単

stakes:

- ライト 2,000円
- スタンダード 5,000円
- プレミアム 10,000円

**JRA公式オッズのみ。synthetic / estimated oddsは禁止。**

## 3. 過去成績の読み方

完成監査14,410R:

- ROI `431.6505898681471%`
- hitRacePct `54.406662040249834%`

ただしこれは `full frozen archive uniform discovery` のfull-period retrospective aggregate。

以下の断定は禁止:

- 「431.7%は完全OOF」
- 「431.7%は未使用期間だけの成績」
- 「431.7%がそのまま将来期待回収率」
- timestamp証拠なしに「過去14,410Rは現在のlive lockと完全同条件」

詳細は `analysis-results/completed-model-methodology-audit-20260813.md` を読む。

## 4. production state

正本: `models/ten-year-production-state-manifest.json`

- throughDate 2026-08-09
- sourceHistoryArtifactId 9056288221
- canonicalFeatureArtifactId 9087261097
- canonicalDemandArtifactId 9074033903

SHA256:

- runner feature state: `86f8fdf6ee82d4465efec50ff36198010a20044bc1187f4b8c8ded912f640f3f`
- race selection state: `b27775dbc645ce326348cf60c6f139f8689db779a7fbd86c19d1b26eb5691ca8`

正本にないmetadataをchecker通過目的で捏造しない。

## 5. Worker parity

- asset builder: `scripts/build-worker-completed-model-assets.py`
- model parity: `scripts/verify-worker-model-parity.ts`
- generated runtime asset: `worker-assets/_internal/completed-model/`
- selection parity workflow: `.github/workflows/verify-worker-selection-parity.yml`

Worker assetはcanonical model本体ではなく生成物。

2026-08-15の検証では644行、最大絶対誤差 `1.1102230246251565e-16` で `WORKER_MODEL_PARITY_OK` を確認済み。

## 6. 2026-08-16 live-lock最終安全要件

詳細正本: `FINAL_STATE_20260816.md`

最低限、以下を維持する。

- public final deadlineはT-15
- 毎分Cronの秒ズレ対策としてdeadline guardはT-16からarm
- T-15 boundaryでは新規モデル推論・再計算・外部オッズfetch・新規買い目生成をしない
- finalは保存済みpreviewのみから作る
- allowed oddsSourceは `jra-fast-official` / `jra-crawl-official` のみ
- probability fallback禁止
- D1 triggerでも非公式locked finalを拒否
- locked finalはimmutable
- strict complete = 3コース×2点 = 6行、各予算一致、source_prediction_id=-2
- GitHub backupは5分ごとのstored-preview-only one-shot
- long-running monitor依存へ戻さない
- 1レースのfailureで後続を止めない
- official previewが作れない外部障害時は偽データで埋めずfail closed

### 過去事故の扱い

正常扱いへ書き換えない。

- 札幌6R: T-15より21.864秒遅延
- 中京6R: 旧monitor/backup詰まりで大幅遅延
- 新潟7R: 厳密T-15基準で10.532秒遅延

これらを受けて現在のT-16 arm + DB防衛線へ変更した。

## 7. frozen history / 公開サイト

- 2016-08-10〜2026-08-09のcanonical history assetが選定身分を決める
- canonical ticketあり → 選定済み
- canonical `skip` → 見送り
- 旧D1買い目だけを理由にcanonical skipを選定済みへ昇格させない
- D1 settlement/refund overlayはcanonical選定済みレースの精算補足に限定
- 公開済み買い目は後から変更しない
- 返還は不的中・見送りと区別する

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

## 8. 絶対にしないこと

- 完成モデルを勝手に再探索・再学習・再選定しない
- completed modelをcandidateへ戻さない
- 過去結果から買い目を後付け変更しない
- synthetic / estimated / probability fallback oddsを使わない
- JRA公式2source以外をlocked finalにしない
- T-15以降に新しい予測やオッズを生成して後付け確定しない
- locked 6行を変更しない
- long-running monitorへ戻さない
- frozen canonical skipを旧D1買い目だけで選定済みにしない
- Worker assetをcanonical model本体扱いしない
- parityを通さずWorker独自モデルへ進めない
- workflow失敗中に「完成」と言わない
- コードだけ見て「本番成功」と断定しない
- validationの種類を根拠なくOOFと呼ばない
- exact odds timestampを証拠なしにlive-equivalentと呼ばない

## 9. 検証ルール

通常のcanonical verifier:

- script: `scripts/verify-canonical-handoff.py`
- workflow: `.github/workflows/verify-canonical-handoff.yml`
- success marker: `CANONICAL_HANDOFF_OK`

live-lock安全検証:

- `scripts/verify-live-lock-safety.py`
- Phase 0 checks

2026-08-16最終baselineではrun `31936304428` / job `95138668577` が以下すべてsuccess:

- Verify live-lock safety
- Verify bodyweight final-lock acquisition
- Verify WIN5 navigation UI
- Verify public language clarity
- Typecheck and test

以後もcurrent mainのcheck結果を直接確認し、赤いまま完成扱いしない。

## 10. 会話上の進め方

ツール作業では進捗を短く表示する。同一タスク内で承認待ちを増やさず進める。

ユーザーが「確認して」と言った場合、保存会話の記憶だけでなくcurrent GitHub / workflow / 必要ならproduction D1を直接確認する。

「絶対」「完璧」と言う場合は、コード存在だけでなく実行証跡まで確認する。

## 11. 一番短い引継ぎ認識

- completed modelは凍結production active。
- weights SHA `63e359...453a5`。
- 14,410R / retrospective ROI 431.6505898681471% / hit 54.4%。完全OOFとは呼ばない。
- 各会場5R、1R2点、異なる2券種。
- race selectionはproxy-ticket raceScore。
- final ticketsは56-feature LightGBM + Plackett-Luce + JRA公式オッズ。
- canonical generation wrapperは `run-ten-year-auto-final-live.py`。T-15 backupとは別。
- live final deadlineはT-15、guardはT-16からarm。
- T-15以降の新規fetch/recompute/generation禁止。
- locked finalはJRA公式2sourceのみ。DBでも強制。
- probability fallback禁止。
- locked final immutable。
- backupはstored-preview-only one-shot。
- 外部障害時は捏造せずfail closed。
- current UIは毎回 `wrangler.jsonc.main` を確認。2026-08-16 17:29 JST時点はv30。
- live-lock最終正本は `FINAL_STATE_20260816.md`。

**2026-08-16の最終状態は `FINAL_STATE_20260816.md` を優先する。**
