from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re
from typing import Optional
import uuid

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from billing_calculation_service import recalculate_claim_total
from extended_care_fee_service import parse_month
from models import (
    BillingChargeLine,
    BillingChargeSourceType,
    BillingClaim,
    BillingClaimStatus,
    BillingCycle,
    BillingCycleStatus,
    BillingPaymentMethod,
    Child,
    ExtendedCareBillingSetting,
    ExtendedCareBillingTransferLog,
    ExtendedCareCharge,
    ExtendedCareChargeStatus,
    FamilyBillingProfile,
    FeeItem,
)
from time_utils import utc_now


EDITABLE_CYCLE_STATUSES = {
    BillingCycleStatus.draft,
    BillingCycleStatus.generated,
    BillingCycleStatus.confirmed,
}
TRANSFERABLE_CHARGE_STATUSES = {
    ExtendedCareChargeStatus.confirmed,
    ExtendedCareChargeStatus.manual_adjusted,
}
DEFAULT_FEE_ITEM_CODE = "monthly_childcare"
DEFAULT_DESCRIPTION_TEMPLATE = "延長保育料（{year}年{month}月分）"


class ExtendedCareBillingTransferError(ValueError):
    pass


@dataclass(slots=True)
class ExtendedCareTransferChildPreview:
    child_id: int
    child_name: str
    classroom_name: str
    family_id: Optional[int]
    charge_count: int
    extended_minutes: int
    target_amount: int
    current_amount: int
    difference: int
    state: str
    errors: list[str] = field(default_factory=list)
    charges: list[ExtendedCareCharge] = field(default_factory=list, repr=False)
    existing_line_id: Optional[int] = None

    @property
    def has_changes(self) -> bool:
        return self.difference != 0 or any(
            charge.billing_charge_line_id is None for charge in self.charges
        )

    @property
    def needs_billing_correction(self) -> bool:
        return any("手入力の延長保育料" in error for error in self.errors)


@dataclass(slots=True)
class ExtendedCareTransferPreview:
    month: str
    start_date: date
    end_date: date
    setting: ExtendedCareBillingSetting
    cycle: Optional[BillingCycle]
    child_rows: list[ExtendedCareTransferChildPreview]
    errors: list[str]
    warnings: list[str]
    unconfirmed_count: int
    excluded_count: int
    zero_count: int
    transferred_charge_count: int
    target_charge_count: int
    target_child_count: int
    target_amount: int
    current_amount: int

    @property
    def can_transfer(self) -> bool:
        return bool(
            self.setting.is_enabled
            and self.cycle is not None
            and not self.errors
            and self.child_rows
        )

    @property
    def has_existing_transfer(self) -> bool:
        return self.transferred_charge_count > 0 or any(
            row.existing_line_id is not None for row in self.child_rows
        )

    @property
    def has_changes(self) -> bool:
        return any(row.has_changes for row in self.child_rows)

    @property
    def status_label(self) -> str:
        if self.errors:
            return "転送不可"
        if not self.has_existing_transfer:
            return "未転送"
        if self.has_changes:
            return "差分あり"
        return "転送済み"


@dataclass(slots=True)
class ExtendedCareTransferResult:
    action: str
    affected_child_count: int
    affected_charge_count: int
    total_amount: int
    changed_child_ids: list[int]

    @property
    def changed(self) -> bool:
        return self.action in {"transfer", "retransfer", "revert"}


def get_extended_care_billing_setting(session: Session) -> ExtendedCareBillingSetting:
    setting = session.exec(
        select(ExtendedCareBillingSetting).order_by(ExtendedCareBillingSetting.id)
    ).first()
    if setting is not None:
        return setting
    return ExtendedCareBillingSetting(
        is_enabled=False,
        fee_item_code=DEFAULT_FEE_ITEM_CODE,
        description_template=DEFAULT_DESCRIPTION_TEMPLATE,
    )


