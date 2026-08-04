# Mac無料学習ランナー

Cloudflare Workers無料プランのCPU上限を避けながら、本番D1へ直接接続して履歴取得・基礎予想・学習・検証・再予想を進めるためのMac用ランナーです。

## 前提

- レース探偵は `~/Projects/race-tantei` に配置する
- 決算探偵とは別フォルダ・別リポジトリのまま扱う
- Cloudflare API Tokenには対象アカウントの `Workers Scripts: Edit` と `D1: Edit` を付与する
- API Tokenをリポジトリ、ファイル、チャットへ保存しない

## 初回またはGitHub更新後

```bash
cd ~/Projects/race-tantei
git checkout main
git pull origin main
npm install
```

## API Tokenを現在のターミナルだけに設定

```bash
export CLOUDFLARE_API_TOKEN="新しいAPIトークン"
```

引用符は半角の `"` を使用します。トークンは画面共有やチャットへ貼り付けません。

接続確認:

```bash
npx wrangler d1 list
```

D1一覧が表示されれば準備完了です。

## 学習処理を開始

```bash
npm run learning:local
```

ランナーは次を自動実行します。

1. Mac上でWorkerを起動
2. 本番D1へ接続
3. scheduled処理を反復実行
4. 各反復後に履歴件数・基礎予想件数・学習進捗を表示
5. 全工程完了時に自動停止
6. 一時エラーは最大10回まで待機して再試行

標準の最大実行時間は6時間です。途中で終了してもD1に確定済みのカーソルから再開します。

実行時間を指定する場合:

```bash
npm run learning:local -- --minutes 120
```

1処理だけ確認する場合:

```bash
npm run learning:local:once
```

## 安全な停止

ターミナルで `Control + C` を押します。確定済みチェックポイントは失われません。再開時は同じコマンドを実行します。

## 注意

- 学習中はMacをスリープさせない
- ブラウザ更新では処理を進めない
- Cloudflare本番Cronは使用しない
- GitHub Actions無料枠が利用可能な月は、同じランナーを1日1回のWorkflowからも実行できる
