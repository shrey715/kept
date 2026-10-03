"""Stage 5: Kept sizing. Plain arithmetic: due 1-2 days after payday, within spare cash."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from kept.contracts.enums import PayrollFrequency
from kept.contracts.nba import PromiseSizing


def promise_due_date(expected_payday: date, *, today: date, offset_days: int = 1) -> date | None:
    """expected_payday + offset_days (offset in {1, 2}, else ValueError). If that is
    before today + 1, roll forward to the next payday is NOT our job: return None
    (no payday-dated promise possible; caller falls back)."""
    raise NotImplementedError("Track D")


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
    raise NotImplementedError("Track D")


def sizing_text(s: PromiseSizing) -> str:
    """'$140 fits inside estimated spare cash of ~$160 a month after rent; due one day after
    the expected payroll date.' Amounts formatted with $ and no trailing .00."""
    raise NotImplementedError("Track D")
