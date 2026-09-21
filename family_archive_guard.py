"""Require audited transitions for archive state, while allowing ordinary use."""

from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from models import Family


@event.listens_for(Session, "before_flush")
def protect_archive_transitions(session, flush_context, instances):
    if session.info.get("family_archive_transition"):
        return
    for family in session.new | session.dirty:
        if not isinstance(family, Family):
            continue
        state = inspect(family)
        if (family in session.new and family.archived_at is not None) or (
            state.persistent and state.attrs.archived_at.history.has_changes()
        ):
            raise HTTPException(409, "アーカイブ確認画面から操作してください。")
