# ローカルβの対話導入アプリ

2026-09-22、3画面のモックを確認後の「実際にためそう」に基づく実装。
利用者向けの説明は [かんたん導入](../docs/beta-quickstart.md)。

2026-09-23、GitHubから検証済みの最新版を取得する変更を実装し、Windows実行ファイルの導入・ログイン・再起動まで検証済み。[v2026.9.23.1を公開済み](https://github.com/hoikuict/open-hoikuict/releases/tag/v2026.9.23.1)。現在のビルド手順・配布物・検証結果は [変更記録](../docs/github-installer-2026-09-23.md) を参照。以下のビルド手順と2026-09-22の結果は従来の同梱版の記録。

## 構成と状態

- `launcher.py`：同梱ランタイム不要で開けるPyInstaller実行ファイルの入口。
- `server.py` / `ui/`：localhost限定の操作画面。起動ごとのランダムトークン、Host・Origin・JSON検査を使用。
- `core.py`：配布ファイル検査、既存先の保護、準備用フォルダーへの展開、確定、起動・停止。
- `runtime.py`：同梱Pythonで動くアプリ側処理。既存の管理者作成・有効化・パスワードポリシーを使用。
- `releases.py`：公開済みの最新版の選択、互換性確認、確認した版の固定、HTTPS取得とサイズ・ハッシュの照合。

「準備をはじめる」までは管理者を作らない。確定前に新規フォルダーで起動を確認する。失敗・中断時に削除するのは、この試行が作ったランダム名の準備用フォルダーのみ。既存環境には更新・再作成をしない。

パスワードと有効化コードはログ・引数・平文ファイルへ出さない。ブラウザーとワーカーのメモリー内で扱い、DBへは既存認証のハッシュを保存する。設定の秘密鍵は初回だけ生成する。`.env` の空の停止用ファイルを配置し、親ディレクトリの開発・本番設定を誤って読み込ませない。

`app/` 以下にDB・設定・添付・文例をまとめる。ランタイムは `runtime/`。今回の試用ビルドでは同一ユーザーの書込可能フォルダーへ導入する。

## ビルド

対象OSごとに、再配置可能なPython 3.12ランタイムを用意する。Windows試作は uv 0.12.17 が取得した python-build-standalone の Python 3.12.14 x64 を使用。

1. 同じPython 3.12からビルド用venvを作り、`requirements.txt` と `pyinstaller==6.22.0` を導入する。配布物に含む各パッケージの版は `bundle.json` に記録する。
2. リポジトリ直下で以下を実行する。`<...>` は実際の絶対パスに置き換える。

```text
python -m PyInstaller --noconfirm --onefile --windowed --name OpenHoikuICT --paths <repo> --add-data <repo>/beta_setup/ui:beta_setup/ui --distpath <launcher-output> --workpath <build-work> --specpath <spec-output> beta_setup/launcher.py
python scripts/build_beta_bundle.py --runtime <portable-python> --site-packages <build-venv-site-packages> --launcher <launcher-output>/OpenHoikuICT.exe --output <new-bundle-folder>
```

Linuxではランチャー名を `OpenHoikuICT` にする。Pythonの実行ファイルを `runtime/bin/python3`、ライブラリを `runtime/lib/python3.12/site-packages` に配置する構成。Ubuntu 24.04 LTS上で別にビルドと検証が必要。

3. `scripts/verify_beta_bundle.py --bundle <new-bundle-folder> --workspace <isolated-test-folder>` で検証する。
4. 配布フォルダー全体をZIPへまとめる。ランチャーだけを渡さない。`payload.zip`、`bundle.json`、案内文も同梱する。

ソース選択は `git ls-files` のアプリ・テンプレート・静的ファイル・配布文例DBの許可リストと明示したワーカーだけ。未追跡の業務データや `.env`、ローカル環境を取り込まない。追跡ファイルはビルド時の内容を使い、各ファイルとZIPのSHA-256を記録する。コミットIDだけで未コミットの差分まで表すものではない。

SHA-256検査は展開時の破損検知用。配布元の認証・署名を代替しない。署名済み配布、更新、OS自動起動、Linux実機、施設公開は今回の試作範囲に含めない。

## 検証

```text
python -m unittest test_beta_setup -v
python -m ruff check beta_setup scripts/build_beta_bundle.py scripts/verify_beta_bundle.py test_beta_setup.py
node --check beta_setup/ui/wizard.js
python scripts/verify_beta_bundle.py --bundle <bundle> --workspace <isolated-test-folder>
```

ユニットテストは業務アプリをimportしない。実行ファイルの検証はUUID名の新規環境に架空の管理者とクラスを作り、失敗時の巻戻し、ログイン、保存、停止、導入先の実行ファイルからの再起動を確認する。生成したテストパスワードは表示・保存しない。

### Windows実機の結果（2026-09-22）

- Windows 11 x64 / 同梱Python 3.12.14で導入・起動を確認。導入にはネットワークからのパッケージ取得を使わない。
- 最終の実行ファイルで、初期管理者作成、実HTTPログイン、healthz、クラスの登録、停止、導入先へコピーした実行ファイルからの再起動、再ログイン、クラスの保持を確認した。検証スクリプトは終了コード0。
- 固定鍵の保持、監査1件、Argon2ハッシュ、有効化コードの使用済み状態、園児・家庭のデモデータ混入なしを確認。
- 弱いパスワードでの失敗・展開途中での中断・準備用フォルダーの片付けは別の実行ファイル試験で確認。最終試験は `--skip-weak-password` でこの確認済みケースを省略した。
- 境界テスト8件、Ruff、JavaScript構文、MkDocsビルドが成功。二重に実行ファイルを開いてもセッションが増えないことを確認した。
- 実画面で準備→管理者、未入力欄への案内、戻る・中断後の入力保持、通常幅・390px幅の表示を確認。利用者のパスワードは未入力で引き渡した。
- 配布物：`dist/OpenHoikuICT-Windows-beta.zip`、83,781,419 bytes。SHA-256：`e2ffec1ccb5c53390014c0b95dd097f5c7d534316f876ab4c5d13f2a511bf04e`。
- 新規のWindows PC、OS再起動、Linux実機、全業務機能の受入試験は未実施。今回は専用フォルダーへのローカル試用ビルド。

## 制約

- 本体の業務画面はCDN資産を参照する。完全オフラインでの画面動作は対象外。
- ブラウザーを閉じてもコントローラーは動作し続ける。「アプリを停止して終了する」で自身が起動した子プロセスを止める。
- セッションURLはローカル操作権限を含む。共有・ログ記録しない。
- サーバーや管理者権限は不要。通常ユーザーの専用ローカルディレクトリを選ぶ。
