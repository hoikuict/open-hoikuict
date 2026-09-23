# 保護者アカウントの利用停止・再開の一本化

2026-09-23、利用再開では現在のパスワードを維持する方針と操作モックをユーザーが確認し、実装・本番反映を承認した。同日06:30:49 JSTに本番反映完了。実機で340テストと既存データ保持・読み取り専用の画面検査が成功した。詳細は [配備記録](deployment-parent-lifecycle-2026-09-23.md) に記載。

## 実装した動作

- 認証管理の上部で、理由入力→確認→確定の順に停止・再開する。確認から戻ると理由を保持する。
- 停止は台帳状態・資格情報・セッション・通知登録・未完了の招待・コードを一括で扱う。通常再開はパスワードと園児の紐づけを維持し、旧セッションや通知登録は復活させない。メールは送信しない。
- パスワード再設定を伴う再開は登録メールへ案内し、本人の設定完了まで停止を維持する。案内の取消・期限切れは停止中へ戻る。取消後も、既存の再設定必須指定は保持する。
- ローカル保護者認証の編集画面を状態表示と認証管理へのリンクへ変更。一覧、編集、園児詳細、認証管理で同じ状態判定を使う。過去の「台帳有効・認証停止」の状態も停止中として扱う。
- 既存アカウントの状態を変えるCSVはプレビュー・取込の双方で拒否する。状態が空欄・現状と同じ場合の台帳更新、新規データの取込は維持する。
- 未登録者は通常再開の対象外。停止後も認証管理から初回登録・初回設定を再案内でき、本人確認や初回承認を通常再開で飛ばせない。
- 停止・再開は管理者限定。理由と対象状態の検証、古い確認・二重送信の拒否、保存失敗時のロールバック、監査記録を実装。

本番で発見した既存の不整合データを自動で有効化する処理は加えていない。DBスキーマ追加も不要。`must_change_password`は既存フィールドを使い、通常再開の可否判断に利用する。

## 対象ファイル

- `parent_account_lifecycle.py`：共通の利用状態、確認リビジョン、停止・再開処理。
- `parent_auth.py`：コード・セッション失効、再設定を伴う再開、初回設定との分離。
- `parent_enrollment.py`：初回入力を途中で停止した未登録者の再案内。既存パスワードのある利用者には適用しない。
- `routers/parent_auth.py`、`templates/parent_auth/`：確認画面、入力保持、履歴、保護者の再開手続き。
- `routers/parent_accounts.py`、`routers/children.py`、関連テンプレート：共通表示とプロフィール経由の状態変更拒否。
- `data_transfer_service.py`：CSVで既存アカウントの状態が変わることを防止。

既存の別作業の変更を含む作業ディレクトリで実装したため、配備するときは最新の配備記録と本番ブランチを確認し、この差分を適切に取り込む必要がある。

配備用ソースは実機で確認した `15b13a9dd1eb6ae1b4d171186cb12c1dcc33326c` を基準に、今回の22ファイルだけを取り込んだ。開発ブランチ全体で本番を置き換えない。

## 確認

- 合意済みモック：`tools/account-lifecycle-review/`。実装では確認画面をサーバーで描画し、JavaScriptがなくても確認・修正・確定を行える。
- 実装確認用：`venv/Scripts/python.exe tools/account-lifecycle-review/preview-app.py`。`http://127.0.0.1:8877/parent-accounts/1/authentication`。架空の100園児・98紐づけ、メモリ内DB、メールの外部送信なし。本番DBへ接続しない。
- ブラウザーで理由入力、確認から修正へ戻る操作、通常再開、利用中表示、セッション0件、プロフィールの状態変更欄廃止、98紐づけの保持を確認。
- 自動テスト：主要な停止・再開、保護者認証、コードメール、98人紐づけ、初回登録・公開登録の最終確認80件が成功。家族同期・CSVを含む最初の関連確認73件、家族管理・園児表示・初期台帳取込・通知等の周辺確認161件も成功（各実行には重複あり）。保存失敗・権限・CSRF・古い確認・CSV・再開案内の完了／取消／期限切れも架空データで確認。
- 本番と同じ版を基準にした29モジュールの回帰確認339件が成功。続いて、初回入力を途中停止した場合の再案内を補正し、その回帰テストを追加した最終関連確認77件が成功。配備イメージで行う最終一式は340件。
- 卒園した園児の状態と既存パスワードを保持したまま、停止中に新しい弟妹を明示的に紐づけ、通常再開できることを架空データで確認。
- 本番用の読み取り専用検査を、利用中・旧版の不整合・停止中・再開手続き待ちの4状態で試し、検査前後のDBダンプが同一であることを確認。

最終の主要確認コマンド：

```powershell
venv/Scripts/python.exe -m pytest test_parent_account_lifecycle.py test_local_parent_auth.py test_parent_code_mail.py test_parent_account_access_controls.py test_parent_enrollment.py test_parent_public_registration.py -q --disable-warnings --tb=short --basetemp=.local-dev/pytest-lifecycle-20260923-final
```

周辺確認コマンド：

```powershell
venv/Scripts/python.exe -m pytest test_parent_portal.py test_parent_registration_links.py test_parent_registration_home.py test_parent_enrollment.py test_parent_public_registration.py test_parent_push_service.py test_family_archive.py test_family_archive_restore.py test_family_archive_usage.py test_family_deletion.py test_children_parent_link_display.py test_initial_ledger_import.py -q --disable-warnings --tb=short --basetemp=.local-dev/pytest-lifecycle-20260923-related
```

職員の停止・再開、連絡先メールとログインIDの窓口、招待の入口整理は次の候補であり、今回の改修には含めていない。
