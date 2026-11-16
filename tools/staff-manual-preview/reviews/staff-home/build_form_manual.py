"""Prepare the four reviewed, illustrated articles for the staff manual."""
from html import escape
from pathlib import Path
import re
from shutil import copyfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "plan-forms"
DEST = HERE.parents[3] / "docs/manual-guide-preview/plans"
FORMS = {
    "annual": ("年案", "年案を引き継いで書く"),
    "monthly": ("月案", "月案を書く・印刷する"),
    "weekly": ("週案", "週案を書く"),
    "daily": ("日案・文例・振返り", "日案を書く・文例を使う・振り返る"),
}
IMAGE_NAMES = {
    "monthly-save.jpg": "monthly-save-review.jpg",
    "weekly-save.jpg": "weekly-save-review.jpg",
}

for slug, (label, title) in FORMS.items():
    article = (SOURCE / f"{slug}.html").read_text(encoding="utf-8")
    body = article[article.index('<p class="intro">'):article.index('<nav class="foot"')]
    body = re.sub(r'<p><a href="daily-findings\.html">[^<]+</a></p>', '', body)
    folder = DEST / slug
    folder.mkdir(exist_ok=True)
    for image in re.findall(r'<img src="([^"]+)"', body):
        assert re.fullmatch(rf"{slug}-[a-z-]+\.jpg", image)
        published_image = IMAGE_NAMES.get(image, image)
        copyfile(SOURCE / image, folder / published_image)
        body = body.replace(f'"{image}"', f'"{published_image}"')
    nav = []
    for key, (name, _) in FORMS.items():
        current = ' aria-current="page"' if key == slug else ''
        nav.append(f'<a href="../{key}/"{current}>{escape(name)}</a>')
    html = f'''<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,follow">
  <title>{title}｜職員用マニュアル</title>
  <link rel="stylesheet" href="../style.css"><link rel="stylesheet" href="../forms.css">
</head>
<body><main id="top">
  <header><a href="../../#home">職員用マニュアル</a><a href="../../#chapter/3">指導計画の目次</a></header>
  <nav class="pages" aria-label="帳票別の手順">{' '.join(nav)}</nav>
  <h1>{title}</h1>
  {body}
  <nav class="foot" aria-label="ページ移動"><a href="../../#chapter/3">指導計画の目次へ</a><a href="#top">このページの先頭へ</a></nav>
</main></body></html>
'''
    (folder / 'index.html').write_text('\n'.join(line.rstrip() for line in html.splitlines()) + '\n', encoding='utf-8')
copyfile(SOURCE / 'forms.css', DEST / 'forms.css')
