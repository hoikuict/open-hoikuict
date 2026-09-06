# TrueNAS実機で保護者の通知を確認する

## 必要な設定

`production`では既定値は引き続き`disabled`。`webpush`を明示設定すると、職員・保護者の`local_password`認証、Secure Cookie、CSRFなどの既存の本番検証に加え、次を起動時に検証する。`capture`は本番では使用しない。

- `HOIKUICT_PUBLIC_ORIGIN`: 利用するHTTPSの施設URL。`HOIKUICT_ALLOWED_ORIGINS`と`HOIKUICT_PARENT_REGISTRATION_BASE_URL`に一致させる。
- `HOIKUICT_PUSH_VAPID_PRIVATE_KEY`: アプリから読み取れるP-256秘密鍵のPEMファイルパス。
- `HOIKUICT_PUSH_VAPID_PUBLIC_KEY`: 同じ秘密鍵から生成した、非圧縮公開鍵のbase64url表現（末尾の`=`なし）。
- `HOIKUICT_PUSH_VAPID_SUBJECT`: 施設の連絡先。例: `mailto:admin@example.com`。

鍵はTrueNAS内で生成し、秘密鍵をチャット・ログ・Gitへ出力しない。既存の鍵を再生成して置換すると、登録済み端末の再登録が必要になるため、再実行では同じ鍵を使用する。秘密鍵をアプリの実行UIDだけが読める0400にして読み取り専用でマウントする。復旧時も同じ鍵を利用できるよう、ランタイムとは別に権限を制限したバックアップに含める。

新規構成では`deploy/truenas/compose.webpush.yaml`を基本Composeに重ねて使用する。TrueNASのCompose CLIでは、スタック直下へコピーし、`.env`に`COMPOSE_FILE=compose.yaml:compose.webpush.yaml`を設定できる。Dockge UIでの適用は未検証のため、この構成の起動・更新はSSHのCLIで行う。明示的な`-f`はこの指定を上書きする。

有効化前に`docker compose --profile '*' config --format json`を`python3 /path/to/source/scripts/check_webpush_compose.py`へパイプし、通知の5項目と秘密鍵の読み取り専用マウントを確認する。出力を絞らないconfigや--environmentはSMTPパスワードなどを含むため共有しない。詳細は[初心者向け手順書の第17章](truenas-beginner-installation-guide.md)と[Docker公式説明](https://docs.docker.com/compose/how-tos/environment-variables/envvars/#compose_file)を参照。

バックアップには基本Compose・通知用Compose・.envをまとめて保管する。複数ファイルを使う場合の本手順のBACKUP_COMPOSE_SHA256は、読み込み順に2ファイルを連結した内容のSHA-256とする。単一ファイル構成とは計算対象が異なることも運用記録へ残す。

## 本人の端末で受信確認

1. 保護者アカウントで施設URLにログインし、「通知設定」を開く。
2. 「この端末で通知を受け取る」を押し、ブラウザーの通知を許可する。権限要求は本人の操作時だけ行う。
3. 「この端末は登録済み」を確認する。画面を開き直した場合は、ブラウザー購読とサーバー上の本人の登録の両方を確認する。
4. 「プッシュ通知を利用する」をオンにして保存する。
5. 「この端末へテスト通知を送る」を押す。本人が今操作している登録端末1台だけに送り、他の登録端末や他の保護者には送らない。60秒に1回、1日10回まで。送信期限は5分。
6. OSの通知表示と、タップして保護者ポータルへ戻れることを確認する。

テスト通知は独立した`push_test`種別で保存する。園児の出欠を変更せず、出欠確認の依頼としても扱わない。業務通知の現在の対象は「出欠確認のお願い」。日次連絡、お知らせ、アンケートへのプッシュ通知追加はこの変更の対象外。

画面の「通知サービスが受け付けました」は端末表示を保証しない。端末からの表示・クリック報告が届くと状態を更新する。Cloudflare Accessの認証が切れていると報告APIが認証画面へ転送されることがあるため、実際の表示・タップでも確認する。既存Accessの保護は解除しない。

iPhone/iPadはiOS/iPadOS 16.4以降でサイトをホーム画面へ追加し、そのアイコンから開いて登録する。[WebKitの説明](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/)

## 配送時の確認

送信直前に、有効なアカウント・資格情報、購読の所有者・環境・状態、受信設定、通知の有効期限を確認する。園児に関する通知では、対象園児との明示的な紐付けが現在もあることを再確認する。明示ログアウト後の端末には配送しない。セッションの期限切れだけでは購読を失効させない。

本番の送信先はブラウザーの通知サービス（FCM、Mozilla、Apple、WNS）に限定し、任意のHTTPSサーバーや内部IPへの購読は受け付けない。送信直前にも確認し、HTTPリダイレクトは追わない。公開鍵・購読鍵の形式も登録時に検証する。

参考: [pywebpush](https://github.com/web-push-libs/pywebpush)、[Mozilla Autopush](https://mozilla-services.github.io/autopush-rs/http.html)、[Apple Web Push](https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers)、[Microsoft WNS](https://learn.microsoft.com/en-us/windows/apps/develop/notifications/push-notifications/wns-overview)。

## 稼働中の環境を変更するとき

現在のイメージと構成、未完了の通知、DB・添付のバックアップを確認してから変更する。未送信の業務通知は有効化後に送信対象となるため、残件は内容を確認して別途扱う。通知を削除して通過させない。

施設固有の接続先・送信元・実行履歴は、公開リポジトリに含めない園内の運用記録へ保存する。構成の準備と実機への反映、端末での受信確認は区別して記録する。
