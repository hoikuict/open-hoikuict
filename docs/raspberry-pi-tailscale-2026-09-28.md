# Raspberry PiのTailscale遠隔確認（2026-09-28）

ユーザー依頼により、既存の検証用PiにTailscaleを導入。初めは監視専用HTTPS入口を設け、その後「別の環境でもTailscale接続端末で試す」という指定に合わせて、アプリ全体を同じHTTPSドメインで利用できる構成に変更した。Kumaへの正しいURLの登録とKuma自身の正常判定は未確認で、通知先は設定していない。

## 接続先

| 項目 | 値 |
| --- | --- |
| Tailscale端末名 | `hoikuict-pi5-test` |
| Tailscale IPv4 | `100.94.99.15` |
| 職員ログイン | `https://hoikuict-pi5-test.tail2d331d.ts.net/staff/login` |
| Kuma用HTTPS監視URL | `https://hoikuict-pi5-test.tail2d331d.ts.net/healthz` |
| 現在地のLAN IPv4 | `192.168.0.16`（Wi-Fi MACをルーターで固定割当） |
| SSHユーザー | `zdan` |
| 導入版 | Tailscale `1.102.4` / Debian 13 ARM64 |

接続元も同じTailscaleネットワークに参加し、対象サービスへのアクセスが許可されている必要がある。別LANへの持ち運び手順は [別のLANでの検証](raspberry-pi-portable-2026-09-28.md)。

## 状態確認

[Tailscale管理画面](https://login.tailscale.com/admin/machines)で `hoikuict-pi5-test` の接続状態を確認する。オンライン表示だけではHOIKUICT自体の正常性は分からない。

HOIKUICTを含む状態確認は、このWindows PCのPowerShellで実行する。

```powershell
ssh -o HostKeyAlias=192.168.0.16 zdan@100.94.99.15 "sudo -n /usr/local/sbin/hoikuict-status"
```

`HostKeyAlias` はこのPCで確認済みのLAN側SSHホスト鍵と同じ鍵を照合する指定で、接続先はTailscale IP。他のPCではSSH公開鍵の登録とホスト鍵の確認が別途必要。

`HOIKUICT: OK` は今回の確認項目がすべて正常であることを示す。異常時は `CHECK REQUIRED` / `FAIL` と終了コード1を返す。単発の確認であり、継続的な稼働や業務データの正確性を保証する表示ではない。

- Docker・tailscaledの稼働、Tailscale接続状態。
- アプリ、HTTPS、バックアップ、復元、Mailpitの5コンテナの状態。
- gateway・backup・workerのheartbeatが20秒以内で、gatewayが通常運転・正常であること。
- Piの `https://127.0.0.1:8443` で証明書を検証した `/healthz` と職員ログイン画面の応答。
- 起動後経過時間、CPU温度、利用可能メモリ、ディスク空き容量、ロードアベレージ。

コマンドは読み取り専用で、業務レコード・メール内容・認証鍵を出力しない。`--json` で機械処理用JSONを返す。バックアップの実行や、接続元からServe経由のHTTPS到達性確認は別途行う。

## 現行HTTPS構成

1. Tailscale Serveが固定DNS名の443番でTLSを終端する。Tailscale内限定で、Funnelは設定していない。
2. Serveは `http://127.0.0.1:18080` へ転送する。このポートはNginxコンテナの8080番につながる。
3. Nginxは固定DNS名のHostを検査し、元のHTTPS接続情報とWebSocket Upgradeをアプリへ渡す。
4. アプリの公開origin、許可origin、職員復旧・保護者登録URLも同じ固定HTTPS originを使用する。

Serveの設定は次のコマンドで永続化済み。

```sh
sudo tailscale serve --bg --yes --https=443 http://127.0.0.1:18080
sudo tailscale serve status
```

以前の監視専用 `hoikuict-health-proxy.service`（loopback 18765）は停止・自動起動無効化済み。関連ファイルは切戻し用にPiへ保持しているが、現在の `/healthz` はアプリへ直接つながる。旧LAN URLおよび `https://100.94.99.15:8443` は現在の利用先ではない。

## Uptime Kuma HTTP監視

| 設定項目 | 値 |
| --- | --- |
| 監視タイプ | HTTP(s) |
| URL | `https://hoikuict-pi5-test.tail2d331d.ts.net/healthz` |
| メソッド | GET |
| 正常とするHTTPステータス | 200 |
| 監視間隔 | 既存の60秒で可 |
| TLS証明書検証 | 有効（エラー無視は不要） |

Kumaの実行環境からTailscale宛てに接続できる必要がある。コンテナで稼働する場合は、そのコンテナからの名前解決・アクセス許可・経路を確認する。端末自体の到達性を別に見る場合は、`100.94.99.15` へのPing監視を追加できる。

Windowsから上記URLのHTTP 200、`{"status":"ok"}`、通常のTLS証明書検証の成功を確認した。これはKuma自身の判定を確認したものではない。

## 導入・検証記録

- 公式 `pkgs.tailscale.com/stable/debian` のtrixie用署名付きAPTリポジトリから導入。既存CoralリポジトリやOS全体の更新は行っていない。
- `tailscaled` はOS起動時に有効。ユーザーのブラウザー認証で、このWindows PCと同じネットワークに登録。
- `--accept-dns=false --accept-routes=false`。サブネットルーター、出口ノード、Tailscale SSH、Funnelは設定していない。SSHは既存OpenSSHと公開鍵認証を使用。
- `/usr/local/sbin/hoikuict-status` はroot所有・0755。元スクリプトはPCの `.local-dev/raspberry-migration-20260928/hoikuict-status.py` とPi作業領域に保持。
- Tailscale経由のSSHとホスト鍵照合、状態確認13項目の正常を確認。固定URL切替後も全項目正常。
- 職員・保護者ログイン画面のHTTPS 200、Secure Cookie、CSRFトークンなしのPOST拒否を確認。
- 隔離したデータコピーに架空アカウントを作り、ログイン・月案保存・WebSocketなど8検査を実施。元の業務データを変更せず、変更前後の115テーブル一致を確認。
- 現行構成に切り替えた後の本体再起動と、別拠点・携帯回線からの接続試験は未実施。

現在はServeを停止すると、監視URLとアプリ画面の両方へアクセスできなくなる。設定の切戻しには、[持ち運び設定の記録](raspberry-pi-portable-2026-09-28.md)にあるPi内の非公開設定バックアップを使用する。

運用時はTailscale管理画面で端末の認証期限も確認する。認証キー・端末秘密鍵・Tailscale状態ファイルはGitへ登録せず、他の実機にも複製しない。

参考：[公式Linux導入手順](https://tailscale.com/docs/install/linux)、[Serveの設定と永続化](https://tailscale.com/docs/reference/tailscale-cli/serve)、[端末への接続](https://tailscale.com/docs/how-to/connect-to-devices)。
