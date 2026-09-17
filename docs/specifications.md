# 仕様・設計文書一覧

現況確認: **2026年9月13日**。利用者向けの概要は[機能と実装状況](features.md)、操作入口は[使い方](daily-work.md)、URLは[画面一覧](screen-transition-list.md)を参照してください。

[仕様と実装の照合記録](spec-consistency-review-2026-09-13.md)に、今回修正した相違点、確認した範囲、残る実装課題をまとめています。

## ステータスの読み方

| 表記 | 意味 |
| --- | --- |
| 現行 | 現在の実装で参照する契約・手順 |
| 実装あり | 記載する主要機能がリポジトリに存在する。配備・実機受入の完了とは別 |
| 一部実装 | 実装済みの範囲と後続の設計を含む |
| 計画 | 未実装の拡張。現行の画面・運用手順として扱わない |
| 履歴 | 当時の設計判断や作業記録。冒頭の現況注記と新しいガイドを優先 |

一つの仕様書に将来フェーズがある場合、文書全体を実装済みとは扱いません。

## 園児・家庭・記録

| 文書 | 状況 | 現在の範囲・残件 |
| --- | --- | --- |
| [児童記録・児童票・保育要録](child-records-spec.md) | 一部実装 | 観察ログ、訂正・無効化、設定版、児童票・進捗一覧。保育要録・送付管理等は後続 |
| [健康管理レビュー](health-record-spec-review.md) | 一部実装・履歴 | プロフィール、アレルギー、健診・グラフ。感染症・与薬等は後続 |
| [インポート・エクスポート](import-export-spec.md) | 実装あり | 職員を含む6種のマスタ、事前検証・確定、CSV/Excel。家庭の保護者①②に対応 |
| [家庭・園児CSVガイド](family-guardian-csv-guide.md) | 現行 | 変換ツール、家庭→園児の取り込み、既存情報の保持 |
| [家族プロフィールとアカウント同期](guardian-account-sync.md) | 現行 | 初回入力の招待、明示的な保護者紐付け、連絡先同期 |
| [認可施設帳票入力](ninka-input-screen-spec.md) | 一部実装 | 台帳からExcelへ直接出力。画面内プレビュー・補正・年度別保存は未実装 |

## 登降園・料金・職員

| 文書 | 状況 | 現在の範囲・残件 |
| --- | --- | --- |
| [保育認定・保育必要量](care-need-certification-spec.md) | 一部実装 | 園児別期間管理、区分別の朝夕料金、計算モード切替。専用の訂正・差額プレビュー・CSV等は後続 |
| [延長料金](extended-care-fee-spec.md) | 実装あり | 日別計算、月次、確定・調整・対象外、CSV、ルール |
| [延長料金・請求転送](extended-care-billing-transfer-spec.md) | 実装あり | プレビュー、転送・再転送・解除、競合処理、監査 |
| [職員ポータル](staff-personal-portal-spec.md) | 実装あり | ホーム、担当クラス、予定、要確認、タイムライン。追加変更は9月11日記録も参照 |
| [職員権限・請求口座](staff-permissions-and-billing-accounts-spec.md) | 実装あり | 集約権限設定、園児台帳・請求口座の専用権限、口座情報保護、監査 |
| [9月10日の画面改善](spec-improvements-2026-09-10.md) | 実装あり・履歴 | お迎え予定変更、料金表示・区分別設定、キオスク、日別予定 |
| [9月11日の機能追加](spec-improvements-2026-09-11.md) | 実装あり・履歴 | 打刻取消、文書確認、端末監視、メール通知、家族検索・きょうだい選択など |

## 認証・通知

| 文書 | 状況 | 現在の範囲・残件 |
| --- | --- | --- |
| [アカウントガイド](accounts.md) | 現行 | 職員・保護者の初期設定、登録経路、復旧、閲覧対象 |
| [ローカル認証設計](local-authentication-spec.md) | 一部実装 | 職員・保護者のArgon2id認証、セッション、試行制限、コード、監査、管理者メール復旧。職員の通常パスワード変更・MFA等は後続 |
| [保護者認証設計](parent-local-authentication-spec.md) | 一部実装・設計履歴 | ログイン、招待・承認、本人パスワード変更、園による再設定、明示的な園児認可は実装あり |
| [共通QR登録](parent-public-registration.md) | 現行 | 受付切替、メール確認、初回申請、承認先選択、利用開始 |
| [プッシュ通知仕様](parent-push-notification-spec.md) | 実装あり・受入継続 | 購読、Service Worker、Web Push、本番設定、配送・再試行・報告。OS別実機受入は別途記録 |
| [通知ガイド](notifications.md) | 現行 | 出欠確認依頼のアプリ内・プッシュ・任意メール、本人端末テスト |

## 保育計画と文例 {#plans}

| 文書 | 状況 | 用途 |
| --- | --- | --- |
| [日案仕様](spec-daily-plan-v1.md) | 一部実装 | SQLModel永続化、版管理、楽観ロック、実施変更、文例、カレンダー、振り返り、確認通知 |
| [週案・日案追加仕様](spec-weekly-daily-plans.md) | 一部実装 | 共通文書基盤と週案・日案。日案コーパス選択は実装済み、当初案の週案・日案文例専用URL等は未実装 |
| [日案コーパス契約](daily-plan-corpus-contract.md) | 現行 | 別途用意する読み取り専用SQLite文例成果物の契約 |
| [日案サンプルDB](daily-plan-sample-db-spec.md) | 計画 | 既存日案の確認・配布用DB作成、希望施設への任意導入・更新・停止 |
| [連携契約](integration-contract.md) | 現行 | 文書種別、状態、セクション、参照キー、JSON互換性 |
| [保育計画統合設計](spec-plan-docs-integration-v2-revised.md) | 履歴・一部実装 | 統合時の判断。児童記録は別仕様へ分割 |

## 未実装の計画

| 文書 | 現在との境界 |
| --- | --- |
| [施設設定](facility-settings-spec.md) | `FacilitySettings`・`/settings/facility` は未実装 |
| [職員有給管理](paid-leave-management-spec.md) | 台帳・申請・承認ルートは未実装 |
| [一括データ移行](beta-production-data-migration-spec.md) | 移行元ID・マニフェスト・CSV一式の一括確定は未実装。明示的な園児リンクと家庭CSVの対応は現行実装へ反映済み |

## 運用・開発の参照先

- 導入: [TrueNAS導入ガイド](truenas-beginner-installation-guide.md)、[運用試験仕様の改訂版](pilot-deployment-spec-v2.md)。
- 運用: [バックアップ・復元](backup-restore-spec.md)、[セキュリティ](security.md)、[リリース確認](release-checklist.md)。
- 開発: [開発環境](development.md)、[コード構成](architecture.md)、[ドキュメント更新](documentation.md)。
- 過去の構成案・配備記録: [変更履歴](history.md)。

新機能の追加時は、この一覧・画面一覧・関連ガイド・navを一緒に見直し、実装の確認日と未実装部分を更新します。
