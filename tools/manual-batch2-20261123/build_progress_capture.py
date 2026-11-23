"""Render the deployed progress dashboard offline with fictional children for the guide."""
from datetime import date
import shutil

from build_capture import CAPTURE, WORKSPACE, offline, render
from build_children_capture import constants


def main():
    CAPTURE.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(WORKSPACE / "tools/staff-manual-preview/dist/assets/tailwind.js", CAPTURE / "tailwind.js")
    labels = constants("child_records/router.py", {"PROGRESS_STATUS_LABELS"})["PROGRESS_STATUS_LABELS"]
    ages = constants("child_records/settings.py", {"AGE_RULES"})["AGE_RULES"]
    classrooms = [dict(id=1, name="さくら組"), dict(id=2, name="もも組")]
    # The sample staff member can read both classes and enter records for the first one.
    examples = [
        (101, "あおい", 1, None), (103, "そら", 1, "draft"),
        (104, "なぎ", 1, "in_review"), (105, "りく", 1, "rejected"),
        (102, "ひなた", 2, None),
    ]
    start, end = date(2026, 7, 1), date(2026, 9, 30)
    rows = []
    for child_id, name, class_id, status in examples:
        classroom = classrooms[class_id - 1]
        rows.append(dict(
            child=dict(id=child_id, full_name=f"見本 {name}", classroom=classroom, withdrawal_date=None),
            cycle=dict(period_start=start, period_end=end), age_label="3歳児" if class_id == 1 else "2歳児",
            group_key=class_id, group_label=classroom["name"], can_create=class_id == 1,
            document=dict(id=child_id + 100, status=status) if status else None,
            can_edit=class_id == 1 and status in {"draft", "rejected"},
            entry_url=f"/children/{child_id}/progress-records/new?period_start={start}&period_end={end}",
        ))
    path = "/child-records/progress"
    options = [("uncreated", "未作成"), ("created", "作成済み（すべて）"), *labels.items()]
    for name, status in [("list", ""), ("filter", "uncreated"), ("empty", "approved")]:
        selected = rows
        if status:
            selected = [r for r in rows if r["group_key"] == 1 and (
                (r["document"] is None and status == "uncreated")
                or (r["document"] and r["document"]["status"] == status))]
        html = render(
            "child_records/progress_dashboard.html", path, period_action=path,
            today=date(2026, 11, 4), selected_target_month="2026-10", is_latest_period=True,
            previous_target_month="2026-09", next_target_month="2026-11", classrooms=classrooms,
            selected_classroom_id="1" if status else "", selected_group_by="classroom",
            selected_age_group="", selected_status=status, rows=selected, total_count=len(rows),
            filtered_count=len(selected), uncreated_count=sum(r["document"] is None for r in rows),
            status_labels=labels, status_filter_options=options, age_filter_options=[(k, v) for k, v, _ in ages],
        )
        marks = ""
        if name == "filter":
            marks = """<script>
            for (const [index, name] of ["classroom_id", "status"].entries()) {
              const select = document.querySelector('select[name="' + name + '"]');
              const label = select.parentElement;
              const caption = document.createElement('span');
              caption.textContent = label.firstChild.textContent.trim();
              caption.dataset.guideNumber = index + 1;
              caption.dataset.markerSide = "right";
              label.firstChild.replaceWith(caption);
            }
            document.querySelector('select[name="status"]').form.querySelector('button').classList.add('guide-target');
            </script>"""
        (CAPTURE / f"capture-progress-{name}.html").write_text(offline(html, marks), encoding="utf-8")


if __name__ == "__main__":
    main()
