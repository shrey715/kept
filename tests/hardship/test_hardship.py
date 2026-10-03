"""Hardship combination and the cash-flow rule. Hardship protects, never scores."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kept.contracts import HardshipSignal, HardshipSource, HardshipStatus
from kept.hardship.cashflow_rule import cash_flow_hardship, is_ei_deposit, new_ei_deposit
from kept.hardship.combine import HardshipObservation, combine

T = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def obs(source: HardshipSource, signal: HardshipSignal, dt: int = 0, **kw: str) -> HardshipObservation:
    return HardshipObservation(source=source, signal=signal, observed_at=T + timedelta(hours=dt), **kw)  # type: ignore[arg-type]


# ----------------------------------------------------------------- combine
def test_no_observations_is_none() -> None:
    assert combine([]) == (HardshipStatus.NONE, None)


@pytest.mark.parametrize("source", list(HardshipSource))
def test_any_signal_restricts_straight_away(source: HardshipSource) -> None:
    status, src = combine([obs(source, HardshipSignal.POSSIBLE)])
    assert status in (HardshipStatus.POSSIBLE, HardshipStatus.CONFIRMED) and src is source


def test_llm_clear_without_a_person_is_only_possible() -> None:
    assert combine([obs(HardshipSource.LLM, HardshipSignal.CLEAR)]) == (
        HardshipStatus.POSSIBLE,
        HardshipSource.LLM,
    )


def test_llm_clear_confirmed_by_agent_is_confirmed() -> None:
    status, _ = combine([obs(HardshipSource.LLM, HardshipSignal.CLEAR, confirmed_by="agent-7")])
    assert status is HardshipStatus.CONFIRMED


@pytest.mark.parametrize("source", [HardshipSource.CUSTOMER_FORM, HardshipSource.MODEL])
def test_forms_and_models_need_a_person_to_confirm(source: HardshipSource) -> None:
    assert combine([obs(source, HardshipSignal.CLEAR)])[0] is HardshipStatus.POSSIBLE
    assert combine([obs(source, HardshipSignal.CLEAR, confirmed_by="hs-1")])[0] is HardshipStatus.CONFIRMED


def test_cash_flow_rule_alone_is_possible() -> None:
    assert combine([obs(HardshipSource.CASH_FLOW, HardshipSignal.CLEAR)])[0] is HardshipStatus.POSSIBLE


@pytest.mark.parametrize("source", [HardshipSource.AGENT, HardshipSource.ACCOUNT_PROGRAMME])
def test_people_and_programmes_confirm(source: HardshipSource) -> None:
    assert combine([obs(source, HardshipSignal.CLEAR)])[0] is HardshipStatus.CONFIRMED


def test_none_signal_never_lowers_status() -> None:
    status, _ = combine(
        [
            obs(HardshipSource.LLM, HardshipSignal.POSSIBLE, 0),
            obs(HardshipSource.LLM, HardshipSignal.NONE, 5),
            obs(HardshipSource.CASH_FLOW, HardshipSignal.NONE, 6),
        ]
    )
    assert status is HardshipStatus.POSSIBLE


def test_only_a_person_clears_and_only_earlier_observations() -> None:
    cleared = combine(
        [
            obs(HardshipSource.LLM, HardshipSignal.POSSIBLE, 0),
            obs(HardshipSource.AGENT, HardshipSignal.NONE, 2, cleared_by="specialist-1"),
        ]
    )
    assert cleared == (HardshipStatus.NONE, None)
    again = combine(
        [
            obs(HardshipSource.LLM, HardshipSignal.POSSIBLE, 0),
            obs(HardshipSource.AGENT, HardshipSignal.NONE, 2, cleared_by="specialist-1"),
            obs(HardshipSource.CASH_FLOW, HardshipSignal.POSSIBLE, 3),
        ]
    )
    assert again[0] is HardshipStatus.POSSIBLE


obs_strategy = st.builds(
    HardshipObservation,
    source=st.sampled_from(list(HardshipSource)),
    signal=st.sampled_from(list(HardshipSignal)),
    observed_at=st.integers(0, 100).map(lambda h: T + timedelta(hours=h)),
    confirmed_by=st.none() | st.just("agent-1"),
)


@given(st.lists(obs_strategy, max_size=8))
def test_combine_is_order_independent(observations: list[HardshipObservation]) -> None:
    assert combine(observations) == combine(list(reversed(observations)))


@given(st.lists(obs_strategy, max_size=8), obs_strategy)
def test_adding_a_signal_never_lowers_status(
    observations: list[HardshipObservation], extra: HardshipObservation
) -> None:
    rank = {HardshipStatus.NONE: 0, HardshipStatus.POSSIBLE: 1, HardshipStatus.CONFIRMED: 2}
    assert rank[combine([*observations, extra])[0]] >= rank[combine(observations)[0]]


# ----------------------------------------------------------------- cash-flow rule
@pytest.mark.parametrize(
    "kw,expected",
    [
        ({"payroll_delay_days": 5, "pay_change_vs_3m_avg": None, "new_ei_deposit": None}, True),
        ({"payroll_delay_days": 4, "pay_change_vs_3m_avg": None, "new_ei_deposit": None}, False),
        ({"payroll_delay_days": None, "pay_change_vs_3m_avg": -0.27, "new_ei_deposit": None}, True),
        ({"payroll_delay_days": None, "pay_change_vs_3m_avg": -0.20, "new_ei_deposit": None}, True),
        ({"payroll_delay_days": None, "pay_change_vs_3m_avg": -0.19, "new_ei_deposit": None}, False),
        ({"payroll_delay_days": None, "pay_change_vs_3m_avg": None, "new_ei_deposit": True}, True),
        ({"payroll_delay_days": None, "pay_change_vs_3m_avg": None, "new_ei_deposit": None}, False),
        ({"payroll_delay_days": 0, "pay_change_vs_3m_avg": 0.10, "new_ei_deposit": False}, False),
    ],
)
def test_cash_flow_triggers(kw: dict[str, object], expected: bool) -> None:
    assert cash_flow_hardship(**kw) is expected  # type: ignore[arg-type]


AS_OF = date(2026, 9, 28)


@pytest.mark.parametrize(
    "flag,first,expected",
    [
        (True, date(2026, 9, 1), True),
        (True, date(2026, 7, 30), True),  # exactly 60 days
        (True, date(2026, 7, 29), False),  # 61 days: an old episode
        (True, None, True),  # flowing, start unknown: treat as new (protective)
        (False, date(2026, 9, 1), False),
        (None, None, None),  # unknown stays unknown
        (True, date(2026, 10, 1), False),  # after as_of: point in time
    ],
)
def test_new_ei_deposit(flag: bool | None, first: date | None, expected: bool | None) -> None:
    assert new_ei_deposit(ei_deposit_flag=flag, ei_first_deposit_date=first, as_of=AS_OF) is expected


def test_card_example_pay_down_27_percent_triggers() -> None:
    # deposit_accounts.payroll_amount_change_pct example in the dictionary is -0.2672
    assert (
        cash_flow_hardship(payroll_delay_days=None, pay_change_vs_3m_avg=-0.2672, new_ei_deposit=None) is True
    )


@pytest.mark.parametrize(
    "descriptor,expected",
    [
        ("EI CANADA DEPOSIT", True),
        ("Employment Insurance", True),
        ("ASSURANCE-EMPLOI", True),
        ("ei benefit", True),
        ("REIMBURSEMENT", False),
        ("PAYROLL ACME", False),
        (None, False),
    ],
)
def test_is_ei_deposit(descriptor: str | None, expected: bool) -> None:
    assert is_ei_deposit(descriptor) is expected


def test_fresh_note_extractions_flip_hardship() -> None:

    from kept.common.llm import Purpose
    from kept.contracts import RedactedText
    from kept.hardship.combine import combine, observations_from_extractions
    from kept.text.extract import LLMExtractor, confirm

    from ..fakes import PurposeLLM
    from ..text.test_extract_and_eval import _reply

    note = RedactedText(
        text="<PERSON> says shifts cut at the plant since Aug. Will pay $140 on 3 Oct after payday. Wife on the line.",
        redactor_version="test",
    )
    x = LLMExtractor(PurposeLLM({Purpose.TEXT_EXTRACT: [_reply()]})).extract(
        note, source_id="N-9", case_id="C-1"
    )
    none = x.model_copy(
        update={"hardship_signal": x.hardship_signal.model_copy(update={"value": HardshipSignal.NONE})}
    )
    assert observations_from_extractions([none]) == []
    assert combine(observations_from_extractions([x])) == (HardshipStatus.POSSIBLE, HardshipSource.LLM)
    confirmed = confirm(x, agent_id="agent-7", at=x.extracted_at)
    assert combine(observations_from_extractions([confirmed]))[0] is HardshipStatus.CONFIRMED