def validate_extended_care_billing_setting(
    *,
    fee_item_code: str,
    description_template: str,
) -> list[str]:
    errors: list[str] = []
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", fee_item_code):
        errors.append("請求費目コードは英小文字、数字、ハイフン、アンダースコアで入力してください。")
    if not description_template.strip():
        errors.append("明細名テンプレートを入力してください。")
    elif len(description_template) > 200:
        errors.append("明細名テンプレートは200文字以内で入力してください。")
    else:
        try:
            description_template.format(year=2026, month=3)
        except (KeyError, ValueError):
            errors.append("明細名テンプレートでは {year} と {month} だけを使用できます。")
    return errors


def build_extended_care_transfer_preview(
    session: Session,
    month: str,
) -> ExtendedCareTransferPreview:
    normalized_month, start_date, end_date = parse_month(month)
    setting = get_extended_care_billing_setting(session)
    errors: list[str] = []
    warnings: list[str] = []

    if not setting.is_enabled:
        errors.append("延長保育料金の請求連携が無効です。")

    cycle = session.exec(
        select(BillingCycle).where(BillingCycle.year_month == normalized_month)
    ).first()
    if cycle is None:
        errors.append("先に対象月の請求月を作成してください。")
    elif cycle.status not in EDITABLE_CYCLE_STATUSES:
        errors.append("全銀データ作成後の請求月は変更できません。")

    charges = session.exec(
        select(ExtendedCareCharge).where(
            ExtendedCareCharge.target_date >= start_date,
            ExtendedCareCharge.target_date <= end_date,
        )
    ).all()
    child_ids = sorted({charge.child_id for charge in charges})
    children = []
    if child_ids:
        children = session.exec(
            select(Child)
            .where(Child.id.in_(child_ids))
            .options(selectinload(Child.classroom))
        ).all()
    children_by_id = {child.id: child for child in children if child.id is not None}

    fee_item = session.exec(
        select(FeeItem).where(FeeItem.code == setting.fee_item_code)
    ).first()
    claims_by_family: dict[int, BillingClaim] = {}
    lines_by_child: dict[int, list[BillingChargeLine]] = {}
    if cycle is not None:
        claims = session.exec(
            select(BillingClaim).where(BillingClaim.billing_cycle_id == cycle.id)
        ).all()
        claims_by_family = {claim.family_id: claim for claim in claims}
        claim_ids = [claim.id for claim in claims if claim.id is not None]
        if fee_item is not None and claim_ids:
            lines = session.exec(
                select(BillingChargeLine).where(
                    BillingChargeLine.billing_claim_id.in_(claim_ids),
                    BillingChargeLine.fee_item_id == fee_item.id,
                )
            ).all()
            for line in lines:
                if line.child_id is not None:
                    lines_by_child.setdefault(line.child_id, []).append(line)

    grouped: dict[int, list[ExtendedCareCharge]] = {}
    unconfirmed_count = 0
    excluded_count = 0
    zero_count = 0
    transferred_charge_count = 0

    for charge in charges:
        child = children_by_id.get(charge.child_id)
        child_label = child.full_name if child else f"園児ID {charge.child_id}"
        if charge.billing_charge_line_id is not None:
            transferred_charge_count += 1
            if (
                charge.status not in TRANSFERABLE_CHARGE_STATUSES
                or charge.final_amount <= 0
                or charge.transferred_amount != charge.final_amount
            ):
                errors.append(
                    f"{child_label} の転送済み料金が転送時点の内容と一致しません。転送を解除してから修正してください。"
                )

        if charge.status == ExtendedCareChargeStatus.draft:
            if charge.final_amount > 0:
                unconfirmed_count += 1
                errors.append(f"{child_label} に未確認の延長保育料金があります。")
            else:
                zero_count += 1
            continue
        if charge.status == ExtendedCareChargeStatus.excluded:
            excluded_count += 1
            continue
        if charge.final_amount <= 0:
            zero_count += 1
            continue
        if charge.status not in TRANSFERABLE_CHARGE_STATUSES:
            continue
        grouped.setdefault(charge.child_id, []).append(charge)

    child_rows: list[ExtendedCareTransferChildPreview] = []
    for child_id, child_charges in sorted(grouped.items()):
        child = children_by_id.get(child_id)
        row_errors: list[str] = []
        if child is None:
            row_errors.append("園児情報が見つかりません。")
            child_name = f"園児ID {child_id}"
            classroom_name = ""
            family_id = None
        else:
            child_name = child.full_name
            classroom_name = child.classroom.name if child.classroom else ""
            family_id = child.family_id
            if family_id is None:
                row_errors.append("家族情報が設定されていません。")

        expected_reference = (
            _source_reference(cycle.id, child_id)
            if cycle is not None and cycle.id is not None
            else ""
        )
        related_lines = lines_by_child.get(child_id, [])
        existing_line = next(
            (line for line in related_lines if line.source_reference == expected_reference),
            None,
        )
        manual_lines = [
            line
            for line in related_lines
            if line.id != (existing_line.id if existing_line else None)
            and line.source_type != BillingChargeSourceType.extension_auto
        ]
        if manual_lines:
            manual_amount = sum(line.amount for line in manual_lines)
            row_errors.append(f"手入力の延長保育料 {manual_amount:,}円と競合しています。")

        if existing_line is not None and (
            existing_line.source_type != BillingChargeSourceType.extension_auto
            or not existing_line.is_locked
        ):
            row_errors.append("既存の転送明細の状態が不正です。")

        target_amount = sum(charge.final_amount for charge in child_charges)
        current_amount = existing_line.amount if existing_line else 0
        for charge in child_charges:
            if charge.billing_charge_line_id is None:
                continue
            if existing_line is None or charge.billing_charge_line_id != existing_line.id:
                row_errors.append("別の請求明細に転送済みの料金が含まれています。")
                break

        if row_errors:
            state = "転送不可"
            errors.extend(f"{child_name}: {message}" for message in row_errors)
        elif existing_line is None:
            state = "新規"
        elif target_amount == current_amount and all(
            charge.billing_charge_line_id == existing_line.id for charge in child_charges
        ):
            state = "変更なし"
        else:
            state = "更新"

        child_rows.append(
            ExtendedCareTransferChildPreview(
                child_id=child_id,
                child_name=child_name,
                classroom_name=classroom_name,
                family_id=family_id,
                charge_count=len(child_charges),
                extended_minutes=sum(charge.extended_minutes for charge in child_charges),
                target_amount=target_amount,
                current_amount=current_amount,
                difference=target_amount - current_amount,
                state=state,
                errors=row_errors,
                charges=child_charges,
                existing_line_id=existing_line.id if existing_line else None,
            )
        )

    if not child_rows and not errors:
        errors.append("転送対象の延長保育料金がありません。")
    if zero_count:
        warnings.append(f"0円の料金 {zero_count}件は転送対象外です。")
    if excluded_count:
        warnings.append(f"対象外の料金 {excluded_count}件は転送しません。")

    return ExtendedCareTransferPreview(
        month=normalized_month,
        start_date=start_date,
        end_date=end_date,
        setting=setting,
        cycle=cycle,
        child_rows=child_rows,
        errors=_deduplicate(errors),
        warnings=warnings,
        unconfirmed_count=unconfirmed_count,
        excluded_count=excluded_count,
        zero_count=zero_count,
        transferred_charge_count=transferred_charge_count,
        target_charge_count=sum(row.charge_count for row in child_rows),
        target_child_count=len(child_rows),
        target_amount=sum(row.target_amount for row in child_rows),
        current_amount=sum(row.current_amount for row in child_rows),
    )


