"""Bounded A4 landscape layout shared by PDF, print preview and Excel."""
import calendar
import math
from datetime import date
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_PATH = Path(__file__).resolve().parents[2] / 'static/fonts/NotoSansJP-Regular.ttf'
FONT = 'MonthlyNotoSansJP'
pdfmetrics.registerFont(TTFont(FONT, str(FONT_PATH)))
MAX_PAGES = 100
WIDTH, UNIT, ROWS, SIZE, LEADING = 785.2, 6, 85, 9.5, 12
COL = WIDTH / 72
PERSONAL = [('life', '生活・健康\n食事・睡眠・排泄・清潔'), ('play', 'あそび\nあそび・ことば'),
            ('help', '環境構成・援助活動'), ('review', '評価・反省')]
DOMAINS = [('care', '生命・情緒'), ('health', '健康'), ('relations', '人間関係'),
           ('nature', '環境'), ('language', '言葉'), ('expression', '表現')]
COLUMNS = [('goal', 'ねらい'), ('environment', '環境設定'), ('expected', '予想される子どもの姿'), ('support', '配慮事項')]


def wrapped(text, span):
    """(original slice, displayed line); concatenating slices preserves every char."""
    width = span * COL - 9
    result, raw, display = [], '', ''
    for char in text:
        if char == '\n':
            result.append((raw + char, display)); raw = display = ''
        elif display and pdfmetrics.stringWidth(display + char, FONT, SIZE) > width:
            if char in '、。，．！？)]）］｝」』】〉》' or display[-1] in '([（［｛「『【〈《':
                last = display[-1]
                if len(display) > 1:
                    result.append((raw[:-1], display[:-1])); raw = display = last + char
                else:
                    result.append((raw, display)); raw = display = char
            else:
                result.append((raw, display)); raw = display = char
        else:
            raw += char; display += char
    if raw or not result or text.endswith('\n'):
        result.append((raw, display))
    return result


def chunks(text, span, lines=12):
    all_lines = wrapped(text, span)
    return [''.join(raw for raw, _ in all_lines[i:i + lines]) for i in range(0, len(all_lines), lines)]


