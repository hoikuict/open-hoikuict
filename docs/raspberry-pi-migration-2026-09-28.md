# ラズパイ検証環境へのデータ複製

2026-09-28。状態：**配備・データ復元・最終検証完了（11:51:56 JST）**。
ユーザー指定どおり、元のTrueNAS実機を残し、ラズパイを独立した検証環境にした。AIは使わない。本番URLの切替や開発mainの配備は行っていない。

## 利用方法

- 職員ログイン：<https://hoikuict-pi5-test.tail2d331d.ts.net/staff/login>
- 保護者ログイン：<https://hoikuict-pi5-test.tail2d331d.ts.net/parent-portal/login>
- 同日、別のLANでも試せるようTailscaleの固定HTTPS URLへ切替済み。接続元も同じTailscaleネットワークへの接続とアクセス許可が必要。証明書はServeが管理し、Windowsで通常の証明書検証に成功。旧LAN URLは現在公開していない。持ち運び手順は [別のLANでの検証](raspberry-pi-portable-2026-09-28.md)。
- 既存アカウントとパスワードハッシュを保持。元実機のログインセッション、途中の登録・復旧トークン、送信待ち通知は、複製側だけで失効・取消済み。
- 月案AIとPush通知は無効。メールはラズパイ内部のMailpitに捕捉され、実際の宛先へ配送しない。
- 定期バックアップは初期無効。手動バックアップと復元ワーカーは稼働。
- 元実機とラズパイのデータは独立し、相互同期しない。複製後の編集はそれぞれの環境だけに保存される。

## 複製基準と保存内容

- [最新の本番更新記録](deployment-attention-scope-2026-09-28.md)と稼働情報を照合。
- アプリコミット：`2ff239ad8ed175ab7fc1ac067a038429af8ec43f`。
- 取得時点：2026-09-28 **11:30:22 JST** のZFS snapshot。
- snapshot：`main/open-hoikuict-pilot/runtime@pi-clone-20260928T023022Z`。
- 元実機の取得セット：`open-hoikuict_20260928T023100Z_2ff239ad8ed1`。
- 主DB、施設文例DB、storage、月案文例DB、同梱文例DB、パスワード禁止リストを複製。
- 復元検査の集計：園児100件、対象記録1,011件、storageファイル13個、写真21件。記録数は既存の復元検査が集計する対象テーブルの合計。
- 業務・アカウント等115テーブルは取得元と内容のハッシュが一致。施設文例DBも一致。旧セッション等の失効対象は別途検査。
- 本番のSMTPパスワード、トンネルtoken、認証鍵、Push秘密鍵は含めない。検証用の認証鍵・復元署名鍵・TLS鍵はラズパイ上で新規生成。

## 配備構成

- Raspberry Pi 5、8GB RAM、Debian 13 ARM64、119.1GiB microSD。
- SSH：`zdan@192.168.0.16`。
- 配備ルート：`/srv/open-hoikuict-pi-test`。
- Compose：`/srv/open-hoikuict-pi-test/compose.json`、非公開設定：同ディレクトリの `.env`。
- データ：`runtime/data`、添付：`runtime/storage`、文例：`library`、バックアップ：`backups`。
- 最終ARM64イメージ：`open-hoikuict:pi-test-2ff239a`。
- イメージID：`sha256:f937af9397f3ab81834f6604b63ca0e511cfae7d4f6b4edf1325d5a7ad939bb0`。
- 現行Compose SHA256：`8781e7ca909ed83efe65f0020b411aa19d04d1fcb78a0ab98c3d652d89e711e7`。初回複製時は `e26ca640578ef72492a631c7fec2fd52f54cd8693d55f87c56b688f1a839f100`。
- Pythonパッケージ76個は元実機の導入版と一致。CPU・OS・Pythonランタイムの完全なバイナリ複製ではなく、ARMで再構築して検証した。
- appとMailpitはDockerのinternal networkだけに接続。バックアップ・復元ワーカーはnetworkなし。現在はTailscale ServeがHTTPSを受け、Pi loopbackの `127.0.0.1:18080` からNginx経由でアプリへ転送する。内部確認用HTTPSは `127.0.0.1:8443` のみ。
- Mailpit管理画面はPiのloopback `127.0.0.1:18025` のみ。確認が必要な場合は `ssh -L 18025:127.0.0.1:18025 zdan@192.168.0.16` で転送し、PCの `http://127.0.0.1:18025` を開く。
- DockerはOS起動時に有効。5サービスは `restart: unless-stopped`。2026-09-28 12:52:05 JSTの本体再起動後、同じLAN IP・5サービスの自動起動・HTTPS職員ログイン画面の正常応答を確認。
- 内部確認用ローカルTLS証明書の期限は2027-09-28。公開CA証明書：`.local-dev/raspberry-migration-20260928/pi-test-ca.crt`。秘密鍵はPiの非公開ディレクトリ内。利用者向けHTTPSは別のServe管理証明書を使用。
- PiはDHCPクライアントのまま。ユーザーがAtermでWi-Fi MAC `2C:CF:67:F0:5C:DA` に `192.168.0.16` の固定割当を設定し、その後の本体再起動でも同じIPを確認。有線LANは別MACのため、この予約の対象ではない。現在はLAN IPに依存しないURL・許可origin・待受設定へ変更済み。有線LANもDHCP・自動接続で、別LANではその場所のアドレスを取得する。
- Tailscaleを追加し、`hoikuict-pi5-test` / `100.94.99.15` でSSH経由の稼働確認が可能。詳細は [Tailscale遠隔確認](raspberry-pi-tailscale-2026-09-28.md)。

