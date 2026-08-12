# レース探偵

> **現行仕様・引継ぎは最初に [`HANDOFF.md`](HANDOFF.md) と [`config/canonical-production-manifest.json`](config/canonical-production-manifest.json) を参照してください。**
>
> 旧研究・旧UI・旧 `scripts/run-auto-final-live.py` から現行仕様を推測しないでください。

JRA中央競馬を対象に、発走前情報だけで完成済み10年モデルからレース選定と2点の買い目を固定し、公開成績を継続記録する Cloudflare Workers / D1 サイトです。

## 現在のproduction

- model: `ten-year-completed-model`
- config: `config/ten-year-completed-model.json`
- weights: `models/ten-year-completed-model.txt`
- model SHA256: `63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5`
- completion audit: `analysis-results/ten-year-model-completion-20260812.json`
- historical completion: 34,566 universe / 14,410 selected / ROI 431.6506%
- live runner: `scripts/run-ten-year-auto-final-live.py`
- workflow: `.github/workflows/auto-final-live-bets.yml`
- public site entry: **`wrangler.jsonc.main`**
  - 引継ぎ作成時点: `src/public-site-entry-v18.ts`
- site: `https://race-tantei-phase0.race-tantei.workers.dev`

## 完成モデル

- 各会場・各開催日5R
- 56特徴量 LightGBM 勝率モデル
- JRA公式オッズのみ
- 対象6券種: 単勝 / ワイド / 馬連 / 馬単 / 3連複 / 3連単
- 1R 2点固定、異なる2券種
- ライト 2,000円 / スタンダード 5,000円 / プレミアム 10,000円
- 各コース50/50
- synthetic oddsなし
- 対象日の結果を予想に使わない
- 過去公開買い目は後から変更しない

## 公開10年履歴

- loader: `src/v1/ten-year-history.ts`
- generated data: `src/v1/ten-year-history-data/`
- runner archive: `data/ten-year-runners/`
- 34,566 races
- 14,410 selected races
- 480,441 runner rows
- 121 months

## 開発・確認

```bash
npm install
npm run check
python scripts/verify-canonical-handoff.py
```

### サイト変更

1. `wrangler.jsonc.main` で現在のentryを確認
2. 必要なentry / 下位wrapperを変更
3. Typecheck
4. Cloudflare deploy
5. production HTTP / workflow verify

### モデル・運用変更

1. canonical config / manifestを確認
2. `scripts/run-ten-year-auto-final-live.py` を確認
3. `--check-only`
4. workflow run確認

## Legacy warning

以下は現行production source-of-truthではありません。

- `scripts/run-auto-final-live.py` 単体
- 下位 `public-site-entry-v*` を単独で現行UIとみなすこと
- research branches / `research-*`
- old `approved-production-model` / ROI200 / rule-based production experiments
- 古い保存会話の途中経過をrepo正本より優先すること

継続作業は必ず [`HANDOFF.md`](HANDOFF.md) から開始してください。

## Disclaimer

公開・学習用途です。結果・利益を保証しません。
