"""Expand the private daily-plan review corpus without changing a live corpus.

Uses the sibling hoiku-plan-corpus extractor and anonymizer. Every new record
remains pending; the output is for local human review, never a runtime release.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import asdict
from datetime import date, datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import sqlite3
import sys


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def content_fingerprint(aims, content, blocks) -> str:
    """Ignore dates, filenames and reflections when detecting repeated plans."""
    payload = [list(aims), content or "", [
        [str(block.get(field) or "").strip() for field in (
            "time_label", "activity_text", "child_state_text",
            "support_text", "considerations_text",
        )] for block in blocks
    ]]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def complete(extracted) -> bool:
    return bool(
        any(aim.strip() for aim in extracted.aims)
        and (extracted.content_text or "").strip()
        and extracted.activity_blocks
        and all(any((getattr(block, field) or "").strip()
                    for block in extracted.activity_blocks)
                for field in ("time_label", "child_state_text", "support_text",
                              "considerations_text"))
    )


def candidate_buckets(records, class_ages, excluded_refs, excluded_hashes):
    buckets = defaultdict(list)
    seen = set(excluded_hashes)
    for record in sorted(records, key=lambda item: str(item.get("source_ref", ""))):
        sha = record.get("sha256")
        if (record.get("actual_format") != "docx"
                or not record.get("is_daily_plan_candidate")
                or record.get("source_ref") in excluded_refs
                or record.get("class_label") not in class_ages
                or not sha or sha in seen):
            continue
        try:
            target = date.fromisoformat(str(record.get("target_date", "")))
        except ValueError:
            continue
        seen.add(sha)
        buckets[class_ages[record["class_label"]], target.month].append(record)
    return buckets


def existing_fingerprints(connection):
    seen = set()
    for plan in connection.execute("SELECT id,content_text FROM extracted_daily_plans"):
        aims = [row[0] for row in connection.execute(
            "SELECT aim_text FROM extracted_aims WHERE daily_plan_id=? ORDER BY position",
            (plan[0],))]
        cursor = connection.execute(
            "SELECT time_label,activity_text,child_state_text,support_text,considerations_text "
            "FROM extracted_activity_blocks WHERE daily_plan_id=? ORDER BY position", (plan[0],))
        fields = [col[0] for col in cursor.description]
        seen.add(content_fingerprint(aims, plan[1], [dict(zip(fields, row)) for row in cursor]))
    return seen


def verify_existing_rows(original: Path, expanded: Path) -> set[str]:
    """Fail if regeneration would discard existing edits or review decisions."""
    with closing(readonly(original)) as source, closing(readonly(expanded)) as target:
        old_ids = {row[0] for row in source.execute('SELECT id FROM daily_plan_examples')}
        for table, key in (
            ('daily_plan_examples', 'id'), ('daily_plan_aims', 'daily_plan_id'),
            ('daily_plan_activity_blocks', 'daily_plan_id'),
            ('daily_plan_activity_tags', 'daily_plan_id'),
        ):
            cursor = source.execute(f'SELECT * FROM {table}')
            columns = [column[0] for column in cursor.description]
            key_index = columns.index(key)
            expected = cursor.fetchall()
            actual = [row for row in target.execute(f'SELECT * FROM {table}')
                      if row[key_index] in old_ids]
            if Counter(expected) != Counter(actual):
                raise RuntimeError(f'Existing rows changed in {table}; human edits must be preserved')
        return old_ids


def write_review_pages(database, output, new_ids, render_plan):
    output.mkdir()
    with closing(readonly(database)) as connection:
        connection.row_factory = sqlite3.Row
        plans = connection.execute(
            "SELECT * FROM daily_plan_examples ORDER BY age_class,month,target_date,id").fetchall()
        aims, blocks = defaultdict(list), defaultdict(list)
        for row in connection.execute("SELECT * FROM daily_plan_aims ORDER BY position"):
            aims[row["daily_plan_id"]].append(row)
        for row in connection.execute("SELECT * FROM daily_plan_activity_blocks ORDER BY position"):
            blocks[row["daily_plan_id"]].append(row)
    style = """
