"""Render a fictional staff home from the saved deployment for manual screenshots."""
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
import re
import shutil

from jinja2 import Environment, FileSystemLoader, select_autoescape


REVIEW = Path(__file__).resolve().parent
WORKSPACE = REVIEW.parents[1]
DEPLOYED = WORKSPACE / ".local-dev/document-search-rollout-20261108/source"
CAPTURE = WORKSPACE / ".local-dev/manual-batch2-20261123/capture"


def render(template_name, path, *, admin=False, **context):
    environment = Environment(
        loader=FileSystemLoader(DEPLOYED / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    environment.filters["jst_datetime"] = lambda value, fmt: value.strftime(fmt)
    staff_name = "見本 園長" if admin else "見本 はなこ"
    role_label = "管理者" if admin else "編集可"
    template = environment.get_template(template_name)
    return template.render(
        request=SimpleNamespace(url=SimpleNamespace(path=path), state=SimpleNamespace(csrf_token="")),
        current_user=SimpleNamespace(staff_id="sample", name=staff_name, role_label=role_label,
                                     is_admin=admin, can_manage_child_records=admin),
        staff_record=SimpleNamespace(display_name=staff_name, staff_role="admin" if admin else "can_edit", calendar_role_label=role_label),
        portal_date="2026年11月4日（水）", target_date=date(2026, 11, 4),
        **context,
    )


def render_home(attention_count=0, **extra):
    classroom = "さくら組"
    return render(
        "portal/index.html", "/", greeting="おはようございます", updated_time="08:30",
        assignment_names=[classroom], attention_count=attention_count, attention_url="/staff/attention",
        present_count=2, can_show_all=True, show_all=False,
        attendance_summaries=[dict(
            classroom_name=classroom, enrolled_count=3, alarm_count=0, checked_in_count=2,
            present_count=2, checked_out_count=0, absent_count=0 if attention_count else 1,
            not_checked_in_count=1 if attention_count else 0, attention_count=1 if attention_count else 0,
            attendance_url="/attendance-checks/?date=2026-11-04&classroom_id=1",
        )],
        **extra,
    )


def render_attention(items, *, admin=False):
    return render(
        "portal/attention.html", "/staff/attention", attention_items=items, attention_count=len(items),
        attendance_attention_count=sum(item["kind_label"] == "出欠" for item in items),
        survey_attention_count=sum(item["kind_label"] == "アンケート" for item in items),
        admin=admin, show_all=False, can_show_all=admin,
    )


def offline(rendered, annotation):
    rendered = re.sub(r"<script\b[^>]*>.*?</script>", "", rendered, flags=re.S | re.I)
    rendered = re.sub(r'\baction="[^"]*"', 'action="#"', rendered)
    head = """<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; img-src 'self' data:; form-action 'none'; connect-src 'none'; base-uri 'none'">
    <script src="tailwind.js"></script>
    <style>
    .guide-target { outline: 2px solid #ff9b54; outline-offset: 3px; border-radius: 2px; }
    .guide-marker { position:absolute; z-index:10; width:21px; height:21px; display:grid; place-items:center; border:2px solid white; border-radius:50%; background:#ae390b; color:white; font:bold 14px/1 Arial,sans-serif; pointer-events:none; }
    [data-guide-number] { position:relative; outline:2px solid #ed853c; outline-offset:2px; }
    [data-guide-number]::before { content:attr(data-guide-number); position:absolute; left:50%; bottom:calc(100% + 6px); transform:translateX(-50%); display:grid; place-items:center; width:21px; height:21px; box-sizing:border-box; border:2px solid white; border-radius:50%; background:#ae390b; color:white; font:bold 14px/1 Arial,sans-serif; }
    .guide-row [data-guide-number]::before { left:auto; right:calc(100% + 8px); bottom:50%; transform:translateY(50%); }
    [data-marker-side]::before { bottom:50%; transform:translateY(50%); }
    [data-marker-side="left"]::before { left:auto; right:calc(100% + 8px); }
    [data-marker-side="right"]::before { left:calc(100% + 8px); }
    </style>"""
    annotation = """<script>
    document.addEventListener('click', event => event.preventDefault(), true);
    document.addEventListener('submit', event => event.preventDefault(), true);
    </script>""" + annotation
    return rendered.replace("<head>", "<head>" + head, 1).replace("</body>", annotation + "</body>")


IDENTITY_MARKERS = """<script>
    addEventListener('load', async () => {
      await document.fonts.ready;
      const heading = document.querySelector('main section h1');
      const date = heading.previousElementSibling;
      const assignment = heading.nextElementSibling.lastElementChild;
      const targets = [date, heading, assignment].map((element, i) => {
        const label = document.createElement('span');
        label.className = 'guide-target';
        label.textContent = element.textContent.trim();
        element.replaceChildren(label);
        const marker = document.createElement('span');
        marker.className = 'guide-marker';
        marker.textContent = i + 1;
        document.body.append(marker);
        return {label, marker};
      });
      function align() {
        for (const {label, marker} of targets) {
          const bounds = label.getBoundingClientRect();
          const after = label === targets[2].label;
          marker.style.left = (scrollX + (after ? bounds.right + 9 : bounds.left - 29)) + 'px';
          marker.style.top = (scrollY + bounds.top + (bounds.height - 21) / 2) + 'px';
        }
      }
      new ResizeObserver(align).observe(heading.closest('section'));
      addEventListener('resize', align);
      requestAnimationFrame(align);
    });
    </script>"""


ATTENTION_TILE = """<script>
    document.querySelector('main a[href="/staff/attention"]').dataset.guideNumber = '1';
    </script>"""

ATTENTION_ROWS = """<script>
    const rows = document.querySelectorAll('main section a[href^="/attendance-checks/"], main section a[href^="/staff-surveys/"]');
    rows.forEach((row, i) => {
      row.classList.add('guide-row');
      row.lastElementChild.dataset.guideNumber = i + 2;
    });
    </script>"""


def home_examples():
    morning = datetime(2026, 11, 4, 8, 10)
    walk = dict(time_label="10:00", title="園庭あそび", state="upcoming",
                calendar_name="さくら組", calendar_color="#378564", location="園庭")
    message = dict(id=1, author_name="見本 みどり", created_at=morning,
                   display_body="園庭あそびの前に、帽子の確認をお願いします。")
    everyday = render_home(2, schedule_items=[walk], next_schedule=walk, timeline_messages=[message])
    returned = dict(kind_label="文書の確認依頼", title="園外活動のおたより",
                    decided_by_name="見本 園長", note="集合場所を書き足してください。",
                    returned_at=morning, url="/document-reviews/1", dismiss_url="/document-reviews/1/dismiss-return")
    notification = dict(id=2, document_title="さくら組の週案", created_at=morning, read_at=None,
                        notification_kind="review_outcome", decision_status="approved", decided_by_name="見本 園長")
    conditional = render_home(2, returned_documents=[returned], returned_document_count=1,
                              plan_notifications=[notification], unread_plan_notification_count=1)
    approval = dict(kind="notice", kind_label="お知らせ", title="遠足のお知らせ",
                    requested_at=morning, requester_name="見本 みどり", url="/notices/1/preview")
    admin = render_home(admin=True, approval_queue_count=1, approval_queue_items=[approval])
    home_markers = """<script>
      const header = document.querySelector('main h1').closest('section');
      header.querySelectorAll('a[href="/staff/attention"], a[href="#attendance"], a[href="#schedule"]').forEach((a, i) => {
        a.dataset.guideNumber = i + 1;
      });
      const scope = document.querySelector('#attendance a[href="/?scope=assigned"]').parentElement;
      scope.dataset.guideNumber = '1';
      scope.dataset.markerSide = 'right';
      const openAttendance = document.querySelector('#attendance article a');
      openAttendance.dataset.guideNumber = '2';
      openAttendance.dataset.markerSide = 'left';
    </script>"""
    return {
        "capture-home-everyday.html": offline(everyday, home_markers),
        "capture-home-location.html": offline(everyday, IDENTITY_MARKERS),
        "capture-home-documents.html": offline(conditional, ""),
        "capture-home-admin.html": offline(admin, ""),
        "capture-attention-empty.html": offline(render_attention([]), ""),
    }


if __name__ == "__main__":
    CAPTURE.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(WORKSPACE / "tools/staff-manual-preview/dist/assets/tailwind.js", CAPTURE / "tailwind.js")
    items = [
        dict(kind_label="出欠", title="見本 あおい", detail="出欠確認が未入力です",
             url="/attendance-checks/?date=2026-11-04&classroom_id=1&filter=unknown", severity="normal"),
        dict(kind_label="アンケート", title="園内研修の日程", detail="回答期限なし",
             url="/staff-surveys/1", severity="normal"),
    ]
    pages = {
        "capture.html": offline(render_home(), IDENTITY_MARKERS),
        "capture-attention-home.html": offline(render_home(len(items)), ATTENTION_TILE),
        "capture-attention-list.html": offline(render_attention(items), ATTENTION_ROWS),
        "capture-attention-admin.html": offline(render_attention(items, admin=True), ""),
        **home_examples(),
    }
    for name, page in pages.items():
        (CAPTURE / name).write_text(page, encoding="utf-8")
