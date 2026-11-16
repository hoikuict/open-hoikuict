# 要確認の集計範囲のモック

起動：リポジトリルートで `venv/Scripts/python.exe tools/attention-scope-preview/server.py`。

URL：<http://127.0.0.1:8924/?assigned=4>

- ユーザー確認済み：役割にかかわらず担当全クラスを集計。出欠未入力も含める。
- ホームの担当／全クラス切替、要確認一覧への移動を試せる。
- 配備記録のコミットをGitから読み、架空データでテンプレートを描画する。
- DB・アプリ本体の読み込みなし。ループバック限定、GETのみ。業務リンクは外部へ遷移しない。
- 未入力・一部入力・入力済み・エラー、担当6・4・3・0クラス、管理者・一般職員を切替可能。
- 集計対象の説明とエラー表示はモックで確認する案。本実装・本番配備は未実施。

現行版の不一致再現：`venv/Scripts/python.exe tools/attention-scope-preview/reproduce.py`。
これはモックサーバーとは独立した検証で、配備版ルーターとメモリー内の架空DBのみを使う。
詳しい整理は `docs/attention-scope-proposal-2026-09-28.md`。
