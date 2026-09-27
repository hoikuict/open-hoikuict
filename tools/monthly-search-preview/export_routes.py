"""Local-only output preview; exports a snapshot without saving the monthly plan."""
import asyncio
from datetime import date
import json
from pathlib import Path
import subprocess
import uuid
from typing import Literal

from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
PYTHON = Path('C:/Users/katet/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')


class Body(BaseModel):
    body: str = Field(default='', max_length=20000)


class ChildSnapshot(BaseModel):
    ref: str = Field(pattern=r'^child:\d+$')
    name: str = Field(max_length=100)
    birth_date: date


class SheetSnapshot(BaseModel):
    children: list[ChildSnapshot] = Field(default_factory=list, max_length=300)
    fields: dict[str, Body]


class ContextSnapshot(BaseModel):
    age: int = Field(ge=0, le=5)
    target_month: str = Field(pattern=r'^(19|20|21)\d{2}-(0[1-9]|1[0-2])$')
    classroom_name: str = Field(max_length=100)
    owner_name: str = Field(max_length=100)
    sheet: SheetSnapshot


class ExportInput(BaseModel):
    kind: Literal['pdf','xlsx']
    context: ContextSnapshot


def install_export_routes(app, temp, field_definitions):
    exports = {}
    gate = asyncio.Semaphore(1)

    @app.post('/plans/monthly-library/preview-export')
    async def create_export(payload: ExportInput):
        ctx = payload.context.model_dump(mode='json')
        fields = ctx['sheet']['fields']
        definitions = field_definitions(ctx['sheet'] | {'age': ctx['age']}, ctx['target_month'])
        if set(fields) - set(definitions) or sum(len(x['body']) for x in fields.values()) > 500000:
            raise HTTPException(422, '出力対象の項目または本文の量を確認してください。')
        token = uuid.uuid4().hex
        folder = Path(temp) / 'exports' / token
        folder.mkdir(parents=True)
        (folder / 'input.json').write_text(json.dumps(ctx,ensure_ascii=False),encoding='utf-8')
        command = [str(PYTHON),str(HERE/'export_worker.py'),str(folder/'input.json'),str(folder),'--kind',payload.kind]
        if payload.kind == 'pdf':
            command.append('--render')
        async with gate:
            try:
                result = await asyncio.to_thread(subprocess.run,command,check=True,timeout=150,capture_output=True,text=True,encoding='utf-8')
                pages = json.loads(result.stdout)['pages']
            except (subprocess.SubprocessError, OSError, ValueError) as exc:
                raise HTTPException(503, '出力できませんでした。画面の入力は保持しています。') from exc
        filename = f"{ctx['target_month']}_{ctx['age']}歳児_月案.{payload.kind}"
        exports[token] = (folder / f'monthly-plan.{payload.kind}', filename, payload.kind, pages)
        url = f'/plans/monthly-library/preview-export/{token}'
        return {'url':url + '/preview' if payload.kind == 'pdf' else url, 'pages':pages}

    @app.get('/plans/monthly-library/preview-export/{token}/preview', response_class=HTMLResponse)
    def preview_export(token: str):
        if token not in exports or exports[token][2] != 'pdf':
            raise HTTPException(404, '印刷内容が見つかりません。')
        pages = exports[token][3]
        prefix = f'/plans/monthly-library/preview-export/{token}'
        images = ''.join(f'<section><img src="{prefix}/page/{i}" alt="月案 {i} / {pages}ページ"></section>' for i in range(1,pages+1))
        return HTMLResponse('''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>月案の印刷確認（操作見本）</title><style>
*{box-sizing:border-box}body{margin:0;background:#e9eeec;color:#21352f;font-family:Meiryo,sans-serif}
header{padding:18px 24px;background:white;border-bottom:1px solid #ced8d2}h1{font-size:22px;margin:0 0 10px}
button,a{display:inline-block;border:0;border-radius:5px;padding:10px 18px;background:#13776a;color:white;font-size:15px;text-decoration:none;cursor:pointer}a{margin-left:10px}p{font-size:14px;margin:10px 0 0}
main{padding:24px}section{max-width:1123px;margin:0 auto 24px;box-shadow:0 2px 10px #b3bdb7;background:white}img{display:block;width:100%;height:auto}
@page{size:A4 landscape;margin:0}@media print{body,main{margin:0;padding:0;background:white}header{display:none}section{margin:0;box-shadow:none;width:297mm;max-width:none;height:210mm;break-after:page;overflow:hidden}section:last-child{break-after:auto}img{width:297mm;height:210mm}}
</style><header><h1>月案の印刷確認</h1><button onclick="window.print()">この帳票を印刷</button>'''
            + f'<a href="{prefix}" download>PDFをダウンロード</a><p>A4横・{pages}ページ。保存前の入力を含みます。架空データの操作見本です。</p></header><main>{images}</main></html>',
            headers={'Cache-Control':'no-store'})

    @app.get('/plans/monthly-library/preview-export/{token}/page/{number}')
    def preview_page(token: str, number: int):
        if token not in exports or exports[token][2] != 'pdf' or not 1 <= number <= exports[token][3]:
            raise HTTPException(404, 'ページが見つかりません。')
        path, _, _, count = exports[token]
        return FileResponse(path.parent / f'page-{number:0{len(str(count))}d}.png', media_type='image/png',headers={'Cache-Control':'no-store'})

    @app.get('/plans/monthly-library/preview-export/{token}')
    def download_export(token: str):
        if token not in exports:
            raise HTTPException(404, '出力ファイルが見つかりません。帳票から出力し直してください。')
        path, filename, kind, _ = exports[token]
        return FileResponse(path,filename=filename,content_disposition_type='inline' if kind=='pdf' else 'attachment',
            media_type='application/pdf' if kind=='pdf' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Cache-Control':'no-store'})
