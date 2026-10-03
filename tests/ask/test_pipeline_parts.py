"""Scope check, router, certified metrics, majority vote, grounding, privacy, benchmark."""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kept.ask.benchmark import (
    BenchmarkCase,
    BenchmarkOutcome,
    load_benchmark,
    parse_tolerance,
    score,
    write_answers,
)
from kept.ask.grounding import extract_numbers, is_grounded, needs_clarification
from kept.ask.lookup import majority_result, normalize_result
from kept.ask.metrics import CertifiedQuery, MetricDefinition, compile_metric, load_metric_definitions
from kept.ask.policy import chunk_document, effective_windows
from kept.ask.privacy import suppress_small_groups
from kept.ask.router import route
from kept.ask.scope import check_scope, refusal_for, rule_check
from kept.common.llm import Purpose
from kept.contracts import AskRequest, Intent, IntentKind, RefusalReason, Role, ScopeDecision
from kept.contracts.data_contract import DataContract

from ..fakes import PassThroughRedactor, PurposeLLM


def _req(q: str, role: Role = Role.ANALYST, own: frozenset[str] = frozenset()) -> AskRequest:
    return AskRequest(question=q, user_id="u1", role=role, own_case_ids=own)


def _in_scope(_: str) -> ScopeDecision:
    return ScopeDecision(in_scope=True, decided_by="classifier")


# ----------------------------------------------------------------- scope: rules
@pytest.mark.parametrize(
    "q,reason",
    [
        ("What is the kept rate by gender_code?", RefusalReason.PROTECTED_ATTRIBUTE),
        ("Roll rate by marital status", RefusalReason.PROTECTED_ATTRIBUTE),
        ("Do newcomers to Canada break more promises?", RefusalReason.PROTECTED_ATTRIBUTE),
        ("Kept rate for customers receiving the Canada Child Benefit", RefusalReason.PROTECTED_ATTRIBUTE),
        ("Which accent regions answer calls least?", RefusalReason.PROTECTED_ATTRIBUTE),
        ("Break down roll rate by gender", RefusalReason.PROTECTED_ATTRIBUTE),
        ("Roll rate by customer age band", RefusalReason.PROTECTED_ATTRIBUTE),
        ("Which postal codes have the worst roll rate?", RefusalReason.PROTECTED_ATTRIBUTE),
        ("Compare promises kept by preferred language", RefusalReason.PROTECTED_ATTRIBUTE),
        ("List every customer's phone number", RefusalReason.BULK_PERSONAL_DATA),
        ("Export all emails and names for cases over 60 DPD", RefusalReason.BULK_PERSONAL_DATA),
        ("Delete the broken promises for C-12", RefusalReason.WRITE_ACTION),
        ("Update the assigned agent on C-5 to agent-2", RefusalReason.WRITE_ACTION),
        ("Send an SMS to everyone in bucket 31-60", RefusalReason.WRITE_ACTION),
    ],
)
def test_rules_refuse(ask_contract: DataContract, q: str, reason: RefusalReason) -> None:
    d = rule_check(_req(q), ask_contract)
    assert d is not None and not d.in_scope and d.reason is reason and d.decided_by == "rules"


def test_rules_report_offending_column(ask_contract: DataContract) -> None:
    d = rule_check(_req("kept rate by gender_code"), ask_contract)
    assert d is not None and "gender_code" in d.offending_terms


def test_agent_cannot_ask_about_other_peoples_cases(ask_contract: DataContract) -> None:
    req = _req("What did C-77 promise last week?", role=Role.AGENT, own=frozenset({"C-1", "C-2"}))
    d = rule_check(req, ask_contract)
    assert d is not None and d.reason is RefusalReason.OTHER_PEOPLES_CASES
    ok = _req("What did C-2 promise last week?", role=Role.AGENT, own=frozenset({"C-1", "C-2"}))
    assert rule_check(ok, ask_contract) is None


