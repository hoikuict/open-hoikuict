# 原本の帳票に合わせた月案の操作見本

2026-09-27。`hoiku-plan-docs` で調整した最新の見本を、open-hoikuictへの引き継ぎ用に保存した。旧 `tools/monthly-library-preview/` と異なり、原本の個人別・集団様式、食育1枠、セル内編集、キーワード検索、過去3か月表示、帳票の縦横維持を反映している。

## ファイル

- `monthly-plan-drive-sheet.html`：編集元のHTML断片（CSS・JavaScriptを含む）。
- `index.html`：ブラウザーで確認するための単独表示用ファイル。編集元から生成したもの。
- [引き継ぎ資料](../../docs/handoff-monthly-library-to-open-hoikuict-2026-09-27.md)。
- [詳細仕様・原本セル対応・DB調査結果](../../docs/monthly-library-layout-requirements-2026-09-27.md)。

## 確認方法

open-hoikuictのルートで実行する。

```powershell
python -m http.server 8894 --bind 127.0.0.1 --directory tools/monthly-library-sheet-preview
```

ブラウザーで <http://127.0.0.1:8894/> を開く。終了はCtrl+C。Pythonが別の環境にある場合は実行ファイルを読み替える。引き継ぎ時点で常駐サーバーは起動していない。

1. 年齢を0〜2歳にし、園児とセルを選ぶ。候補を選択し、そのままセル内で修正・Backspace削除する。
2. 候補一覧でキーワード検索を試す。原文／AI提案の切り替えと出典を確認する。
3. 「過去3か月を表示」を開く。月は縦の行、4項目は元の帳票と同じ横の列で、今月の入力欄とも位置が揃う。
4. 園児A/B/Cを切り替える。園児Bは8月欠損、園児Cは全月記録なし。閉じると通常の園児一覧へ戻り、入力は保持される。
5. 3〜5歳へ切り替え、集団様式と食育1枠を確認する。
6. 狭い画面でも項目の縦横は変わらず、帳票部分を左右にスクロールできることを確認する。

## 動作範囲

- 2026年10月固定。園児・文例・AI提案・過去履歴は架空データ。
- DB・Drive・AI・本体の保存APIには接続しない。アプリ本体をimportしない。
- 単独表示用ファイルは、このブラウザー内に見本の入力状態を保持する。実データは入力しない。
- キーワード検索は見本内の固定候補が対象。`getsuan.sqlite` 全体を検索する実装ではない。
- `window.openai.widgetState` / `setWidgetState` は見本の状態保持に使用し、単独表示用ファイルには代替処理がある。
- 見本は本体の認証・保存・権限を備えた業務画面ではない。既存の業務項目を削除する根拠にも使わない。

再生成する場合、このPCでは次のスクリプトが利用できる。

```powershell
python C:/Users/katet/.codex/plugins/cache/openai-bundled/visualize/1.0.41/skills/visualize/scripts/render.py tools/monthly-library-sheet-preview/monthly-plan-drive-sheet.html tools/monthly-library-sheet-preview/index.html --force
```

これは作成時の環境のパス。他PCでの閲覧にこのスクリプトは不要。再生成環境がない場合も、同梱の `index.html` をそのまま確認できる。
