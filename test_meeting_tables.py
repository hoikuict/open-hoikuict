from io import BytesIO
from zipfile import ZipFile

from docx import Document
import unittest

from meeting_note_export import export_note
import test_meeting_notes as meeting_notes_tests


def table_op(rows=None, header=True):
    return {"insert": {"meeting_table": {"version": 1, "header": header, "rows": rows or [["担当", "期限"], ["職員A\n職員B", "12月1日"]]}}}


INVALID_TABLES = [
    {"version": 2, "header": True, "rows": [["a"]]},
    {"version": 1, "header": "true", "rows": [["a"]]},
    {"version": 1, "header": True, "rows": []},
    {"version": 1, "header": True, "rows": [["a"], ["b", "c"]]},
    {"version": 1, "header": True, "rows": [[{"html": "bad"}]]},
    {"version": 1, "header": True, "rows": [["\x00"]]},
    {"version": 1, "header": True, "rows": [["a"] * 33]},
]

class MeetingTableTests(unittest.TestCase):
    def test_word_preserves_editable_table_order_header_and_cell_breaks(self):
        data, _, extension = export_note("会議", [{"insert": "表の前\n"}, table_op(), {"insert": "表の後\n"}], "docx")
        doc = Document(BytesIO(data))
        assert extension == "docx"
        assert len(doc.tables) == 1
        assert [[cell.text for cell in row.cells] for row in doc.tables[0].rows] == [["担当", "期限"], ["職員A\n職員B", "12月1日"]]
        assert doc.tables[0].cell(0, 0).paragraphs[0].runs[0].bold
        assert [element.tag.rsplit("}", 1)[-1] for element in doc.element.body] == ["p", "p", "tbl", "p", "sectPr"]
        with ZipFile(BytesIO(data)) as archive:
            assert b"tblHeader" in archive.read("word/document.xml")


    def test_markdown_table_escapes_cells_and_keeps_non_header_first_row(self):
        data, _, _ = export_note("会議", [table_op([["A|B", "<script>"], ["2行\n本文", "担当"]], False)], "md")
        text = data.decode()
        assert "|  |  |\n| --- | --- |" in text
        assert "A\\|B" in text and "\\<script\\>" in text and "2行<br>本文" in text


    def test_export_rejects_malformed_tables(self):
        for value in INVALID_TABLES:
            for format_name in ("docx", "md"):
                with self.subTest(value=value, format=format_name), self.assertRaises(ValueError):
                    export_note("会議", [{"insert": {"meeting_table": value}}], format_name)


    def test_table_text_counts_towards_document_limit(self):
        with self.assertRaises(ValueError):
            export_note("会議", [{"insert": "a" * 499999}, table_op([["ab"]])], "docx")


    def test_old_editor_cannot_overwrite_saved_table_document(self):
        case = meeting_notes_tests.MeetingNoteRouterTests()
        case.setUp()
        try:
            created = case.client.post('/meeting-notes/', follow_redirects=False)
            note_id = int(created.headers['location'].rsplit('/', 1)[1])
            value = {'title': '保存済み', 'content_base64': 'AQID', 'plain_text': '担当表', 'editor_version': 2}
            assert case.client.post(f'/meeting-notes/api/{note_id}/save', json=value).status_code == 200
            before = case.client.get(f'/meeting-notes/api/{note_id}/content').json()
            del value['editor_version']
            value.update(title='旧画面からの保存', content_base64='BAUG')
            response = case.client.post(f'/meeting-notes/api/{note_id}/save', json=value)
            assert response.status_code == 426 and response.json()['status'] == 'upgrade_required'
            assert case.client.get(f'/meeting-notes/api/{note_id}/content').json() == before
        finally:
            case.tearDown()
