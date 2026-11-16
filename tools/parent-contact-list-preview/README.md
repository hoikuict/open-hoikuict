# 保護者連絡・内容一覧の確認用モック

仕様と未確定事項：`docs/parent-contact-content-list-proposal-2026-09-28.md`。

<http://127.0.0.1:8906/>

```powershell
venv/Scripts/python.exe -m http.server 8906 --bind 127.0.0.1 --directory tools/parent-contact-list-preview
```

`index.html` は生成済みで、そのまま配信できる。外部通信・本番DB・送信処理なし。
「状態を切り替えて試す」で、未入力・入力済み・一部入力・エラーを切り替える。
日付・クラス・表示順は「表示」で反映。名前から詳細を開き、「一覧へ戻る」で閉じる。
日付を変えると架空サンプルの組み合わせが変わる。実在する日々の記録ではない。

既存の配備テンプレートと照合して再生成する場合：

```powershell
venv/Scripts/python.exe -X utf8 tools/parent-contact-list-preview/build.py
```

本番用作業コピーと Jinja2 が必要。配備版f79846c31e36の10ファイルの一致を確認後、静的ページと `baseline.json` を生成する。アプリ・モデル・DB接続はimportしない。

内容一覧と、名前横の丸い頭文字アイコンを削除する修正は本番反映済み（2026-09-28 08:02 JST）。この画面は架空データの確認用モック。名前下のクラス・提出状況・更新日時・提出者は保持する。詳細ダイアログは試用のための表示であり、本実装の既存返信画面を置き換える仕様ではない。