操作例（ラズパイ側）：

```sh
sudo docker compose --project-directory /srv/open-hoikuict-pi-test --env-file /srv/open-hoikuict-pi-test/.env -f /srv/open-hoikuict-pi-test/compose.json ps
```

## 検証

以下は初回複製時の検証記録。後続のTailscale固定URL切替では、アプリイメージを維持し、業務・アカウント等115テーブルの内容が変更前後で一致することを確認した。新構成のログイン・保存・WebSocket・バックアップの検証と未実施事項は [別のLANでの検証](raspberry-pi-portable-2026-09-28.md)に記録。

- 最終イメージで244テスト成功、失敗・スキップなし。
- 架空データの復元演習成功：メンテナンス、CSRF、パスワード再確認、復元後の再ログイン、WebSocket、バックアップ予定の無効化。
- 取得アーカイブSHA256とpayload全25ファイルのサイズ・ハッシュ・一覧を照合。
- 配備版の形式1バックアップ検査と `restore_data.prepare_copy` を使用。外部キー、写真、添付参照を検査し、複製側だけでトークン等を失効。
- 実データの主要10検査が成功：ホーム要確認、家庭関連、初回台帳、保護者ライフサイクル、お知らせ、連絡帳、月案、承認済み機能。
- 月案文例検索、0〜5歳の帳票、PDF日本語フォント、Excel出力、担当権限、共同編集の既存仕様を確認。検査は読み取り専用トランザクションで実施。
- Windowsから証明書のCA署名と接続先IPを検証し、HTTPS `/healthz` と職員ログイン画面のHTTP 200を確認。ローカルCAに失効配信先がないためcurlでは `--ssl-revoke-best-effort` を併用。
- ラズパイの手動バックアップ成功：`open-hoikuict_20260928T025042Z_2ff239ad8ed1`。17ファイル検証、警告なし。Git SHA・ARMイメージID・Compose SHA256が実配備と一致。
- 実データの読み取り検査前後で全テーブルが一致。起動後も業務・アカウント等115テーブルを保持。バックアップ・復元サービスのheartbeat、署名鍵、保存済み全3バックアップの写真・添付・DB検査が成功。
- appからインターネットと元実機Ollamaへの接続ができないことを確認。架空宛先へのSTARTTLSメールは内部Mailpitで捕捉。Mailpitはinternal networkのまま、管理画面だけNginx経由のPi loopbackに限定した。
- 実アカウントのパスワード入力による操作確認はユーザー側で行う。パスワードは取得・表示していない。

## 元実機の保全と取得経過

- r1は別コンテナFile Browserの書込み共有を検出して、元実機の停止前に中断。
- r2はワーカーのSIGTERM終了が不正常だったため中断し、自動再開した。
- 架空環境で実ワーカーの停止を検証し、r3ではワーカーをSIGINTで終了。15個の取得制御テストをTrueNASとPiで確認。
- ユーザーがr3をsudo起動。app・backup-worker・restore-worker・File Browserを一時停止し、snapshot取得後に同じコンテナを再開。データの検査・アーカイブ作成はsnapshotのコピーに対して行った。
- r3完了：11:31:04 JST。元実機およびFile Browserの再開を確認。公開 `https://hikarinomori.hoikuict.net/healthz` は正常。
- 元実機の取得作業ディレクトリ：`/home/truenas_admin/pi-clone-export-20260928-r3`。
- アーカイブ：27,429,893 bytes、SHA256 `aebe1657921e6bc78f3f8cabd97e547839c73832678f169c2598cbd5953eb8d8`。
- SSH転送はWindowsを中継する `scp -3`。実データアーカイブをPCのファイルとして保存していない。
- Pi作業領域：`/home/zdan/hoikuict-migration-20260928`。アクセス制限した取得原本と検証ログを保持。
- Piの初回復元はPython検索パス不足によりコピー前に停止。空の作業ディレクトリを `...-empty-attempt1` として保持し、修正後に復元成功。
- 既存SSH・VNC・印刷サービスは維持。既存Coral APTリポジトリの署名鍵不足は変更せず、Docker導入時はDebianとDockerの取得先に限定。

## 証跡

PC：`.local-dev/raspberry-migration-20260928/` の `export-completed.json`、`final-image.json`、`preflight.json`、最終検証記録。Pi：作業領域の `final-image.log`、`deploy-clone-r2.log`、`clone-verification.json`、`backup-verification.json` と、配備ルートの `deployment.json`、`restore-report.json`。

[Docker ARMビルド](https://docs.docker.com/build/building/multi-platform/)／[Debian導入条件](https://docs.docker.com/engine/install/debian/)／[MailpitのSMTP設定](https://mailpit.axllent.org/docs/configuration/smtp/)。
