"""Cash-flow hardship rule: late payroll, salary drop, new EI deposits. No AI.

Inputs come straight from deposit_accounts: payroll_delay_days (already net of a 2-day
processing tolerance), payroll_amount_change_pct (fraction, -0.2672 = down 27%),
ei_deposit_flag + ei_first_deposit_date, and transactions.benefit_type == "ei".
EI is a benefit flag (a proxy), so it may only ever PROTECT: it feeds this rule, never a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class CashFlowRuleConfig:
    late_payroll_days: int = 5  # TBC
    new_ei_window_days: int = 60  # TBC: an EI episode that started this recently is "new"
    salary_drop_threshold: float = -0.20  # TBC: pay down 20%+ vs 3-month average
    ei_descriptor_keywords: tuple[str, ...] = ("EI", "EMPLOYMENT INSURANCE", "ASSURANCE-EMPLOI")


DEFAULT_CONFIG = CashFlowRuleConfig()


def cash_flow_hardship(
    *,
    payroll_delay_days: int | None,
    pay_change_vs_3m_avg: float | None,
    new_ei_deposit: bool | None,
    config: CashFlowRuleConfig = DEFAULT_CONFIG,
) -> bool:
    """True if any trigger fires: delay >= late_payroll_days, change <= salary_drop_threshold,
    or a new EI deposit. All-None inputs -> False (missing is not evidence)."""
    return (
        (payroll_delay_days is not None and payroll_delay_days >= config.late_payroll_days)
        or (pay_change_vs_3m_avg is not None and pay_change_vs_3m_avg <= config.salary_drop_threshold)
        or new_ei_deposit is True
    )


def new_ei_deposit(
    *,
    ei_deposit_flag: bool | None,
    ei_first_deposit_date: date | None,
    as_of: date,
    config: CashFlowRuleConfig = DEFAULT_CONFIG,
) -> bool | None:
    """True when EI deposits are flowing and the episode began within new_ei_window_days
    before as_of (inclusive). Flag True with no first date -> True (protective). Flag False ->
    False. Flag None -> None (unknown). A first deposit date after as_of -> False (point in time)."""
    if ei_deposit_flag is None:
        return None
    if not ei_deposit_flag:
        return False
    if ei_first_deposit_date is None:
        return True
    return 0 <= (as_of - ei_first_deposit_date).days <= config.new_ei_window_days


def is_ei_deposit(descriptor: str | None, config: CashFlowRuleConfig = DEFAULT_CONFIG) -> bool:
    """For transactions.raw_description: case-insensitive whole-word match on EI keywords
    ("EI" must not match "REIMBURSE"). Prefer transactions.benefit_type == "ei" when present."""
    if not descriptor:
        return False
    words = "|".join(map(re.escape, config.ei_descriptor_keywords))
    return re.search(rf"\b(?:{words})\b", descriptor, flags=re.IGNORECASE) is not None