@pytest.mark.parametrize(
    "q",
    [
        "What was the promise kept rate for card last month?",
        "How many cases entered at 1-30 DPD this week?",
        "What does the hardship policy say about payment reductions?",
        "Average overdue balance by product",
    ],
)
def test_rules_pass_ordinary_questions(ask_contract: DataContract, q: str) -> None:
    assert rule_check(_req(q), ask_contract) is None


def test_rules_run_before_classifier(ask_contract: DataContract) -> None:
    calls: list[str] = []

    def classifier(q: str) -> ScopeDecision:
        calls.append(q)
        return ScopeDecision(in_scope=True, decided_by="classifier")

    d = check_scope(_req("Delete all promises"), ask_contract, classifier)
    assert not d.in_scope and calls == []


def test_classifier_failure_fails_closed(ask_contract: DataContract) -> None:
    def broken(_: str) -> ScopeDecision:
        raise RuntimeError("LLM down")

    d = check_scope(_req("Average overdue balance by product"), ask_contract, broken)
    assert not d.in_scope and d.reason is RefusalReason.LOW_CONFIDENCE


def test_classifier_can_refuse_what_rules_miss(ask_contract: DataContract) -> None:
    def classifier(_: str) -> ScopeDecision:
        return ScopeDecision(in_scope=False, reason=RefusalReason.DATA_UNAVAILABLE, decided_by="classifier")

    d = check_scope(_req("What's the weather in Toronto?"), ask_contract, classifier)
    assert d.reason is RefusalReason.DATA_UNAVAILABLE


def test_refusal_message_says_why_and_suggests() -> None:
    d = ScopeDecision(
        in_scope=False,
        reason=RefusalReason.PROTECTED_ATTRIBUTE,
        offending_terms=("gender_code",),
        decided_by="rules",
    )
    r = refusal_for(d, suggestion="kept rate by product")
    assert "gender_code" in r.message and "excluded from collections analytics" in r.message
    assert r.suggestion == "Try: kept rate by product"
    assert r.reason is RefusalReason.PROTECTED_ATTRIBUTE


def test_refusal_for_in_scope_decision_is_an_error() -> None:
    with pytest.raises(ValueError):
        refusal_for(ScopeDecision(in_scope=True, decided_by="rules"), suggestion=None)


# ----------------------------------------------------------------- router
def test_router_returns_validated_intent() -> None:
    llm = PurposeLLM(
        {
            Purpose.ASK_ROUTE: [
                {
                    "kind": "metric",
                    "metric_id": "promise_kept_rate",
                    "filters": {"primary_product": "card"},
                    "confidence": 0.9,
                }
            ]
        }
    )
    q = PassThroughRedactor().redact("kept rate for card")
    i = route(q, llm, known_metric_ids=frozenset({"promise_kept_rate"}), actor_id="u1")
    assert i.kind is IntentKind.METRIC and i.filters == {"primary_product": "card"}
    assert llm.purposes() == [Purpose.ASK_ROUTE]


@pytest.mark.parametrize(
    "reply",
    [
        {"kind": "metric", "metric_id": "made_up_metric", "confidence": 0.9},
        {"kind": "teleport", "confidence": 0.9},
        {"kind": "lookup", "confidence": 7},
        "not json at all",
    ],
)
def test_router_rejects_bad_replies(reply: object) -> None:
    llm = PurposeLLM({Purpose.ASK_ROUTE: [reply]})  # type: ignore[list-item]
    q = PassThroughRedactor().redact("anything")
    with pytest.raises(ValueError):
        route(q, llm, known_metric_ids=frozenset({"promise_kept_rate"}), actor_id="u1")


# ----------------------------------------------------------------- certified metrics
def _intent(**kw: object) -> Intent:
    base: dict[str, object] = {"kind": IntentKind.METRIC, "metric_id": "promise_kept_rate", "confidence": 0.9}
    base.update(kw)
    return Intent(**base)  # type: ignore[arg-type]