def transfer_extended_care_charges(
    session: Session,
    month: str,
    *,
    executed_by_user_id: Optional[uuid.UUID],
    executed_by_name: str,
) -> ExtendedCareTransferResult:
    preview = build_extended_care_transfer_preview(session, month)
    if not preview.can_transfer or preview.cycle is None or preview.cycle.id is None:
        raise ExtendedCareBillingTransferError(" ".join(preview.errors) or "請求へ転送できません。")
    if not preview.has_changes:
        return ExtendedCareTransferResult(
            action="none",
            affected_child_count=0,
            affected_charge_count=0,
            total_amount=preview.target_amount,
            changed_child_ids=[],
        )

    setting = preview.setting
    fee_item = _ensure_fee_item(session, setting.fee_item_code)
    had_existing_transfer = preview.has_existing_transfer
    now = utc_now()
    changed_child_ids: list[int] = []
    affected_charge_count = 0
    touched_claims: list[BillingClaim] = []

    for row in preview.child_rows:
        if not row.has_changes:
            continue
        if row.family_id is None:
            raise ExtendedCareBillingTransferError(f"{row.child_name} に家族情報がありません。")
        claim = _ensure_claim(
            session,
            cycle=preview.cycle,
            family_id=row.family_id,
        )
        if claim.status in {BillingClaimStatus.exported, BillingClaimStatus.paid}:
            raise ExtendedCareBillingTransferError(f"{row.child_name} の請求は変更できません。")

        reference = _source_reference(preview.cycle.id, row.child_id)
        line = session.exec(
            select(BillingChargeLine).where(BillingChargeLine.source_reference == reference)
        ).first()
        if line is None:
            line = BillingChargeLine(
                billing_claim_id=claim.id,
                fee_item_id=fee_item.id,
                child_id=row.child_id,
                source_type=BillingChargeSourceType.extension_auto,
                source_reference=reference,
                description=_description(setting.description_template, preview.month),
            )
        line.billing_claim_id = claim.id
        line.fee_item_id = fee_item.id
        line.child_id = row.child_id
        line.source_type = BillingChargeSourceType.extension_auto
        line.source_date = preview.start_date
        line.source_reference = reference
        line.description = _description(setting.description_template, preview.month)
        line.quantity = 1
        line.unit_label = "月"
        line.unit_price = row.target_amount
        line.amount = row.target_amount
        line.is_locked = True
        line.updated_at = now
        session.add(line)
        session.flush()

        for charge in row.charges:
            charge.billing_charge_line_id = line.id
            charge.transferred_amount = charge.final_amount
            charge.transferred_at = now
            charge.transferred_by_user_id = executed_by_user_id
            charge.transferred_by_name = executed_by_name
            charge.updated_at = now
            session.add(charge)
            affected_charge_count += 1

        touched_claims.append(claim)
        changed_child_ids.append(row.child_id)

    _recalculate_claims(session, preview.cycle, touched_claims)
    action = "retransfer" if had_existing_transfer else "transfer"
    session.add(
        ExtendedCareBillingTransferLog(
            action=action,
            target_month=preview.month,
            billing_cycle_id=preview.cycle.id,
            affected_child_count=len(changed_child_ids),
            affected_charge_count=affected_charge_count,
            total_amount=preview.target_amount,
            changed_child_ids=changed_child_ids,
            executed_by_user_id=executed_by_user_id,
            executed_by_name=executed_by_name,
            executed_at=now,
        )
    )
    session.flush()
    return ExtendedCareTransferResult(
        action=action,
        affected_child_count=len(changed_child_ids),
        affected_charge_count=affected_charge_count,
        total_amount=preview.target_amount,
        changed_child_ids=changed_child_ids,
    )


