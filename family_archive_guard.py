"""One write boundary for archived families, independent of HTTP entry points."""

from fastapi import HTTPException
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from models import (
    Child,
    Family,
    Guardian,
    ParentAccount,
    ParentChildLink,
    ParentEnrollment,
)


MESSAGE = "アーカイブ済みの家庭です。家族一覧から使用中に戻してから変更してください。"


def require_active_family(session, family_id):
    if family_id is not None:
        # Read the database, not a possibly stale ORM object.
        archived = (
            session.connection()
            .execute(select(Family.archived_at).where(Family.id == family_id))
            .scalar_one_or_none()
        )
        if archived is not None:
            raise HTTPException(409, MESSAGE)


@event.listens_for(Session, "before_flush")
def protect_archived_families(session, flush_context, instances):
    """Do not hide historical rows; reject ledger edits and new associations."""
    if session.info.get("family_archive_transition"):
        return
    pending = session.new | session.dirty | session.deleted
    guarded = (
        Family,
        Child,
        ParentAccount,
        Guardian,
        ParentChildLink,
        ParentEnrollment,
    )
    if not any(isinstance(obj, guarded) for obj in pending):
        return
    connection = session.connection()
    if (
        connection.dialect.name == "sqlite"
        and not connection.connection.driver_connection.in_transaction
    ):
        # Hold the same writer lock as archive/restore until flush and commit.
        # A read followed by an INSERT without this lock could race an archive.
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    for obj in pending:
        state = inspect(obj)
        if obj in session.dirty and not session.is_modified(
            obj, include_collections=False
        ):
            continue
        ids = set()
        if isinstance(obj, Family):
            if state.persistent:
                require_active_family(session, obj.id)
                if state.attrs.archived_at.history.has_changes():
                    raise HTTPException(409, "アーカイブ確認画面から操作してください。")
        elif isinstance(obj, (Child, ParentAccount)):
            ids.add(obj.family_id)
            ids.update(state.attrs.family_id.history.deleted)
            if state.persistent:
                ids.add(
                    session.connection()
                    .execute(select(type(obj).family_id).where(type(obj).id == obj.id))
                    .scalar_one_or_none()
                )
        elif isinstance(obj, (Guardian, ParentChildLink)):
            child_ids = {obj.child_id, *state.attrs.child_id.history.deleted}
            for child_id in child_ids:
                ids.add(
                    session.connection()
                    .execute(select(Child.family_id).where(Child.id == child_id))
                    .scalar_one_or_none()
                )
            if isinstance(obj, ParentChildLink):
                account_ids = {
                    obj.parent_account_id,
                    *state.attrs.parent_account_id.history.deleted,
                }
                if state.persistent:
                    account_ids.add(
                        session.connection()
                        .execute(
                            select(ParentChildLink.parent_account_id).where(
                                ParentChildLink.id == obj.id
                            )
                        )
                        .scalar_one_or_none()
                    )
                for account_id in account_ids:
                    ids.add(
                        session.connection()
                        .execute(
                            select(ParentAccount.family_id).where(
                                ParentAccount.id == account_id
                            )
                        )
                        .scalar_one_or_none()
                    )
        elif isinstance(obj, ParentEnrollment):
            # Existing intake snapshots are historical and remain readable.
            if obj in session.new or state.attrs.applied_at.history.has_changes():
                snapshot = obj.source_snapshot or {}
                ids.add(snapshot.get("family_id"))
                if obj.child_id:
                    ids.add(
                        session.connection()
                        .execute(
                            select(Child.family_id).where(Child.id == obj.child_id)
                        )
                        .scalar_one_or_none()
                    )
        for family_id in ids:
            require_active_family(session, family_id)
