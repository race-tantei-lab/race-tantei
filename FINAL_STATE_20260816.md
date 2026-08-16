# レース探偵 — 2026-08-16 最終状態

> **最終確定時刻: 2026-08-16 17:29 JST**
>
> 次スレッドで「レース探偵を引き継いで」「最終状態から再開」と言われたら、`HANDOFF.md` とこのファイルを最初に読むこと。
> live-lock / T-15 / JRA公式オッズ / 本番確定経路について、古い保存会話・旧ブランチ・旧UI番号から推測しない。
> このファイルと現行 `main` / `wrangler.jsonc` / 本番D1の直接確認を優先する。

## 1. この時点の基準

- repository: `race-tantei-lab/race-tantei`
- production branch: `main`
- completed model: `ten-year-completed-model`
- completed model SHA256: `63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5`
- completed modelは凍結。今回のlive-lock修正でモデル自体は変更していない。
- final safety implementation baseline: `6c96994f250fc6e91a33ff7e8a5b26a6c565a8a7`
  - この後のHANDOFF更新等、文書のみのcommitは実装baseline変更とはみなさない。
- current production entryは固定値で覚えず、必ず `wrangler.jsonc.main` を読む。
- 2026-08-16 17:29 JST時点の `wrangler.jsonc.main`: `src/public-site-entry-v30.ts`
- その時点の deploy revision: `ten-year-completed-public-v30-clear-language-20260816`
- Worker cron: `* * * * *`（毎分）
- D1: `race-tantei-phase0`
- D1 database ID: `949b5e8b-d1a4-4c4e-80d1-d031afdc03de`

## 2. 過去に実際に起きた締切事故

以下を「正常だった」と書き換えない。

- 札幌6R: 発走12:50、要求T-15=12:35:00、実際のfinal lock=12:35:21.864。**21.864秒遅れ**。
- 中京6R: 旧backup/monitor経路の詰まりで大幅に遅延してfinal。
- 新潟7R: 発走15:25、final=15:10:10.532。旧会話では正常扱いされたが、**厳密なT-15:00基準なら10.532秒遅れ**。

これらの事故を受けて、単なる監視追加ではなく確定経路・DB防衛線まで再設計した。

## 3. 現在のT-15最終確定仕様

### 締切そのもの

- 公開買い目の最終締切は **T-15** のまま。
- `DEADLINE_GUARD_MS = 15 * 60 * 1000`。
- 毎分Cronの実行秒ズレでT-15を超えないよう、締切ガードは **T-16からarm** する。
- `DEADLINE_GUARD_ARM_MS = 16 * 60 * 1000`。
- T-16〜発走直前までガード対象。開始時刻以降に新しいfinalを作らない。
- 目的は「T-15になってから確定処理を開始」ではなく、**T-15時点ではすでにimmutable finalが存在すること**。

### T-15境界で禁止されること

T-15のhard boundaryでは、以下をしない。

- 新規モデルロード
- 新規モデル推論
- 新規レース再計算
- 新規JRAオッズHTTP取得
- 締切後の買い目生成
- synthetic odds / estimated odds / probability fallbackでの代替確定

締切ガードは保存済みpreviewからfinalへ昇格するDB中心の経路に限定する。

## 4. JRA公式オッズ強制 — 二重ガード

最終確認で、`completed-worker-live-lock` 側の別T-15経路が保存済みpreviewの `oddsSource` をJRA公式2種類に限定しておらず、旧 `probability_fallback` 禁止だけでは理論上すり抜けられる穴を発見した。

この穴は2026-08-16に修正済み。

### アプリケーション側

最終確定に使える `oddsSource` は次の2種類だけ。

- `jra-fast-official`
- `jra-crawl-official`

それ以外はfinalize拒否。

### D1最終防衛線

`src/v1/completed-final-invariants.ts` にDB triggerを持つ。

- `rt_guard_probability_fallback_final_insert`
- `rt_guard_probability_fallback_final_update`
- `PROBABILITY_FALLBACK_FORBIDDEN`
- `rt_guard_official_odds_final_insert`
- `rt_guard_official_odds_final_update`
- 非公式sourceなら `OFFICIAL_JRA_ODDS_REQUIRED`

つまり、あるアプリ経路でチェック漏れが再発しても、**DBへlocked finalを書き込む時点でJRA公式オッズ以外を拒否する**。

## 5. finalのimmutable条件

locked後の公開買い目は変更しない。

D1 triggerで少なくとも以下を保護する。

- `rt_guard_locked_public_bet_terms`
- `IMMUTABLE_FINAL_BET_TERMS`
- `rt_guard_locked_worker_final_state`
- `IMMUTABLE_WORKER_FINAL_STATE`

1レースのstrict complete条件:

- `rt_public_bets` が6行
- ライト / スタンダード / プレミアム各2点
- 各コースで異なる2券種
- 3コースの買い目組合せは同一
- `source_prediction_id = -2`
- ライト合計2,000円
- スタンダード合計5,000円
- プレミアム合計10,000円
- final stateがlocked

D1 `batch()` による確定処理で途中statementが失敗した場合、半端なfinalを残さない設計を前提とする。

## 6. 独立バックアップ

