from __future__ import annotations

from datetime import date

from .text import clean_text, confirmation_items
from ..auth_adapter import StaffUser
from ..contracts import (
    ANNUAL_TERM_ORDER,
    DAILY_SECTIONS,
    DocumentStatus,
    DocumentType,
    MONTHLY_SECTIONS,
    SectionDefinition,
    WEEKLY_SECTIONS,
    annual_section_definitions,
    evidence_tags_for,
)
from ..models import PlanDocument, PlanSchedule, ScheduleCell, ScheduleColumn, ScheduleRow, SectionBlock


def _section(
    definition: SectionDefinition,
    body: str,
    source_refs: list[str],
    *,
    needs_confirmation: bool = False,
    editor_note: str | None = None,
) -> SectionBlock:
    return SectionBlock(
        section_key=definition.key,
        title=definition.title,
        body=body,
        source_refs=source_refs,
        evidence_tags=evidence_tags_for(source_refs),
        needs_confirmation=needs_confirmation,
        editor_note=editor_note,
    )


def _term_label(term_key: str) -> str:
    return dict(ANNUAL_TERM_ORDER).get(term_key, term_key)


def _needs_note(value: str, label: str) -> tuple[bool, str | None]:
    if value:
        return False, None
    return True, f"{label}が未入力のため、担任確認が必要です。"


