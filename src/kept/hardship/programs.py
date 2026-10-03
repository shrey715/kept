"""Hardship programme eligibility (hardship_programs table). Plain rules, no AI.

The NBA card names the programmes a case is eligible for ("HP-REDUCE v2 eligible");
offering one is still a RED-tier action released by the approver_level person.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from kept.contracts.enums import HardshipSignal, Role


@dataclass(frozen=True, slots=True)
class HardshipProgram:
    """One row of hardship_programs (data dictionary column names)."""

    program_id: str
    version: str
    program_name: str
    product_types: frozenset[str]  # e.g. {"personal_loan", "auto_loan"}
    policy_section: str
    min_hardship_level: HardshipSignal  # none / possible / clear
    max_dpd: int | None
    min_months_on_book: int | None
    max_uses_12m: int | None
    excludes_insolvency: bool
    excludes_broken_plan_90d: bool
    requires_income_evidence: bool
    payment_reduction_pct: float | None
    duration_months: int | None
    approver_level: Role  # agent / hardship_specialist / team_lead
    effective_from: date
    effective_to: date | None


@dataclass(frozen=True, slots=True)
class ProgramCase:
    product_type: str
    hardship_level: HardshipSignal
    dpd: int
    months_on_book: int
    uses_last_12m: int
    insolvency: bool
    broken_plan_90d: bool


def eligible_programs(
    case: ProgramCase, programs: list[HardshipProgram], *, as_of: date
) -> list[HardshipProgram]:
    """Programmes the case qualifies for, sorted by program_id then version. A programme
    applies when effective_from <= as_of < effective_to (None = open), the product is in
    product_types, hardship_level >= min_hardship_level (none < possible < clear),
    dpd <= max_dpd, months_on_book >= min_months_on_book, uses_last_12m < max_uses_12m,
    and neither exclusion fires. None limits are not checked. Only the current version
    of each program_id can be returned."""
    current: dict[str, HardshipProgram] = {}
    for p in programs:
        live = p.effective_from <= as_of and (p.effective_to is None or as_of < p.effective_to)
        if live and (p.program_id not in current or p.effective_from > current[p.program_id].effective_from):
            current[p.program_id] = p  # overlapping versions: the newest one wins
    return sorted(
        (p for p in current.values() if _qualifies(case, p)), key=lambda p: (p.program_id, p.version)
    )


_LEVEL = {HardshipSignal.NONE: 0, HardshipSignal.POSSIBLE: 1, HardshipSignal.CLEAR: 2}


def _qualifies(case: ProgramCase, p: HardshipProgram) -> bool:
    return (
        case.product_type in p.product_types
        and _LEVEL[case.hardship_level] >= _LEVEL[p.min_hardship_level]
        and (p.max_dpd is None or case.dpd <= p.max_dpd)
        and (p.min_months_on_book is None or case.months_on_book >= p.min_months_on_book)
        and (p.max_uses_12m is None or case.uses_last_12m < p.max_uses_12m)
        and not (p.excludes_insolvency and case.insolvency)
        and not (p.excludes_broken_plan_90d and case.broken_plan_90d)
    )