def revert_extended_care_transfer(
    session: Session,
    month: str,
    *,
    executed_by_user_id: Optional[uuid.UUID],
    executed_by_name: str,
) -> ExtendedCareTransferResult:
    normalized_month, _, _ = parse_month(month)
    cycle = session.exec(
        select(BillingCycle).where(BillingCycle.year_month == normalized_month)
    ).first()
    if cycle is None or cycle.id is None:
        raise ExtendedCareBillingTransferError("対象月の請求月が見つかりません。")
    if cycle.status not in EDITABLE_CYCLE_STATUSES:
        raise ExtendedCareBillingTransferError("全銀データ作成後の請求月は転送解除できません。")

    claims = session.exec(
        select(BillingClaim).where(BillingClaim.billing_cycle_id == cycle.id)
    ).all()
    if any(claim.status in {BillingClaimStatus.exported, BillingClaimStatus.paid} for claim in claims):
        raise ExtendedCareBillingTransferError("出力済みまたは入金済みの請求は転送解除できません。")
    claim_ids = [claim.id for claim in claims if claim.id is not None]
    if not claim_ids:
        raise ExtendedCareBillingTransferError("転送済みの延長保育料金がありません。")

    reference_prefix = f"extended-care:{cycle.id}:"
    lines = session.exec(
        select(BillingChargeLine).where(
            BillingChargeLine.billing_claim_id.in_(claim_ids),
            BillingChargeLine.source_type == BillingChargeSourceType.extension_auto,
            BillingChargeLine.source_reference.like(f"{reference_prefix}%"),
        )
    ).all()
    if not lines:
        raise ExtendedCareBillingTransferError("転送済みの延長保育料金がありません。")

    line_ids = [line.id for line in lines if line.id is not None]
    charges = session.exec(
        select(ExtendedCareCharge).where(
            ExtendedCareCharge.billing_charge_line_id.in_(line_ids)
        )
    ).all()
    now = utc_now()
    for charge in charges:
        charge.billing_charge_line_id = None
        charge.transferred_amount = None
        charge.transferred_at = None
        charge.transferred_by_user_id = None
        charge.transferred_by_name = None
        charge.updated_at = now
        session.add(charge)

    total_amount = sum(line.amount for line in lines)
    changed_child_ids = sorted({line.child_id for line in lines if line.child_id is not None})
    touched_claim_ids = {line.billing_claim_id for line in lines}
    for line in lines:
        session.delete(line)
    session.flush()
    touched_claims = [claim for claim in claims if claim.id in touched_claim_ids]
    _recalculate_claims(session, cycle, touched_claims)
    session.add(
        ExtendedCareBillingTransferLog(
            action="revert",
            target_month=normalized_month,
            billing_cycle_id=cycle.id,
            affected_child_count=len(changed_child_ids),
            affected_charge_count=len(charges),
            total_amount=total_amount,
            changed_child_ids=changed_child_ids,
            executed_by_user_id=executed_by_user_id,
            executed_by_name=executed_by_name,
            executed_at=now,
        )
    )
    session.flush()
    return ExtendedCareTransferResult(
        action="revert",
        affected_child_count=len(changed_child_ids),
        affected_charge_count=len(charges),
        total_amount=total_amount,
        changed_child_ids=changed_child_ids,
    )


