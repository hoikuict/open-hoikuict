# GitHubの検証済み最新版を取得するインストーラー

2026-09-23。ユーザーの「その方式に合わせたインストーラーを作って」に基づく変更。操作モックを試した後、「この流れで実装を進める」と回答済み。

## 要望と対象

- 要望：新しいPCへ導入する際、GitHubから検証済みの最新版を取得する。
- 対象：既存のWindows 11 x64向けローカル試用を引き継ぐ。Git・Pythonの個別導入は不要。管理者の名前・メール・パスワード・確認、および保存場所・ポート・ログインID・作成理由・実行者・承認者を保持。
- 通常の本体更新は配布版の更新で対応する。導入済み環境は保存した版を起動する。既存環境の上書き更新、園内公開設定、Linux実行ファイルは今回の対象に含めない。
- 基準となる業務アプリ：本番配備済み `06951a6eed379536e1791d4abdcf775ecd799a99`。保護者の停止・再開、初期台帳、家庭アーカイブ、復元等を含む。開発中main全体で置き換えない。

## 合意した操作

1. 新規導入画面を開くと最新版を確認する。公開版・OS・導入アプリとの互換性を確認できるまで進めない。
2. 版番号、取得元、ダウンロードサイズと変更内容を表示する。管理者情報を入力し、確認画面へ進む。
3. 「ダウンロードして準備」で表示中の版を取得し、検証、展開、設定・管理者作成、起動確認を行う。初回情報を入力しただけでは保存しない。
4. 確認後に配布版が変わった場合は新しい版を表示して再確認する。版の一致にはrelease IDとasset ID・サイズ・SHA-256を含める。
5. 通信失敗は入力を保持して再試行できる。未公開・非対応OS・古い導入アプリ・配布ファイルの不一致を分けて案内する。
6. 中断時はこの試行が作った準備フォルダーだけを片付ける。既存環境やデータは変更しない。完了後は保存先の実行ファイルから起動する。

モック：`tools/github-installer-preview/`、`http://127.0.0.1:18847/`。版番号・通信・導入処理は架空で、DB・外部通信・保存処理に接続しない。

## 配布の仕様

配布元は既存の公開リポジトリ `hoikuict/open-hoikuict` に固定する。2026-09-23のAPI確認では公開リポジトリでpush権限があり、Release一覧は空だった。最初の配布版を作る必要がある。

- 最新版の取得：GitHub REST APIの `/repos/hoikuict/open-hoikuict/releases/latest`。公開済みでdraft・prereleaseでない版を使う。
- 添付：`OpenHoikuICT.exe`、`OpenHoikuICT-windows-x64.json`、`OpenHoikuICT-windows-x64.zip`。
- JSON：本体のcommit、OS・アーキテクチャ、導入／起動プロトコル、ZIPのサイズ・SHA-256、全ファイルのSHA-256。
- HTTPSのGitHubと配布CDNだけへ接続する。利用者にGitHub認証やトークンの入力を求めない。
- GitHub APIのasset digestでJSONを検証し、JSONとAPIが示すZIPのサイズ・ハッシュが一致する場合だけ取得する。取得したZIPと展開ファイルも照合する。
- 配布用ビルドは変更がコミット済みの専用ソースから作る。未追跡の新機能が欠落するビルドや、未コミットの差分を含む配布を拒否する。

GitHubの公式仕様：[Releases API](https://docs.github.com/en/rest/releases/releases)、[Release assets API](https://docs.github.com/en/rest/releases/assets)。

## 検証と結果

境界テスト17件、Ruff、JavaScript構文の確認が成功。Windowsの長い保存先で展開が止まるケースを修正し、配布ファイル一覧から準備中のパス長を事前検査する。標準の保存先を使えばWindows全体の長いパス設定を変更する必要はない。

実行ファイルのビルド・新規導入を検証中。配布版の公開と実ダウンロード試験の結果は完了後に追記する。

## 配布版を作る手順

本番機能を含む専用チェックアウトで、変更をコミットしてから次を実行する。各パスは絶対パスで指定する。検証先には階層の浅い専用フォルダーを選ぶ。

```powershell
./scripts/build_windows_installer.ps1 -Runtime <Python3.12-x64> -BuildPython <build-venv/python.exe> -SitePackages <build-venv/Lib/site-packages> -Output <new-output> -VerificationWorkspace <short-test-folder> -ReleaseTag v2026.9.23.1
```

このコマンドは境界テスト、実行ファイル・配布データの生成、架空の管理者での実導入・ログイン・再起動を順に行い、失敗した場合は止まる。全て成功した後に3点の添付ファイルをReleaseへ登録し、アップロード後のdigestを照合してから公開する。

公開後には、生成した実行ファイルを使って実際の取得元から導入する。

```text
python scripts/verify_beta_bundle.py --bundle <output/bundle> --workspace <short-test-folder> --online --skip-weak-password
```
