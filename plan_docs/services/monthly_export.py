"""Monthly document snapshots: no database writes or persistent export files."""
from __future__ import annotations

from io import BytesIO
from threading import BoundedSemaphore
from typing import Literal
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .monthly_library import field_definitions

EXPORT_GATE = BoundedSemaphore(1)
NO_CACHE = {'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'X-Content-Type-Options': 'nosniff'}


class ExportCell(BaseModel):
    model_config = ConfigDict(extra='forbid')
    body: str = Field(default='', max_length=20000)

    @field_validator('body')
    @classmethod
    def supported_controls(cls, value):
        if any(ord(c) < 32 and c not in '\n\r\t' for c in value):
            raise ValueError('本文に出力できない制御文字が含まれています')
        return value.replace('\r\n', '\n').replace('\r', '\n').replace('\t', '    ')


class ExportInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['pdf', 'xlsx']
    mode: Literal['current', 'saved']
    document_id: int | None = Field(default=None, gt=0)
    lock_version: int = Field(default=0, ge=0)
    classroom_id: int = Field(gt=0)
    target_month: str
    age: int = Field(ge=0, le=5)
    owner_name: str | None = Field(default=None, max_length=100)
    fields: dict[str, ExportCell] | None = None


def export_context(payload, user, repository, classroom, document, sheet):
    """Resolve names/roster on the server; only authorized draft text is accepted."""
    if payload.mode == 'saved':
        if not document or payload.document_id != document.id:
            raise HTTPException(404, '保存済みの月案が見つかりません')
        if payload.fields is not None or payload.owner_name is not None:
            raise HTTPException(422, '保存済みの出力に編集内容は指定できません')
        # _scope may have appended new enrolments; saved means the saved roster.
        sheet = document.monthly_sheet
        owner = document.owner_name
    else:
        if not user.can_edit:
            raise HTTPException(403, '未保存の内容の出力には編集権限が必要です')
        if document and (not document.can_edit_body or payload.document_id != document.id
                         or payload.lock_version != repository.lock_version(document.id)):
            raise HTTPException(409, '月案の状態が変わりました。入力は保持しています。別画面で最新版を確認してください')
        if payload.fields is None or payload.owner_name is None:
            raise HTTPException(422, '出力する本文と担任名を指定してください')
        if set(payload.fields) - field_definitions(sheet, payload.target_month).keys():
            raise HTTPException(422, '帳票に存在しない欄または園児が指定されています')
        sheet = sheet | {'fields': {k: {'body': v.body} for k, v in payload.fields.items()}}
        owner = payload.owner_name
    # Apply the same bounds to saved records, which can predate current validation.
    if len(sheet['children']) > 300 or sum(len(v.get('body', '')) for v in sheet['fields'].values()) > 500000:
        raise HTTPException(422, '出力できる容量を超えています。本文や園児数を確認してください')
    return {'target_month': payload.target_month, 'age': payload.age, 'classroom_name': classroom.name,
            'owner_name': owner, 'sheet': sheet}


def pdf_bytes(layout, fixture=False):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen.canvas import Canvas
    from .monthly_export_layout import FONT
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=landscape(A4))
    canvas.setTitle(layout['title']); canvas.setAuthor('open-hoikuict')
    page_height = landscape(A4)[1]
    for index, page in enumerate(layout['pages'], 1):
        for cell in page['cells']:
            x, top = 28.35 + cell['col'] * layout['width'] / 72, 28.35 + cell['row'] * 6
            width, height = cell['span'] * layout['width'] / 72, cell['height'] * 6
            canvas.setFillColorRGB(*((.94, .95, .94) if cell['style'] == 'label' else (1, 1, 1)))
            canvas.setStrokeColorRGB(.35, .4, .37); canvas.setLineWidth(.6)
            canvas.rect(x, page_height - top - height, width, height, stroke=cell['style'] != 'title', fill=1)
            canvas.setFillColorRGB(.08, .1, .09); canvas.setFont(FONT, cell['font_size'])
            for i, line in enumerate(cell['lines']):
                baseline = page_height - top - cell['font_size'] - (2 if cell['style'] == 'calendar' else 3) - i * cell['leading']
                if cell['style'] in ('label', 'name'):
                    canvas.drawCentredString(x + width / 2, baseline, line)
                else:
                    canvas.drawString(x + 4, baseline, line)
        canvas.setFont(FONT, 8)
        canvas.drawString(28.35, 17, ('操作見本（架空データ）　' if fixture else '') + page['caption'])
        canvas.drawRightString(813.55, 17, f'{index} / {len(layout["pages"])}')
        canvas.showPage()
    canvas.save()
    return stream.getvalue()


