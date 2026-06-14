from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    VIEW_ONLY = "view_only"
    CAN_EDIT = "can_edit"
    ADMIN = "admin"


ROLE_LABELS: dict[Role, str] = {
    Role.VIEW_ONLY: "閲覧のみ",
    Role.CAN_EDIT: "編集可",
    Role.ADMIN: "管理者",
}


class DocumentType(StrEnum):
    ANNUAL_PLAN = "annual_plan"
    MONTHLY_PLAN = "monthly_plan"
    WEEKLY_PLAN = "weekly_plan"
    DAILY_PLAN = "daily_plan"
    INDIVIDUAL_PLAN = "individual_plan"


DOCUMENT_TYPE_LABELS: dict[DocumentType, str] = {
    DocumentType.ANNUAL_PLAN: "年案",
    DocumentType.MONTHLY_PLAN: "月案",
    DocumentType.WEEKLY_PLAN: "週案",
    DocumentType.DAILY_PLAN: "日案",
    DocumentType.INDIVIDUAL_PLAN: "個別指導計画",
}


DOCUMENT_TYPE_ALIASES = {
    "annual": DocumentType.ANNUAL_PLAN,
    "monthly": DocumentType.MONTHLY_PLAN,
    "weekly": DocumentType.WEEKLY_PLAN,
    "daily": DocumentType.DAILY_PLAN,
    "individual": DocumentType.INDIVIDUAL_PLAN,
}


class DocumentStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


STATUS_LABELS: dict[DocumentStatus, str] = {
    DocumentStatus.DRAFT: "下書き",
    DocumentStatus.IN_REVIEW: "レビュー待ち",
    DocumentStatus.APPROVED: "承認済み",
    DocumentStatus.REJECTED: "差戻し",
    DocumentStatus.ARCHIVED: "アーカイブ",
}


STATUS_ALIASES = {
    "returned": DocumentStatus.REJECTED,
}


SOURCE_REF_PREFIX_TAGS = {
    "profile.": "園方針",
    "knowledge.": "公的根拠",
    "form.": "入力",
    "annual.": "入力",
    "monthly.": "入力",
    "weekly.": "入力",
    "daily.": "入力",
    "individual.": "入力",
    "bunrei.": "文例",
    "facility.": "園文例",
    "record.daily_contact": "記録",
    "record.attendance": "記録",
    "record.health_check": "記録",
    "outline.": "AI構成",
    "linking.": "AI構成",
}


AGE_CLASS_OPTIONS: tuple[str, ...] = (
    "0歳児",
    "1歳児",
    "2歳児",
    "3歳児",
    "4歳児",
    "5歳児",
)


@dataclass(frozen=True, slots=True)
class SectionDefinition:
    key: str
    title: str
    purpose: str


ANNUAL_TERM_ORDER: tuple[tuple[str, str], ...] = (
    ("term_1", "4〜6月"),
    ("term_2", "7〜9月"),
    ("term_3", "10〜12月"),
    ("term_4", "1〜3月"),
)

ANNUAL_BASE_SECTIONS: tuple[SectionDefinition, ...] = (
    SectionDefinition("annual_goal", "年間の大きなねらい", "年間全体の軸"),
)

ANNUAL_TERM_SECTION_SUFFIXES: tuple[tuple[str, str, str], ...] = (
    ("outlook", "見通し", "各期の見通し"),
    ("environment", "環境構成", "各期の環境構成"),
    ("support", "援助", "各期の援助方針"),
    ("family_collaboration", "家庭連携", "各期の家庭との連携"),
    ("reflection_viewpoint", "振り返り観点", "各期の確認観点"),
)

MONTHLY_SECTIONS: tuple[SectionDefinition, ...] = (
    SectionDefinition("monthly_goal", "今月のねらい", "月案の中心目標"),
    SectionDefinition("children_snapshot", "子どもの姿の捉え", "現在の姿の整理"),
    SectionDefinition("monthly_environment", "環境構成", "月の環境構成"),
    SectionDefinition("monthly_support", "援助", "月の援助方針"),
    SectionDefinition("monthly_health_safety", "健康・安全への配慮", "保健・安全面の配慮"),
    SectionDefinition("monthly_food_education", "食育", "食育の視点"),
    SectionDefinition("monthly_events", "行事", "月の行事"),
    SectionDefinition("monthly_10_perspectives", "10の姿", "幼児期の終わりまでに育ってほしい姿"),
    SectionDefinition("monthly_family_collaboration", "家庭連携", "保護者との連携方針"),
    SectionDefinition("monthly_reflection_viewpoint", "月末の振り返り観点", "次月につなぐ確認観点"),
)

