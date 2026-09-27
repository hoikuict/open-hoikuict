# 仕様と実装の照合記録（2026-09-13）

基準コミット: `e74840f`（`main`）。本記録はリポジトリのコードと仕様を照合した結果であり、配備先の状態や全端末での受入完了を示すものではありません。

## 確認方法

仕様一覧から主要な仕様書を確認し、ルーター、モデル、サービス、テンプレート、関連テストと照合しました。特にURL、権限、保存する値、実装済みと後続設計の境界を確認しています。制度・法令の再調査や、過去の配備記録の再検証は今回の対象に含めていません。

アプリケーションの動作は変更せず、食い違う仕様本文と一覧を修正しました。設計上の目標がコードより広い場合は、目標を取り下げず「後続設計」として区別しています。

## 修正した相違点

| 仕様 | 古い記述・不足 | 現行コードに合わせた修正 | 確認先 |
| --- | --- | --- | --- |
| [職員ポータル](staff-personal-portal-spec.md) | 全クラス切替は管理者のみ、予定は表示中のカレンダーから最大6件 | 一般職員も全クラスの人数サマリーを選択可能。要確認の全クラス明細は管理者のみ。予定は表示OFFの接続カレンダーも含む確定予定を全件表示 | `routers/staff_portal.py`、`staff_portal_service.py` |
| 職員ポータル | 文書確認依頼・端末監視・承認待ちの追加が本文に未反映 | 管理者の承認待ち、端末警告、サイドバーの文書確認依頼への入口を追記 | 同上、`templates/base.html` |
| [認可施設帳票](ninka-input-screen-spec.md) | 画面内のプレビュー・補正を実装済みと記載 | 年度とExcelを指定して直接出力する機能。プレビュー・補正・年度別保存は後続設計へ分離 | `routers/data_transfers.py`、`ninka_transfer_service.py`、`templates/data_transfers/index.html` |
| 認可施設帳票 | 定員と利用者数を独立して扱う説明 | 現行は両列に同じ園児数を書き込むこと、集計日・年齢・学級数の計算条件を明記 | `ninka_transfer_service.py` |
| [保育認定](care-need-certification-spec.md) | 拡張前の調査を「現行」と表記。直接訂正・新規園児フォーム・一括差額プレビューを利用可能に読める | 新規期間登録と理由付き無効化を現行操作とし、直接訂正・専用絞り込み・一括事前検証を後続へ分離。`is_active` と監査に含まれる情報を追記 | `child_care_certification_service.py`、`routers/care_certifications.py`、`models.py` |
| [延長料金](extended-care-fee-spec.md) | 転送済み料金と打刻取消の扱いが不足 | 転送済み料金の再計算除外、保護された料金がある打刻の取消拒否を追記 | `extended_care_fee_service.py`、`attendance_correction_service.py` |
| [請求転送](extended-care-billing-transfer-spec.md) | 未計算の出欠を止める条件が不足 | 降園打刻があるのに料金がない出欠を止めることを追記。既存料金すべての認定・ルールを再評価する機能とは区別 | `extended_care_billing_transfer_service.py` |
| [連携契約](integration-contract.md) | 児童票種別・セクション・根拠キーが未記載、JSON APIは参照のみ、承認ログは将来実装 | 現行の文書種別・JSON追加フィールド・実施変更API・永続化済み承認ログを反映。監査の `action` は操作動詞ではなく状態値 | `plan_docs/contracts.py`、`serializers.py`、`db_models.py`、`store.py`、`routers/documents.py` |
| 連携契約 | 一般職員は担当クラスだけに限定されると読める | 現行アダプターは全クラス名を渡すこと、空のクラス集合も制限にならないことを明記。児童票の別認可と区別 | `plan_docs/auth_adapter.py`、`child_records/access.py` |
| 連携契約・日案 | 日案の標準列が古い、作成中の行操作を後続として記載 | 新規日案は `children / support / considerations` と時刻・活動の横4列。作成中の行追加・挿入・削除は実装済み。既存の `env` 列は別の互換形として保持 | `plan_docs/services/generators.py`、`templates/plan_docs/daily_plans/form.html` |
| [日案](spec-daily-plan-v1.md)・[週案日案](spec-weekly-daily-plans.md) | Phase 2以降を一律未実装と記載 | 日案コーパス選択、カレンダー、振り返り下書き・提出、確認通知の追加実装を反映。当初案の文例専用URLや構造化した実施記録とは分離 | `plan_docs/routers/plans.py`、`routers/documents.py`、`services/daily_reflections.py`、`services/review_notifications.py` |
| [ローカル認証](local-authentication-spec.md) | 管理者の初期設定後にTOTP必須と案内 | TOTP・回復コードは未実装の設計と明示。現在の初期設定手順から分離 | `local_auth.py`、`routers/staff_auth.py` |
| [保護者認証](parent-local-authentication-spec.md) | 認証管理の入口が曖昧 | 現行の `/parent-accounts/{account_id}/authentication` を明記 | `routers/parent_auth.py` |
| [職員権限・請求口座](staff-permissions-and-billing-accounts-spec.md) | 実効権限式に職員の有効状態・編集ロールの条件が不足 | 有効職員かつ管理者、または有効な編集職員かつ口座管理フラグという条件へ修正 | `models.py`、`staff_permissions.py` |