body{margin:0;background:#f3f6f4;color:#233129;font:16px/1.65 'Yu Gothic UI',Meiryo,sans-serif}
header{background:#183c2b;color:white;padding:24px max(20px,calc((100% - 1240px)/2))}
h1{font-size:25px;margin:0}main{max-width:1240px;margin:24px auto;padding:0 20px 48px}
a{color:#08664e}header a{color:white}.notice{padding:16px;background:#fff2cf;border-left:4px solid #a85d00}
table{border-collapse:collapse;width:100%;background:white}th,td{padding:10px;border:1px solid #d6e0da;text-align:left;vertical-align:top}
.coverage td{text-align:center}.coverage th{white-space:nowrap}.scroll,.timeline-wrap{overflow-x:auto}
.timeline-wrap table{min-width:960px;table-layout:fixed}.timeline-wrap td{white-space:pre-wrap;overflow-wrap:anywhere}
details{margin:16px 0;background:white;border:1px solid #d6e0da;border-radius:8px;overflow:hidden}
summary{padding:16px;cursor:pointer;font-weight:bold}.body{padding:0 16px 16px}.label{color:#246344;font-weight:bold}
.value{white-space:pre-wrap;padding:12px;background:#f6f9f7}.field{margin:12px 0}.redaction,small{color:#705400}
small{display:block}.toolbar{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:20px 0}
input,select,button{font:inherit;padding:8px}input{min-width:280px}.note{color:#52675a}
"""
    def page(title, body, script=""):
        return (f'<!doctype html><html lang="ja"><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{html.escape(title)}</title><style>{style}</style>'
                f'<header><h1>{html.escape(title)}</h1><p>日案例の追加候補・内容確認用</p></header>'
                f'<main>{body}</main><script>{script}</script></html>')
    counts = Counter((p["age_class"], p["month"]) for p in plans)
    added = Counter((p["age_class"], p["month"]) for p in plans if p["id"] in new_ids)
    incomplete_existing = sum(not blocks[p['id']] for p in plans if p['id'] not in new_ids)
    notice = ('<p class="notice">過去の日案を自動抽出・匿名化した確認用データです。'
              '内容・個人情報は人による確認待ちで、本番には未反映です。'
              '文章や4列の対応、固有名の残りを確認してください。</p>')
    rows = []
    for age in range(6):
        cells = ''.join(f'<td><a href="age-{age}-month-{month:02}.html">{counts[age,month]}件</a>'
                        f'<small>追加 {added[age,month]}件</small></td>' for month in range(1,13))
        rows.append(f'<tr><th>{age}歳児</th>{cells}</tr>')
    headings = ''.join(f'<th>{month}月</th>' for month in range(1,13))
    index = (notice + f'<p>既存 {len(plans)-len(new_ids)}件 ＋ 追加 {len(new_ids)}件 ＝ '
             f'<strong>{len(plans)}件</strong>。年齢・月の件数を選ぶと本文を確認できます。</p>'
             '<p class="note">日付・子どもの様子・反省は過去資料の記述です。自園の当日の記録として扱わず、'
             f'利用時には内容を確認して編集します。既存候補のうち活動行が抽出されていない{incomplete_existing}件は保持し、要確認と表示しています。</p>'
             f'<div class="scroll"><table class="coverage"><thead><tr><th>年齢</th>{headings}</tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>')
    (output/'index.html').write_text(page('全年齢・全月の日案例', index), encoding='utf-8')
    for age in range(6):
        for month in range(1,13):
            selected = [p for p in plans if (p['age_class'],p['month']) == (age,month)]
            cards=[]
            for plan in selected:
                new = plan['id'] in new_ids
                card=render_plan(plan,aims[plan['id']],blocks[plan['id']])
                label='追加候補' if new else '既存候補'
                if not blocks[plan['id']]:
                    label+='・活動行なし（要確認）'
                card=card.replace('<details>',f'<details data-new="{int(new)}">',1)
                card=card.replace('<summary>',f'<summary>{label}｜',1)
                cards.append(card)
            body=('<p><a href="index.html">← 全年齢・全月の件数へ</a></p>'+notice+
                  '<div class="toolbar"><label>検索 <input id="query" type="search" placeholder="活動・ねらい・援助など"></label>'
                  '<label>表示 <select id="scope"><option value="">すべて</option><option value="1">追加候補のみ</option>'
                  '<option value="0">既存候補のみ</option></select></label><span id="count" role="status"></span></div>'
                  '<p id="empty" hidden>条件に合う候補がありません。</p>'+''.join(cards))
            script="""
const q=document.getElementById('query'),s=document.getElementById('scope'),cards=[...document.querySelectorAll('details')];
function filter(){let n=0;const v=q.value.trim().toLowerCase();for(const c of cards){c.hidden=!!((s.value&&c.dataset.new!==s.value)||(v&&!c.textContent.toLowerCase().includes(v)));if(!c.hidden)n++}document.getElementById('count').textContent=n+'件';document.getElementById('empty').hidden=n!==0}q.addEventListener('input',filter);s.addEventListener('change',filter);filter();
"""
            (output/f'age-{age}-month-{month:02}.html').write_text(
                page(f'{age}歳児・{month}月の日案例',body,script),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--per-cell',type=int,default=10)
    args=parser.parse_args()
    if args.per_cell<1:
        parser.error('--per-cell must be positive')
    corpus=args.corpus.resolve(); output=args.output.resolve()
    if output.exists():
        parser.error('output must be a new private directory')
    sys.path.insert(0,str(corpus/'src'))
    from hoiku_plan_corpus.review_sample import load_inventory,load_class_ages,_insert_record
    from hoiku_plan_corpus.extract_docx import extract_daily_plan
    from hoiku_plan_corpus.anonymize import build_anonymized_review_database,_render_plan
    source=corpus/'work/review-sample.sqlite'
    old_anonymized=corpus/'work/anonymized-review.sqlite'
    key=corpus/'work/anonymization.key'
    if not key.is_file():
        parser.error('existing anonymization key is required to preserve identifiers')
    originals={str(p):digest(p) for p in (source,old_anonymized,key)}
    with closing(readonly(source)) as db:
        excluded_refs={r[0] for r in db.execute('SELECT source_ref FROM source_files')}
        excluded_hashes={r[0] for r in db.execute('SELECT sha256 FROM source_files')}
        fingerprints=existing_fingerprints(db)
    class_ages=load_class_ages(corpus/'mappings/class_age.yml')
    buckets=candidate_buckets(load_inventory(corpus/'work/inventory.jsonl'),class_ages,excluded_refs,excluded_hashes)
    if any(not buckets[age,month] for age in range(6) for month in range(1,13)):
        raise RuntimeError('At least one age/month has no new source candidates')
    output.mkdir(parents=True)
    staging=output/'review-expanded.sqlite'
    with closing(readonly(source)) as db, closing(sqlite3.connect(staging)) as target:
        db.backup(target)
    created=datetime.now(timezone.utc).isoformat()
    skipped=Counter(); additions=[]
    with closing(sqlite3.connect(staging)) as db:
        for age in range(6):
            for month in range(1,13):
                candidates=list(buckets[age,month]); activities=Counter(); years=Counter(); count=0
                while candidates and count<args.per_cell:
                    # Vary activities and source years within each age/month.
                    record=min(candidates,key=lambda r:(activities[str(r.get('activity_hint') or '')],
                               years[str(r['target_date'])[:4]],str(r['source_ref'])))
                    candidates.remove(record)
                    try:
                        path=Path(record['source_path'])
                        if digest(path)!=record['sha256']:
                            skipped['source_changed_since_inventory']+=1; continue
                        extracted=extract_daily_plan(path)
                    except Exception as exc:
                        skipped[type(exc).__name__]+=1; continue
                    if not complete(extracted):
                        skipped['incomplete_fields']+=1; continue
                    fingerprint=content_fingerprint(extracted.aims,extracted.content_text,
                                                    [asdict(b) for b in extracted.activity_blocks])
                    if fingerprint in fingerprints:
                        skipped['duplicate_content']+=1; continue
                    _insert_record(db,record,extracted,class_ages,created)
                    fingerprints.add(fingerprint); count+=1
                    activities[str(record.get('activity_hint') or '')]+=1
                    years[str(record['target_date'])[:4]]+=1
                    additions.append(record['source_ref'])
                db.commit()
                print(json.dumps({'age':age,'month':month,'added':count,'total_added':len(additions)},ensure_ascii=False),flush=True)
                if count<args.per_cell:
                    raise RuntimeError(f'Insufficient complete candidates for {age}/{month}: {count}')
    database=output/'anonymized-review.sqlite'
    report=build_anonymized_review_database(
        source_database=staging,output_database=database,output_html=output/'anonymized-review-all.html',
        report_path=output/'anonymization-report.json',schema_path=corpus/'schema/anonymized_review.sql',
        key_path=key)
    old_ids=verify_existing_rows(old_anonymized,database)
    with closing(sqlite3.connect(database)) as db:
        all_ids={row[0] for row in db.execute('SELECT id FROM daily_plan_examples')}
        new_ids=all_ids-old_ids
        if not old_ids<=all_ids or len(new_ids)!=len(additions):
            raise RuntimeError('Identifier preservation check failed')
        db.executemany('INSERT OR REPLACE INTO corpus_metadata(key,value) VALUES (?,?)',[
            ('corpus_version','2026.10.11-review-expansion'),('record_count',str(len(all_ids))),
            ('purpose','private-human-review-only')])
        db.commit()
        coverage=db.execute('SELECT age_class,month,count(*) FROM daily_plan_examples GROUP BY age_class,month').fetchall()
        foreign_keys=db.execute('PRAGMA foreign_key_check').fetchall()
        statuses=db.execute('SELECT review_status,pii_review_status,count(*) FROM daily_plan_examples GROUP BY 1,2').fetchall()
    unchanged=all(digest(Path(path))==value for path,value in originals.items())
    if not unchanged or foreign_keys or report['integrity']!='ok':
        raise RuntimeError('Integrity or source preservation check failed')
    write_review_pages(database,output/'review',new_ids,_render_plan)
    result={'status':'pending_human_review','existing_count':len(old_ids),'added_count':len(new_ids),
            'total_count':len(all_ids),'per_age_month_added':args.per_cell,'coverage':coverage,
            'skipped':dict(skipped),'source_files_unchanged':unchanged,
            'existing_rows_unchanged':True,'integrity':report['integrity'],
            'foreign_key_findings':foreign_keys,'review_status_counts':statuses,
            'remaining_pii_findings':report['remaining_pii_findings'],
            'forbidden_columns_found':report['forbidden_columns_found'],
            'database_sha256':digest(database),'new_ids':sorted(new_ids)}
    (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key not in ('new_ids','coverage')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