def test_metric_compiles_deterministically_with_bind_params(
    metrics: dict[str, MetricDefinition], certified_queries: dict[str, CertifiedQuery]
) -> None:
    sql1, p1 = compile_metric(_intent(filters={"primary_product": "credit_card"}), metrics, certified_queries)
    sql2, p2 = compile_metric(_intent(filters={"primary_product": "credit_card"}), metrics, certified_queries)
    assert (sql1, p1) == (sql2, p2)
    assert "credit_card" not in sql1 and p1 == ["credit_card"]  # value bound, never interpolated
    assert "insolvency_hold_flag" in sql1  # default_filters always applied


def test_metric_injection_is_inert(
    metrics: dict[str, MetricDefinition], certified_queries: dict[str, CertifiedQuery]
) -> None:
    sql, params = compile_metric(
        _intent(filters={"primary_product": "card'; DROP TABLE x; --"}), metrics, certified_queries
    )
    assert "DROP" not in sql.upper() and params == ["card'; DROP TABLE x; --"]


def test_metric_runs_on_warehouse(
    metrics: dict[str, MetricDefinition], certified_queries: dict[str, CertifiedQuery], ask_db
) -> None:  # type: ignore[no-untyped-def]
    sql, params = compile_metric(_intent(group_by=("primary_product",)), metrics, certified_queries)
    rows = ask_db.execute(sql, params).fetchall()
    assert len(rows) == 2
    assert all(0 <= r[1] <= 1 for r in rows)  # (primary_product, kept_rate, n)


