# レース探偵 — 正本引継ぎ

> **次スレッドで「レース探偵を引き継いで」「最終状態から再開」と言われたら、このファイル → `config/canonical-production-manifest.json` → 現行 `main` / runtime の順で確認すること。**
>
> 保存会話・古いREADME・研究ブランチ・旧 `public-site-entry-v*` から現行仕様を推測しない。
> `FINAL_STATE_20260816.md` は2026-08-16時点の事故対応・安全要件を残す**historical baseline**であり、現在のライブ確定アーキテクチャそのものではない。

## 0. 現在地

- repository: `race-tantei-lab/race-tantei`
- production branch: `main`
- status: **completed model / production active**
- handoff version: **5**
- canonical manifest: `config/canonical-production-manifest.json`
- manifest as-of: `2026-08-22T19:20:00+09:00`
- verified live-architecture baseline commit: `5265321ad2186271aee96f45f98cbeec79c7df83`
- production site: `https://race-tantei-phase0.race-tantei.workers.dev`
- public Worker: `race-tantei-phase0`
- D1: `race-tantei-phase0`
- D1 database ID: `949b5e8b-d1a4-4c4e-80d1-d031afdc03de`
- current UI entry: **固定値で覚えず必ず `wrangler.jsonc.main` を読む**
  - 2026-08-22確認値: `src/public-site-entry-v34.ts`
- current deploy revision: **必ず `wrangler.jsonc.vars.DEPLOY_REVISION` を読む**
  - 2026-08-22確認値: `ten-year-completed-public-v34-live-deadline-detached-20260822`
- public Worker version IDも固定しない。必要なら `analysis-results/production-deployment.log` と本番deploymentを直接確認する。

### 現行ライブ確定の正本

- scheduler entry: `src/live-deadline-entry-v2.ts`
- primary Worker config: `wrangler.live-deadline.jsonc`
- backup Worker config: `wrangler.live-deadline-backup.jsonc`
- deploy workflow: `.github/workflows/deploy-live-deadline.yml`
- production readiness: `.github/workflows/verify-live-deadline-production.yml`
- primary schedule: **毎分** (`* * * * *`)
- backup schedule: **5分間隔で2分ずらし** (`2-59/5 * * * *`)
- public live mutation: **disabled**
- 旧 `/_ops/live-tick`: **本番404 / hard-disabled**

2026-08-22の実装baseline `5265321...` では:

- live-deadline deploy run `32567140449`: **success**
- live-deadline readiness run `32567140403`: **success**
- その後のpublic deploy run `32567363557`: **success**

以後コードが進んだ場合はこの固定値より**現行main・GitHub Actions・必要なら本番D1**を優先する。ただし下記の安全要件を後退させてはいけない。

## 1. 次スレッドの開始順

1. `HANDOFF.md`（このファイル）
2. `config/canonical-production-manifest.json`
3. `wrangler.jsonc` のcurrent public entry / revision / D1
4. `wrangler.live-deadline.jsonc`
5. `wrangler.live-deadline-backup.jsonc`
6. `src/live-deadline-entry-v2.ts`
7. `src/v1/completed-worker-live-lock.ts`
8. `src/v1/completed-worker-deadline-guard.ts`
9. `src/v1/completed-final-invariants.ts`
10. `src/v1/live-preview-safety.ts`
11. `.github/workflows/deploy-live-deadline.yml`
12. `.github/workflows/verify-live-deadline-production.yml`
13. `config/ten-year-completed-model.json`
14. `analysis-results/ten-year-model-completion-20260812.json`
15. `analysis-results/completed-model-methodology-audit-20260813.md`
16. 最新mainのproduction checks / readiness / deploymentを直接確認
17. 必要なら本番D1で対象レースのpreview / final state / `locked_at` / `oddsSource` を確認
18. 依頼された具体作業へ進む。**モデル探索からやり直さない。**

