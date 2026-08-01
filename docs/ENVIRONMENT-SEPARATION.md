# 決算探偵との環境分離ルール

このプロジェクトの**所有・本番運用環境・データ・秘密情報**は、決算探偵から分離する。

## 現在の所有構成

- GitHub Organization所有者: 競馬用アカウント `racetantei-bot`
- GitHub Organization: `race-tantei-lab`
- リポジトリ: `race-tantei-lab/race-tantei`
- Cloudflare所有者: `race.tantei@gmail.com` の競馬専用アカウント

ChatGPTからコードを操作するため、既存GitHubユーザー `kessantantei-gif` には**このリポジトリだけの共同管理権限**を付与している。これは接続上の作業権限であり、競馬用Organization、Cloudflare、D1、URL、Secretの所有権は競馬用環境に残す。

## 必須の分離

- 競馬専用GitHub Organization・リポジトリ
- 競馬専用Cloudflareアカウント
- 競馬専用Worker
- 競馬専用D1データベース
- 競馬専用workers.devサブドメイン
- 競馬専用管理トークン
- 競馬専用環境変数・Secret

## 禁止事項

- 決算探偵リポジトリへの競馬コード追加
- 決算探偵のCloudflare、Vercel、Supabase、DB、APIキーの流用
- 決算探偵の本番URL・独自ドメインの利用
- 決算探偵の`.env`やSecretのコピー
- 競馬用データを決算探偵DBへ保存すること
