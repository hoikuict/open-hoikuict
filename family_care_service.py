"""Family-managed recognition, materialized as dated child records for billing.

No fee rows are changed here. Common records are never resolved dynamically from
today's family relationship: each child's historical snapshot keeps its source.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json

from fastapi import HTTPException
from sqlmodel import select

from child_care_certification_service import (
    certification_snapshot, create_certification, deactivate_certification,
    list_certifications,
)
from models import (
    CareNeedReason, CareTimeCategory, Child, ChildCareCertification,
    ChildCareCertificationAuditLog, FamilyCareAudit,
    FamilyCareCertification, FamilyCareCertificationLink, FamilyCareChildSetting,
)
from time_utils import local_today, utc_now

TABLES = (FamilyCareCertification, FamilyCareChildSetting,
          FamilyCareCertificationLink, FamilyCareAudit)


def blank():
    return dict(category="", **{"from": "", "to": ""}, reason1="", other1="",
                reason2="", other2="", note="")


def child_plan(cert):
    if cert is None:
        return None
    result = dict(blank(), category=cert.care_time_category.value,
                  **{"from": cert.effective_from.isoformat(),
                     "to": cert.effective_to.isoformat() if cert.effective_to else ""},
                  note=cert.internal_note or "")
    for item in cert.reasons:
        if item.guardian_order in (1, 2):
            result[f"reason{item.guardian_order}"] = item.reason.value
            result[f"other{item.guardian_order}"] = item.other_reason_detail or ""
    return result


def family_records(session, family_id):
    return list(session.exec(select(FamilyCareCertification).where(
        FamilyCareCertification.family_id == family_id).order_by(
        FamilyCareCertification.effective_from.desc(), FamilyCareCertification.id.desc())).all())


def latest_common(session, family_id):
    records = family_records(session, family_id)
    # A cancelled latest period must not revive an older, ended recognition.
    return records[0] if records and records[0].is_active else None


def latest_child(session, child_id):
    return next((r for r in list_certifications(session, child_id) if r.is_active), None)


def child_care_context(session, child):
    """Read-only detail context; sources describe snapshots, not today's family."""
    certs = list_certifications(session, child.id)
    setting = session.get(FamilyCareChildSetting, child.id)
    sources = {}
    for cert in certs:
        link = session.get(FamilyCareCertificationLink, cert.id)
        source = session.get(FamilyCareCertification, link.family_certification_id) if link else None
        sources[cert.id] = ("家族共通" if source.family_id == child.family_id else "以前の家族共通") if source else "園児個別設定"
    return dict(care_sources=sources,
        care_mode_label="家族共通を使用中" if setting and setting.family_id == child.family_id and setting.mode == "inherit" else "園児個別設定" if certs else "未設定",
        care_edit_url=f"/families/{child.family_id}/care-certifications#child-{child.id}" if child.family_id else f"/children/{child.id}/care-certifications")