`FINAL_STATE_20260816.md` は過去事故・旧安全baselineの確認が必要な場合だけ参照する。現在のscheduler構成をそこから復元しない。

## 2. 完成モデルの正本

- model: `ten-year-completed-model`
- config: `config/ten-year-completed-model.json`
- weights: `models/ten-year-completed-model.txt`
- completion audit: `analysis-results/ten-year-model-completion-20260812.json`
- methodology audit: `analysis-results/completed-model-methodology-audit-20260813.md`
- state manifest: `models/ten-year-production-state-manifest.json`
- runner state: `models/ten-year-runner-feature-state.json.gz`
- selection state: `models/ten-year-race-selection-state.json.gz`
- canonical generation wrapper: `scripts/run-ten-year-auto-final-live.py`

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

- `targetDayResultsUsedForSelection = false`
- `historicalFinalOddsUsedForSelection = false`
- `syntheticOddsUsed = false`

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

**JRA公式オッズのみ。synthetic / estimated / probability-derived substitute oddsは禁止。**

## 3. 過去成績の読み方

完成監査14,410R:

- ROI `431.6505898681471%`
- hitRacePct `54.406662040249834%`

これは完成ルールを凍結10年アーカイブ全体へ適用した `full-period retrospective aggregate`。

以下の断定は禁止:

- 「431.65%は完全OOF」
- 「431.65%は未使用期間だけの成績」
- 「431.65%がそのまま将来期待回収率」
- timestamp証拠なしに「過去14,410Rは現在のlive lockと完全同条件」

詳細は `analysis-results/completed-model-methodology-audit-20260813.md` を読む。

## 4. 現行ライブ確定アーキテクチャ

ライブ買い目生成・確定は**隔離されたlive-deadline Workersだけ**が所有する。公開サイトの閲覧・APIアクセス・一般リクエストからライブ買い目を生成・再計算・確定してはいけない。

### 時系列

- **T-90**: JRA公式オッズでpreview作成を開始
- **T-40**: 早期SLA監査
- **T-30**: official previewが無ければ異常検知
- **T-17**: 最新情報でfresh previewを再生成してimmutable finalを確定
- **T-16**: fresh経路失敗時だけ、保存済みofficial previewを使うDB中心の最終救済guard
- **T-15**: hard creation boundary。新規作成を一切しない。既に正しくfinal済みか確認するだけ
- **T-15経過後**: D1 trigger自体が新規final / 後付けfinalを拒否

T-15境界以降に禁止されること:

- 新規モデルロード
- 新規モデル推論
- 新規レース再計算
- 新規JRAオッズfetch
- 新規買い目生成
- backfillによる後付け確定
- synthetic / estimated / probability fallbackでの代替確定

### 冗長化と排他

- primary Workerは毎分実行
- backup Workerは5分ごとに2分ずらして実行
- D1 leaseで同時mutationを排他
- official previewはappend-only archiveにも保存
- 障害時はnewest last-good official previewを復元可能
- 各工程で現在時刻を取り直し、古いscheduled timestampを締切判定へ流用しない
- 1レースの異常を理由に他レースの確定経路全体を長時間停止させない

### official odds only

finalに使える `oddsSource` は次の2種類だけ。

- `jra-fast-official`
- `jra-crawl-official`

JRA公式previewが作れない外部障害時は、偽データで埋めず**fail closed**する。

### final immutable

strict completeは1レースにつき:

- `rt_public_bets` 6行
- ライト / スタンダード / プレミアム各2点
- 各コースで異なる2券種
- 3コースの買い目組合せは同一
- `source_prediction_id = -2`
- ライト合計2,000円
- スタンダード合計5,000円
- プレミアム合計10,000円
- final state = locked

locked後の公開買い目はD1 invariantでもimmutable。

## 5. 旧構成との関係

2026-08-16の `FINAL_STATE_20260816.md` に記録されたT-16 arm + stored-preview backup構成は、札幌6R・中京6R・新潟7Rの締切事故を受けて作られた重要なhistorical safety baseline。ただし**2026-08-22現在のproduction schedulerではない**。

