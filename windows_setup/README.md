# Windows導入アプリのソース

`beta_setup` はダウンロード・試用導入とループバックUI、`windows_setup` はサービス化・LAN・公開接続を扱う。配布版v2026.9.23.5の実装をmain側のソースへ統合した。今後、配布タグだけに変更を置かず、このソースとテストを基準にリリースする。

mainのバックアップv2・復元契約・業務機能を維持する。Windowsでは検証済みpayloadのSHA-256とcloudflaredのSHA-256を成果物識別子に使う。サービス用設定のハッシュ、配布版、初回移行と復元練習の記録を保持する。従来の未固定な `windows-managed` 等をバックアップの出所として渡さない。

## 今回反映した不具合修正

- LANの名前検査は、選択したインターフェースのDNSサーバーを個別に指定して `Resolve-DnsName -NoHostsFile -DnsOnly` で照会する。Aの不一致、複数A、AAAA、問い合わせ失敗を合格にしない。VPN等の別アダプターやローカルhostsの成功を証拠にしない。
- トークン確認は有効状態とゾーン参照の確認。実際のDNS編集権限の検証とは区別する。
- Caddyは固定済みのv5リリースから取得し、ZIPと実行ファイルをそれぞれロックのSHA-256で検証する。可変のビルドAPIと自動 `--record-lock` は使用しない。新規ソースビルドを再現したという意味ではない。

## 次の画面変更

[園用ドメイン方式の変更案・操作モック](../tools/windows-domain-setup-preview/README.md) を参照。DNS Aレコードの自動作成、園内名と公開名の分離、既存internal環境の移行は、画面の合意後に適用処理へ接続する。今回の不具合修正だけで既存環境のDNSが自動作成されるわけではない。

## 検証

```powershell
python -m unittest test_windows_dns test_windows_components test_windows_server_setup test_atomic_file test_beta_setup test_beta_releases test_restore_runtime
node test_windows_setup_ui.cjs
python scripts/build_windows_components.py --output <新しい検証用フォルダー>
```

`scripts/verify_windows_server.py` の通常モードは架空データとループバック接続でサービスワーカー・HTTPS・バックアップ・復元を確認する。`--service` を付けた実機検証は管理者権限でWindowsサービスを作成するため別作業とする。本番の設定、DNS、トークン、データをテストへ流用しない。

## 2026-09-23の検証記録

- 関連Pythonテスト133件、既存UIテスト8件が成功。その後の移行件数記録・v2保持区分の追加を含む36件の再確認も成功。
- Ruff、MkDocs strict、差分の空白検査が成功。
- 新しい空のフォルダーへ固定リリースから3部品を取得し、ZIP・実行ファイル・Caddyモジュール一覧を照合した。
- 現PCの `hoikuict.home.arpa` はhostsでは開けるが、選択したLAN DNSへの直接検査で `dns_unresolved` になることを読み取り専用で確認した。
- 架空データのループバック検証でHTTPS、適用前のアクセス遮断、移行後のパスワード、Secure Cookie、バックアップv2と隔離復元、ワーカー再起動、認証鍵の維持が成功。Windowsサービス登録は今回の検査に含めていない。
- 実ドメインのA作成・ACME発行・他Windows/iPadからの接続は未実施。公開済みv5や稼働中の環境への配備は行っていない。