def xlsx_bytes(layout, fixture=False):
    import xlsxwriter
    stream = BytesIO()
    workbook = xlsxwriter.Workbook(stream, {'in_memory': True, 'strings_to_formulas': False,
                                          'strings_to_urls': False, 'strings_to_numbers': False})
    formats = {}
    for index, page in enumerate(layout['pages'], 1):
        sheet = workbook.add_worksheet(f'月案{index:02}')
        sheet.hide_gridlines(2)
        sheet.set_default_row(6)
        sheet.set_column_pixels(0, 71, layout['width'] / 72 * 96 / 72)
        sheet.set_paper(9); sheet.set_landscape(); sheet.fit_to_pages(1, 1)
        sheet.set_margins(.39, .39, .39, .39)
        sheet.print_area(0, 0, 84, 71)
        sheet.set_footer(('&L操作見本（架空データ）' if fixture else '') + f'&R{index} / {len(layout["pages"])}')
        for cell in page['cells']:
            key = (cell['style'], cell['font_size'])
            if key not in formats:
                options = {'font_name': 'Meiryo', 'font_size': cell['font_size'], 'font_color': '#18221C',
                           'valign': 'top', 'text_wrap': True,
                           'align': 'center' if cell['style'] in ('label', 'name') else 'left'}
                if cell['style'] != 'title':
                    options.update(border=1, border_color='#617168')
                else:
                    options['bold'] = True
                if cell['style'] == 'label':
                    options['bg_color'] = '#F0F3F1'
                formats[key] = workbook.add_format(options)
            sheet.merge_range(cell['row'], cell['col'], cell['row'] + cell['height'] - 1,
                              cell['col'] + cell['span'] - 1, '\n'.join(cell['lines']), formats[key])
    workbook.close()
    return stream.getvalue()


def render_export(context, kind, mode, fixture=False, pdf_attachment=False, download_snapshot='', csrf_token=''):
    if not EXPORT_GATE.acquire(blocking=False):
        raise HTTPException(429, '別の帳票を出力中です。少し待ってからもう一度お試しください', headers={'Retry-After': '3'})
    try:
        from .monthly_export_layout import make_layout
        layout = make_layout(context)
        filename = f"{context['target_month']}_{context['age']}歳児_月案.{kind}"
        if kind == 'xlsx':
            return Response(xlsx_bytes(layout, fixture), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            headers=NO_CACHE | {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename)})
        if pdf_attachment:
            return Response(pdf_bytes(layout, fixture), media_type='application/pdf',
                            headers=NO_CACHE | {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename)})
        env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[2] / 'templates/plan_docs/monthly_library'),
                          autoescape=select_autoescape(['html']))
        html = env.get_template('print.html').render(layout=layout, mode=mode, fixture=fixture,
            download_snapshot=download_snapshot, csrf_token=csrf_token)
        return JSONResponse({'pages': len(layout['pages']), 'html': html}, headers=NO_CACHE)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (OSError, ImportError) as exc:
        raise HTTPException(503, '出力に必要なファイルを読み込めません。入力は保持されています') from exc
    finally:
        EXPORT_GATE.release()
