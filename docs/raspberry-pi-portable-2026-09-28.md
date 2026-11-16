# 別のLANでHOIKUICTを検証する（2026-09-28）

ユーザー指定：「このPCなど、Tailscaleに接続できる端末で試す」。既存Piのアプリとデータを保ち、LAN IPが変わっても同じURLを利用する構成へ変更した。

## 持ち運び時の操作

1. 移動前にPiを正常にシャットダウンし、停止してから電源を外す。
2. 移動先のDHCPが使える有線LANにPiをつなぎ、電源を入れる。有線接続はDHCP・自動接続に設定済み。
3. PiがインターネットとTailscaleへ接続できるまで待つ。このPCもTailscaleへ接続する。
4. [職員ログイン](https://hoikuict-pi5-test.tail2d331d.ts.net/staff/login)を開き、既存のアカウントでログインする。

Wi-Fiを使う場合、移動先のSSIDとパスワードの設定が別途必要。職場のネットワークでTailscale通信が許可されていることも必要。この構成は、インターネットのない環境での利用を検証したものではない。

旧 `https://192.168.0.16:8443` は現在公開していない。今後は上記固定URLを使用する。現在地のルーターのDHCP予約は残っているが、アプリへの接続にはそのLAN IPを使わない。

保護者画面は [保護者ログイン](https://hoikuict-pi5-test.tail2d331d.ts.net/parent-portal/login)。監視URLは引き続き [healthz](https://hoikuict-pi5-test.tail2d331d.ts.net/healthz)。Kumaの実行環境もTailscaleへ到達できる必要があり、Kuma自身の正常判定は未確認。

## 変更した設定

| 対象 | 現在の設定 |
| --- | --- |
| 公開HTTPS origin | `https://hoikuict-pi5-test.tail2d331d.ts.net` |
| Serve | HTTPS 443 → `http://127.0.0.1:18080`、`--bg` で永続化、Funnelなし |
| Nginxのホスト側待受 | `127.0.0.1:18080:8080`、内部HTTPS `127.0.0.1:8443:443`、Mailpit `127.0.0.1:18025:8025` |
| アプリURL設定 | `HOIKUICT_ALLOWED_ORIGINS`、`HOIKUICT_PUBLIC_ORIGIN`、`HOIKUICT_PARENT_REGISTRATION_BASE_URL`、`HOIKUICT_STAFF_RECOVERY_BASE_URL` を上記originに統一 |
| ローカル状態確認 | `/usr/local/sbin/hoikuict-status` が `https://127.0.0.1:8443` を検査 |
| 旧監視専用サービス | `hoikuict-health-proxy.service` は停止・自動起動無効化、ファイルは保持 |

Nginxは固定DNS名のHostを検査し、HTTPS接続情報とWebSocket Upgradeをアプリへ渡す。Secure Cookie、CSRF、ログイン認証を維持。Tailscale接続だけでアプリのログインが省略されることはない。

配備ルートは `/srv/open-hoikuict-pi-test`。アプリコミット `2ff239ad8ed175ab7fc1ac067a038429af8ec43f`、イメージ `sha256:f937af9397f3ab81834f6604b63ca0e511cfae7d4f6b4edf1325d5a7ad939bb0` を維持。現行Compose SHA256は `8781e7ca909ed83efe65f0020b411aa19d04d1fcb78a0ab98c3d652d89e711e7`。

DockerとtailscaledはOS起動時に有効。5コンテナは `restart: unless-stopped`。AI・Push通知の無効化、内部Mailpitへのメール捕捉、アプリから外部への通信制限、定期バックアップの初期無効設定を維持した。元TrueNAS実機への変更はない。

## 検証結果と限界

実機では、Windowsから固定URLの職員・保護者ログイン画面と `/healthz` がHTTP 200を返し、証明書検証も成功。Secure・HttpOnly CookieとCSRFトークンなしPOSTの403拒否を確認。ブラウザーでも職員ログイン画面の表示を確認した。

同じアプリイメージと候補Nginxを使い、Pi内の隔離ネットワークとデータコピー上で以下の8検査が成功。架空アカウントで保存を試しており、実環境の業務レコードにはテストデータを追加していない。

1. Nginx経由のヘルスチェック。
2. 職員ログイン画面とSecureなCSRF Cookie。
3. パスワード認証とログイン後ホーム表示。
4. CSRFトークンなし保存の拒否と、正しいトークンでの月案保存。
5. 認証付きWebSocket接続。
6. 許可していないoriginからのWebSocket接続拒否。
7. 保護者ログイン画面。
8. コピーDBの整合性と外部キー検査。

設定変更前後で業務・アカウント等115テーブルが一致。変更前後に手動バックアップを作成・検証し、変更後バックアップのGit SHA・イメージID・Compose SHA256も実配備と一致した。

**現行構成へ切り替えた後の本体再起動、および実際に別LANへ持ち運んだ状態での確認は未実施。** 自動起動設定と現在地からのTailscale接続は確認済み。移動先で接続できない場合は、Piのインターネット接続、Tailscale管理画面のオンライン状態、端末認証期限、アクセス許可、HTTPS応答の順に確認する。

## バックアップと記録

- 変更前バックアップ：`open-hoikuict_20260928T052004Z_2ff239ad8ed1`。
- 変更後バックアップ：`open-hoikuict_20260928T052025Z_2ff239ad8ed1`。
- 変更前設定：Pi内 `/srv/open-hoikuict-pi-test/configuration-backups/portable-20260928`。Compose、Nginx、非公開 `.env`、配備記録、状態確認スクリプト、Serve設定を保持。
- 現行配備記録：`/srv/open-hoikuict-pi-test/deployment.json`。
- 完了記録：`/home/zdan/hoikuict-migration-20260928/portable-20260928/completed.json`。
- 作業スクリプト：PCの `.local-dev/raspberry-migration-20260928/` 内 `prepare-portable.py`、`portable-smoke.py`、`run-portable-smoke.py`、`apply-portable.py`、`finalize-portable.py`。

非公開設定と実データのバックアップはPi内に保持し、Gitへ登録しない。切戻す場合は変更前設定を一式で扱う。旧設定は現在地のLAN IPに依存するため、別LANでそのまま戻すと接続できなくなる。業務データの復元はこの設定変更の切戻しには不要。

関連：[初回移植記録](raspberry-pi-migration-2026-09-28.md)、[Tailscaleでの状態確認とKuma設定](raspberry-pi-tailscale-2026-09-28.md)。仕組みの参考：[Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve)、[ネットワークが変わっても使える端末アドレス](https://tailscale.com/docs/concepts/ip-and-dns-addresses)。