その後の監査で見つかった次の問題を解消するため、現行v5へ移行した。

- scheduled時刻と実処理時刻の混同
- 公開Worker Cronとライブ確定処理の結合
- 複数のライブ生成経路
- ページ閲覧からのバックグラウンド生成
- 外部から叩けるライブmutation endpoint
- primary/backupの重複mutation

現在は隔離Worker + lease + archive + T-90/T-17/T-16/T-15構成を正本とする。旧GitHub backup方式や公開サイト経由のlive-tickを現行経路として復活させない。

## 6. frozen history / 公開サイト

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

## 7. 絶対にしないこと

- 完成モデルを勝手に再探索・再学習・再選定しない
- completed modelをcandidateへ戻さない
- 過去結果から買い目を後付け変更しない
- synthetic / estimated / probability fallback oddsを使わない
- JRA公式2source以外をlocked finalにしない
- T-15以降に新しい予測・オッズ・買い目を生成して後付け確定しない
- locked 6行を変更しない
- 公開サイト・ページアクセスへライブmutationを戻さない
- 旧 `/_ops/live-tick` を再公開しない
- long-running monitorへ戻さない
- frozen canonical skipを旧D1買い目だけで選定済みにしない
- Worker assetをcanonical model本体扱いしない
- parityを通さずWorker独自モデルへ進めない
- workflow失敗中に「完成」と言わない
- コードだけ見て「本番成功」と断定しない
- validationの種類を根拠なくOOFと呼ばない
- exact odds timestampを証拠なしにlive-equivalentと呼ばない

## 8. 検証ルール

canonical verifier:

- script: `scripts/verify-canonical-handoff.py`
- workflow: `.github/workflows/verify-canonical-handoff.yml`
- success marker: `CANONICAL_HANDOFF_OK`

live production:

- deploy: `.github/workflows/deploy-live-deadline.yml`
- readiness: `.github/workflows/verify-live-deadline-production.yml`
- safety verifier: `scripts/verify-live-lock-safety.py`

「完成」と言うときは、コード存在だけでなく**current mainの実行証跡**を確認する。関連production checkが赤い場合は完成扱いしない。

なお、旧研究・ROI探索用workflowはproduction正本ではない。研究workflowの失敗をcompleted modelやlive-deadline productionの失敗と混同しない一方、production checkの失敗を研究扱いして無視することもしない。

## 9. 会話上の進め方

ツール作業では進捗を短く表示する。同一タスク内で不要な承認待ちを増やさず進める。

ユーザーが「確認して」「完璧に引き継いで」と言った場合、保存会話の記憶だけでなくcurrent GitHub / workflow / 必要ならproduction D1を直接確認する。

## 10. 一番短い引継ぎ認識

- completed modelは凍結production active。
- weights SHA `63e359...453a5`。
- 34,566R中14,410R選定、retrospective ROI 431.6505898681471%、hit 54.4%。完全OOFとは呼ばない。
- 各会場5R、1R2点、異なる2券種。
- race selectionはprior-only proxy-ticket raceScore。
- final ticketsは56-feature LightGBM + Plackett-Luce + JRA公式オッズ。
- public live mutationはdisabled。
- live schedulerは `src/live-deadline-entry-v2.ts`。
- primary毎分 + backup 5分staggered + D1 lease。
- T-90 preview開始 / T-30 required / T-17 fresh final / T-16 rescue / T-15 hard no-new-final。
- official oddsは `jra-fast-official` / `jra-crawl-official` のみ。
- T-15後の新規finalはD1でも拒否。
- locked finalはimmutable。
- external outage時は偽データで埋めずfail closed。
- `FINAL_STATE_20260816.md` はhistorical baselineでありcurrent schedulerではない。
- 次回も必ず現行main・Actions・必要ならD1まで直接確認してから続ける。
