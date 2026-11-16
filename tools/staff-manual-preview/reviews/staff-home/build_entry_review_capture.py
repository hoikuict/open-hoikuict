"""Exercise the saved release against an in-memory test DB and record its rendered pages."""
from datetime import date
from unittest.mock import patch
import os
import sys

from build_capture import WORKSPACE

DEPLOYED = WORKSPACE / ".local-dev/child-review-rollout-20261108/source"


def main():
    output = WORKSPACE / ".local-dev/manual-entry-review"
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(HOIKUICT_DATABASE_URL="sqlite://", HOIKUICT_ENV="test", HOIKU_NURSERY_REF="見本保育園")
    os.chdir(DEPLOYED)
    sys.path.insert(0, str(DEPLOYED))
    from auth import Role, StaffUser, get_optional_current_staff_user
    from models import Child, Classroom, StaffClassroomAssignment, User
    from plan_docs.db_models import PlanReviewNotificationRow
    from plan_docs.routers.documents import router
    from sqlmodel import Session, select
    from test_child_progress_periods import ChildProgressPeriodTests, FormInputs
    from child_records.settings import default_config

    fixture = ChildProgressPeriodTests()
    fixture.setUp()
    try:
        fixture.set_config(default_config())
        fixture.app.include_router(router, prefix="/plans")
        fixture.app.dependency_overrides[get_optional_current_staff_user] = lambda: fixture.current_user
        with Session(fixture.engine) as session:
            teacher = User(display_name="見本 はなこ", email="teacher@example.invalid")
            director = User(display_name="見本 園長", email="director@example.invalid", staff_role="admin")
            session.add_all([teacher, director])
            session.flush()
            director_id = director.id
            fixture.current_user = StaffUser(name=teacher.display_name, user_id=teacher.id, role=Role.CAN_EDIT)
            session.add(StaffClassroomAssignment(staff_user_id=teacher.id, classroom_id=fixture.classroom_id,
                                                 starts_on=date(2025, 4, 1)))
            classroom = session.get(Classroom, fixture.classroom_id)
            classroom.name = "さくら組"
            child = session.get(Child, fixture.child_id)
            child.last_name, child.first_name, child.birth_date = "見本", "あおい", date(2022, 6, 14)
            session.commit()

        def snapshot(name, response, expected):
            assert response.status_code == 200 and expected in response.text, (name, response.status_code)
            (output / (name + ".html")).write_text(response.text, encoding="utf-8")

        log_id = fixture.log(date(2026, 9, 14), "友だちに砂の入ったカップを渡し、一緒にお店屋さんごっこをした。")
        overview = "砂場で「どうぞ」とカップを渡し、友だちと一緒に遊ぶ姿が増えた。"
        with patch("child_records.router.local_today", return_value=date(2026, 11, 8)):
            snapshot("list", fixture.client.get("/child-records/progress"), "入力する")
            response, fields = fixture.form(target_month="2026-10")
            snapshot("new", response, "2026/07/01")
            saved = fixture.save(fields, body_progress_children_overview=overview, source_log_ids=[str(log_id)])
            assert saved.status_code == 303
            form = fixture.client.get(saved.headers["location"])
            snapshot("saved", form, "下書きを保存しました。")
            assert str(log_id) in FormInputs(form.text).checked
            document_url = "/plans/documents/" + FormInputs(form.text).values["document_id"]
            detail = fixture.client.get(document_url)
            snapshot("detail", detail, "レビュー依頼</button>")

            def change(page, status, comment="", no_recipient=False):
                res = fixture.client.post(document_url + "/status", follow_redirects=False, data={
                    "status": status, "comment": comment, "lock_version": FormInputs(page.text).values["lock_version"],
                })
                expected = document_url + ("?review_error=no_recipient#review-status" if no_recipient else "")
                assert res.status_code == 303 and res.headers["location"] == expected
                return fixture.client.get(expected)

            pending = change(detail, "in_review")
            snapshot("pending", pending, "レビューを取り下げる")
            assert overview in pending.text and fixture.rows()[0].status == "in_review"
            with Session(fixture.engine) as session:
                notifications = session.exec(select(PlanReviewNotificationRow)).all()
                assert len(notifications) == 1 and notifications[0].recipient_user_id == director_id
            draft = change(pending, "draft")
            assert "レビュー依頼</button>" in draft.text and fixture.rows()[0].status == "draft"
            pending = change(draft, "in_review")
            teacher_user = fixture.current_user
            fixture.current_user = StaffUser(name="見本 園長", user_id=director_id, role=Role.ADMIN)
            change(pending, "rejected", "砂場でのやりとりを一つ書き足してください。")
            fixture.current_user = teacher_user
            returned = fixture.client.get(document_url)
            snapshot("returned", returned, "砂場でのやりとりを一つ書き足してください。")
            edit = fixture.client.get(document_url + "/edit")
            assert "児童票を入力" in edit.text and "保存済みの差戻し" in edit.text
            updated = fixture.save(FormInputs(edit.text), body_progress_children_overview=overview + "友だちは笑顔で受け取った。", source_log_ids=[str(log_id)])
            assert updated.status_code == 303
            updated_detail = fixture.client.get(document_url)
            assert "レビュー依頼</button>" in updated_detail.text and "友だちは笑顔で受け取った。" in updated_detail.text
            with Session(fixture.engine) as session:
                before_count = len(session.exec(select(PlanReviewNotificationRow)).all())
                session.get(User, director_id).is_active = False
                session.commit()
            before_status = fixture.rows()[0].status
            no_recipient = change(updated_detail, "in_review", no_recipient=True)
            snapshot("no-recipient", no_recipient, "確認を頼める管理者がいません。")
            assert fixture.rows()[0].status == before_status and "レビュー依頼</button>" in no_recipient.text
            with Session(fixture.engine) as session:
                final_notifications = session.exec(select(PlanReviewNotificationRow)).all()
                assert len(final_notifications) == before_count
            print("Verified draft, evidence, request, admin notice, withdrawal, return, editing and resubmission.")
            print("With no active administrator the previous status, revision text and notification count are retained.")
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    main()