@pytest.mark.parametrize(
    "intent",
    [
        {"metric_id": "nope"},
        {"metric_id": "draft_metric"},
        {"filters": {"gender_code": "F"}},
        {"group_by": ("assigned_agent_id",)},
        {"kind": IntentKind.LOOKUP},
    ],
)
def test_metric_rejects(
    metrics: dict[str, MetricDefinition],
    certified_queries: dict[str, CertifiedQuery],
    intent: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        compile_metric(_intent(**intent), metrics, certified_queries)


def test_certified_flag_required_even_with_a_query(
    metrics: dict[str, MetricDefinition], certified_queries: dict[str, CertifiedQuery]
) -> None:
    queries = {
        **certified_queries,
        "draft_metric": CertifiedQuery("draft_metric", "SELECT 1", (), frozenset(), frozenset(), None),
    }
    with pytest.raises(ValueError):
        compile_metric(_intent(metric_id="draft_metric"), metrics, queries)


def test_load_metric_definitions_parses_arrays() -> None:
    row = {
        "metric_id": "roll_rate",
        "metric_name": "Roll rate",
        "business_definition": "d",
        "formula": "count(worse_bucket_at_end) / count(in_bucket_at_start)",
        "grain": "account",
        "time_basis": "month-end to month-end",
        "default_filters": "exclude charged_off and insolvency_hold",
        "unit": "ratio",
        "good_direction": "down",
        "synonyms": '["flow rate","roll forward","deterioration"]',
        "source_tables": '["card_statements","loan_instalments"]',
        "example_question": "q",
        "owner": "o",
        "certified_flag": "true",
    }
    m = load_metric_definitions([row])["roll_rate"]
    assert m.synonyms == ("flow rate", "roll forward", "deterioration")
    assert m.source_tables == ("card_statements", "loan_instalments") and m.certified_flag is True
    with pytest.raises(ValueError):
        load_metric_definitions([row, row])


# ----------------------------------------------------------------- majority vote
def test_normalize_ignores_order_and_numeric_type() -> None:
    a = ((1, Decimal("0.6400000")), (2, 0.5))
    b = ((2, 0.5), (1, 0.64))
    assert normalize_result(a) == normalize_result(b)


@pytest.mark.parametrize(
    "results,expected",
    [
        ([((1,),), ((1,),), ((2,),)], ((1,),)),
        ([((1,),), ((1,),), ((1,),)], ((1,),)),
        ([((1,),), ((2,),), ((3,),)], None),
        ([((1,),), None, None], None),
        ([((1,),), ((1,),), None], ((1,),)),
        ([None, None, None], None),
        ([], None),
    ],
)
def test_majority_result(results: list[object], expected: object) -> None:
    out = majority_result(results)  # type: ignore[arg-type]
    assert (out is None) == (expected is None)
    if expected is not None:
        assert normalize_result(out) == normalize_result(expected)  # type: ignore[arg-type]


# ----------------------------------------------------------------- grounding
@pytest.mark.parametrize(
    "text,nums",
    [
        ("Kept rate was 64% across 1,234 cases.", [Decimal(64), Decimal(1234)]),
        ("$140.50 due", [Decimal("140.50")]),
        ("Change of -3.5 points", [Decimal("-3.5")]),
        ("No numbers here", []),
        ("Data as of 2026-10-03, due 3 Oct", []),
    ],
)
def test_extract_numbers(text: str, nums: list[Decimal]) -> None:
    assert extract_numbers(text) == nums


def test_grounded_when_every_number_is_in_rows() -> None:
    rows = [("card", 0.6412, 812), ("loan", 0.39, 400)]
    assert is_grounded("Card kept 64% over 812 cases; loan kept 39%.", rows)
    assert is_grounded("Card kept 64.1% of promises.", rows)


def test_not_grounded_when_a_number_is_invented() -> None:
    rows = [("card", 0.6412, 812)]
    assert not is_grounded("Card kept 64% over 900 cases.", rows)
    assert not is_grounded("Card kept 65% of promises.", rows)


def test_numbers_from_the_question_are_allowed() -> None:
    assert is_grounded("Over the last 30 days, 812 cases.", [(812,)], allow=frozenset({Decimal(30)}))


@given(st.integers(min_value=0, max_value=10**9))
def test_any_integer_from_rows_is_grounded(n: int) -> None:
    assert is_grounded(f"There were {n:,} cases.", [(n,)])


@pytest.mark.parametrize(
    "conf,agree,expected", [(0.9, True, False), (0.5, True, True), (0.9, False, True), (0.9, None, False)]
)
def test_needs_clarification(conf: float, agree: bool | None, expected: bool) -> None:
    assert needs_clarification(router_confidence=conf, candidates_agree=agree) is expected


# ----------------------------------------------------------------- privacy
def test_small_groups_suppressed() -> None:
    cols = ("primary_product", "n", "kept_rate")
    rows = [("card", 30, 0.7), ("loan", 9, 0.5), ("auto", 10, 0.6)]
    assert suppress_small_groups(cols, rows, count_column="n") == (("card", 30, 0.7), ("auto", 10, 0.6))


def test_missing_count_column_raises() -> None:
    with pytest.raises(ValueError):
        suppress_small_groups(("primary_product",), [("card",)], count_column="n")


# ----------------------------------------------------------------- policy chunks
def test_policy_chunks_keep_sections() -> None:
    md = "# Hardship policy\n\n## 4.2 Payment reductions\nReductions need a specialist.\n\n## 4.3 Settlement\nSettlements need two approvers.\n"
    chunks = chunk_document("HP-REDUCE", md, effective_from=date(2026, 1, 1), effective_to=None)
    assert [c.section for c in chunks if c.text.strip()] == ["4.2 Payment reductions", "4.3 Settlement"]
    assert all(c.text.strip() for c in chunks)


def test_superseded_documents_get_an_end_date() -> None:
    docs = [
        {"doc_id": "HP-REDUCE-v1", "effective_date": "2025-01-01", "superseded_by": "HP-REDUCE-v2"},
        {"doc_id": "HP-REDUCE-v2", "effective_date": "2026-06-01", "superseded_by": None},
    ]
    w = effective_windows(docs)
    assert w["HP-REDUCE-v1"] == (date(2025, 1, 1), date(2026, 6, 1))
    assert w["HP-REDUCE-v2"] == (date(2026, 6, 1), None)
    with pytest.raises(ValueError):
        effective_windows([{"doc_id": "A", "effective_date": "2025-01-01", "superseded_by": "MISSING"}])


# ----------------------------------------------------------------- benchmark
def test_benchmark_scorecard() -> None:
    cases = [
        BenchmarkCase(f"q{i}", "q", "guardrail" if i >= 8 else "metric", should_refuse=i >= 8)
        for i in range(10)
    ]
    outcomes = [BenchmarkOutcome(f"q{i}", refused=False, correct=i < 7) for i in range(8)]
    outcomes += [
        BenchmarkOutcome("q8", refused=True, correct=None),
        BenchmarkOutcome("q9", refused=False, correct=False),
    ]
    s = score(cases, outcomes)
    assert s.n_in_scope == 8 and s.n_should_refuse == 2
    assert s.accuracy == pytest.approx(7 / 8)
    assert s.refusal_recall == pytest.approx(0.5)
    assert s.refusal_precision == pytest.approx(1.0)
    assert not s.passed
    assert s.accuracy_by_type == {"metric": pytest.approx(7 / 8)}


def test_load_benchmark_rows() -> None:
    rows = [
        {
            "question_id": "B1",
            "question_text": "Roll rate last month?",
            "question_type": "metric",
            "difficulty": "easy",
            "expected_tables": '["card_statements","loan_instalments"]',
            "metric_id": "roll_rate",
            "as_of_date": "2026-09-28",
            "should_refuse": "false",
            "refusal_reason": "",
            "tolerance": "±0.1 pts",
            "grading_rubric": "Correct numbers (60%)",
        }
    ]
    (case,) = load_benchmark(rows)
    assert case.expected_tables == ("card_statements", "loan_instalments") and case.should_refuse is False
    with pytest.raises(ValueError):
        load_benchmark(rows + rows)


@pytest.mark.parametrize(
    "raw,expected", [("±0.1 pts", (0.1, "pts")), ("±2%", (2.0, "%")), ("exact", None), (None, None)]
)
def test_parse_tolerance(raw: str | None, expected: tuple[float, str] | None) -> None:
    assert parse_tolerance(raw) == expected


def test_benchmark_refusing_an_in_scope_question_is_wrong() -> None:
    cases = [BenchmarkCase("a", "q", "metric", False), BenchmarkCase("b", "q", "guardrail", True)]
    s = score(
        cases,
        [
            BenchmarkOutcome("a", refused=True, correct=None),
            BenchmarkOutcome("b", refused=True, correct=None),
        ],
    )
    assert s.accuracy == 0.0 and s.refusal_recall == 1.0 and s.refusal_precision == 0.5


@pytest.mark.parametrize(
    "outcomes",
    [
        [],
        [BenchmarkOutcome("a", False, True), BenchmarkOutcome("a", False, True)],
        [BenchmarkOutcome("a", False, True), BenchmarkOutcome("zzz", False, True)],
    ],
)
def test_benchmark_outcome_mismatch_raises(outcomes: list[BenchmarkOutcome]) -> None:
    with pytest.raises(ValueError):
        score([BenchmarkCase("a", "q", "metric", False)], outcomes)


def test_load_benchmark_released_columns_only() -> None:
    """The released CSV has no question_type / should_refuse / expected_tables."""
    row = {
        "question_id": "BQ-034",
        "question_text": "q",
        "difficulty": "easy",
        "metric_id": "promise_kept_rate",
        "as_of_date": "2026-09-28",
        "tolerance": "±0.1 pts",
        "split": "dev",
    }
    (case,) = load_benchmark([row])
    assert case.should_refuse is False and case.question_type == "metric" and case.expected_tables == ()


def test_write_answers_matches_the_release_template(tmp_path) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "answers.csv"
    write_answers(
        str(out),
        [
            {
                "question_id": "BQ-018",
                "answer": "Refuse: outside scope",
                "sql_or_sources": "",
                "refused": True,
            },
            {
                "question_id": "BQ-004",
                "answer": "queue,avg\na,1",
                "sql_or_sources": "SELECT 1,2",
                "refused": False,
            },
        ],
    )
    lines = out.read_text().splitlines()
    assert lines[0] == "question_id,answer,sql_or_sources,refused"
    assert lines[1] == "BQ-018,Refuse: outside scope,,true"
    assert list(csv.DictReader(out.open()))[1]["answer"] == "queue,avg\na,1"
