"""Bundled-runtime PDF/layout writer and narrow XLSX print-setting completion."""
import argparse
import json
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen.canvas import Canvas
from export_layout import FONT, make_layout

NODE = Path('C:/Users/katet/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
POPPLER = NODE.parents[2] / 'native/poppler/Library/bin/pdftoppm.exe'
HERE = Path(__file__).resolve().parent
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def pdf(layout, path):
    c = Canvas(str(path), pagesize=landscape(A4))
    c.setTitle(layout['title']); c.setAuthor('open-hoikuict')
    page_height = landscape(A4)[1]
    for index, page in enumerate(layout['pages'], 1):
        for cell in page['cells']:
            x, top = 28.35 + cell['col'] * layout['width'] / 72, 28.35 + cell['row'] * 6
            w, h = cell['span'] * layout['width'] / 72, cell['height'] * 6
            y = page_height - top - h
            label = cell['style'] == 'label'
            c.setFillColorRGB(*((.94, .95, .94) if label else (1, 1, 1)))
            c.setStrokeColorRGB(.35, .4, .37); c.setLineWidth(.45)
            c.rect(x, y, w, h, stroke=cell['style'] != 'title', fill=1)
            c.setFillColorRGB(.08, .1, .09)
            c.setFont(FONT, cell['font_size'])
            for i, line in enumerate(cell['lines']):
                baseline = page_height - top - cell['font_size'] - (2 if cell['style'] == 'calendar' else 3) - i * cell['leading']
                if label or cell['style'] == 'name':
                    c.drawCentredString(x + w / 2, baseline, line)
                else:
                    c.drawString(x + 4, baseline, line)
        c.setFont(FONT, 8)
        c.drawString(28.35, 17, '操作見本（架空データ）' + ('　' + page['caption'] if page['caption'] else ''))
        c.drawRightString(813.55, 17, f'{index} / {len(layout["pages"])}')
        c.showPage()
    c.save()


def print_settings(path, count):
    """Artifact Tool lacks print setup: complete only these OpenXML settings."""
    ET.register_namespace('', NS)
    with ZipFile(path) as z:
        content = {n: z.read(n) for n in z.namelist()}
    for i in range(1, count + 1):
        key = f'xl/worksheets/sheet{i}.xml'
        root = ET.fromstring(content[key])
        props = root.find(f'{{{NS}}}sheetPr')
        if props is None:
            props = ET.Element(f'{{{NS}}}sheetPr'); root.insert(0, props)
        ET.SubElement(props, f'{{{NS}}}pageSetUpPr', fitToPage='1')
        for name in ('pageMargins', 'pageSetup'):
            for old in root.findall(f'{{{NS}}}{name}'):
                root.remove(old)
        # The generated files contain no drawings/tables; schema order is explicit here.
        margins = ET.Element(f'{{{NS}}}pageMargins', left='0.39', right='0.39', top='0.39', bottom='0.39', header='0.1', footer='0.1')
        setup = ET.Element(f'{{{NS}}}pageSetup', paperSize='9', orientation='landscape', fitToWidth='1', fitToHeight='1')
        for element in (margins, setup):
            root.append(element)
        content[key] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    root = ET.fromstring(content['xl/workbook.xml'])
    names = root.find(f'{{{NS}}}definedNames')
    if names is None:
        names = ET.Element(f'{{{NS}}}definedNames')
        sheets_index = list(root).index(root.find(f'{{{NS}}}sheets'))
        root.insert(sheets_index + 1, names)
    for i in range(count):
        item = ET.SubElement(names, f'{{{NS}}}definedName', name='_xlnm.Print_Area', localSheetId=str(i))
        item.text = f"'月案{i + 1:02}'!$A$1:$BT$85"
    content['xl/workbook.xml'] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    with ZipFile(path, 'w', ZIP_DEFLATED) as z:
        for name, data in content.items():
            z.writestr(name, data)


def run(input_path, output, kind, render=False):
    context = json.loads(input_path.read_text(encoding='utf-8'))
    layout = make_layout(context)
    output.mkdir(parents=True, exist_ok=True)
    layout_path = output / 'layout.json'
    layout_path.write_text(json.dumps(layout, ensure_ascii=False), encoding='utf-8')
    if kind in ('pdf', 'both'):
        pdf(layout, output / 'monthly-plan.pdf')
        if render:
            subprocess.run([str(POPPLER), '-png', '-r', '150', str(output / 'monthly-plan.pdf'),
                            str(output / 'page')], check=True, timeout=120, capture_output=True)
    if kind in ('xlsx', 'both'):
        command = [str(NODE), str(HERE / 'export_xlsx.mjs'), str(layout_path), str(output / 'monthly-plan.xlsx')]
        if render:
            command.append('--render')
        subprocess.run(command, check=True, timeout=120, capture_output=True)
        print_settings(output / 'monthly-plan.xlsx', len(layout['pages']))
    print(json.dumps({'pages': len(layout['pages']), 'kind': kind}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path); parser.add_argument('output', type=Path)
    parser.add_argument('--kind', choices=['pdf', 'xlsx', 'both'], default='both')
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args()
    run(args.input, args.output, args.kind, args.render)