def remove_manual_extended_care_billing_conflict(
    session: Session,
    month: str,
    *,
    child_id: int,
) -> int:
    normalized_month, _, _ = parse_month(month)
    setting = get_extended_care_billing_setting(session)
    cycle = session.exec(
        select(BillingCycle).where(BillingCycle.year_month == normalized_month)
    ).first()
    if cycle is None or cycle.id is None:
        raise ExtendedCareBillingTransferError("対象月の請求月が見つかりません。")
    if cycle.status not in EDITABLE_CYCLE_STATUSES:
        raise ExtendedCareBillingTransferError("全銀データ作成後の請求明細は修正できません。")

    child = session.get(Child, child_id)
    if child is None:
        raise ExtendedCareBillingTransferError("園児情報が見つかりません。")
    claims = session.exec(
        select(BillingClaim).where(BillingClaim.billing_cycle_id == cycle.id)
    ).all()
    claim_ids = [claim.id for claim in claims if claim.id is not None]
    fee_item = session.exec(
        select(FeeItem).where(FeeItem.code == setting.fee_item_code)
    ).first()
    if not claim_ids or fee_item is None:
        raise ExtendedCareBillingTransferError("競合する手入力の延長保育料が見つかりません。")

    lines = session.exec(
        select(BillingChargeLine).where(
            BillingChargeLine.billing_claim_id.in_(claim_ids),
            BillingChargeLine.child_id == child_id,
            BillingChargeLine.fee_item_id == fee_item.id,
            BillingChargeLine.source_type != BillingChargeSourceType.extension_auto,
        )
    ).all()
    if not lines:
        raise ExtendedCareBillingTransferError("競合する手入力の延長保育料が見つかりません。")
    affected_claim_ids = {line.billing_claim_id for line in lines}
    affected_claims = [claim for claim in claims if claim.id in affected_claim_ids]
    if any(
        claim.status in {BillingClaimStatus.exported, BillingClaimStatus.paid}
        for claim in affected_claims
    ):
        raise ExtendedCareBillingTransferError("出力済みまたは入金済みの請求は修正できません。")
    if any(line.is_locked for line in lines):
        raise ExtendedCareBillingTransferError("ロック済みの請求明細は削除できません。")

    removed_amount = sum(line.amount for line in lines)
    for line in lines:
        session.delete(line)
    session.flush()
    _recalculate_claims(session, cycle, affected_claims)
    return removed_amount


