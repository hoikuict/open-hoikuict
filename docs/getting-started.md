# 導入方法を選ぶ

画面を試すのか、認証・メールを確認するのか、サーバーを構築するのかを選びます。同じソースコードを使い、環境設定と保存先を分けます。

Windowsの新しいPCで始める方は、[導入アプリのダウンロード](download.md)から[利用開始マニュアル](start-manual.md)へ進んでください。導入、Excelの初期台帳、保護者の利用開始まで順番に確認できます。

| 目的 | 使う環境 | 最初に読むページ |
| --- | --- | --- |
| 手元で画面・業務の流れを確認 | development・モック認証・架空データ | [開発環境とテスト](development.md) |
| Windows 11／Ubuntu 24.04 LTSにβを新規導入 | development・ローカルパスワード認証・β専用DB | [β版の導入手順書](beta-installation.md) |
| 既存のローカル環境で認証設定を確認 | development・ローカルパスワード認証 | [ローカル環境の設定](environment-profiles.md) |
| TrueNASへ空の状態から導入 | production・HTTPS・SMTP・専用保存領域 | [TrueNAS導入ガイド](truenas-beginner-installation-guide.md) |
| 稼働しているTrueNASを更新 | 現在のDB・秘密鍵・保存領域を継続使用 | [導入ガイドの更新手順](truenas-beginner-installation-guide.md#maintenance) |

公開デモの案内先は[保育ICTデモ](https://demo.hoikuict.net/)です。公開デモは独立した配備先なので、このリポジトリの最新機能と差がある場合があります。実在する名前・連絡先・健康情報は入力しないでください。

## ローカルで画面を試す

1. [開発手順](development.md)に沿ってPython環境と依存ライブラリを用意します。CIとDockerの基準はPython 3.12です。
2. `.env.example`を使い、モック認証と開発用DBを指定します。
3. 必要な場合だけ、専用の架空データDBに[100人規模デモデータ](demo-data.md)を投入します。
4. `http://127.0.0.1:8000/` を開きます。

通常起動は業務デモデータを自動投入しません。空DBで職員選択に候補がない場合は、用途に応じてデモ投入またはローカル認証の初期管理者作成へ進みます。

## 認証を含めて試す

Windowsでまず試す場合は、[かんたん導入](beta-quickstart.md)で名前・メールアドレス・パスワードを入力して始められます。

手動で導入する場合は、[β版の導入手順書](beta-installation.md)に[Windows 11版](beta-installation-windows.md)と[Ubuntu 24.04 LTS版](beta-installation-linux.md)を用意しています。Python・Gitの準備から初期管理者の作成、起動・停止、停止中の退避・復旧まで順に進められます。まずは架空データを使うローカル試用が対象です。

[ローカルβの設定](environment-profiles.md)で専用DBと固定の秘密鍵を準備し、CLIで初期管理者を作成します。その後、[アカウントガイド](accounts.md)に沿って職員と保護者の利用開始を確認します。

ローカルβの `capture` メールは送信内容を検証用に保持する方式で、実メールを配送しません。SMTPを使う実機の確認は、担当者が受信できるテスト用アドレスで行います。

## 園のサーバーへ導入する

[TrueNAS導入ガイド](truenas-beginner-installation-guide.md)を入口に、[初期構成の詳細](truenas-fresh-install.md)で保存先とComposeを確認します。現在の配布構成は `deploy/truenas/compose.yaml` です。

最初の到達点は、管理者ログイン、架空の園児1名の登録、保護者への招待、園の承認、保護者ログインです。次にキオスク、通知、バックアップと隔離環境への復元を確認します。

!!! note "初期値を確認する"
    TrueNAS用の基本ComposeはキオスクとWeb Pushが `disabled` です。必要な機能は[キオスク端末](chromebook-guardian-kiosk.md)と[Web Push設定](parent-push-production-setup.md)に沿って有効化します。パスワード認証とSMTPはproductionの起動条件です。

実データを使う範囲と開始日は、[導入までの進め方](roadmap.md)と[運用試験の受入条件](pilot-deployment-spec-v2.md)に沿って施設で決めます。
