# 職員のQR付き案内・確認用モック

版：STAFF-PRINT-MOCK-001、2026-11-01 JST。本体未実装・未配備。

`index.html` をブラウザーで開くか、このフォルダーだけを静的配信します。

```powershell
python -m http.server 8898 --bind 127.0.0.1 --directory tools/staff-auth-print-preview
```

`http://127.0.0.1:8898/` を開き、初回設定・再設定、発行前後・本人入力、未入力・一部入力・エラー・期限切れを切り替えてください。「QR付き案内を印刷」でA4の印刷プレビューが出ます。実際の職員やパスワードを入力しないでください。

QRは架空URLです。「QRの先の画面を試す」で本人の画面を確認します。コードは初回 `H7K3MP`、再設定 `R9T4NW`。発行時刻を2026-11-01 10:00に固定し、認証・保存・メール送信は再現表示だけです。

基準ソースとハッシュは `baseline.json`。操作検証は `verification.json`、PDFは `../../output/pdf/staff-activate-handout-preview.pdf` と `../../output/pdf/staff-reset-handout-preview.pdf`。対象範囲と未確定事項は `../../docs/staff-auth-print-proposal-2026-11-01.md`、決定記録は `../../docs/spec-decisions.md` のSD-004を参照してください。

再生成：`tools/build_staff_auth_print_preview.py`。操作確認：`tools/verify_staff_auth_print_preview.cjs`（このPCのPlaywright実行環境と上記静的サーバーを使用）。Tailwindは既存のローカルキャッシュをコピーし、実行時にCDNへアクセスしません。
