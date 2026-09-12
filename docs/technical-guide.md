# 導入・運用・開発を担当する方へ

<div class="home-hero" markdown>

<p class="home-eyebrow">オープンソースの保育ICT</p>

## 機能や仕組みを、詳しく調べる

園児と家庭の情報、登降園、保護者との連絡、健康記録、保育計画、職員の情報共有を、一つのアプリで扱います。こちらは、園への導入やシステムの運用・開発を担当する方のための資料の入口です。設定、現在の実装、検証方法を調べるときに使ってください。

[導入方法を選ぶ](getting-started.md){ .home-button .home-button-primary }
[機能と実装状況を見る](features.md){ .home-button .home-button-secondary }

</div>

!!! info "現在の位置づけ — 2026年9月13日確認"
    職員・保護者のパスワード認証、共通QRによる保護者登録、Web Push、登降園端末の監視まで実装が進み、TrueNASでの実機検証・更新記録があります。機能の実装、端末ごとの動作確認、施設での運用開始はそれぞれ確認が必要です。公開デモとローカル検証には架空データを使ってください。

## 目的から探す

<div class="home-grid" markdown>

<div class="home-card" markdown>

### まず試したい

[導入方法](getting-started.md)で、画面確認用のモック、認証を試すローカルβ、TrueNASへの導入を選べます。[デモデータ](demo-data.md)は100人規模の架空の園を用意しています。

</div>

<div class="home-card" markdown>

### 園で使いたい

[日々の業務](daily-work.md)から、朝の連絡確認、打刻の訂正、記録、延長料金の確認へ。[アカウントと利用開始](accounts.md)に職員・保護者の登録手順をまとめています。

</div>

<div class="home-card" markdown>

### 運用を担当する

[TrueNAS導入ガイド](truenas-beginner-installation-guide.md)、[本番設定](security.md)、[バックアップ・復元](backup-restore-spec.md)を確認し、[日常運用](operations.md)へ進みます。

</div>

<div class="home-card" markdown>

### 開発・仕様を確認する

[開発環境とテスト](development.md)、[コード構成](architecture.md)、[仕様一覧](specifications.md)、[画面・URL一覧](screen-transition-list.md)から実装をたどれます。

</div>

</div>

## 現在扱える業務

| 業務 | 主な機能 |
| --- | --- |
| 園児・家庭 | 名簿、家族プロフィール、保護者アカウントとの同期、CSV取り込み、変更申請 |
| 登降園・連絡 | 受付端末、出欠確認、日次連絡、お迎え予定の変更、誤打刻の取消と履歴 |
| 保護者とのやり取り | 招待・共通QR登録、園の承認、お知らせ・アンケート、出欠確認のプッシュ・メール通知 |
| 記録・計画 | 健康管理、子どもの記録、児童票、年案・月案・週案・日案、振り返り |
| 料金・請求 | 保育必要量別の延長料金、月次確認、請求転送、請求口座、全銀データ出力 |
| 職員・運用 | 職員ホーム、カレンダー、職員ルーム、園内記録、文書の確認依頼、端末監視、バックアップ管理 |

実装範囲と後続計画は[機能と実装状況](features.md)で確認できます。施設設定の専用画面、職員有給管理、MFAなどは未実装です。

## 最近の変更

- **9月13日**: 9月11日の変更について[TrueNASへの更新完了記録](deployment-2026-09-13.md)を追加。
- **9月11日**: [文書の確認依頼、端末監視、誤打刻の取消、メール通知の併用など](spec-improvements-2026-09-11.md)を追加。
- **9月10日**: [お迎え予定の編集、延長料金・カレンダー・キオスクの画面改善](spec-improvements-2026-09-10.md)を反映。

過去の記録と旧設計の位置づけは[変更履歴](history.md)にまとめています。

## プロジェクトに参加する

[GitHubリポジトリ](https://github.com/hoikuict/open-hoikuict)からコードを確認し、[Issues](https://github.com/hoikuict/open-hoikuict/issues)へ不具合や改善案を投稿できます。実在の個人情報や認証情報は含めないでください。セキュリティの連絡先は[ライセンス・問い合わせ](license.md)に記載しています。