WEEKLY_SECTIONS: tuple[SectionDefinition, ...] = (
    SectionDefinition("weekly_goal", "今週のねらい", "月案を受けた1週間の中心目標"),
    SectionDefinition("weekly_children_snapshot", "前週の子どもの姿", "直近の姿の捉えと連続性"),
    SectionDefinition("weekly_activities", "主な活動・経験", "週内に予想または用意する活動"),
    SectionDefinition("weekly_environment", "環境構成", "週の環境構成"),
    SectionDefinition("weekly_support", "保育者の援助・配慮", "週の援助方針"),
    SectionDefinition("weekly_health_safety", "健康・安全への配慮", "保健・安全面の配慮"),
    SectionDefinition("weekly_family_collaboration", "家庭連携", "保護者との連携方針"),
    SectionDefinition("weekly_reflection_viewpoint", "週の評価・反省", "次週へつなぐ振り返り観点"),
)

DAILY_SECTIONS: tuple[SectionDefinition, ...] = (
    SectionDefinition("daily_goal", "本日のねらい", "その日の中心目標"),
    SectionDefinition("daily_children_snapshot", "前日までの子どもの姿", "直近の姿と連続性"),
    SectionDefinition("daily_main_activity", "主な活動", "中心活動とねらいとの関係"),
    SectionDefinition("daily_health_safety", "健康・安全への配慮", "当日の保健・安全"),
    SectionDefinition("daily_food_education", "食育", "給食・おやつの配慮"),
    SectionDefinition("daily_family_collaboration", "家庭連携", "送迎時の伝達など"),
    SectionDefinition("daily_reflection_viewpoint", "本日の評価・反省", "翌日・翌週へつなぐ振り返り観点"),
)

INDIVIDUAL_SECTIONS: tuple[SectionDefinition, ...] = (
    SectionDefinition("individual_children_snapshot", "前月までの子どもの姿", "前月までの姿の整理"),
    SectionDefinition("individual_goal_care", "養護のねらい", "生命の保持と情緒の安定"),
    SectionDefinition("individual_goal_education", "教育のねらい", "発達に応じた経験"),
    SectionDefinition("individual_life_rhythm", "生活リズム（食事・睡眠・排泄・遊び）", "生活リズムの把握"),
    SectionDefinition("individual_environment_support", "環境構成・援助", "個別の環境と援助"),
    SectionDefinition("individual_family_collaboration", "家庭との連携", "家庭との共有"),
    SectionDefinition("individual_reflection_viewpoint", "評価・反省", "次月へつなぐ観点"),
)


def annual_section_definitions() -> list[SectionDefinition]:
    definitions = list(ANNUAL_BASE_SECTIONS)
    for term_key, term_label in ANNUAL_TERM_ORDER:
        for suffix, short_title, purpose in ANNUAL_TERM_SECTION_SUFFIXES:
            definitions.append(
                SectionDefinition(
                    key=f"{term_key}_{suffix}",
                    title=f"{term_label}の{short_title}",
                    purpose=purpose,
                )
            )
    return definitions


def section_definitions(document_type: DocumentType) -> list[SectionDefinition]:
    if document_type == DocumentType.ANNUAL_PLAN:
        return annual_section_definitions()
    if document_type == DocumentType.MONTHLY_PLAN:
        return list(MONTHLY_SECTIONS)
    if document_type == DocumentType.WEEKLY_PLAN:
        return list(WEEKLY_SECTIONS)
    if document_type == DocumentType.DAILY_PLAN:
        return list(DAILY_SECTIONS)
    if document_type == DocumentType.INDIVIDUAL_PLAN:
        return list(INDIVIDUAL_SECTIONS)
    raise ValueError(f"Unsupported document_type: {document_type}")


def normalize_document_type(raw_value: str) -> DocumentType:
    value = (raw_value or "").strip()
    if value in DOCUMENT_TYPE_ALIASES:
        return DOCUMENT_TYPE_ALIASES[value]
    return DocumentType(value)


def normalize_status(raw_value: str) -> DocumentStatus:
    value = (raw_value or "").strip()
    if value in STATUS_ALIASES:
        return STATUS_ALIASES[value]
    return DocumentStatus(value)


def evidence_tags_for(source_refs: list[str]) -> list[str]:
    tags: list[str] = []
    for source_ref in source_refs:
        for prefix, tag in SOURCE_REF_PREFIX_TAGS.items():
            if source_ref.startswith(prefix) and tag not in tags:
                tags.append(tag)
    return tags or ["入力"]