def _to_int(value: str | int | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def week_start_date_from_target_week(target_week: str) -> date:
    value = clean_text(target_week)
    if "-W" not in value:
        raise ValueError("target_week must be formatted as YYYY-Www")
    year_text, week_text = value.split("-W", 1)
    return date.fromisocalendar(int(year_text), int(week_text), 1)


def school_year_from_date(value: date) -> int:
    return value.year if value.month >= 4 else value.year - 1


def _is_infant_age(age_class: str) -> bool:
    return age_class.startswith(("0", "1", "2"))


def _cell(
    body: str = "",
    *,
    source_refs: list[str] | None = None,
    needs_confirmation: bool = False,
    editor_note: str | None = None,
) -> ScheduleCell:
    return ScheduleCell(
        body=body,
        source_refs=source_refs or ["form.schedule"],
        needs_confirmation=needs_confirmation,
        editor_note=editor_note,
    )


def _daily_columns() -> list[ScheduleColumn]:
    return [
        ScheduleColumn("env", "環境構成"),
        ScheduleColumn("children", "予想される子どもの姿"),
        ScheduleColumn("support", "保育者の援助・配慮"),
    ]


def _weekly_columns() -> list[ScheduleColumn]:
    return [
        ScheduleColumn("activity", "主な活動・予想される活動"),
        ScheduleColumn("support", "環境・保育者の援助"),
    ]


def attach_daily_schedule(document: PlanDocument, age_class: str, main_activity_note: str) -> PlanDocument:
    columns = _daily_columns()
    core_missing = not bool(main_activity_note)
    main_children = main_activity_note or "主な活動を、子どもの姿と結び付けて追記する。"
    main_support = (
        f"{main_activity_note}に向かう子どもの気づきや試行を受け止め、必要な素材や場を調整する。"
        if main_activity_note
        else "主な活動に必要な環境と、保育者の援助・声かけを追記する。"
    )
    main_note = "主活動の子どもの姿と援助を確認してください。" if core_missing else None

    if _is_infant_age(age_class):
        row_specs = [
            ("t_arrival", 10, "08:00", "順次登園・視診", "安心できる保育者と関わりながら身支度をする。"),
            ("t_health_check", 20, "08:30", "健康観察", "機嫌、睡眠、食事、体調を保育者と一緒に確認する。"),
            ("t_care_am", 30, "09:00", "授乳・排泄・個別の生活", "一人ひとりの生活リズムに合わせて過ごす。"),
            ("t_free_am", 40, "09:30", "午前の遊び", "興味を向けた玩具や素材に触れて遊ぶ。"),
            ("t_lunch", 50, "11:00", "昼食・給食", "体調や発達に合わせて食事を楽しむ。"),
            ("t_nap", 60, "12:00", "午睡", "安心して休息する。"),
            ("t_care_pm", 70, "14:30", "授乳・排泄・個別の生活", "目覚めや体調に合わせてゆったり過ごす。"),
            ("t_free_pm", 80, "15:00", "午後の遊び", "落ち着いた環境で好きな遊びを楽しむ。"),
            ("t_departure", 90, "16:30", "順次降園", "保育者と一日の安心できた場面を振り返る。"),
        ]
        care_support = "授乳・離乳食、排泄、睡眠のリズムを個別に記録し、体調に応じて無理なく関わる。"
    else:
        row_specs = [
            ("t_arrival", 10, "08:00", "順次登園・視診", "健康観察、持ち物の始末をする。"),
            ("t_free_am", 20, "09:00", "午前の遊び", "好きな遊びを選び、友だちとの関わりを広げる。"),
            ("t_meeting", 30, "10:00", "朝の集まり", "出席、歌、今日の予定を共有する。"),
            ("t_main", 40, "10:15", "主な活動", main_children),
            ("t_lunch", 50, "11:30", "昼食・給食", "手洗い、配膳、食事を通して生活の見通しを持つ。"),
            ("t_nap", 60, "12:45", "午睡", "体を休め、午後の生活へ向かう。"),
            ("t_free_pm", 70, "15:00", "午後の遊び", "落ち着いた雰囲気の中で好きな遊びを続ける。"),
            ("t_departure", 80, "16:30", "順次降園", "片付け、降園準備、保護者への伝達を行う。"),
        ]
        care_support = ""

    rows: list[ScheduleRow] = []
    for row_key, order, start_time, label, children_body in row_specs:
        support_body = ""
        env_body = "安全に動ける動線と、子どもが選べる素材・場を整える。"
        needs_confirmation = False
        editor_note = None
        if row_key == "t_main":
            support_body = main_support
            needs_confirmation = core_missing
            editor_note = main_note
        elif row_key in {"t_care_am", "t_care_pm"}:
            support_body = care_support
            env_body = "個別の生活リズムに合わせて、落ち着いて関われる場を整える。"
        elif row_key == "t_lunch":
            support_body = "手洗い、姿勢、食具、食材への関心を一人ひとりのペースに合わせて支える。"
        elif row_key == "t_departure":
            support_body = "保護者へ体調、遊び、印象的な姿を簡潔に共有する。"
        rows.append(
            ScheduleRow(
                row_key=row_key,
                label=label,
                order=order,
                start_time=start_time,
                cells={
                    "env": _cell(env_body),
                    "children": _cell(children_body, needs_confirmation=needs_confirmation, editor_note=editor_note),
                    "support": _cell(support_body, needs_confirmation=needs_confirmation, editor_note=editor_note),
                },
            )
        )

    document.schedule = PlanSchedule(layout="daily_timeline", columns=columns, rows=rows)
    return document


def attach_weekly_grid(document: PlanDocument, *, include_saturday: bool = False, weekly_activities_note: str = "") -> PlanDocument:
    day_specs = [
        ("mon", 10, "月"),
        ("tue", 20, "火"),
        ("wed", 30, "水"),
        ("thu", 40, "木"),
        ("fri", 50, "金"),
    ]
    if include_saturday:
        day_specs.append(("sat", 60, "土"))
    rows = []
    for row_key, order, label in day_specs:
        activity = weekly_activities_note if row_key == "mon" and weekly_activities_note else ""
        rows.append(
            ScheduleRow(
                row_key=row_key,
                label=label,
                order=order,
                cells={
                    "activity": _cell(activity),
                    "support": _cell(""),
                },
            )
        )
    document.schedule = PlanSchedule(layout="weekly_grid", columns=_weekly_columns(), rows=rows)
    return document


def generate_annual_plan(data: dict[str, str], user: StaffUser) -> PlanDocument:
    school_year = int(clean_text(data.get("school_year")) or "2026")
    classroom_ref = clean_text(data.get("classroom_ref")) or user.classroom_refs[0]
    class_name = clean_text(data.get("class_name")) or classroom_ref or "クラス未設定"
    owner_name = clean_text(data.get("owner_name")) or user.name
    focus_growth = clean_text(data.get("focus_growth"))
    class_outlook = clean_text(data.get("class_outlook"))
    annual_events = clean_text(data.get("annual_events"))
    seasonal_context = clean_text(data.get("seasonal_context"))
    care_points = clean_text(data.get("care_points"))
    family_policy = clean_text(data.get("family_collaboration_policy"))
    health_safety = clean_text(data.get("health_safety_policy"))
    preferred_expressions = clean_text(data.get("preferred_expressions"))

    required = confirmation_items(
        [
            ("クラスの姿", class_outlook),
            ("年間で大切にしたい育ち", focus_growth),
            ("配慮事項", care_points),
        ]
    )
    sections: list[SectionBlock] = []

    for definition in annual_section_definitions():
        if definition.key == "annual_goal":
            body = (
                f"{school_year}年度の{class_name}では、{focus_growth or '子どもの主体的な育ち'}を年間の軸に据える。"
                f"{class_outlook or '現在の子どもの姿を確認しながら、生活と遊びがつながる計画として更新する。'}"
            )
            if preferred_expressions:
                body += f" 表現は「{preferred_expressions}」を意識して整える。"
            needs_confirmation, editor_note = _needs_note(focus_growth and class_outlook, "年間の中心情報")
            sections.append(
                _section(
                    definition,
                    body,
                    ["profile.childcare_goal", "form.focus_growth", "form.class_outlook"],
                    needs_confirmation=needs_confirmation,
                    editor_note=editor_note,
                )
            )
            continue

        term_key = "_".join(definition.key.split("_")[:2])
        suffix = definition.key.replace(f"{term_key}_", "")
        term_label = _term_label(term_key)
        term_note = clean_text(data.get(f"{term_key}_note"))

        if suffix == "outlook":
            body = (
                f"{term_label}は、{term_note or seasonal_context or '季節や行事を踏まえた子どもの姿'}を捉え、"
                f"{focus_growth or '年間のねらい'}につながる経験を積み重ねる。"
            )
            refs = ["form.seasonal_context", f"form.{term_key}_note", "form.focus_growth"]
        elif suffix == "environment":
            body = (
                f"{term_label}の環境は、子どもが選び、試し、友だちと関わり直せる余白を残して構成する。"
                f" 行事や生活の流れは「{annual_events or '園行事'}」と接続して調整する。"
            )
            refs = ["profile.indoor_environment", "form.annual_events"]
        elif suffix == "support":
            body = (
                f"保育者は{term_label}の姿を観察し、{care_points or '安全面と個別配慮'}を確認しながら、"
                "子どもの言葉や試行錯誤を次の活動へつなげる。"
            )
            refs = ["profile.support_policy", "form.care_points"]
        elif suffix == "family_collaboration":
            body = (
                f"家庭には{term_label}の育ちの見通しを共有し、"
                f"{family_policy or '園での姿と家庭での姿を相互に伝え合う'}。"
            )
            refs = ["profile.family_collaboration_policy", "form.family_collaboration_policy"]
        else:
            body = (
                f"{term_label}の終わりに、ねらいに対する子どもの変化、環境の働き、"
                f"{health_safety or '健康と安全の配慮'}を振り返り、次期の計画へ反映する。"
            )
            refs = ["knowledge.health_and_safety", "form.health_safety_policy"]

        needs_confirmation, editor_note = _needs_note(term_note or seasonal_context or annual_events, f"{term_label}の具体情報")
        sections.append(
            _section(
                definition,
                body,
                refs,
                needs_confirmation=needs_confirmation and suffix == "outlook",
                editor_note=editor_note if suffix == "outlook" else None,
            )
        )

    return PlanDocument(
        id=0,
        document_type=DocumentType.ANNUAL_PLAN,
        title=f"{school_year}年度 年案（{class_name}）",
        status=DocumentStatus.DRAFT,
        nursery_ref=user.nursery_ref,
        classroom_ref=classroom_ref,
        actor_ref=user.actor_ref,
        owner_name=owner_name,
        school_year=school_year,
        sections=sections,
        confirmation_items=required,
    )


def generate_monthly_plan(data: dict[str, str], user: StaffUser) -> PlanDocument:
    target_month = clean_text(data.get("target_month")) or "2026-04"
    classroom_ref = clean_text(data.get("classroom_ref")) or user.classroom_refs[0]
    class_name = clean_text(data.get("class_name")) or classroom_ref or "クラス未設定"
    owner_name = clean_text(data.get("owner_name")) or user.name
    related_annual_summary = clean_text(data.get("related_annual_summary"))
    previous_reflection = clean_text(data.get("previous_reflection"))
    current_children_snapshot = clean_text(data.get("current_children_snapshot"))
    play_interests = clean_text(data.get("play_interests"))
    seasonal_context = clean_text(data.get("seasonal_context"))
    family_context = clean_text(data.get("family_context"))
    class_notes = clean_text(data.get("class_notes"))

    required = confirmation_items(
        [
            ("年間計画の関連文脈", related_annual_summary),
            ("前月の反省", previous_reflection),
            ("現在の子どもの姿", current_children_snapshot),
        ]
    )
    needs_core_confirmation = bool(required)

    definitions = {definition.key: definition for definition in MONTHLY_SECTIONS}

    sections = [
        _section(
            definitions["monthly_goal"],
            (
                f"{target_month}の{class_name}では、{related_annual_summary or '年間計画の方向性'}を踏まえ、"
                f"{previous_reflection or '前月の姿'}から見えた課題を受けて、"
                f"{current_children_snapshot or '現在の子どもの姿'}を次の経験につなげる。"
            ),
            ["annual.related_context", "monthly.previous_reflection", "form.current_children_snapshot"],
            needs_confirmation=needs_core_confirmation,
            editor_note="年間計画、前月反省、現在の姿を確認してください。" if needs_core_confirmation else None,
        ),
        _section(
            definitions["children_snapshot"],
            (
                f"現在は、{current_children_snapshot or '子どもの姿を記録してください'}。"
                f" 遊びの関心は{play_interests or '観察から追記'}し、個別差を踏まえて捉える。"
            ),
            ["form.current_children_snapshot", "form.play_interests"],
            needs_confirmation=not bool(current_children_snapshot),
            editor_note="現在の姿が未入力です。" if not current_children_snapshot else None,
        ),
        _section(
            definitions["monthly_environment"],
            (
                f"{seasonal_context or '季節や行事'}を取り入れながら、子どもが選択できる素材と場を用意する。"
                f" {play_interests or '興味のある遊び'}が広がるよう、少人数で試せる環境を整える。"
            ),
            ["form.seasonal_context", "form.play_interests", "profile.indoor_environment"],
        ),
        _section(
            definitions["monthly_support"],
            (
                "保育者は子どもの言葉、動き、関係性の変化を観察し、必要な場面で選択肢を示す。"
                f" クラス内の留意点は「{class_notes or '日々の記録から追記'}」として共有する。"
            ),
            ["profile.support_policy", "form.class_notes"],
        ),
        _section(
            definitions["monthly_health_safety"],
            (
                f"{seasonal_context or '季節や行事'}に応じて、体調確認、休息、水分補給、用具の安全点検を行う。"
                " 活動量や生活リズムの個人差を見ながら、無理なく参加できるようにする。"
            ),
            ["knowledge.health_and_safety", "form.seasonal_context"],
        ),
        _section(
            definitions["monthly_food_education"],
            (
                f"{seasonal_context or '季節'}に関わる食材や食文化に触れ、食べることへの関心を広げる。"
                " 一人ひとりの食べる意欲や体調に合わせて、楽しい雰囲気を大切にする。"
            ),
            ["knowledge.food_education", "form.seasonal_context"],
        ),
        _section(
            definitions["monthly_events"],
            (
                f"{seasonal_context or '今月の行事'}を、子どもの実態に合わせた無理のない形で取り入れる。"
                " 行事そのものよりも、準備や当日の経験を通した育ちを大切にする。"
            ),
            ["form.seasonal_context", "profile.event_policy"],
        ),
        _section(
            definitions["monthly_10_perspectives"],
            (
                "10の姿の観点から、遊びや生活の中で見られる主体性、協同性、言葉による伝え合い、"
                "豊かな感性と表現などの育ちを捉え、次の経験につなげる。"
            ),
            ["knowledge.juu_no_sugata", "linking.next_month"],
        ),
        _section(
            definitions["monthly_family_collaboration"],
            (
                f"家庭には今月のねらいと遊びの広がりを伝え、{family_context or '家庭での様子'}を聞き取る。"
                " 園と家庭で共通して見守れる姿を短く共有する。"
            ),
            ["profile.family_collaboration_policy", "form.family_context"],
        ),
        _section(
            definitions["monthly_reflection_viewpoint"],
            (
                "月末には、ねらいに対する子どもの変化、環境の働き、保育者の関わり、家庭連携の手応えを確認する。"
                " 次月へ残す課題は、具体的な場面とともに記録する。"
            ),
            ["monthly.reflection_viewpoint", "linking.next_month"],
        ),
    ]

    return PlanDocument(
        id=0,
        document_type=DocumentType.MONTHLY_PLAN,
        title=f"{target_month} 月案（{class_name}）",
        status=DocumentStatus.DRAFT,
        nursery_ref=user.nursery_ref,
        classroom_ref=classroom_ref,
        actor_ref=user.actor_ref,
        owner_name=owner_name,
        target_month=target_month,
        sections=sections,
        confirmation_items=required,
    )


def generate_weekly_plan(data: dict[str, str], user: StaffUser) -> PlanDocument:
    target_week = clean_text(data.get("target_week"))
    if not target_week:
        raise ValueError("target_week is required")
    week_start = week_start_date_from_target_week(target_week)
    school_year = school_year_from_date(week_start)
    classroom_ref = clean_text(data.get("classroom_ref")) or user.classroom_refs[0]
    class_name = clean_text(data.get("class_name")) or classroom_ref or "クラス未設定"
    age_class = clean_text(data.get("age_class"))
    owner_name = clean_text(data.get("owner_name")) or user.name
    parent_document_id = _to_int(data.get("parent_document_id"))
    related_monthly_summary = clean_text(data.get("related_monthly_summary"))
    connection_warning = clean_text(data.get("connection_warning"))
    previous_week_reflection = clean_text(data.get("previous_week_reflection"))
    current_children_snapshot = clean_text(data.get("current_children_snapshot"))
    weekly_activities_note = clean_text(data.get("weekly_activities_note"))
    seasonal_context = clean_text(data.get("seasonal_context"))
    family_context = clean_text(data.get("family_context"))
    class_notes = clean_text(data.get("class_notes"))
    include_saturday = clean_text(data.get("include_saturday")).lower() in {"on", "true", "1", "yes"}

    required = confirmation_items(
        [
            ("月案との接続", related_monthly_summary or (str(parent_document_id) if parent_document_id else "")),
            ("前週の振り返り", previous_week_reflection),
            ("現在の子どもの姿", current_children_snapshot),
        ]
    )
    if connection_warning:
        required.append(connection_warning)
    needs_core_confirmation = bool(required)
    definitions = {definition.key: definition for definition in WEEKLY_SECTIONS}

    sections = [
        _section(
            definitions["weekly_goal"],
            (
                f"{week_start.isoformat()}週の{class_name}では、"
                f"{related_monthly_summary or '月案のねらいを確認しながら'}、"
                f"{previous_week_reflection or '前週の振り返り'}と"
                f"{current_children_snapshot or '今の子どもの姿'}をつなげ、"
                "子どもが自分で選び、友だちや環境と関わって遊びを深められるようにする。"
            ),
            ["monthly.related_context", "weekly.previous_reflection", "form.current_children_snapshot"],
            needs_confirmation=needs_core_confirmation,
            editor_note="月案、前週の振り返り、現在の姿を確認してください。" if needs_core_confirmation else None,
        ),
        _section(
            definitions["weekly_children_snapshot"],
            (
                f"前週から、{current_children_snapshot or '子どもの具体的な姿を追記してください'}。"
                f" {previous_week_reflection or '印象的な場面や保育者の気づき'}をもとに、今週の環境と援助を調整する。"
            ),
            ["form.current_children_snapshot", "weekly.previous_reflection"],
            needs_confirmation=not bool(current_children_snapshot),
            editor_note="子どもの姿を具体的な場面で確認してください。" if not current_children_snapshot else None,
        ),
        _section(
            definitions["weekly_activities"],
            (
                f"主な活動・経験は、{weekly_activities_note or '子どもの興味から選べる遊びや活動'}を中心にする。"
                " 活動を決め切りすぎず、子どもの試し方や友だちとの関わりに応じて展開を変えられる余白を残す。"
            ),
            ["form.weekly_activities_note", "monthly.related_context"],
        ),
        _section(
            definitions["weekly_environment"],
            (
                f"{seasonal_context or '季節や行事、生活の流れ'}を踏まえ、子どもが見通しを持って選べる場を整える。"
                " 素材、場所、少人数で試せる空間を用意し、活動が一つに固定されないようにする。"
            ),
            ["form.seasonal_context", "profile.indoor_environment"],
        ),
        _section(
            definitions["weekly_support"],
            (
                "保育者は、子どもの言葉、表情、友だちとの関わりを観察し、必要な場面で選択肢や素材を差し出す。"
                f" クラス内で共有したい配慮は「{class_notes or '日々の記録から追記'}」として担任間で確認する。"
            ),
            ["profile.support_policy", "form.class_notes"],
        ),
        _section(
            definitions["weekly_health_safety"],
            (
                f"{seasonal_context or '季節や活動量'}に応じて、体調確認、休息、水分補給、用具や動線の安全点検を行う。"
                " 活動への参加は一人ひとりの体調と生活リズムに合わせて調整する。"
            ),
            ["knowledge.health_and_safety", "form.seasonal_context"],
        ),
        _section(
            definitions["weekly_family_collaboration"],
            (
                f"家庭には、今週大切にしたい経験と子どもの姿を簡潔に共有し、{family_context or '家庭での様子'}を聞き取る。"
                " 園と家庭で同じ姿を見守れるよう、送迎時の伝達を短く具体的にする。"
            ),
            ["profile.family_collaboration_policy", "form.family_context"],
        ),
        _section(
            definitions["weekly_reflection_viewpoint"],
            (
                "週末には、ねらいに対する子どもの変化、環境の働き、保育者の援助、家庭連携の手応えを振り返る。"
                " 次週へ残す問いを、具体的な場面とともに記録する。"
            ),
            ["weekly.reflection_viewpoint", "linking.next_week"],
        ),
    ]

    document = PlanDocument(
        id=0,
        document_type=DocumentType.WEEKLY_PLAN,
        title=f"{week_start.isoformat()}週 週案（{class_name}）",
        status=DocumentStatus.DRAFT,
        nursery_ref=user.nursery_ref,
        classroom_ref=classroom_ref,
        actor_ref=user.actor_ref,
        owner_name=owner_name,
        sections=sections,
        confirmation_items=required,
        school_year=school_year,
        target_week=target_week,
        week_start_date=week_start.isoformat(),
        age_class=age_class or None,
        parent_document_id=parent_document_id,
    )
    return attach_weekly_grid(document, include_saturday=include_saturday, weekly_activities_note=weekly_activities_note)


def generate_daily_plan(data: dict[str, str], user: StaffUser) -> PlanDocument:
    target_date = clean_text(data.get("target_date"))
    if not target_date:
        raise ValueError("target_date is required")
    try:
        date.fromisoformat(target_date)
    except ValueError as exc:
        raise ValueError("target_date must be formatted as YYYY-MM-DD") from exc
    classroom_ref = clean_text(data.get("classroom_ref")) or user.classroom_refs[0]
    class_name = clean_text(data.get("class_name")) or classroom_ref or "クラス未設定"
    age_class = clean_text(data.get("age_class"))
    owner_name = clean_text(data.get("owner_name")) or user.name
    parent_document_id = _to_int(data.get("parent_document_id"))
    related_weekly_summary = clean_text(data.get("related_weekly_summary"))
    connection_warning = clean_text(data.get("connection_warning"))
    current_children_snapshot = clean_text(data.get("current_children_snapshot"))
    daily_main_activity_note = clean_text(data.get("daily_main_activity_note"))
    seasonal_context = clean_text(data.get("seasonal_context"))
    health_notes = clean_text(data.get("health_notes"))
    family_context = clean_text(data.get("family_context"))

    required = confirmation_items(
        [
            ("週案との接続", related_weekly_summary or (str(parent_document_id) if parent_document_id else "")),
            ("前日までの子どもの姿", current_children_snapshot),
            ("本日の主な活動", daily_main_activity_note),
        ]
    )
    if connection_warning:
        required.append(connection_warning)
    if not daily_main_activity_note:
        required.append("主活動の子どもの姿と援助")
    needs_core_confirmation = bool(required)
    definitions = {definition.key: definition for definition in DAILY_SECTIONS}

    sections = [
        _section(
            definitions["daily_goal"],
            (
                f"{target_date}の{class_name}では、"
                f"{related_weekly_summary or '週案のねらいを確認しながら'}、"
                f"{current_children_snapshot or '前日までの子どもの姿'}を受けて、"
                f"{daily_main_activity_note or '本日の主な活動'}を通して子どもが自分なりに試し、表現できるようにする。"
            ),
            ["weekly.related_context", "form.current_children_snapshot", "form.daily_main_activity_note"],
            needs_confirmation=needs_core_confirmation,
            editor_note="週案、子どもの姿、主活動を確認してください。" if needs_core_confirmation else None,
        ),
        _section(
            definitions["daily_children_snapshot"],
            (
                f"前日までの姿は、{current_children_snapshot or '登園時や前日の記録から追記してください'}。"
                " その姿が本日の活動や援助にどうつながるかを確認する。"
            ),
            ["form.current_children_snapshot", "daily.observation"],
            needs_confirmation=not bool(current_children_snapshot),
            editor_note="子どもの姿を具体的な場面で確認してください。" if not current_children_snapshot else None,
        ),
        _section(
            definitions["daily_main_activity"],
            (
                f"主な活動は、{daily_main_activity_note or '子どもの興味から選ぶ活動'}。"
                " 活動の達成だけでなく、子どもが気づき、友だちと関わり、環境を使いながら深める過程を大切にする。"
            ),
            ["form.daily_main_activity_note", "weekly.related_context"],
            needs_confirmation=not bool(daily_main_activity_note),
            editor_note="本日の主な活動を確認してください。" if not daily_main_activity_note else None,
        ),
        _section(
            definitions["daily_health_safety"],
            (
                f"{health_notes or seasonal_context or '当日の体調、天候、活動量'}に応じて、"
                "視診、休息、水分補給、用具と動線の安全確認を行う。"
            ),
            ["knowledge.health_and_safety", "form.health_notes", "form.seasonal_context"],
        ),
        _section(
            definitions["daily_food_education"],
            (
                f"{seasonal_context or '季節'}に関わる食材や食事の場面を通して、"
                "食べる意欲、友だちとの会話、準備や片付けへの参加を一人ひとりのペースで支える。"
            ),
            ["knowledge.food_education", "form.seasonal_context"],
        ),
        _section(
            definitions["daily_family_collaboration"],
            (
                f"送迎時には、体調、遊びの中で見られた姿、{family_context or '家庭と共有したいこと'}を簡潔に伝える。"
                " 家庭からの情報は翌日の援助や環境構成に反映する。"
            ),
            ["profile.family_collaboration_policy", "form.family_context"],
        ),
        _section(
            definitions["daily_reflection_viewpoint"],
            (
                "保育後には、ねらいに対する子どもの姿、環境の働き、保育者の援助、個別配慮を振り返る。"
                " 翌日や次週に残す問いを、印象的な場面とともに記録する。"
            ),
            ["daily.reflection_viewpoint", "linking.next_day"],
        ),
    ]

    document = PlanDocument(
        id=0,
        document_type=DocumentType.DAILY_PLAN,
        title=f"{target_date} 日案（{class_name}）",
        status=DocumentStatus.DRAFT,
        nursery_ref=user.nursery_ref,
        classroom_ref=classroom_ref,
        actor_ref=user.actor_ref,
        owner_name=owner_name,
        sections=sections,
        confirmation_items=required,
        target_date=target_date,
        age_class=age_class or None,
        parent_document_id=parent_document_id,
    )
    return attach_daily_schedule(document, age_class, daily_main_activity_note)