def _ensure_fee_item(session: Session, code: str) -> FeeItem:
    item = session.exec(select(FeeItem).where(FeeItem.code == code)).first()
    if item is None:
        item = FeeItem(
            code=code,
            name="延長保育料",
            category="monthly",
            charge_unit="child",
            taxable_type="non_taxable",
            display_order=120,
        )
        session.add(item)
        session.flush()
    return item


def _ensure_claim(
    session: Session,
    *,
    cycle: BillingCycle,
    family_id: int,
) -> BillingClaim:
    claim = session.exec(
        select(BillingClaim).where(
            BillingClaim.billing_cycle_id == cycle.id,
            BillingClaim.family_id == family_id,
        )
    ).first()
    if claim is not None:
        return claim
    profile = session.exec(
        select(FamilyBillingProfile).where(FamilyBillingProfile.family_id == family_id)
    ).first()
    claim = BillingClaim(
        billing_cycle_id=cycle.id,
        family_id=family_id,
        payment_method=(
            profile.payment_method if profile else BillingPaymentMethod.direct_debit
        ),
        total_amount=0,
        status=(
            BillingClaimStatus.confirmed
            if cycle.status == BillingCycleStatus.confirmed
            else BillingClaimStatus.draft
        ),
    )
    session.add(claim)
    session.flush()
    return claim


def _recalculate_claims(
    session: Session,
    cycle: BillingCycle,
    claims: list[BillingClaim],
) -> None:
    seen: set[int] = set()
    for claim in claims:
        if claim.id is None or claim.id in seen:
            continue
        seen.add(claim.id)
        lines = session.exec(
            select(BillingChargeLine).where(BillingChargeLine.billing_claim_id == claim.id)
        ).all()
        recalculate_claim_total(claim, lines)
        if cycle.status == BillingCycleStatus.confirmed:
            claim.status = BillingClaimStatus.confirmed
        elif claim.status != BillingClaimStatus.confirmed:
            claim.status = BillingClaimStatus.draft
        claim.updated_at = utc_now()
        session.add(claim)


def _source_reference(cycle_id: int, child_id: int) -> str:
    return f"extended-care:{cycle_id}:{child_id}"


def _description(template: str, month: str) -> str:
    year = int(month[:4])
    month_number = int(month[5:7])
    return template.format(year=year, month=month_number)


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