`.github/workflows/auto-final-live-bets.yml` は現行の独立backup。

- JRA開催対象時間帯に5分間隔
- `timeout-minutes: 3`
- `scripts/run-stored-preview-deadline-backup.py`
- mode=`stored_preview_only`
- 締切後にモデル推論しない
- 締切後にJRAオッズを新規収集しない
- `generatedRaceIds` は常に空であるべき
- due raceが未確定ならHTTP race page経由の本番self-healを起動
- self-heal後もstrict completeでなければfailure
- 1レースの不足が後続レースをブロックする旧long-running monitor設計へ戻さない

旧 `for ... sleep 60` 型の長時間monitor、既存monitor検出でbackup自体をskipする設計へ戻さない。

## 7. race page self-heal

T-15以降のrace detail self-healも保存済みpreviewのみ。

- 外部オッズfetchなし
- モデル再推論なし
- 新規買い目生成なし
- DB保存済みpreviewが不正・不足ならfail closed

## 8. 2026-08-16最終検証

安全検証スクリプト `scripts/verify-live-lock-safety.py` も新仕様へ更新済み。

旧仕様の「T-15から作動」文字列を期待する検証を廃止し、以下を検査する。

- T-16 arm
- T-15 hard boundary
- stored-preview-only guard
- JRA公式2source allowlist
- probability fallback禁止DB trigger
- official odds required DB trigger
- final immutable
- 5分backupがstored-preview-only
- post-deadline prediction generation禁止

### Phase 0 checks

run: `31936304428`
job: `95138668577`
head SHA: `6c96994f250fc6e91a33ff7e8a5b26a6c565a8a7`

最終結果: **success**

成功確認したstep:

- Verify live-lock safety
- Verify bodyweight final-lock acquisition
- Verify WIN5 navigation UI
- Verify public language clarity
- Typecheck and test

最終確認途中で一度CIがfailureになったが、原因は製品コードではなく安全検証スクリプトが旧T-15仕様を要求していたため。検証を新T-16 arm仕様へ更新後、上記runで全step successまで確認した。

## 9. 「同じミスは起きない」の正確な意味

現在の設計では、過去の主要2事故経路:

1. Cron秒ズレ等でT-15を過ぎてからfinalを作る
2. JRA公式オッズがないのにsynthetic / probability fallback等でfinalを作る

に対して、処理経路だけでなくDB最終防衛線まで入れた。

ただし、外部システム障害を含めて「未来のあらゆる障害が100%ゼロ」とは断定しない。

JRA取得障害、Cloudflare/D1障害等で必要なofficial previewが作れなければ、**偽データで確定するのではなく、確定失敗として止まる（fail closed）**のが正しい挙動。

「買い目が必ず何があっても生成される」よりも、

- 正規条件ならT-15までにofficial final
- 正規データが無いなら捏造せずfailure

を優先する。

## 10. 次スレッドで最初に確認するもの

次スレッドでは、保存会話の文章だけを信じず次の順で直接確認する。

1. `HANDOFF.md`
2. `FINAL_STATE_20260816.md`（このファイル）
3. `wrangler.jsonc` のcurrent `main` / cron / deploy revision
4. `src/v1/completed-worker-deadline-guard.ts`
5. `src/v1/completed-worker-live-lock.ts`
6. `src/v1/completed-final-invariants.ts`
7. `.github/workflows/auto-final-live-bets.yml`
8. `scripts/run-stored-preview-deadline-backup.py`
9. 最新mainのPhase 0 checks / production checks
10. 必要なら本番D1で対象レースのlocked_at / final state / oddsSourceを直接確認

## 11. 次スレッドで絶対にしないこと

- 旧Sapporo/Chukyo/Niigataの遅延実績を「成功」と書き換えない。
- `probability_fallback` を再導入しない。
- JRA公式2source以外をlocked finalへ許可しない。
- T-15以降に新しい予測を生成しない。
- T-15以降にオッズを取り直して後付け買い目を作らない。
- long-running monitorの1レース失敗で後続を止める旧構成へ戻さない。
- 既にlockedの6行を変更しない。
- 完成モデルを今回のlive-lock問題と混同して再探索・再学習しない。
- workflowが赤い状態で「完成」と言わない。
- コードを見ただけで「本番成功」と言わない。実行結果/D1証跡を確認する。

## 12. 一番短い最終引継ぎ

- completed modelは凍結維持。
- public final deadlineはT-15。
- cron jitter対策としてguardはT-16からarm。
- T-15境界では新規fetch/recompute/generation禁止。
- finalは保存済みpreviewのみから作る。
- official odds sourceは `jra-fast-official` / `jra-crawl-official` のみ。
- probability fallbackは禁止。
- DB triggerでも非公式finalを拒否。
- locked finalはDB triggerでimmutable。
- GitHub backupは5分ごとのstored-preview-only one-shot。
- Phase 0 checks run `31936304428` は全step success。
- external outage時は偽データで埋めずfail closed。
- 現行entryは固定値で覚えず、毎回 `wrangler.jsonc.main` を読む。2026-08-16 17:29 JST時点はv30。

**ここを2026-08-16のlive-lock最終状態とする。**