class Layout:
    def __init__(self, context):
        self.context = context
        self.fields = context['sheet']['fields']
        self.pages = []

    def body(self, key):
        return self.fields.get(key, {}).get('body', '')

    def cell(self, page, row, col, height, span, text='', style='body', key=None, part=0):
        assert row >= 0 and row + height <= ROWS and col + span <= 72
        lines = [line for _, line in wrapped(text, span)]
        leading, size, padding = (10, 8.5, 2) if style == 'calendar' else (16, 13, 6) if style == 'title' else (LEADING, SIZE, 6)
        assert len(lines) * leading + padding <= height * UNIT + .1, (key, text, height)
        page['cells'].append({'row': row, 'col': col, 'height': height, 'span': span,
                              'text': text, 'lines': lines, 'style': style, 'key': key, 'part': part,
                              'font_size': size, 'leading': leading})

    def height(self, values, spans, minimum=7):
        return max(minimum, max(len(wrapped(text, span)) * 2 + 1 for text, span in zip(values, spans)))

    def new_page(self, caption=''):
        if len(self.pages) >= MAX_PAGES:
            raise ValueError('出力が100ページを超えます。本文の量を確認してください。')
        c = self.context
        page = {'cells': [], 'caption': caption}
        self.pages.append(page)
        title = f"{c['target_month']}　{c['age']}歳児　" + ('乳児指導計画' if c['age'] < 3 else '月指導計画')
        self.cell(page, 0, 0, 4, 72, title, 'title')
        labels = [('クラス：' + c['classroom_name'], 0, 22), ('担任：' + c['owner_name'], 22, 28),
                  ('園長印：', 50, 11), ('主任印：', 61, 11)]
        height = self.height([v for v, _, _ in labels], [s for _, _, s in labels], 5)
        for text, col, span in labels:
            self.cell(page, 4, col, height, span, text, 'meta')
        return page, 4 + height

    def personal(self):
        common_keys = ['common:goal', 'common:home', 'common:review']
        common_labels = ['ねらい', '家庭との連携', '評価・反省']
        common = [self.body(k) for k in common_keys]
        separate_common = max(len(wrapped(t, 24)) for t in common) > 8
        split_common = [chunks(t, 24, 32) for t in common]
        common_parts = max(map(len, split_common))
        separate_events = len(wrapped(self.body('common:events'), 64)) > 6
        events = chunks(self.body('common:events'), 64, 32 if separate_events else 6)
        # Long class-wide text is printed in complete continuation blocks first.
        if separate_common:
            for part in range(common_parts):
                p, y = self.new_page('クラス共通欄' + ('（続き）' if part else ''))
                values = [v[part] if part < len(v) else '' for v in split_common]
                for i, label in enumerate(common_labels):
                    self.cell(p, y, i * 24, 3, 24, label + ('（続き）' if part else ''), 'label')
                h = self.height(values, [24] * 3)
                for i, text in enumerate(values):
                    self.cell(p, y + 3, i * 24, h, 24, text, key=common_keys[i], part=part)
        if separate_events:
            for part, text in enumerate(events):
                title = '行事' + ('（続き）' if part else '')
                p, y = self.new_page(title)
                self.cell(p, y, 0, 3, 72, title, 'label')
                self.cell(p, y + 3, 0, self.height([text], [72]), 72, text, key='common:events', part=part)

        def start():
            p, y = self.new_page()
            if not separate_events:
                event_h = self.height([events[0]], [64], 5)
                self.cell(p, y, 0, event_h, 8, '行事', 'label')
                self.cell(p, y, 8, event_h, 64, events[0], key='common:events')
                y += event_h
            if not separate_common:
                for i, label in enumerate(common_labels):
                    self.cell(p, y, i * 24, 3, 24, label, 'label')
                y += 3
                h = self.height(common, [24] * 3)
                for i, text in enumerate(common):
                    self.cell(p, y, i * 24, h, 24, text, key=common_keys[i])
                y += h
            self.cell(p, y, 0, 7, 9, '名前', 'label')
            self.cell(p, y, 9, 3, 31, '個人別保育計画', 'label')
            self.cell(p, y + 3, 9, 4, 16, '生活・健康', 'label')
            self.cell(p, y + 3, 25, 4, 15, 'あそび', 'label')
            self.cell(p, y, 40, 7, 16, '環境構成・援助活動', 'label')
            self.cell(p, y, 56, 7, 16, '評価・反省', 'label')
            return p, y + 7

        p, y = start()
        lines_per_child = max(4, (ROWS - y - 3) // 2)
        count = 0
        limit = 6 if self.context['age'] == 0 else 7
        spans, cols = [16, 15, 16, 16], [9, 25, 40, 56]
        children = self.context['sheet']['children']
        for child in children:
            keys = [child['ref'] + ':' + k for k, _ in PERSONAL]
            parts = [chunks(self.body(k), span, lines_per_child) for k, span in zip(keys, spans)]
            for part in range(max(map(len, parts))):
                values = [v[part] if part < len(v) else '' for v in parts]
                birth = date.fromisoformat(child['birth_date'])
                target = date.fromisoformat(self.context['target_month'] + '-01')
                months = max(0, (target.year - birth.year) * 12 + target.month - birth.month - (birth.day > 1))
                name = child['name'] + f'\n{months // 12}歳{months % 12}か月' + ('\n（続き）' if part else '')
                h = self.height([name] + values, [9] + spans, 7)
                if y + h > ROWS or count >= limit:
                    p, y = start(); count = 0
                self.cell(p, y, 0, h, 9, name, 'name')
                for key, text, col, span in zip(keys, values, cols, spans):
                    self.cell(p, y, col, h, span, text, key=key, part=part)
                y += h; count += 1
        if not children:
            self.cell(p, y, 0, 7, 72, '対象園児はいません。', 'name')

    def group(self):
        left, right = [], []
        common_keys = ['common:goal', 'common:home']
        vals = [chunks(self.body(k), 27, 6) for k in common_keys]
        for part in range(max(map(len, vals))):
            left.append({'labels': [(0, 27, '今月のねらい'), (27, 27, '家庭との連携')],
                         'values': [(i * 27, 27, v[part] if part < len(v) else '', common_keys[i], part) for i, v in enumerate(vals)]})
        for domain, label in DOMAINS:
            keys = [f'group:{domain}:{key}' for key, _ in COLUMNS]
            vals = [chunks(self.body(k), 12, 12) for k in keys]
            for part in range(max(map(len, vals))):
                left.append({'domain': label + ('（続き）' if part else ''), 'section': '養護' if domain == 'care' else '教育',
                             'values': [(6 + i * 12, 12, v[part] if part < len(v) else '', keys[i], part) for i, v in enumerate(vals)]})
        for key, label in [('group:food', '食育'), ('common:review', '評価・反省')]:
            for part, text in enumerate(chunks(self.body(key), 48, 12)):
                left.append({'wide': label + ('（続き）' if part else ''), 'values': [(6, 48, text, key, part)]})
        year, month = map(int, self.context['target_month'].split('-'))
        for day in range(1, calendar.monthrange(year, month)[1] + 1):
            key = f'event:{day}'
            for part, text in enumerate(chunks(self.body(key), 14, 12)):
                right.append((str(day) + ('続' if part else ''), '月火水木金土日'[date(year, month, day).weekday()], text, key, part))

        while left or right:
            p, y = self.new_page()
            ly = ry = y
            self.cell(p, ry, 54, 4, 2, '日', 'label')
            self.cell(p, ry, 56, 4, 2, '曜', 'label')
            self.cell(p, ry, 58, 4, 14, '行事・活動', 'label'); ry += 4
            while right:
                day, week, text, key, part = right[0]
                h = max(2, math.ceil((max(len(wrapped(day, 2)), len(wrapped(text, 14))) * 10 + 2) / UNIT))
                if ry + h > ROWS:
                    break
                self.cell(p, ry, 54, h, 2, day, 'calendar')
                self.cell(p, ry, 56, h, 2, week, 'calendar')
                self.cell(p, ry, 58, h, 14, text, 'calendar', key=key, part=part)
                ry += h; right.pop(0)
            domain_heading = False
            while left:
                block = left[0]
                values = block['values']
                texts, spans = [v[2] for v in values], [v[1] for v in values]
                h = self.height(texts, spans, 6)
                if 'domain' in block:
                    h = max(h, self.height([block['section'] + '\n' + block['domain']], [6], 6))
                if 'wide' in block:
                    h = max(h, self.height([block['wide']], [6], 6))
                extra = 3 if 'labels' in block else 5 if 'domain' in block and not domain_heading else 0
                if ly + extra + h > ROWS:
                    break
                if 'labels' in block:
                    for col, span, text in block['labels']:
                        self.cell(p, ly, col, 3, span, text, 'label')
                    ly += 3
                elif 'domain' in block:
                    if not domain_heading:
                        self.cell(p, ly, 0, 5, 6, '領域', 'label')
                        for i, (_, text) in enumerate(COLUMNS):
                            self.cell(p, ly, 6 + i * 12, 5, 12, text, 'label')
                        ly += 5; domain_heading = True
                    self.cell(p, ly, 0, h, 6, block['section'] + '\n' + block['domain'], 'label')
                else:
                    self.cell(p, ly, 0, h, 6, block['wide'], 'label')
                for col, span, text, key, part in values:
                    self.cell(p, ly, col, h, span, text, key=key, part=part)
                ly += h; left.pop(0)

    def build(self):
        if self.context['age'] < 3:
            self.personal()
        else:
            self.group()
        return {'width': WIDTH, 'row_height': UNIT, 'rows': ROWS, 'columns': 72,
                'font_size': SIZE, 'leading': LEADING, 'pages': self.pages,
                'title': self.context['target_month'] + ' 月案'}


def make_layout(context):
    return Layout(context).build()
