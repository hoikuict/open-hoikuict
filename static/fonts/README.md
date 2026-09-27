# 月案出力用フォント

Noto Sans JP。SIL Open Font License 1.1（同梱 `NotoSansJP-OFL.txt`）。
公式配布元: https://github.com/google/fonts/tree/main/ofl/notosansjp

2026-09-27に公式の可変TTFを取得し、fonttools 4.62.1 の
`instantiateVariableFont(font, {'wght': 400})` でRegularの静的TTFにした。
予約名のSourceはフォント名として使用していない。

- 元TTF SHA256: `c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f`
- 同梱TTF SHA256: `584a19d5d35eeae3114226f526a914496ada9a68fb0bfa43982dcef9bf825fd9`

PDFでは必要な字形だけを埋め込み、印刷確認画面では同じフォントをローカル配信する。
外部のフォントサーバーへの問い合わせはしない。ExcelのセルはMeiryoを指定する。
