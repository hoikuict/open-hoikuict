# 保護者向けプッシュ通知 実機確認ガイド

このガイドは、development環境で保護者向けWeb PushをPC、Android、iPhone/iPadへ実送信し、`accepted`、`shown`、`clicked` を配送Target単位で照合するための手順である。

実機確認が終わるまではPhase 1の受入完了とはしない。productionでは本番保護者認証が未実装のため、Web Push transportを有効化できない。

## 1. 安全上の前提

- `HOIKUICT_ENV=development` でのみ実施する
- development専用のVAPID鍵を使い、productionの鍵と共有しない
- VAPID秘密鍵、Push endpoint、購読鍵、receipt tokenを画面記録、チャット、通常ログへ残さない
- 最初は `capture` で確認し、対象端末が正しいことを確認してから `webpush` へ切り替える
- 通知設定画面で本人が「テスト端末」として登録した端末だけを使う
- 複数人で共有するdevelopment環境では、実施日時と対象のモック保護者を事前に共有する

Service WorkerとPush APIを利用できる、安定したHTTPS originを推奨する。PCで同一端末から確認する場合は、対応ブラウザのlocalhostも利用できる。`HOIKUICT_PUBLIC_ORIGIN` は端末が実際に開くoriginと完全に一致させる。

## 2. VAPID鍵の準備

鍵はリポジトリ外のdevelopment専用ディレクトリで生成する。次はPowerShellの例である。`C:\path\outside-repo` は実際の安全な保存先へ置き換える。

```powershell
New-Item -ItemType Directory C:\path\outside-repo\vapid-dev-20260812
Set-Location C:\path\outside-repo\vapid-dev-20260812
C:\python\open-hoikuict\venv\Scripts\python.exe -m py_vapid --gen
C:\python\open-hoikuict\venv\Scripts\python.exe -m py_vapid --applicationServerKey --private-key .\private_key.pem
```

最後のコマンドが出力するapplication server keyを公開鍵として使う。生成された `private_key.pem` と `public_key.pem` はコミットしない。

リポジトリ直下の `.env` には、実施環境に合わせて次を設定する。

```dotenv
HOIKUICT_ENV=development
HOIKUICT_PUSH_TRANSPORT=capture
HOIKUICT_PUSH_VAPID_PUBLIC_KEY=<application server key>
HOIKUICT_PUSH_VAPID_PRIVATE_KEY=C:\path\outside-repo\vapid-dev-20260812\private_key.pem
HOIKUICT_PUSH_VAPID_SUBJECT=mailto:developer@example.com
HOIKUICT_PUBLIC_ORIGIN=https://<development-origin>
```

`.env` と秘密鍵の取扱いは環境のsecret管理方針に従う。

## 3. アプリの起動と端末登録

1. リポジトリ直下でアプリを起動する。

   ```powershell
   .\venv\Scripts\python.exe -m uvicorn main:app --reload
   ```

2. 対象端末で `HOIKUICT_PUBLIC_ORIGIN` のURLを開き、対象のモック保護者としてログインする。
3. `/parent-portal/push-settings` を開く。
4. iPhone/iPadでは、iOS/iPadOS 16.4以降を使用し、サイトをホーム画面へ追加して、そのホーム画面Webアプリ内で以降の操作を行う。
5. 画面上の明示的な登録操作から通知権限を許可し、現在端末をテスト端末として登録する。
6. 登録済み表示と端末名を確認する。権限を拒否した場合はブラウザまたはOSの設定を直してから再登録する。

通知権限要求は必ず利用者の操作を起点にする。通常のページ表示だけで権限ダイアログを出さない。

## 4. captureによる事前確認

1. `HOIKUICT_PUSH_TRANSPORT=capture` のままアプリを再起動する。
2. 職員側の出欠確認画面から、対象園児について「保護者へ連絡」を実行する。
3. `/dev/push-notifications` を開き、作成された通知、配送、対象Targetを確認する。
4. 通知ID、作成時刻、対象のテスト端末名を記録する。
5. payloadプレビューに園児名、病名、体温、欠席理由などの禁止情報がなく、endpoint、鍵、receipt tokenも表示されていないことを確認する。

対象のモック保護者または端末が想定と違う場合は、実送信へ進まない。

## 5. Web Push実送信

