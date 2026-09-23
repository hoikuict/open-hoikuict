# Windows導入アプリの適用開始エラー修正

2026-09-23。配布候補 `v2026.9.23.4`。画面の「引継ぎ元と配布版を確認」で停止した報告に対応。

## 修正

- フォルダーのアクセス権を再設定すると、通常ユーザーで `SeSecurityPrivilege` が要求されて失敗していた。DirectoryInfoのAccessセクションだけを更新し、所有者や監査設定に触れないようにした。SYSTEM・Administrators・導入者の許可に限定する保護は維持。
- 専用仮想サービスアカウントへ切り替える際、空文字のパスワード指定でWindowsエラー1057が発生した。仮想アカウントにはNULLが必要なため、`sc.exe config` のパスワード引数を省略。
- WinSWの停止用引数と共通引数が重なっていた。公式仕様に従って起動用を `startarguments` に変更。
- WinSWコマンド終了だけで停止完了とせず、SCMのRunning/Stoppedを待つ。Stop Pending中に停止命令を重ねず、停止前のプロセスを再起動済みと誤認しない。
- 初回PCでのサービス検証用の親フォルダー作成を修正。検証記録は後片付け成功後に出力し、再起動では起動時刻が実際に変わったことを確認する。

## 検証

- 導入・配布・サーバー設定のPythonテスト47件、既存UI状態テスト8件、通常ユーザーでの実Windows権限テスト1件に成功。
- 旧v2026.9.23.3の実EXEで2回目の下書き保存が失敗することを再現。権限修正版EXEで保存・再保存・終了・再起動後の下書き復帰を確認。
- 権限修正版の配布一式で架空環境を新規導入し、管理者ログイン、クラス保存、停止・再起動、データと鍵の保持、初期台帳・保護者一覧を確認。
- 実Windowsサービスの専用仮想アカウントでHTTPS、移行したパスワードによるログイン、Secure Cookie、適用前アクセス制限、バックアップ、隔離復元、実際の停止と再起動、セッション鍵保持を確認。
- 最終サービス検証の記録先は `.local-dev/wsqa-acl-fix/1cb58089/verification.json`。終了コード0。検証用サービスとProgram Files/ProgramDataの専用インスタンスを削除。
- サービス検証では同じ実行コードの検証済みバンドルと、修正したサービス登録・構成生成・状態待機処理を使用。園の実DB、ファイアウォール、証明書ストア、電源、ルーター、SMTPには変更を加えていない。

別端末からのLAN接続、Windows本体の再起動、実SMTP、園外公開は今回の隔離検証の対象外。GitHub公開前のため、利用中の環境へのLAN適用は未完了。

## 公式仕様

- [Windows DirectoryInfo.GetAccessControl](https://learn.microsoft.com/en-us/dotnet/api/system.io.directoryinfo.getaccesscontrol?view=netframework-4.8.1)
- [Windows ChangeServiceConfigW](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-changeserviceconfigw)
- [WinSW 2.12.0 XML設定](https://github.com/winsw/winsw/blob/v2.12.0/doc/xmlConfigFile.md)