## 主要契約を確認し、今回変更しなかった範囲

| 範囲 | 確認した点 | 確認先 |
| --- | --- | --- |
| [児童記録](child-records-spec.md) | 設定版、ログ訂正・無効化、児童票作成のルート。保育要録・個別指導計画の専用一覧は後続設計 | `child_records/router.py`、`models.py`、`access.py`、`test_child_records.py` |
| [入出力](import-export-spec.md) | 6種マスタ、園児台帳管理権限、職員CSVの管理者制限、事前検証と確定 | `routers/data_transfers.py`、`test_data_transfers.py` |
| [日案コーパス](daily-plan-corpus-contract.md) | 対応スキーマ、読み取り専用アクセス、レビュー状態による候補制限 | `plan_docs/services/daily_examples.py`、`test_plan_docs.py` |
| [通知](parent-push-notification-spec.md) | 本番での有効化条件、任意メール併用、90日保持処理がアプリ起動時だけという制約 | `parent_push_operations.py`、`main.py`、関連テスト |
| [バックアップ](backup-restore-spec.md) | バックアップ作成・検査、日次／週次スケジュール。稼働中の添付とDBの一括固定、復元後の全資格情報一括失効は別の残件 | `scripts/backup_runtime.py`、`test_backup_runtime.py`、`test_backup_schedule.py` |
| [健康管理](health-record-spec-review.md) | 専用ルーターと、プロフィール・アレルギー・健診の現行範囲。後続節は初回レビューの履歴 | `routers/child_health.py` |
| 施設設定・有給・一括移行 | 共通の施設設定モデル、有給台帳・申請、移行元IDを使う一括確定は引き続き計画 | モデル・ルーターの定義、現在の入出力サービス |

この表は記載した主要契約の確認範囲です。仕様書に残るすべての受入条件や非機能要件を達成済みとするものではありません。日付付きの変更記録・旧運用試験仕様は、履歴としての位置付けを維持します。

## 次に実装側で検討する点

1. **計画文書のクラス範囲**: 担当クラスだけに限定する製品方針なら、認証アダプターが全クラスを渡す現在の実装を変更する必要があります。現在の参照キーがクラス名である点も含めて設計します。
2. **認可施設帳票**: 人数から認可定員を作らず、施設の定員値・補正・出力前確認を扱う仕組みが必要です。年度のサーバー側範囲検証も残っています。
3. **保育認定の変更**: 既存期間の直接訂正、切替前の不足・差額チェック、既存料金の再評価範囲を決める必要があります。
4. **日案の後続機能**: 振り返り本文は保存できますが、構造化した事実・評価・次への問い、版履歴、週案への集約は後続です。
5. **運用・認証の残件**: TOTP、職員本人の通常パスワード変更、起動時だけでないPush保存期間処理、復元後の一括失効は、現行ガイドでも未実装として扱います。

## 検証記録

関連する既存テスト **172件成功**。メモリDB・一時ディレクトリとcapture配送を使い、業務DBや実際の宛先への配送は行っていません。

```text
python -m pytest -q -p no:cacheprovider
  test_staff_portal.py test_plan_docs.py test_child_records.py
  test_care_certifications.py test_extended_care_fees.py
  test_extended_care_billing_transfer.py test_data_transfers.py
  test_spec_improvements_20260911.py test_local_staff_auth.py
  test_local_parent_auth.py test_parent_push_operations.py
  test_parent_push_production.py test_backup_runtime.py
  test_backup_schedule.py test_spec_changes.py
```

全体テストの再実行や、ブラウザーでの業務シナリオの再実施はこの件数に含めていません。文書変更にはMkDocsのstrictビルドと `git diff --check` を適用します。