def bootstrap(session, family):
    members = list(session.exec(select(Child).where(Child.family_id == family.id).order_by(Child.id)).all())
    records = family_records(session, family.id)
    common = latest_common(session, family.id)
    state = dict(common=deepcopy(common.data) if common else None, children={}, history=[], childHistory={})
    children, revisions = [], []
    for child in members:
        setting = session.get(FamilyCareChildSetting, child.id)
        if setting and setting.family_id != family.id:
            raise HTTPException(409, "家族の紐づけを確認してください。")
        certs = list_certifications(session, child.id)
        cert = next((r for r in certs if r.is_active), None)
        mode = setting.mode if setting else ("individual" if cert else "inherit")
        state["children"][str(child.id)] = dict(mode=mode, cert=child_plan(cert))
        sources = child_care_context(session, child)["care_sources"]
        state["childHistory"][str(child.id)] = [dict(id=r.id, cert=child_plan(r), active=r.is_active,
            source=sources[r.id], reasons=[dict(name=x.guardian_name_snapshot,
                relationship=x.relationship_snapshot, label=x.reason.label, other=x.other_reason_detail or "") for x in r.reasons],
            canDeactivate=bool(r.is_active and mode == "individual" and not session.get(FamilyCareCertificationLink, r.id))) for r in certs]
        excluded = bool(child.withdrawal_date and child.withdrawal_date < local_today())
        children.append(dict(id=str(child.id), name=child.full_name,
            classroom=child.classroom.name if child.classroom else "クラス未設定",
            enrolled=child.enrollment_date.isoformat(),
            left=child.withdrawal_date.isoformat() if child.withdrawal_date else "",
            joined=setting.joined_on.isoformat() if setting else child.enrollment_date.isoformat(),
            excluded=excluded, status="卒園・退園" if excluded else "入園予定" if child.enrollment_date > local_today() else "在園"))
        revisions.append(dict(child=child.model_dump(mode="json"),
            setting=setting.model_dump(mode="json") if setting else None,
            certs=[dict(id=r.id, **certification_snapshot(r)) for r in certs]))
    for record in records:
        state["history"].append(dict(name="家族共通", cert=record.data,
            text="登録済み" if record.is_active else "無効化済み",
            active=bool(common and record.id == common.id)))
    for audit in session.exec(select(FamilyCareAudit).where(FamilyCareAudit.family_id == family.id)
                              .order_by(FamilyCareAudit.id.desc()).limit(30)).all():
        state["history"].append(dict(name="変更記録", cert=audit.after_snapshot.get("common") or blank(),
            text=f"{audit.created_at.isoformat()} ／ {audit.actor_name} ／ {audit.reason or audit.action}", active=False))
    profiles = family.guardian_profiles()[:2]
    guardians = [dict(name=f"{p.get('last_name', '')} {p.get('first_name', '')}".strip() or f"保護者{i}",
                     relationship=p.get("relationship", "")) for i, p in enumerate(profiles, 1)]
    if not guardians:
        guardians = [dict(name="保護者1", relationship="")]
    token_data = dict(family=family.model_dump(mode="json"), members=revisions,
                      records=[r.model_dump(mode="json") for r in records])
    revision = hashlib.sha256(json.dumps(token_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return dict(familyId=family.id, familyName=family.identity_label, children=children,
                guardians=guardians, store=state, revision=revision, today=local_today().isoformat())


def normalize(raw, guardians, label):
    if not isinstance(raw, dict):
        raise ValueError(f"{label}の入力が不正です。")
    result = {k: str(raw.get(k) or "").strip() for k in blank()}
    try:
        CareTimeCategory(result["category"])
        start = date.fromisoformat(result["from"])
        end = date.fromisoformat(result["to"]) if result["to"] else None
    except ValueError:
        raise ValueError(f"{label}の保育必要量・適用期間を正しく入力してください。") from None
    if end and end < start:
        raise ValueError(f"{label}の適用終了日は開始日以降にしてください。")
    if len(result["note"]) > 500:
        raise ValueError("施設内メモは500文字以内にしてください。")
    for i in (1, 2):
        if i > len(guardians) and not result[f"reason{i}"]:
            continue
        try:
            reason = CareNeedReason(result[f"reason{i}"])
        except ValueError:
            raise ValueError(f"{label}：保護者{i}の事由を選択してください。") from None
        if reason == CareNeedReason.other_municipal and not result[f"other{i}"]:
            raise ValueError(f"{label}：保護者{i}のその他事由を入力してください。")
        if len(result[f"other{i}"]) > 200:
            raise ValueError("その他事由は200文字以内にしてください。")
        if reason != CareNeedReason.other_municipal:
            result[f"other{i}"] = ""
    return result


def _end_record(session, cert, end, actor, reason):
    before = certification_snapshot(cert)
    if end < cert.effective_from:
        deactivate_certification(session, cert, reason=reason,
            actor_user_id=actor.user_id, actor_name=actor.name)
        return
    cert.effective_to = end
    cert.updated_at = utc_now()
    cert.updated_by_name, cert.updated_by_user_id = actor.name, actor.user_id
    session.add(cert)
    session.add(ChildCareCertificationAuditLog(certification_id=cert.id, child_id=cert.child_id,
        action="period_ended", before_snapshot=before, after_snapshot=certification_snapshot(cert),
        reason=reason, executed_by_user_id=actor.user_id, executed_by_name=actor.name))


def materialize(session, child, plan, guardians, actor, reason, source=None, floor=None):
    start = max(date.fromisoformat(plan["from"]), child.enrollment_date, floor or date.min)
    ends = [d for d in (date.fromisoformat(plan["to"]) if plan["to"] else None, child.withdrawal_date) if d]
    end = min(ends) if ends else None
    if end and start > end:
        return
    desired = dict(plan, **{"from": start.isoformat(), "to": end.isoformat() if end else ""})
    existing = [r for r in list_certifications(session, child.id) if r.is_active]
    latest = existing[0] if existing else None
    if latest and child_plan(latest) == desired:
        # Even identical values need an explicit source when switching mode.
        link = session.get(FamilyCareCertificationLink, latest.id)
        if (source is None and link is None) or (source and link and link.family_certification_id == source.id):
            return
    if any(r.effective_from > start for r in existing):
        raise ValueError(f"{child.full_name}には開始日より後の認定があります。開始日を確認してください。")
    for record in existing:
        if record.effective_to is None or record.effective_to >= start:
            _end_record(session, record, start - timedelta(days=1), actor, reason)
    rows = []
    for i in (1, 2):
        if not plan[f"reason{i}"]:
            continue
        profile = guardians[i-1] if i <= len(guardians) else dict(name=f"保護者{i}", relationship="")
        rows.append(dict(guardian_order=i, guardian_name_snapshot=profile["name"],
            relationship_snapshot=profile["relationship"], reason=CareNeedReason(plan[f"reason{i}"]),
            other_reason_detail=plan[f"other{i}"]))
    cert = create_certification(session, child=child, care_time_category=CareTimeCategory(plan["category"]),
        effective_from=start, effective_to=end, internal_note=plan["note"], guardian_reasons=rows,
        actor_user_id=actor.user_id, actor_name=actor.name)
    if source:
        session.add(FamilyCareCertificationLink(certification_id=cert.id, family_certification_id=source.id))
    session.flush()


def save_family(session, family, payload, actor):
    before = bootstrap(session, family)
    if payload.get("revision") != before["revision"]:
        raise HTTPException(409, "別の画面で家族・園児・認定が更新されています。入力を控えて再読み込みしてください。")
    reason = str(payload.get("editReason") or "").strip()
    operation = payload.get("operation")
    if operation not in ("new", "correct") or len(reason) > 500:
        raise ValueError("登録方法・訂正理由を確認してください。")
    draft = payload.get("draft")
    if not isinstance(draft, dict) or not isinstance(draft.get("children"), dict):
        raise ValueError("入力の形式が不正です。")
    if set(draft["children"]) != set(before["store"]["children"]):
        raise ValueError("反映対象が変わりました。画面を再読み込みしてください。")
    plan = normalize(draft.get("common"), before["guardians"], "家族共通")
    start = date.fromisoformat(plan["from"])
    common = latest_common(session, family.id)
    records = family_records(session, family.id)
    if operation == "correct":
        if not common or not reason or start != common.effective_from:
            raise ValueError("訂正理由を入力してください。登録済み期間の開始日は変更できません。")
    elif records and (start < records[0].effective_from or (common and start == common.effective_from)):
        raise ValueError("新しい期間は登録済み期間の開始日より後にしてください。")
    # Validate every child's payload before modifying any record.
    normalized = {}
    individual_reasons = payload.get("individualReasons") or {}
    if not isinstance(individual_reasons, dict) or any(not isinstance(v, str) or len(v) > 500 for v in individual_reasons.values()):
        raise ValueError("園児個別の訂正理由は500文字以内にしてください。")
    for item in before["children"]:
        entry = draft["children"][item["id"]]
        if not isinstance(entry, dict) or entry.get("mode") not in ("inherit", "individual"):
            raise ValueError("園児の設定方法が不正です。")
        if item["excluded"]:
            continue
        old_entry = before["store"]["children"][item["id"]]
        unchanged_individual = entry["mode"] == old_entry["mode"] == "individual" and (entry.get("cert") or blank()) == (old_entry["cert"] or blank())
        normalized[item["id"]] = dict(mode=entry["mode"], cert=deepcopy(old_entry["cert"]) if unchanged_individual else normalize(entry.get("cert"),
            before["guardians"], item["name"]) if entry["mode"] == "individual" else None)
    if operation == "new":
        if common and (common.effective_to is None or common.effective_to >= start):
            common.effective_to = start - timedelta(days=1)
            common.data = dict(common.data, to=common.effective_to.isoformat())
            common.updated_at = utc_now()
            session.add(common)
        common = FamilyCareCertification(family_id=family.id, effective_from=start, data=plan)
    common.data = plan
    common.effective_to = date.fromisoformat(plan["to"]) if plan["to"] else None
    common.updated_at = utc_now()
    session.add(common)
    session.flush()
    for item in before["children"]:
        if item["excluded"]:
            continue
        child = session.get(Child, int(item["id"]))
        entry = normalized[item["id"]]
        setting = session.get(FamilyCareChildSetting, child.id)
        if setting is None:
            setting = FamilyCareChildSetting(child_id=child.id, family_id=family.id,
                mode=entry["mode"], joined_on=child.enrollment_date)
        setting.mode = entry["mode"]
        session.add(setting)
        old = before["store"]["children"][item["id"]]
        if entry["mode"] == "individual" and old["mode"] == "individual" and entry["cert"] == old["cert"]:
            continue
        if entry["mode"] == "inherit":
            # End prior common snapshots even if the new period finishes before
            # this child's enrollment. An expired period must never fall back.
            boundary = max(start, setting.joined_on)
            for cert in list_certifications(session, child.id):
                link = session.get(FamilyCareCertificationLink, cert.id)
                source_record = session.get(FamilyCareCertification, link.family_certification_id) if link else None
                if cert.is_active and source_record and source_record.family_id == family.id and (cert.effective_to is None or cert.effective_to >= boundary):
                    _end_record(session, cert, boundary - timedelta(days=1), actor, reason or "家族共通認定の期間切替")
        materialize(session, child, entry["cert"] if entry["mode"] == "individual" else plan,
            before["guardians"], actor, (individual_reasons.get(item["id"], "").strip() if entry["mode"] == "individual" else "") or reason or "家族認定画面から登録・切替",
            source=common if entry["mode"] == "inherit" else None, floor=setting.joined_on)
    session.flush()
    after = bootstrap(session, family)
    session.add(FamilyCareAudit(family_id=family.id, action=operation,
        before_snapshot=before["store"], after_snapshot=after["store"], reason=reason,
        actor_name=actor.name, actor_user_id=actor.user_id))
    return after


def deactivate_family(session, family, payload, actor):
    before = bootstrap(session, family)
    if payload.get("revision") != before["revision"]:
        raise HTTPException(409, "設定が更新されています。画面を再読み込みしてください。")
    reason = str(payload.get("reason") or "").strip()
    if not reason or len(reason) > 500:
        raise ValueError("無効化理由を500文字以内で入力してください。")
    common = latest_common(session, family.id)
    if not common:
        raise ValueError("無効化できる共通認定がありません。")
    for link in session.exec(select(FamilyCareCertificationLink).where(
            FamilyCareCertificationLink.family_certification_id == common.id)).all():
        cert = session.get(ChildCareCertification, link.certification_id)
        child = session.get(Child, cert.child_id) if cert else None
        setting = session.get(FamilyCareChildSetting, cert.child_id) if cert else None
        if cert and cert.is_active and child and child.family_id == family.id and setting and setting.mode == "inherit":
            deactivate_certification(session, cert, reason=reason,
                actor_user_id=actor.user_id, actor_name=actor.name)
    common.is_active = False
    common.updated_at = utc_now()
    session.add(common)
    session.flush()
    after = bootstrap(session, family)
    session.add(FamilyCareAudit(family_id=family.id, action="deactivated", before_snapshot=before["store"],
        after_snapshot=after["store"], reason=reason, actor_name=actor.name, actor_user_id=actor.user_id))
    return after


def require_individual_mode(session, child_id):
    setting = session.get(FamilyCareChildSetting, child_id)
    if setting and setting.mode == "inherit":
        raise HTTPException(409, "家族共通の保育認定画面から変更してください。園児だけ変える場合は個別設定を選びます。")


def update_individual(session, family, payload, actor, *, deactivate=False):
    """Save one child without creating/changing a common period or sibling."""
    before = bootstrap(session, family)
    if payload.get("revision") != before["revision"]:
        raise HTTPException(409, "設定が更新されています。入力を控えて再読み込みしてください。")
    child_id = str(payload.get("childId", ""))
    if child_id not in before["store"]["children"]:
        raise HTTPException(404, "この家族の園児が見つかりません。")
    child = session.get(Child, int(child_id))
    reason = str(payload.get("reason") or "").strip()
    if len(reason) > 500:
        raise ValueError("理由は500文字以内にしてください。")
    old = before["store"]["children"][child_id]
    if deactivate:
        require_individual_mode(session, child.id)
        record = next((r for r in list_certifications(session, child.id) if str(r.id) == str(payload.get("certificationId"))), None)
        if not record or not record.is_active:
            raise ValueError("無効化できる認定がありません。")
        if session.get(FamilyCareCertificationLink, record.id):
            raise ValueError("家族共通から反映した認定は、家族共通の操作から変更してください。")
        deactivate_certification(session, record, reason=reason,
            actor_user_id=actor.user_id, actor_name=actor.name)
    else:
        plan = normalize(payload.get("cert"), before["guardians"], child.full_name)
        start = date.fromisoformat(plan["from"])
        end = date.fromisoformat(plan["to"]) if plan["to"] else None
        member = next(i for i in before["children"] if i["id"] == child_id)
        floor = max(child.enrollment_date, date.fromisoformat(member["joined"]))
        effective_start = max(start, floor)
        ends = [d for d in (end, child.withdrawal_date) if d]
        effective_end = min(ends) if ends else None
        if effective_end and effective_start > effective_end:
            raise ValueError("在籍している期間を指定してください。")
        records = [r for r in list_certifications(session, child.id) if r.is_active]
        overlaps = [r for r in records if max(start, floor) <= (r.effective_to or date.max) and r.effective_from <= (end or date.max)]
        if overlaps and old["mode"] == "individual" and plan != old["cert"] and start <= max(r.effective_from for r in overlaps) and not reason:
            raise ValueError("登録済みの認定を訂正する場合は訂正理由を入力してください。")
        if any(r.effective_from > max(start, floor) for r in records):
            # Preserve the old editor's ability to fill an earlier, non-overlapping period.
            if overlaps or old["mode"] != "individual":
                raise ValueError("後の期間に登録済みの認定があります。重複しない適用期間を指定してください。")
            rows = [dict(guardian_order=i, guardian_name_snapshot=before["guardians"][i-1]["name"] if i <= len(before["guardians"]) else f"保護者{i}",
                relationship_snapshot=before["guardians"][i-1]["relationship"] if i <= len(before["guardians"]) else "",
                reason=CareNeedReason(plan[f"reason{i}"]), other_reason_detail=plan[f"other{i}"]) for i in (1, 2) if plan[f"reason{i}"]]
            create_certification(session, child=child, care_time_category=CareTimeCategory(plan["category"]),
                effective_from=effective_start, effective_to=effective_end,
                internal_note=plan["note"], guardian_reasons=rows, actor_user_id=actor.user_id, actor_name=actor.name)
        else:
            materialize(session, child, plan, before["guardians"], actor,
                reason or "園児個別の認定を登録", floor=floor)
    setting = session.get(FamilyCareChildSetting, child.id)
    if setting is None:
        setting = FamilyCareChildSetting(child_id=child.id, family_id=family.id, joined_on=child.enrollment_date)
    setting.mode = "individual"
    session.add(setting)
    session.flush()
    after = bootstrap(session, family)
    session.add(FamilyCareAudit(family_id=family.id, action="individual_deactivated" if deactivate else "individual_saved",
        before_snapshot=before["store"], after_snapshot=after["store"], reason=reason,
        actor_name=actor.name, actor_user_id=actor.user_id))
    return after
