"""Hardship programme eligibility (hardship_programs table)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from kept.contracts import HardshipSignal, Role
from kept.hardship.programs import HardshipProgram, ProgramCase, eligible_programs

AS_OF = date(2026, 9, 28)

REDUCE_V1 = HardshipProgram(
    program_id="HP-REDUCE",
    version="v1",
    program_name="Payment reduction",
    product_types=frozenset({"personal_loan", "auto_loan"}),
    policy_section="§4.2",
    min_hardship_level=HardshipSignal.POSSIBLE,
    max_dpd=90,
    min_months_on_book=6,
    max_uses_12m=1,
    excludes_insolvency=True,
    excludes_broken_plan_90d=True,
    requires_income_evidence=False,
    payment_reduction_pct=0.25,
    duration_months=3,
    approver_level=Role.HARDSHIP_SPECIALIST,
    effective_from=date(2025, 1, 1),
    effective_to=date(2026, 6, 1),
)
REDUCE_V2 = replace(REDUCE_V1, version="v2", effective_from=date(2026, 6, 1), effective_to=None)
SKIP = HardshipProgram(
    program_id="HP-SKIP",
    version="v1",
    program_name="Skip a payment",
    product_types=frozenset({"credit_card"}),
    policy_section="§4.4",
    min_hardship_level=HardshipSignal.CLEAR,
    max_dpd=None,
    min_months_on_book=None,
    max_uses_12m=None,
    excludes_insolvency=False,
    excludes_broken_plan_90d=False,
    requires_income_evidence=True,
    payment_reduction_pct=None,
    duration_months=1,
    approver_level=Role.AGENT,
    effective_from=date(2024, 1, 1),
    effective_to=None,
)
ALL = [REDUCE_V1, REDUCE_V2, SKIP]


def case(**kw: object) -> ProgramCase:
    base: dict[str, object] = dict(
        product_type="personal_loan",
        hardship_level=HardshipSignal.POSSIBLE,
        dpd=18,
        months_on_book=24,
        uses_last_12m=0,
        insolvency=False,
        broken_plan_90d=False,
    )
    base.update(kw)
    return ProgramCase(**base)  # type: ignore[arg-type]


def ids(progs: list[HardshipProgram]) -> list[tuple[str, str]]:
    return [(p.program_id, p.version) for p in progs]


def test_card_example_hp_reduce_v2_eligible() -> None:
    assert ids(eligible_programs(case(), ALL, as_of=AS_OF)) == [("HP-REDUCE", "v2")]


def test_only_the_version_current_on_as_of() -> None:
    assert ids(eligible_programs(case(), ALL, as_of=date(2026, 1, 1))) == [("HP-REDUCE", "v1")]
    assert ids(eligible_programs(case(), ALL, as_of=date(2026, 6, 1))) == [
        ("HP-REDUCE", "v2")
    ]  # effective_to exclusive


@pytest.mark.parametrize(
    "kw",
    [
        {"product_type": "mortgage"},
        {"hardship_level": HardshipSignal.NONE},
        {"dpd": 91},
        {"months_on_book": 5},
        {"uses_last_12m": 1},
        {"insolvency": True},
        {"broken_plan_90d": True},
    ],
)
def test_each_rule_excludes(kw: dict[str, object]) -> None:
    assert eligible_programs(case(**kw), ALL, as_of=AS_OF) == []


@pytest.mark.parametrize("dpd,mob", [(90, 6)])
def test_limits_are_inclusive(dpd: int, mob: int) -> None:
    assert ids(eligible_programs(case(dpd=dpd, months_on_book=mob), ALL, as_of=AS_OF)) == [
        ("HP-REDUCE", "v2")
    ]


def test_hardship_level_ordering_and_none_limits() -> None:
    card = case(product_type="credit_card", dpd=400, months_on_book=1, uses_last_12m=9, insolvency=True)
    assert eligible_programs(card, ALL, as_of=AS_OF) == []  # needs clear hardship
    assert ids(eligible_programs(replace(card, hardship_level=HardshipSignal.CLEAR), ALL, as_of=AS_OF)) == [
        ("HP-SKIP", "v1")
    ]
