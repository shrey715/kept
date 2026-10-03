"""LLM extraction with evidence, agent confirmation, and the F1 release gate."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kept.common.llm import Purpose
from kept.contracts import HardshipSignal, RedactedText, StatedReason, TextExtraction
from kept.text.evaluate import adjudicate, binary_metrics, cohens_kappa, text_feature_gate
from kept.text.extract import LLMExtractor, confirm, locate_quote, resolve_day_of_month

from ..fakes import PurposeLLM

AT = datetime(2026, 10, 2, 22, 0, tzinfo=UTC)
NOTE = RedactedText(
    text="<PERSON> says shifts cut at the plant since Aug. Will pay $140 on 3 Oct after payday. Wife on the line.",
    redactor_version="test",
)


def _reply(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "hardship_signal": {
            "value": "possible",
            "quote": "shifts cut at the plant since Aug",
            "confidence": 0.8,
        },
        "stated_reason": {"value": "reduced_income", "quote": "shifts cut at the plant", "confidence": 0.8},
        "promise_intent": {"value": True, "quote": "Will pay $140 on 3 Oct", "confidence": 0.9},
        "promised_date": {"value": "2026-10-03", "quote": "3 Oct", "confidence": 0.9},
        "promised_amount": {"value": "140.00", "quote": "$140", "confidence": 0.9},
        "dispute": {"value": False, "quote": None, "confidence": 0.9},
        "cease_request": {"value": False, "quote": None, "confidence": 0.9},
        "third_party_present": {"value": True, "quote": "Wife on the line", "confidence": 0.85},
    }
    base.update(over)
    return base


def _extract(reply: dict[str, Any]) -> TextExtraction:
    llm = PurposeLLM({Purpose.TEXT_EXTRACT: [reply]})
    out = LLMExtractor(llm).extract(NOTE, source_id="N-1", case_id="C-118204")
    assert llm.purposes() == [Purpose.TEXT_EXTRACT]
    return out


# ----------------------------------------------------------------- quotes
def test_locate_quote_exact_offsets() -> None:
    ev = locate_quote(NOTE.text, "shifts cut at the plant", source_id="N-1")
    assert ev is not None
    assert NOTE.text[ev.char_start : ev.char_end] == "shifts cut at the plant"


def test_locate_quote_tolerates_whitespace_only() -> None:
    assert locate_quote("a  b\nc", "a b c", source_id="N") is not None
    assert (
        locate_quote(NOTE.text, "shifts were cut at the plant", source_id="N-1") is None
    )  # paraphrase = hallucination


# ----------------------------------------------------------------- relative dates
@pytest.mark.parametrize(
    "day,written,expected",
    [
        (2, date(2026, 9, 18), date(2026, 10, 2)),  # dictionary note: "can pay 800 on the 2nd"
        (2, date(2026, 10, 1), date(2026, 10, 2)),
        (2, date(2026, 10, 2), date(2026, 10, 2)),  # on or after
        (31, date(2026, 9, 5), date(2026, 10, 31)),  # September has no 31st
        (29, date(2027, 2, 1), date(2027, 3, 29)),  # Feb 2027 has no 29th
        (1, date(2026, 12, 15), date(2027, 1, 1)),
    ],
)
def test_resolve_day_of_month(day: int, written: date, expected: date) -> None:
    assert resolve_day_of_month(day, written_at=written) == expected


@pytest.mark.parametrize("day", [0, 32, -1])
def test_resolve_day_of_month_rejects(day: int) -> None:
    with pytest.raises(ValueError):
        resolve_day_of_month(day, written_at=date(2026, 9, 18))


# ----------------------------------------------------------------- extraction
def test_extraction_with_evidence() -> None:
    x = _extract(_reply())
    assert x.hardship_signal.value is HardshipSignal.POSSIBLE
    assert x.hardship_signal.evidence is not None
    assert x.promised_amount.value == Decimal("140.00")
    assert x.promised_date.value == date(2026, 10, 3)
    assert x.third_party_present.value is True
    assert x.stated_reason.value is StatedReason.REDUCED_INCOME
    assert x.extractor.startswith("llm:") and x.confirmed_by_agent_id is None


def test_hallucinated_quote_drops_value() -> None:
    x = _extract(_reply(cease_request={"value": True, "quote": "stop calling me", "confidence": 0.99}))
    assert x.cease_request.value is False and x.cease_request.confidence == 0


def test_clear_hardship_without_evidence_downgrades_to_possible() -> None:
    x = _extract(_reply(hardship_signal={"value": "clear", "quote": None, "confidence": 0.95}))
    assert x.hardship_signal.value is HardshipSignal.POSSIBLE


def test_invalid_llm_reply_raises() -> None:
    with pytest.raises(ValueError):
        _extract({"hardship_signal": "maybe?"})


def test_every_kept_quote_is_in_the_note() -> None:
    x = _extract(_reply())
    for name in (
        "hardship_signal",
        "promise_intent",
        "promised_date",
        "promised_amount",
        "third_party_present",
    ):
        ev = getattr(x, name).evidence
        assert ev is not None and NOTE.text[ev.char_start : ev.char_end] == ev.quote


def test_agent_confirmation_and_edit() -> None:
    x = _extract(_reply())
    c = confirm(x, agent_id="agent-7", at=AT, edits={"promised_amount": Decimal("120.00")})
    assert c.confirmed_by_agent_id == "agent-7"
    assert c.promised_amount.value == Decimal("120.00") and c.promised_amount.confidence == 1.0
    assert c.hardship_signal == x.hardship_signal  # untouched fields unchanged
    assert x.confirmed_by_agent_id is None  # original not mutated


# ----------------------------------------------------------------- evaluation
def test_binary_metrics() -> None:
    p, r, f = binary_metrics([True, True, False, False], [True, False, True, False])
    assert (p, r, f) == pytest.approx((0.5, 0.5, 0.5))
    assert binary_metrics([False, False], [False, False]) == (0.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        binary_metrics([], [])
    with pytest.raises(ValueError):
        binary_metrics([True], [True, False])


def _pairs(tp: int, fn: int, fp: int, tn: int) -> tuple[list[bool], list[bool]]:
    y = [True] * (tp + fn) + [False] * (fp + tn)
    p = [True] * tp + [False] * fn + [True] * fp + [False] * tn
    return y, p


def test_gate_f1_threshold() -> None:
    assert text_feature_gate("dispute_flag", *_pairs(80, 20, 20, 180)).passed  # f1 0.80
    assert not text_feature_gate("dispute_flag", *_pairs(79, 21, 21, 179)).passed


def test_gate_hardship_needs_recall_090() -> None:
    # precision 1.0, recall 0.85 -> f1 0.919 but recall too low for hardship
    y, p = _pairs(85, 15, 0, 200)
    assert text_feature_gate("dispute_flag", y, p).passed
    g = text_feature_gate("hardship_signal", y, p)
    assert not g.passed and "recall" in g.reason
    assert text_feature_gate("hardship_signal", *_pairs(90, 10, 10, 190)).passed


def test_kappa() -> None:
    assert cohens_kappa(["a", "b", "a"], ["a", "b", "a"]) == pytest.approx(1.0)
    assert cohens_kappa(["a", "a"], ["a", "a"]) == pytest.approx(1.0)
    k = cohens_kappa(["y", "y", "n", "n"], ["y", "n", "y", "n"])
    assert k == pytest.approx(0.0)
    with pytest.raises(ValueError):
        cohens_kappa([], [])


@given(st.lists(st.sampled_from(["none", "possible", "clear"]), min_size=1, max_size=50))
def test_kappa_self_agreement_is_one(labels: list[str]) -> None:
    assert cohens_kappa(labels, labels) == pytest.approx(1.0)


def test_adjudicate_lists_disagreements() -> None:
    assert adjudicate(["a", "b", "c", "d"], ["a", "x", "c", "y"]) == [1, 3]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-10-03", date(2026, 10, 3)),
        ("day:2", date(2026, 10, 2)),
        ("weekday:friday", date(2026, 9, 18)),  # written on a Friday: same day
        ("weekday:monday", date(2026, 9, 21)),
        ("01-05", date(2027, 1, 5)),
        ("09-30", date(2026, 9, 30)),
        ("someday", None),
    ],
)
def test_relative_promised_dates(value: str, expected: date | None) -> None:
    llm = PurposeLLM(
        {Purpose.TEXT_EXTRACT: [_reply(promised_date={"value": value, "quote": "3 Oct", "confidence": 0.9})]}
    )
    x = LLMExtractor(llm).extract(
        NOTE, source_id="N-1", case_id="C-1", written_at=datetime(2026, 9, 18, 15, tzinfo=UTC)
    )
    assert x.promised_date.value == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("140.00", "140.00"),
        ("$140", "140.00"),
        ("17$", "17.00"),
        ("1 635 $", "1635.00"),
        ("17,50", "17.50"),
        ("1,635", "1635.00"),
        (55, "55.00"),
    ],
)
def test_amount_formats(raw: object, expected: str) -> None:
    x = _extract(_reply(promised_amount={"value": raw, "quote": "$140", "confidence": 0.9}))
    assert x.promised_amount.value == Decimal(expected)
