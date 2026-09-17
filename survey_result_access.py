"""Explicit per-survey result access, independent of the answer audience."""
from fastapi import HTTPException
from sqlmodel import Session, select

from models import SurveyResultViewer


def can_view_survey_results(session: Session, survey_id: int, user) -> bool:
    return user.is_admin or bool(user.user_id and session.get(SurveyResultViewer, (survey_id, user.user_id)))


def require_survey_results(session: Session, survey_id: int, user) -> None:
    if not can_view_survey_results(session, survey_id, user):
        raise HTTPException(403, "このアンケートの結果を閲覧する権限がありません")


def viewer_ids(session: Session, survey_id: int) -> set[str]:
    return {str(value) for value in session.exec(select(SurveyResultViewer.user_id).where(
        SurveyResultViewer.survey_id == survey_id)).all()}
