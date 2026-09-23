import io
import json
import re
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
from csrf import CsrfTokenMiddleware
from data_transfer_service import build_xlsx_content
from initial_ledger_import import HEADERS, commit_ledger, preview_ledger, read_workbook
from models import Child, ChildProfileHistory, Classroom, DataTransferLog, Family, Guardian, ParentAccount, ParentChildLink
import routers.initial_ledger as route


def rows():
    base = dict.fromkeys(HEADERS, "")
    base.update(きょうだいグループ="A", 姓="見本", 名="花", 姓カナ="ミホン", 名カナ="ハナ", 生年月日="2022-04-10", 入園日="2026-04-01", 在園状態="在園", クラス名="ひよこ組", 家庭住所="架空市1-1", 家庭電話番号="000-0000-0001")
    base.update({"保護者①姓": "見本", "保護者①名": "春", "保護者①電話番号": "000-0000-1001", "保護者①メールアドレス": "sample@example.invalid"})
    second = {**base, "名": "空", "名カナ": "ソラ", "生年月日": "2024-05-20", "園児住所": "架空の個別連絡先"}
    third = {**base, "きょうだいグループ": "", "名": "光", "名カナ": "ヒカリ", "生年月日": "2021-07-01", "家庭住所": "架空市2-2", "保護者①名": "秋"}
    return [{**r, "_line": i+5} for i,r in enumerate((base, second, third))]


def workbook(source=None, name="入力用"):
    source = rows() if source is None else source
    return build_xlsx_content([["初期台帳"], [""], [""], HEADERS] + [[r.get(k, "") for k in HEADERS] for r in source], name)


def replace_xml(content, path, change):
    output=io.BytesIO()
    with ZipFile(io.BytesIO(content)) as original, ZipFile(output,"w",ZIP_DEFLATED) as target:
        for name in original.namelist():
            data=original.read(name)
            target.writestr(name, change(data.decode()).encode() if name==path else data)
    return output.getvalue()


class InitialLedgerTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.session=Session(self.engine)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def commit(self, source=None):
        source=rows() if source is None else source
        plan=preview_ledger(self.session,source)
        self.assertFalse(plan.errors, plan.errors)
        result=commit_ledger(self.session,source,filename="sample.xlsx",expected_revision=plan.revision,actor_name="検証担当")
        self.assertFalse(result.errors, result.errors)
        return result

    def test_template_reads_only_empty_input_sheet(self):
        self.assertEqual(read_workbook(route.TEMPLATE_PATH.read_bytes()),[])
        self.assertEqual(len(HEADERS),38)
        self.assertNotIn("家庭整理番号",HEADERS)
        with self.assertRaisesRegex(ValueError,"入力用"):
            read_workbook(workbook(name="記入例"))

    def test_parse_and_atomic_commit_preserve_contacts_and_create_no_accounts(self):
        source=read_workbook(workbook())
        plan=preview_ledger(self.session,source)
        self.assertEqual(len(self.session.exec(select(Child)).all()),0)
        self.assertEqual([f["name"] for f in plan.families],["見本 花","見本 光"])
        self.assertEqual(plan.children[0]["family_id"],plan.children[1]["family_id"])
        result=self.commit(source)
        self.assertTrue(result.committed)
        children=self.session.exec(select(Child).order_by(Child.id)).all()
        self.assertEqual(len(children),3)
        self.assertEqual(children[0].home_phone,"000-0000-0001")
        self.assertEqual(children[1].home_address,"架空の個別連絡先")
        self.assertEqual(len(self.session.exec(select(Guardian)).all()),3)
        self.assertEqual(len(self.session.exec(select(ChildProfileHistory)).all()),3)
        self.assertEqual(len(self.session.exec(select(ParentAccount)).all()),0)
        self.assertEqual(len(self.session.exec(select(ParentChildLink)).all()),0)
        profiles=self.session.exec(select(Family).order_by(Family.id)).first().guardian_profiles()
        self.assertEqual(profiles[0]["email"],"sample@example.invalid")
        log=self.session.exec(select(DataTransferLog)).one()
        self.assertNotIn("sample@example.invalid",json.dumps(log.change_metadata))

    def test_reimport_and_reordered_same_file_is_idempotent(self):
        self.commit()
        source=list(reversed(rows()))
        result=preview_ledger(self.session,source)
        self.assertTrue(result.already_imported)
        repeated=commit_ledger(self.session,source,filename="renamed.xlsx",expected_revision="old-revision",actor_name="検証")
        self.assertTrue(repeated.already_imported)
        self.assertEqual(len(self.session.exec(select(Child)).all()),3)
        self.assertEqual(len(self.session.exec(select(DataTransferLog)).all()),1)

    def test_blank_groups_never_merge_same_contact_and_full_names_have_suffix(self):
        source=rows()
        for row in source: row["きょうだいグループ"]=""
        source[2]["名"]="花"
        plan=preview_ledger(self.session,source)
        self.assertEqual(len(plan.families),3)
        self.assertEqual(len({f["name"] for f in plan.families}),3)
        self.assertIn("F-00003",plan.families[2]["name"])
        source=rows();source[2]["姓"]="手本"
        self.assertEqual([f["name"] for f in preview_ledger(self.session,source).families],["見本","手本"])

    def test_validation_conflicts_numeric_phone_dates_duplicates_and_guardian(self):
        cases=[("家庭電話番号",999), ("生年月日","2022-02-30"), ("保護者①名",""), ("照合用氏名種別","kanji")]
        for key,value in cases:
            source=rows();source[0][key]=value
            with self.subTest(key=key): self.assertTrue(preview_ledger(self.session,source).errors)
        source=rows();source[1]["家庭電話番号"]="different"
        self.assertTrue(preview_ledger(self.session,source).errors)
        source=rows();source.append({**source[0],"_line":8})
        self.assertTrue(preview_ledger(self.session,source).errors)
        self.assertEqual(len(self.session.exec(select(Family)).all()),0)

    def test_stale_revision_and_mid_commit_failure_leave_no_partial_rows(self):
        plan=preview_ledger(self.session,rows())
        self.session.add(Classroom(name="別の操作",display_order=1));self.session.commit()
        result=commit_ledger(self.session,rows(),filename="test.xlsx",expected_revision=plan.revision,actor_name="検証")
        self.assertTrue(any("更新" in m.message for m in result.errors))
        self.assertEqual(len(self.session.exec(select(Child)).all()),0)
        plan=preview_ledger(self.session,rows())
        with patch("child_profile_history.record_child_profile_history",side_effect=RuntimeError("injected")):
            result=commit_ledger(self.session,rows(),filename="test.xlsx",expected_revision=plan.revision,actor_name="検証")
        self.assertTrue(result.errors)
        for model in (Child,Family,Guardian,DataTransferLog):self.assertEqual(len(self.session.exec(select(model)).all()),0)
        self.assertEqual([c.name for c in self.session.exec(select(Classroom)).all()],["別の操作"])

    def test_changed_workbook_does_not_overwrite_existing_child(self):
        self.commit();source=rows();source[0]["家庭電話番号"]="000-9999"
        plan=preview_ledger(self.session,source)
        self.assertTrue(any("既存台帳" in m.message for m in plan.errors))
        self.assertEqual(self.session.exec(select(Child).order_by(Child.id)).first().home_phone,"000-0000-0001")

    def test_existing_class_and_98_explicit_links_are_untouched(self):
        family=Family(family_name="配信検証");self.session.add(family);self.session.flush()
        account=ParentAccount(display_name="配信確認",email="test@example.invalid",family_id=family.id)
        self.session.add(account);self.session.flush()
        for i in range(98):
            child=Child(last_name="架空",first_name=str(i),last_name_kana="カクウ",first_name_kana=str(i),birth_date=date(2020,1,1),enrollment_date=date(2026,4,1))
            self.session.add(child);self.session.flush()
            self.session.add(ParentChildLink(parent_account_id=account.id,child_id=child.id))
        self.session.add(Classroom(name="ひよこ組",display_order=9));self.session.commit()
        before=[link.model_dump() for link in self.session.exec(select(ParentChildLink)).all()]
        self.commit()
        after=[link.model_dump() for link in self.session.exec(select(ParentChildLink)).all()]
        self.assertEqual(before,after)
        self.assertEqual(len(after),98)
        self.assertEqual(len(self.session.exec(select(ParentAccount)).all()),1)
        self.assertEqual(self.session.exec(select(Classroom)).one().display_order,9)

    def test_formula_unknown_headers_and_tampered_rows_rejected(self):
        altered=replace_xml(workbook(),"xl/worksheets/sheet1.xml",lambda s:s.replace('<c r="D5" t="inlineStr">','<c r="D5" t="inlineStr"><f>1+1</f>'))
        with self.assertRaisesRegex(ValueError,"数式"):read_workbook(altered)
        self.assertTrue(preview_ledger(self.session,[{**rows()[0],"id":999}]).errors)
        self.assertTrue(preview_ledger(self.session,[{**rows()[0],"_line":1}]).errors)
        altered=replace_xml(workbook(),"xl/worksheets/sheet1.xml",lambda s:s.replace('きょうだいグループ','家庭ID'))
        with self.assertRaisesRegex(ValueError,"見出し"):read_workbook(altered)

    def test_excel_numeric_dates_and_1904_epoch(self):
        altered=replace_xml(workbook(),"xl/worksheets/sheet1.xml",lambda s:re.sub(r'<c r="H5".*?</c>','<c r="H5"><v>44661</v></c>',s))
        self.assertEqual(read_workbook(altered)[0]["生年月日"],"2022-04-10")
        altered=replace_xml(workbook(),"xl/workbook.xml",lambda s:s.replace('<sheets>','<workbookPr date1904="1"/><sheets>'))
        altered=replace_xml(altered,"xl/worksheets/sheet1.xml",lambda s:re.sub(r'<c r="H5".*?</c>','<c r="H5"><v>43199</v></c>',s))
        self.assertEqual(read_workbook(altered)[0]["生年月日"],"2022-04-10")


class InitialLedgerRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict("os.environ",{"HOIKUICT_PREVIEW_DIR":self.tmp.name,"HOIKUICT_CSRF_ENFORCE":"1","HOIKUICT_SECURE_COOKIES":"0","HOIKUICT_ENV":"development"})
        self.env.start()
        self.engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        app=FastAPI();app.add_middleware(CsrfTokenMiddleware);app.include_router(route.router)
        self.user=StaffUser(role=Role.CAN_EDIT,name="担当1",can_manage_child_records=True)
        def session():
            with Session(self.engine) as db:yield db
        app.dependency_overrides[route.get_session]=session
        app.dependency_overrides[route.get_current_staff_user]=lambda:self.user
        self.client=TestClient(app)
        self.client.get("/initial-ledger/")
        self.csrf=self.client.cookies.get("hoikuict_csrf")

    def tearDown(self):
        self.client.close();self.engine.dispose();self.env.stop();self.tmp.cleanup()

    def preview(self, content=None):
        response=self.client.post("/initial-ledger/preview",data={"csrf_token":self.csrf},files={"file":("test.xlsx",content or workbook())})
        self.assertEqual(response.status_code,200,response.text[:1000])
        return re.search(r'name="preview_token" value="([a-f0-9]+)"',response.text)[1]

    def test_preview_edit_recheck_commit_receipt_and_replay(self):
        token=self.preview()
        with Session(self.engine) as session:self.assertEqual(len(session.exec(select(Child)).all()),0)
        source=rows();source[0]["名"]="春花"
        updated=self.client.post("/initial-ledger/repreview",data={"csrf_token":self.csrf,"preview_token":token,"rows_json":json.dumps(source)})
        self.assertEqual(updated.status_code,200)
        self.assertIn("見本 春花",updated.text)
        fresh=re.search(r'name="preview_token" value="([a-f0-9]+)"',updated.text)[1]
        response=self.client.post("/initial-ledger/commit",data={"csrf_token":self.csrf,"preview_token":fresh,"confirmed":"yes"},follow_redirects=False)
        self.assertEqual(response.status_code,303,response.text)
        receipt=self.client.get(response.headers["location"])
        self.assertIn("園児 3人",receipt.text)
        replay=self.client.post("/initial-ledger/commit",data={"csrf_token":self.csrf,"preview_token":fresh,"confirmed":"yes"})
        self.assertEqual(replay.status_code,400)

    def test_csrf_permissions_owner_and_cancel(self):
        no_csrf=self.client.post("/initial-ledger/preview",files={"file":("t.xlsx",workbook())})
        self.assertEqual(no_csrf.status_code,403)
        token=self.preview()
        self.user=StaffUser(role=Role.CAN_EDIT,name="担当2",can_manage_child_records=True)
        other=self.client.post("/initial-ledger/commit",data={"csrf_token":self.csrf,"preview_token":token,"confirmed":"yes"})
        self.assertEqual(other.status_code,403)
        self.user=StaffUser(role=Role.VIEW_ONLY,name="閲覧",can_manage_child_records=False)
        for path in ("/initial-ledger/","/initial-ledger/template.xlsx"):self.assertEqual(self.client.get(path).status_code,403)
        denied=self.client.post("/initial-ledger/preview",data={"csrf_token":self.csrf},files={"file":("t.xlsx",workbook())})
        self.assertEqual(denied.status_code,403)
        self.user=StaffUser(role=Role.CAN_EDIT,name="担当1",can_manage_child_records=True)
        cancelled=self.client.post("/initial-ledger/cancel",data={"csrf_token":self.csrf,"preview_token":token},follow_redirects=False)
        self.assertEqual(cancelled.status_code,303)
        self.assertFalse((Path(self.tmp.name)/f"{token}.json").exists())

    def test_download_and_empty_template_never_imports_examples(self):
        template=self.client.get("/initial-ledger/template.xlsx")
        self.assertEqual(template.status_code,200)
        response=self.client.post("/initial-ledger/preview",data={"csrf_token":self.csrf},files={"file":("template.xlsx",template.content)})
        self.assertEqual(response.status_code,400)
        self.assertNotIn('id="ledger-review"',response.text)


class ConcurrentInitialLedgerTests(unittest.TestCase):
    def test_two_workers_cannot_duplicate_a_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            engine=create_engine(f"sqlite:///{Path(directory)/'test.db'}",connect_args={"check_same_thread":False,"timeout":15})
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:revision=preview_ledger(session,rows()).revision
            def register(_):
                with Session(engine) as session:
                    return commit_ledger(session,rows(),filename="t.xlsx",expected_revision=revision,actor_name="並列検証")
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(register,range(2)))
            self.assertEqual(sum(r.committed for r in results),1)
            self.assertEqual(sum(r.already_imported for r in results),1)
            with Session(engine) as session:self.assertEqual(len(session.exec(select(Child)).all()),3)
            engine.dispose()


if __name__ == "__main__":unittest.main()
