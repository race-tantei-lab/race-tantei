# race-tantei

友人共有用の自動競馬予想サイト「レース探偵（仮）」の開発リポジトリです。

現在は **Phase 0：データ取得成立性の検証** を進めています。この段階では予想モデルを作らず、無料のCloudflare Workers環境からJRA公開ページへ到達できるか、ページ種別・アクセス拒否・構造変更を安全に検知できるかを検証します。

## Phase 0で確認すること

- JRAのrobots.txtへ到達できること
- 実在する出馬表を`race-entry`と判定できること
- 実在する結果ページを`race-result`と判定できること
- HTTP拒否、CAPTCHA、想定外ページを成功扱いしないこと
- ページ本文を保存せず、取得結果・SHA-256・サイズだけをD1へ記録すること

## 環境分離

GitHubの所有、Cloudflare、D1、Worker URL、Secretは決算探偵とは分離します。ChatGPT連携のため既存GitHubユーザーにこのリポジトリだけの共同管理権限がありますが、競馬用Organizationと本番環境の所有者は競馬用アカウントです。

## ローカル確認

```bash
npm install
npm run check
```

GitHub Actionsでも、mainへの更新ごとに型チェックと単体テストを自動実行します。

## Cloudflare導入

Cloudflare設定は競馬専用アカウントで行います。D1作成後、`wrangler.jsonc`の`database_id`を競馬用D1のIDへ置き換え、マイグレーションとSecret登録後にデプロイします。

`PROBE_ENABLED`は初回デプロイ時は`false`のままにし、`GET /health`を確認してから有効化します。

## 開発フェーズ

- Phase 0：データ取得成立性の検証
- Phase 1：開催・出馬表・結果・払戻の自動記録
- Phase 2：予想着順・推定確率モデル
- Phase 3：期待値判定・買い目・金額配分
- Phase 4：成績分析・モデル改善

詳細は`docs/`を参照してください。
