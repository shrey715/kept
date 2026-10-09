"""Stage 5: Kept sizing. Plain arithmetic: due 1-2 days after payday, within spare cash."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal

from kept.config import CENT, PROMISE_DAYS_AFTER_PAYDAY
from kept.contracts.enums import PayrollFrequency
from kept.contracts.nba import PromiseSizing

PERIODS_PER_YEAR = {
    PayrollFrequency.WEEKLY: 52,
    PayrollFrequency.BIWEEKLY: 26,
    PayrollFrequency.SEMI_MONTHLY: 24,
    PayrollFrequency.MONTHLY: 12,
}  # IRREGULAR and UNKNOWN: monthly


_STEP_DAYS = {PayrollFrequency.WEEKLY: 7, PayrollFrequency.BIWEEKLY: 14, PayrollFrequency.SEMI_MONTHLY: 15}


def next_payday(expected: date | None, frequency: PayrollFrequency, *, today: date) -> date | None:
    """The bank's expected payday rolled forward along the pay schedule to the first one on or after today.
    The deposit snapshot ages: a payday it expected last week is the start of the next cycle, not "no payday".
    Semi-monthly steps 15 days, as in the features (dbt account_features); irregular or unknown pay isn't
    projected."""
    if expected is None or expected >= today:
        return expected
    if step := _STEP_DAYS.get(frequency):
        return expected + timedelta(days=step * -(-(today - expected).days // step))
    if frequency is PayrollFrequency.MONTHLY:
        months = (today.year - expected.year) * 12 + today.month - expected.month
        for k in (months, months + 1):
            y, m = divmod(expected.month - 1 + k, 12)
            d = date(
                expected.year + y, m + 1, min(expected.day, calendar.monthrange(expected.year + y, m + 1)[1])
            )
            if d >= today:
                return d
    return expected


def promise_due_date(expected_payday: date, *, today: date, offset_days: int = 1) -> date | None:
    """expected_payday + offset_days (offset in {1, 2}, else ValueError). If that is
    before today + 1, roll forward to the next payday is NOT our job: return None
    (no payday-dated promise possible; caller falls back)."""
    if offset_days not in PROMISE_DAYS_AFTER_PAYDAY:
        raise ValueError(f"offset_days must be one of {PROMISE_DAYS_AFTER_PAYDAY}")
    due = expected_payday + timedelta(days=offset_days)
    return due if due >= today + timedelta(days=1) else None


def size_promise(
    *,
    balance_due: Decimal,
    spare_cash_monthly: Decimal | None,
    expected_payday: date | None,
    payroll_frequency: PayrollFrequency,
    today: date,
    max_installments: int = 3,
) -> PromiseSizing | None:
    """Smallest number of installments (1..max_installments) such that each installment
    <= spare cash per pay period; amount rounded UP to the cent, last installment may be
    smaller. Spare cash per period = monthly x 12 / periods-per-year (weekly 52, biweekly 26,
    semi-monthly 24, monthly 12; IRREGULAR and UNKNOWN are treated as monthly), rounded DOWN
    to the cent (conservative); installments are compared against that rounded value.
    Installments fall one per pay period; the first is due promise_due_date(payday).
    Returns None (no promise; consider hardship review) when spare cash or payday is
    unknown, spare cash <= 0, or even max_installments doesn't fit."""
    options = promise_options(
        balance_due=balance_due,
        spare_cash_monthly=spare_cash_monthly,
        expected_payday=expected_payday,
        payroll_frequency=payroll_frequency,
        today=today,
        max_installments=max_installments,
    )
    return options[0] if options else None


def promise_options(
    *,
    balance_due: Decimal,
    spare_cash_monthly: Decimal | None,
    expected_payday: date | None,
    payroll_frequency: PayrollFrequency,
    today: date,
    max_installments: int = 3,
    stated_per_payday: Decimal | None = None,
) -> list[PromiseSizing]:
    """Every installment count from the smallest that fits up to max_installments (#89: the
    customer picks one). More installments are smaller, so once one fits the rest do. [] = none fit.
    stated_per_payday: what the customer said they can put toward it each payday (the pay page asks when
    the bank doesn't know); it replaces the spare cash estimate, and the plan stays within it."""
    if stated_per_payday is not None:
        spare_cash_monthly = None
        per_period = stated_per_payday.quantize(CENT, rounding=ROUND_DOWN)
    elif spare_cash_monthly is None or spare_cash_monthly <= 0:
        return []
    else:
        periods = PERIODS_PER_YEAR.get(payroll_frequency, 12)
        per_period = (spare_cash_monthly * 12 / periods).quantize(CENT, rounding=ROUND_DOWN)
    if expected_payday is None or balance_due <= 0:
        return []
    due = promise_due_date(expected_payday, today=today)
    if per_period <= 0 or due is None:
        return []
    out = []
    for n in range(1, max_installments + 1):
        amount = (balance_due / n).quantize(CENT, rounding=ROUND_CEILING)
        if amount <= per_period:
            s = PromiseSizing(
                amount=amount,
                due_date=due,
                installments=n,
                spare_cash_estimate=per_period,
                payday=expected_payday,
                rationale="",
            )
            out.append(
                s.model_copy(update={"rationale": sizing_text(s, stated=stated_per_payday is not None)})
            )
    return out


def sizing_text(s: PromiseSizing, *, stated: bool = False) -> str:
    """'$140 fits inside estimated spare cash of ~$160 a month after rent; due one day after
    the expected payroll date.' Amounts formatted with $ and no trailing .00."""
    days = {1: "one day", 2: "two days"}.get(
        (s.due_date - s.payday).days, f"{(s.due_date - s.payday).days} days"
    )
    plan = _money(s.amount) + (
        f" a pay period for {s.installments} pay periods" if s.installments > 1 else ""
    )
    if stated:
        return (
            f"{plan} fits inside the {_money(s.spare_cash_estimate)} a payday the customer said they can "
            f"afford; due {days} after the payday they gave."
        )
    return (
        f"{plan} fits inside estimated spare cash of ~{_money(s.spare_cash_estimate)} per pay period "
        f"after rent, essentials and other lenders; due {days} after the expected payroll date."
    )


def _money(d: Decimal) -> str:
    return f"${d:,.2f}".removesuffix(".00")
