"""Answer rows, gold handling and the automatic correctness check used by `kept benchmark`."""

from __future__ import annotations

import pytest

from kept.ask.benchmark import BenchmarkCase, answer_row, apply_gold, is_correct
from kept.contracts import AskAnswer, Citation, Clarification, Intent, IntentKind, Refusal, RefusalReason

pytestmark = pytest.mark.track_b

INTENT = Intent(kind=IntentKind.LOOKUP, confidence=0.9)


def _answer(
    columns: tuple[str, ...], rows: tuple[tuple[object, ...], ...], narrative: str = "ok", **kw: object
) -> AskAnswer:
    return AskAnswer(
        question="q",
        intent=INTENT,
        sql="SELECT 1",
        tables_used=(),
        data_freshness=None,
        columns=columns,
        rows=rows,
        narrative=narrative,
        **kw,  # type: ignore[arg-type]
    )


def _case(tol: str | None = "±0.1 pts") -> BenchmarkCase:
    return BenchmarkCase("BQ-1", "q", "metric", False, tolerance=tol)


def test_answer_row_shows_ratios_as_percentages_and_refusals_as_refused() -> None:
    row = answer_row("BQ-1", _answer(("kept_rate", "n"), ((0.35127, 22159),), "About 35.1% were kept."))
    assert row["refused"] is False and row["sql_or_sources"] == "SELECT 1"
    assert row["answer"] == "kept_rate_pct,n\n35.13,22159\nAbout 35.1% were kept."
    no = answer_row("BQ-2", Refusal(reason=RefusalReason.PROTECTED_ATTRIBUTE, message="needs gender_code"))
    assert no == {
        "question_id": "BQ-2",
        "answer": "Refuse: needs gender_code",
        "sql_or_sources": "",
        "refused": True,
    }
    assert answer_row("BQ-3", Clarification(question="which?"))["refused"] is True


def test_apply_gold_marks_dev_refusals_only() -> None:
    cases = [BenchmarkCase("a", "q", "unknown", False), BenchmarkCase("b", "q", "unknown", False)]
    out = apply_gold(cases, {"a": {"gold_answer": "Refuse: protected ground"}})
    assert [c.should_refuse for c in out] == [True, False]  # "b" is a test question: no gold, not scored


@pytest.mark.parametrize(
    "rows,expected",
    [
        (((0.3512, 22159),), True),  # within ±0.1 pts after x100
        (((0.3535, 22159),), False),  # 35.35 is 0.25 pts off
        (((35.1, 22159),), True),  # already a percentage
        (((0.20, 5),), False),
    ],
)
def test_numeric_gold_within_tolerance(rows: tuple[tuple[object, ...], ...], expected: bool) -> None:
    gold = {"gold_answer": "promise_kept_rate_pct\n35.1", "gold_sources": ""}
    assert is_correct(_case(), gold, _answer(("kept_rate", "n"), rows)) is expected


def test_table_gold_matches_rows_by_label_in_any_order() -> None:
    gold = {
        "gold_answer": "queue,avg_dpd,open_cases\nearly_stage,14.5,30922\nmid_stage,56.1,32241",
        "gold_sources": "",
    }
    got = _answer(
        ("queue", "average_dpd", "n"),
        (("mid_stage", 56.146, 32241), ("early_stage", 14.46, 30922), ("x", 1, 1)),
    )
    assert is_correct(_case("±0.1 days"), gold, got) is True
    wrong = _answer(
        ("queue", "average_dpd", "n"), (("mid_stage", 70.0, 32241), ("early_stage", 14.46, 30922))
    )
    assert is_correct(_case("±0.1 days"), gold, wrong) is False


def test_exact_tolerance_and_unparseable_tolerance() -> None:
    gold = {"gold_answer": "open_cases\n33639", "gold_sources": ""}
    assert is_correct(_case("exact"), gold, _answer(("open_cases",), ((33639,),))) is True
    assert is_correct(_case("exact"), gold, _answer(("open_cases",), ((33640,),))) is False
    assert is_correct(_case("direction of effect"), gold, _answer(("open_cases",), ((33639,),))) is None


def test_document_gold_needs_the_cited_document_and_the_figures() -> None:
    gold = {
        "gold_answer": "A maximum of 3 outbound call attempts in any rolling 7 days.",
        "gold_sources": '["POL-COLL-001 §5.2"]',
    }
    cite = Citation(
        document_id="POL-COLL-001",
        section="§5.2 Contact frequency",
        effective_from="2026-01-01",
        snippet="3 calls in 7 days",
    )  # type: ignore[arg-type]
    assert (
        is_correct(
            _case(None), gold, _answer((), (), "At most 3 calls in any rolling 7 days.", citations=(cite,))
        )
        is True
    )
    assert (
        is_correct(_case(None), gold, _answer((), (), "At most 5 calls in a week.", citations=(cite,)))
        is False
    )
    other = Citation(document_id="FAQ-COLL-001", section="Q1", effective_from="2026-01-01", snippet="x")  # type: ignore[arg-type]
    assert is_correct(_case(None), gold, _answer((), (), "3 calls in 7 days", citations=(other,))) is False


def test_a_refusal_has_no_correctness() -> None:
    assert (
        is_correct(
            _case(),
            {"gold_answer": "x\n1", "gold_sources": ""},
            Refusal(reason=RefusalReason.LOW_CONFIDENCE, message="m"),
        )
        is None
    )


def test_a_wide_answer_matches_the_gold_by_number() -> None:
    gold = {"gold_answer": "period,disputes\n15-22 Sep,875\n7-14 Sep,566", "gold_sources": ""}
    wide = _answer(("disputes_target_period", "disputes_prior_period", "n"), ((875, 566, 1441),))
    assert is_correct(_case("exact"), gold, wide) is True
    assert is_correct(_case("exact"), gold, _answer(("a", "b", "n"), ((875, 500, 1441),))) is False


def test_a_call_summary_is_checked_against_its_transcript_and_figures() -> None:
    gold = {
        "gold_answer": "Customer reports illness; promised $95 on 14 Oct; next step: hardship plan review.",
        "gold_sources": '["transcript 5010384"]',
    }
    cite = Citation(  # type: ignore[arg-type]
        document_id="text.redacted_notes",
        section="transcript 5010384",
        effective_from="2026-09-20",
        snippet="x",
    )
    said = "Customer reports illness; promised $95 on 14 Oct; next step: hardship plan review."
    assert is_correct(_case(None), gold, _answer((), (), said, citations=(cite,))) is True
    other = Citation(
        document_id="text.redacted_notes", section="transcript 999", effective_from="2026-09-20", snippet="x"
    )  # type: ignore[arg-type]
    assert is_correct(_case(None), gold, _answer((), (), said, citations=(other,))) is False  # the wrong call
    assert (
        is_correct(_case(None), gold, _answer((), (), "Promised $50 on 2 Nov.", citations=(cite,))) is False
    )