1. アプリを停止し、`.env` の `HOIKUICT_PUSH_TRANSPORT` を `webpush` に変更して再起動する。
2. 起動時の設定検証が成功し、確認画面に `transport: webpush` と警告が表示されることを確認する。
3. 職員側で新しい「保護者へ連絡」を実行する。既存通知と区別できるよう、通知IDと実施時刻を記録する。
4. `/dev/push-notifications` で対象Targetが `accepted` になることを確認する。
5. 対象端末に通知が表示され、同じTargetが `shown` になることを確認する。
6. 通知をクリックし、保護者ポータルの正しい遷移先が開き、同じTargetが `clicked` になることを確認する。

正常時のTarget状態は、概ね次の順で進む。

```text
pending -> processing -> accepted -> shown -> clicked
```

`accepted` はPush Serviceが受理した状態であり、端末表示の保証ではない。表示とクリックはService Workerからのreceiptで記録する。端末がオフラインの場合はreceiptが記録されないことがあるため、通信を復旧して再確認する。

複数端末を登録した場合はTargetを個別に確認する。たとえば端末1が `accepted`、端末2が `retry_wait` の場合、配送集約が `accepted` でも端末2の再試行Targetが残り、後続ワーカーで再試行されることを確認する。

## 6. 端末別チェック表

| 確認項目 | PC対応ブラウザ | Android対応ブラウザ | iPhone/iPadホーム画面Webアプリ |
| --- | --- | --- | --- |
| 権限許可と購読登録 | [ ] | [ ] | [ ] |
| ブラウザを前面に出していない状態で受信 | [ ] | [ ] | [ ] |
| `accepted` と `shown` の区別 | [ ] | [ ] | [ ] |
| クリックで正しい画面へ遷移 | [ ] | [ ] | [ ] |
| `clicked` の記録 | [ ] | [ ] | [ ] |
| 明示ログアウト後に新規配送されない | [ ] | [ ] | [ ] |
| セッション期限切れだけでは購読が維持される | [ ] | [ ] | [ ] |
| 再ログイン後に安全な遷移先へ戻る | [ ] | [ ] | [ ] |

各OS・ブラウザの名称とバージョンも記録する。iPhone/iPadは通常のブラウザタブではなく、ホーム画面から起動したWebアプリで確認する。

## 7. 異常系確認

| 条件 | 期待結果 |
| --- | --- |
| 通知権限を拒否 | 登録できず、設定画面に許可方法が案内される |
| 明示ログアウト | 現在端末の購読が無効になり、以後の新規配送対象にならない |
| セッション期限切れ | 購読は無効化されず、通知受信を継続できる |
| Push Serviceが404 / 410 | Targetは終端失敗、購読は無効化される |
| Push Serviceが429 / 500系 | Targetは `retry_wait` となり、有効期限内で再試行される |
| VAPID鍵またはsubjectが拒否される | `vapid_auth_failed` の終端失敗となり、ERRORログと日次指標で識別できる |
| 通知の有効期限切れ | 送信・再試行されず `expired` になる |

異常系を実サービスで意図的に再現する必要はない。404 / 410、429、500系、401 / 403は自動テストで確認し、実機確認中に発生した場合だけ安全な識別情報で照合する。

## 8. 証跡の残し方

次の項目だけを記録する。

- 実施日時と実施者
- 端末種別、OS、ブラウザと各バージョン
- development origin
- モック保護者を識別できる非機密なテスト用ラベル
- 通知ID、配送ID、Target ID、Attempt ID
- `accepted_at`、`shown_at`、`clicked_at` と内部エラーコード
- 端末別チェック表の結果と再現手順

endpoint、`p256dh`、`auth`、receipt token、VAPID秘密鍵は記録しない。画面キャプチャを残す場合も、これらが含まれていないことを確認する。

## 9. 終了処理

1. `.env` の `HOIKUICT_PUSH_TRANSPORT` を `capture` に戻してアプリを再起動する。
2. `/dev/push-notifications` で `transport: capture` を確認する。
3. 不要になったテスト端末は通知設定画面から解除する。
4. 秘密鍵を一時配置した場合は、組織のsecret保管場所へ移すか、安全に廃棄する。

productionへ設定を転用しない。productionはtransport、HTTPS、鍵、本番保護者認証の起動時検証をすべて通過できる実装になるまで無効のままとする。

## 10. 参考資料

- [Apple: Sending web push notifications in web apps and browsers](https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers)
- [pywebpush](https://github.com/web-push-libs/pywebpush)
