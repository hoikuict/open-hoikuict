# 2026-11-23 マニュアル4項目の更新

SD-069の照合に続く本文・画像の更新。合意と状態はSD-070を参照。

- `fixture.py` は保存済み配備系列のテストから架空DBを作り、localhostの8171/8172で画面を表示する。本番起動コードや本番DBは使わない。`MANUAL_SOURCE` で対象版のチェックアウトを指定できる。
- `capture.cjs parent` → `capture.cjs medical` の順で保護者・職員の画像を撮る。別のbilling fixtureで `capture.cjs billing` を実行する。撮り直すときはfixtureを再起動し、空のDBから順番に行う。
- `build.py` は更新対象の記事・画像参照と3本の職員向け手順を作成する。ほかの手順は再生成しない。Nodeのバンドル位置が異なる環境ではnodeパスを合わせる。
- `verify.cjs` は9画面を1366/390/320pxで検査する。引数に公開ガイドのベースURLを渡せば同じ内容を公開後にも確認できる。
- NodeのPlaywrightはCodexのバンドルを使用する。ライブラリの参照先は実行環境に合わせる。元画像は `docs/manual-guide-preview/assets/r2-*.jpg`、検証出力はGit管理外の `.local-dev/manual-refresh-20261123/`。

初期のマニュアル一括出力ツールを使う場合は、この更新を含めた最新記事・画像を保持する。初期の見本データだけで更新済みの記事を上書きしない。
