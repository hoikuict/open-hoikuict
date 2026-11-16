# 自園の4帳票のマニュアルをHPと園の実機に掲載

2026年11月8日、一般職員向けに年案・月案・週案・日案の4記事を公開した。園ではログイン前の「使い方マニュアル」、ログイン後は「指導計画」の「指導計画の書き方を見る」から実機上のコピーを開ける。[HPの目次](https://open.hoikuict.net/manual-guide-preview/#chapter/3)／[園の実機の目次](https://hikarinomori.hoikuict.net/manual-guide-preview/#chapter/3)

- **HP**　公開用 `main` の `30ec93c`。MkDocs strictビルド、Cloudflare Pages、GitHubのテストと依存関係チェックが成功した。[公開コミット](https://github.com/hoikuict/open-hoikuict/commit/30ec93c65eef9b0f0615b0edd6893ece7ff2bc29)
- **実機**　11:48 JSTに光の原保育園で切り替え完了。稼働版 `1d0aadb` を基に、取説一式、静的な取説の配信設定、2つの入口を加えた。[実機用コミット](https://github.com/hoikuict/open-hoikuict/commit/1c4179f1d1617c0a53630c1c411baed1343f1a92)
- **コピーの範囲**　両コミットの `docs/manual-guide-preview/` は同じGitツリー `cfc2d56d62fa34c48904c4a5479fd4550ae56243`。画像・本文を含む183ファイルを実機の配信経路で照合した。各版の更新時にコピーを反映する。既存の仕様資料へのリンクはHPを開く。
- **利用確認**　HPと実機をそれぞれ1366px幅・390px幅で開き、4記事と撮影元の画像34枚の一致、画像拡大、検索、記事間と目次への移動を確認した。園の実機ではHP宛ての通信を遮断したブラウザーでも4記事を読めた。職員側の入口は配備したアプリに架空の職員を設定して確認した。
- **稼働と保全**　アプリとバックアップ・復元ワーカー、接続サービスが稼働。業務データ・添付・スケジュール・マウント・依存パッケージ76件の保持を配備後に確認した。復旧用バックアップは `before-bundled-manual-20261108-r2-1c4179f1d161`。
- **配備中の問題**　初回は改行を変換する旧検査が取説のハッシュ不一致を報告し自動復旧した。再配備は同じ候補イメージを使い、切り替え前と切り替え後に186ファイルをバイト単位で照合した。[発生条件と対処](staff-manual-findings.md#manual-deploy-bytes)
- **全体CI**　実機系統のGitHub Actionsは更新前と同じくLintで停止。変更したPythonファイル `main.py` の指摘は前後とも0件、全体は50件。実機の候補・切替後の検証は別に成功している。[実機用ブランチのCI](https://github.com/hoikuict/open-hoikuict/runs/128604439211)

ローカルの進捗表は既存の4行を更新し、公開資料のリンクも各帳票の手順に変更した。[対象と合意](spec-decisions.md#sd-040)
