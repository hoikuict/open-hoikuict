"""Build fictional samples and verify pagination/content without production data."""
import json
from pathlib import Path

from export_layout import make_layout

DEST = Path(__file__).resolve().parents[2] / '.local-dev/monthly-print-export-20260927'


def context(age, count=6, long=False):
    children = [{'ref': f'child:{i}', 'name': f'架空園児{i}', 'birth_date': '2025-05-01'} for i in range(1,count+1)]
    fields = {k:{'body':v} for k,v in {
        'common:goal':'安心して過ごし、好きな遊びを楽しむ。',
        'common:home':'家庭と生活の様子を伝え合う。',
        'common:review':'自分から好きな遊びを選ぶ姿が見られた。',
    }.items()}
    if age < 3:
        fields['common:events']={'body':'15日　お楽しみ会\n22日　身体測定'}
        for child in children:
            for field,text in [('life','体調や気温に合わせて衣服を調節し、心地よく過ごす。'),
                               ('play','友達の真似をして体を動かしたり、身近な素材で遊んだりする。'),
                               ('help','安心して遊べる場所を整え、保育者とゆったりやり取りを楽しめるようにする。'),
                               ('review','友達の遊びに関心をもち、同じ遊びを繰り返し楽しんでいた。')]:
                fields[child['ref']+':'+field]={'body':'○'+text+('\n○'+text if child['ref']=='child:1' else '')}
        if long:
            fields['child:1:play']['body'] = ('長文の確認。友達と一緒にいろいろな遊びを楽しむ。\n' * 90) + '最後の文章も残す。'
            fields['common:home']['body'] = '家庭と様子を伝え合う。' * 150
            fields['common:events']['body'] = '行事の詳しい内容。' * 200
    else:
        for domain in ('care','health','relations','nature','language','expression'):
            for field,text in [('goal','身近な人や物に関心をもち、遊びを楽しむ。'),('environment','好きな素材を選べるように用意する。'),
                               ('expected','友達とやり取りしながら遊ぼうとする。'),('support','一人ひとりの思いを受け止めて関わる。')]:
                fields[f'group:{domain}:{field}']={'body':'○'+text}
        fields['group:food']={'body':'食材に親しみ、みんなで楽しく食事をする。'}
        for day in range(1,32):
            fields[f'event:{day}']={'body':'身体測定' if day==22 else 'お楽しみ会' if day==15 else ''}
        if long:
            fields['group:expression:expected']['body']='歌やリズムに合わせて、友達と楽しみながら表現する。\n'*70+'表現の最後。'
            fields['event:15']['body']='行事の長文。'*120+'行事の最後。'
    return {'age':age,'target_month':'2026-10','classroom_name':'架空A組','owner_name':'架空職員',
            'sheet':{'children':children if age<3 else [],'fields':fields}}


def verify(ctx):
    layout = make_layout(ctx)
    collected = {}
    for page in layout['pages']:
        occupied = set()
        for cell in page['cells']:
            for r in range(cell['row'],cell['row']+cell['height']):
                for c in range(cell['col'],cell['col']+cell['span']):
                    assert (r,c) not in occupied, ('overlap',cell)
                    occupied.add((r,c))
            if cell['key']:
                pieces = collected.setdefault(cell['key'],{})
                assert cell['part'] not in pieces or pieces[cell['part']]==cell['text']
                pieces[cell['part']] = cell['text']
    for key, data in ctx['sheet']['fields'].items():
        assert ''.join(v for k,v in sorted(collected.get(key,{}).items())) == data['body'], ('missing-text',key)
    return len(layout['pages'])


if __name__ == '__main__':
    DEST.mkdir(parents=True,exist_ok=True)
    results = []
    for age in range(6):
        for long in (False,True):
            c = context(age,long=long)
            results.append({'age':age,'long':long,'pages':verify(c)})
    c=context(0,count=20)
    results.append({'children':20,'pages':verify(c)})
    for age in (0,3):
        for fields in ({},context(age)['sheet']['fields']):
            c=context(age,count=0);c['sheet']['fields']=fields if age==3 else {k:v for k,v in fields.items() if k.startswith('common:')}
            results.append({'age':age,'empty':True,'pages':verify(c)})
    (DEST/'personal-input.json').write_text(json.dumps(context(0),ensure_ascii=False),encoding='utf-8')
    (DEST/'group-input.json').write_text(json.dumps(context(3),ensure_ascii=False),encoding='utf-8')
    (DEST/'long-input.json').write_text(json.dumps(context(1,long=True),ensure_ascii=False),encoding='utf-8')
    (DEST/'layout-checks.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results))
