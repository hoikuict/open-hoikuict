from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from models import BillingChargeSourceType, BillingClaim, BillingChargeLine, Child, MealFeeRule, MealFeeProrationPolicy, ProrationRounding


class BillingCalculationError(ValueError):
    pass


def apply_proration_rounding(value: Decimal, rounding: ProrationRounding | str) -> int:
    mode = ProrationRounding(rounding)
    quantize_mode = {
        ProrationRounding.round: ROUND_HALF_UP,
        ProrationRounding.floor: ROUND_FLOOR,
        ProrationRounding.ceil: ROUND_CEILING,
    }[mode]
    return int(value.quantize(Decimal("1"), rounding=quantize_mode))


def count_enrolled_days(child: Child, period_start, period_end) -> int:
    start = max(child.enrollment_date, period_start)
    end = period_end
    if child.withdrawal_date is not None:
        end = min(end, child.withdrawal_date)
    if end < start:
        return 0
    return (end - start).days + 1


def calculate_monthly_fixed_meal_fee(child: Child, rule: MealFeeRule, cycle) -> int:
    if rule.monthly_amount is None:
        raise BillingCalculationError("月額固定給食費には monthly_amount が必要です")

    if rule.proration_policy == MealFeeProrationPolicy.none:
        return rule.monthly_amount if count_enrolled_days(child, cycle.period_start, cycle.period_end) > 0 else 0

    if rule.proration_policy == MealFeeProrationPolicy.manual_adjustment:
        return rule.monthly_amount

    if rule.proration_policy == MealFeeProrationPolicy.daily_by_enrolled_days:
        total_days = (cycle.period_end - cycle.period_start).days + 1
        if total_days <= 0:
            raise BillingCalculationError("請求対象期間が不正です")
        enrolled_days = count_enrolled_days(child, cycle.period_start, cycle.period_end)
        raw = Decimal(rule.monthly_amount) * Decimal(enrolled_days) / Decimal(total_days)
        return apply_proration_rounding(raw, rule.proration_rounding)

    raise BillingCalculationError("未対応の日割り方針です")


def validate_charge_amount(source_type: BillingChargeSourceType | str, amount: int, *, allow_zero_note: bool = False) -> None:
    if not isinstance(amount, int):
        raise BillingCalculationError("金額は円単位の整数で指定してください")

    source = BillingChargeSourceType(source_type)
    if amount == 0 and not allow_zero_note:
        raise BillingCalculationError("0円明細は施設設定で許可された場合のみ登録できます")

    if amount < 0 and source not in {BillingChargeSourceType.adjustment, BillingChargeSourceType.manual}:
        raise BillingCalculationError("自動計算明細と繰越明細では負の金額を登録できません")


def recalculate_claim_total(claim: BillingClaim, lines: list[BillingChargeLine]) -> int:
    total = sum(line.amount for line in lines)
    claim.total_amount = total
    return total


def iter_dates(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
