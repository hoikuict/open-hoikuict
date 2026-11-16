# 健康管理一覧の実機反映（2026-11-16）

[SD-059](spec-decisions.md#sd-059)のモックr2を利用者が採用し、実機反映、これまでの変更のコミット・プッシュ、デモへの適合を依頼した。実機への反映は2026-11-16 10:07:02 JSTに完了した。

## 反映内容

健康管理一覧の中央の余白と行高を減らし、園児・クラス・健康フラグ・アレルギー・最新測定・健診状態・操作の7項目を維持した。720px以上では列幅を配分し、719px以下では園児ごとの一覧に全項目と操作を表示する。健康サマリー、健診記録、条件付きの医療回答確認のリンクを維持する。既存4フィルター、判定、保存、遷移は変更していない。

- 直前版：`67f4d728c51d67a6c6c1da38ea8f10b6f4186b8f`。
- アプリ版：`0cadb5625cd9ee85170ffd22517b0cface46fbb0`、`codex/health-overview-20261116`。
- 対象：`templates/health/overview.html`、`static/css/health-overview.css` の2ファイル。
- イメージ：`sha256:e173520c2f8573eebd569b96df9b762f07bd49a0ee6bcc1917d59d83ab4fc5cc`。
- 配備先：`/mnt/main/open-hoikuict-pilot/releases/health-overview-20261116-0cadb5625cd9`。
- 停止後バックアップ：`/mnt/main/open-hoikuict-pilot/backups/before-health-overview-20261116-0cadb5625cd9`。

## 確認結果

関連24テストが成功。実際の共通メニューを含む架空データの画面を1366・1100・1024・847・768・720・719・390・320pxで確認し、操作リンク33個が画面幅内に収まることを確認した。

実機候補の隔離検証後に切り替え、アプリhealthyとバックアップ・復元worker・公開接続の稼働を確認した。実機のテンプレートを架空データと3権限で描画し、7列・4フィルター・条件付き操作・一部測定・空の一覧を確認した。この描画確認による業務レコードの読み書きは0件。

業務DB、添付14件、設定、バックアップ予約、マウント、依存関係76パッケージ、既存配備履歴を保持。DB移行なし。日案例820件・週案例533件を保持し、バックアップの運用形式1を継続した。独立した事後検証と、公開URLでのCSSハッシュ一致・healthz 200・未ログイン時の303を確認した。

証跡は `.local-dev/health-overview-rollout-20261116/` の `bundle/UPDATE.json`、`latest-status.json`、`completed-verification.json`、`public-verification.json`、`browser-verification.json`。実機の業務データと秘密設定は公開対象に含めない。

main・GitHub・デモへの統合は別工程としてSD-059へ追記する。職員の実利用確認、課題一覧・Excelの更新は未実施。
