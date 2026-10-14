"""End-to-end Collections Ask against a tiny warehouse, with a purpose-routed fake LLM."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import duckdb
import pytest

from kept.ask.grounding import is_grounded
from kept.ask.metrics import CertifiedQuery, MetricDefinition
from kept.common.llm import Purpose
from kept.contracts import (
    AskAnswer,
    AskRequest,
    AuditKind,
    Clarification,
    Refusal,
    RefusalReason,
    Role,
    ScopeDecision,
)
from kept.contracts.data_contract import DataContract

from ..fakes import InMemoryAuditLog, PassThroughRedactor, PurposeLLM

pytest.importorskip("sqlglot")  # Track B's `ask` extra; CI installs core only
from kept.ask.service import CollectionsAsk

LOOKUP_INTENT = {"kind": "lookup", "confidence": 0.9}
METRIC_INTENT = {
    "kind": "metric",
    "metric_id": "promise_kept_rate",
    "group_by": ["primary_product"],
    "confidence": 0.95,
}
GOOD_SQL = "SELECT primary_product, count(*) AS n FROM silver.collections_cases GROUP BY primary_product ORDER BY primary_product"


def _ok(_: str) -> ScopeDecision:
    return ScopeDecision(in_scope=True, decided_by="classifier")


@pytest.fixture
def build(
    ask_db: duckdb.DuckDBPyConnection,
    ask_contract: DataContract,
    metrics: dict[str, MetricDefinition],
    certified_queries: dict[str, CertifiedQuery],
    audit_log: InMemoryAuditLog,
):  # type: ignore[no-untyped-def]
    def _build(replies: Mapping[str, Sequence[Any]]) -> tuple[CollectionsAsk, PurposeLLM]:
        llm = PurposeLLM(replies)
        svc = CollectionsAsk(
            conn=ask_db,
            contract=ask_contract,
            llm=llm,
            redactor=PassThroughRedactor(),
            classifier=_ok,
            metrics=metrics,
            certified_queries=certified_queries,
            policy_index=None,
            audit_log=audit_log,
        )
        return svc, llm

    return _build


@pytest.fixture
def build_with_calls(  # type: ignore[no-untyped-def]
    ask_db, ask_contract, metrics, certified_queries, audit_log
):
    """A service whose call summariser is a fake (Track C's lives in kept.text.calls)."""

    def _build(summarise):  # type: ignore[no-untyped-def]
        llm = PurposeLLM({})
        svc = CollectionsAsk(
            conn=ask_db,
            contract=ask_contract,
            llm=llm,
            redactor=PassThroughRedactor(),
            classifier=_ok,
            metrics=metrics,
            certified_queries=certified_queries,
            policy_index=None,
            audit_log=audit_log,
            summarise_call=summarise,
        )
        return svc, llm

    return _build


def _req(q: str, *, role: Role = Role.ANALYST, round_: int = 0) -> AskRequest:
    return AskRequest(question=q, user_id="u1", role=role, clarification_round=round_)


def test_metric_answer_shows_sql_tables_and_freshness(build, audit_log: InMemoryAuditLog) -> None:  # type: ignore[no-untyped-def]
    svc, llm = build(
        {
            Purpose.ASK_ROUTE: [METRIC_INTENT],
            Purpose.ASK_NARRATE: ["Promise kept rate by product is shown in the table."],
        }
    )
    a = svc.ask(_req("promise kept rate by product"))
    assert isinstance(a, AskAnswer)
    assert a.sql and "promises_to_pay" in a.sql
    assert "silver.promises_to_pay" in a.tables_used
    assert a.data_freshness is not None
    assert Purpose.ASK_SQL not in llm.purposes()  # certified metric: the LLM never writes the SQL
    assert len(audit_log.read(kind=AuditKind.ASK_QUERY)) == 1


def test_lookup_majority_answer(build) -> None:  # type: ignore[no-untyped-def]
    svc, llm = build(
        {
            Purpose.ASK_ROUTE: [LOOKUP_INTENT],
            Purpose.ASK_SQL: [GOOD_SQL, GOOD_SQL, "SELECT 1 AS n FROM silver.collections_cases LIMIT 1"],
            Purpose.ASK_NARRATE: ["There are 30 card cases and 30 loan cases."],
        }
    )
    a = svc.ask(_req("how many cases per product"))
    assert isinstance(a, AskAnswer)
    assert a.rows == (("credit_card", 30), ("personal_loan", 30))
    assert llm.purposes().count(Purpose.ASK_SQL) == 3


def test_ungrounded_narrative_never_reaches_the_user(build) -> None:  # type: ignore[no-untyped-def]
    svc, _ = build(
        {
            Purpose.ASK_ROUTE: [LOOKUP_INTENT],
            Purpose.ASK_SQL: [GOOD_SQL],
            Purpose.ASK_NARRATE: ["There are 31 card cases and 29 loan cases."],
        }
    )
    a = svc.ask(_req("how many cases per product"))
    assert isinstance(a, (AskAnswer, Refusal, Clarification))
    if isinstance(a, AskAnswer):
        assert is_grounded(a.narrative, a.rows)


def test_protected_question_refused_before_any_llm_call(build) -> None:  # type: ignore[no-untyped-def]
    svc, llm = build({})
    r = svc.ask(_req("kept rate by gender_code"))
    assert isinstance(r, Refusal) and r.reason is RefusalReason.PROTECTED_ATTRIBUTE
    assert "gender_code" in r.message
    assert r.suggestion == "Try: What is the promise kept rate for cards?"  # nearest allowed question
    assert llm.calls == []


def test_nearest_question_needs_shared_words(metrics) -> None:  # type: ignore[no-untyped-def]
    from kept.ask.service import nearest_question

    assert (
        nearest_question("Which customers broke a promise, by gender?", metrics)
        == metrics["promise_kept_rate"].example_question
    )
    assert nearest_question("What will the weather be in Toronto tomorrow?", metrics) is None
    assert nearest_question("draft metric please", {"d": metrics["draft_metric"]}) is None  # uncertified


def test_disagreeing_candidates_clarify_then_refuse(build) -> None:  # type: ignore[no-untyped-def]
    replies = {
        Purpose.ASK_ROUTE: [LOOKUP_INTENT],
        Purpose.ASK_SQL: [
            GOOD_SQL,
            "SELECT count(*) AS n FROM silver.collections_cases",
            "SELECT count(*) AS n FROM silver.promises_to_pay WHERE ptp_status = 'kept'",
        ],
    }
    svc, _ = build(replies)
    assert isinstance(svc.ask(_req("how many?")), Clarification)
    svc, _ = build(replies)
    r = svc.ask(_req("how many?", round_=1))
    assert isinstance(r, Refusal) and r.reason is RefusalReason.LOW_CONFIDENCE


def test_llm_sql_touching_blocked_columns_is_never_executed(build, ask_db: duckdb.DuckDBPyConnection) -> None:  # type: ignore[no-untyped-def]
    svc, _ = build(
        {
            Purpose.ASK_ROUTE: [LOOKUP_INTENT],
            Purpose.ASK_SQL: ["SELECT display_name, email FROM gold.c360_customer"],
        }
    )
    r = svc.ask(_req("who owes the most?"))
    assert not isinstance(r, AskAnswer)


def test_llm_outage_does_not_raise(build) -> None:  # type: ignore[no-untyped-def]
    svc, _ = build({Purpose.ASK_ROUTE: [RuntimeError("provider down")]})
    r = svc.ask(_req("promise kept rate by product"))
    assert isinstance(r, (Refusal, Clarification))


def test_analyst_small_groups_suppressed(build) -> None:  # type: ignore[no-untyped-def]
    small = "SELECT golden_customer_id, count(*) AS n FROM gold.c360_customer GROUP BY 1 ORDER BY 1"
    svc, _ = build(
        {
            Purpose.ASK_ROUTE: [LOOKUP_INTENT],
            Purpose.ASK_SQL: [small],
            Purpose.ASK_NARRATE: ["No group is large enough to show."],
        }
    )
    r = svc.ask(_req("count per customer"))
    if isinstance(r, AskAnswer):
        assert r.rows == ()
    else:
        assert isinstance(r, Refusal)


def test_every_call_is_audited(build, audit_log: InMemoryAuditLog) -> None:  # type: ignore[no-untyped-def]
    svc, _ = build({Purpose.ASK_ROUTE: [RuntimeError("down")]})
    svc.ask(_req("kept rate by gender_code"))
    svc.ask(_req("anything"))
    assert len(audit_log.read(kind=AuditKind.ASK_QUERY)) == 2


def test_ungrounded_narrative_is_replaced_not_returned(build) -> None:  # type: ignore[no-untyped-def]
    svc, _ = build(
        {
            Purpose.ASK_ROUTE: [LOOKUP_INTENT],
            Purpose.ASK_SQL: [GOOD_SQL],
            Purpose.ASK_NARRATE: ["There are 31 card cases and 29 loan cases."],  # the rows say 30 and 30
        }
    )
    a = svc.ask(_req("how many cases per product"))
    assert isinstance(a, AskAnswer) and "31" not in a.narrative and is_grounded(a.narrative, a.rows)


def test_grounded_narrative_is_kept(build) -> None:  # type: ignore[no-untyped-def]
    svc, _ = build(
        {
            Purpose.ASK_ROUTE: [LOOKUP_INTENT],
            Purpose.ASK_SQL: [GOOD_SQL],
            Purpose.ASK_NARRATE: ["There are 30 card cases and 30 loan cases."],
        }
    )
    a = svc.ask(_req("how many cases per product"))
    assert isinstance(a, AskAnswer) and a.narrative == "There are 30 card cases and 30 loan cases."


def test_low_router_confidence_clarifies_without_running_sql(build) -> None:  # type: ignore[no-untyped-def]
    svc, llm = build({Purpose.ASK_ROUTE: [{"kind": "lookup", "confidence": 0.2}]})
    assert isinstance(svc.ask(_req("hmm")), Clarification)
    assert Purpose.ASK_SQL not in llm.purposes()


def test_policy_question_without_an_index_is_refused_politely(build) -> None:  # type: ignore[no-untyped-def]
    svc, _ = build({Purpose.ASK_ROUTE: [{"kind": "policy", "confidence": 0.9}]})
    r = svc.ask(_req("what does the hardship policy say?"))
    assert isinstance(r, Refusal) and r.reason is RefusalReason.DATA_UNAVAILABLE


def test_audit_payload_holds_the_redacted_question_only(build, audit_log: InMemoryAuditLog) -> None:  # type: ignore[no-untyped-def]
    svc, _ = build({Purpose.ASK_ROUTE: [RuntimeError("down")]})
    svc.ask(_req("anything"))
    (event,) = audit_log.read(kind=AuditKind.ASK_QUERY)
    assert event.payload["question"] == "anything" and event.payload["response"] in {
        "clarification",
        "refusal",
    }


def test_policy_question_is_answered_with_citations(
    tmp_path, ask_db, ask_contract, metrics, certified_queries, audit_log
) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("lancedb")
    from datetime import date

    from kept.ask.policy import PolicyChunk, PolicyIndex

    idx = PolicyIndex(tmp_path / "lance")
    idx.add(
        [
            PolicyChunk(
                "POL-COLL-001",
                "§5.2 Contact frequency",
                "A maximum of 3 outbound call attempts in any rolling 7 days.",
                date(2026, 1, 1),
                None,
                "policy",
            )
        ]
    )
    llm = PurposeLLM(
        {
            Purpose.ASK_ROUTE: [{"kind": "policy", "confidence": 0.9}],
            Purpose.ASK_NARRATE: ["At most 3 attempts in any rolling 7 days (POL-COLL-001 §5.2)."],
        }
    )
    svc = CollectionsAsk(
        conn=ask_db,
        contract=ask_contract,
        llm=llm,
        redactor=PassThroughRedactor(),
        classifier=_ok,
        metrics=metrics,
        certified_queries=certified_queries,
        policy_index=idx,
        audit_log=audit_log,
    )
    a = svc.ask(_req("how many call attempts can we make in a week?"))
    assert isinstance(a, AskAnswer) and a.sql is None
    assert a.citations and a.citations[0].document_id == "POL-COLL-001"
    assert (
        a.narrative == "At most 3 attempts in any rolling 7 days (POL-COLL-001 §5.2)."
    )  # grounded in the excerpt


def test_relative_dates_use_the_snapshot_date_not_the_gold_build_time(build, ask_db) -> None:  # type: ignore[no-untyped-def]
    """Gold's refreshed_at is when it was built; "today" for the router is its as_of_date."""
    ask_db.execute("ALTER TABLE gold.c360_customer ADD COLUMN as_of_date DATE DEFAULT DATE '2026-09-28'")
    svc, llm = build({Purpose.ASK_ROUTE: [METRIC_INTENT], Purpose.ASK_NARRATE: ["ok"]})
    svc.ask(_req("promise kept rate by product"))
    route_call = next(c for c in llm.calls if c["purpose"] == Purpose.ASK_ROUTE)
    assert "relative to 2026-09-28" in route_call["system"]


def test_a_draft_that_will_not_run_is_repaired_once_with_the_error(build) -> None:  # type: ignore[no-untyped-def]
    """Draft 1 names a column that does not exist; the model sees the error and corrects it, so the vote has
    two agreeing drafts instead of refusing."""
    other = "SELECT count(*) AS n FROM silver.collections_cases"
    svc, llm = build(
        {
            Purpose.ASK_ROUTE: [LOOKUP_INTENT],
            Purpose.ASK_SQL: [
                "SELECT nope FROM silver.collections_cases",
                GOOD_SQL,
                other,
                GOOD_SQL,
            ],  # last: the repair
            Purpose.ASK_NARRATE: ["There are 30 card cases and 30 loan cases."],
        }
    )
    a = svc.ask(_req("how many cases per product"))
    assert isinstance(a, AskAnswer) and a.rows == (("credit_card", 30), ("personal_loan", 30))
    repair = [c for c in llm.calls if c["purpose"] == Purpose.ASK_SQL][-1]
    assert "failed with" in repair["user"].text and "nope" in repair["user"].text


# ----------------------------------------------------------------- "summarise the most recent call on case X"
CALL_Q = (
    "Summarise the most recent recorded call on case CS-2026-614370: what did the customer say and agree to?"
)


class _Summary:
    def __init__(self) -> None:
        self.transcript_id = "5010384"
        self.call_start = "2026-09-20 10:15:00"
        self.summary = "Customer reports illness; promised $95 on 14 Oct; next step: hardship review."


def test_call_summary_is_answered_before_the_scope_check(build_with_calls) -> None:  # type: ignore[no-untyped-def]
    seen: list[str] = []

    def summarise(case_id: str, **kw: object) -> _Summary:
        seen.append(case_id)
        assert kw["conn"] is not None and kw["actor_id"] == "u1"  # the Ask's connection and the asker
        return _Summary()

    svc, llm = build_with_calls(summarise)
    a = svc.ask(_req(CALL_Q))
    assert isinstance(a, AskAnswer) and seen == ["CS-2026-614370"]
    assert a.narrative.startswith("Customer reports illness; promised $95")
    assert (
        a.citations[0].document_id == "text.redacted_notes" and a.citations[0].section == "transcript 5010384"
    )
    assert llm.calls == []  # no router or scope call: the transcript summary is the whole answer


def test_call_summary_with_no_recorded_call_is_an_answer_not_a_refusal(build_with_calls) -> None:  # type: ignore[no-untyped-def]
    svc, _ = build_with_calls(lambda case_id, **kw: None)
    a = svc.ask(_req(CALL_Q))
    assert isinstance(a, AskAnswer) and a.narrative == "There is no recorded call on case CS-2026-614370."


def test_an_agent_cannot_summarise_a_call_on_someone_elses_case(build_with_calls) -> None:  # type: ignore[no-untyped-def]
    called: list[str] = []
    svc, _ = build_with_calls(lambda case_id, **kw: called.append(case_id))
    req = AskRequest(question=CALL_Q, user_id="a1", role=Role.AGENT, own_case_ids=frozenset({"CS-1"}))
    r = svc.ask(req)
    assert isinstance(r, Refusal) and r.reason is RefusalReason.OTHER_PEOPLES_CASES and called == []


def test_a_failing_summariser_is_a_polite_refusal_not_a_crash(build_with_calls) -> None:  # type: ignore[no-untyped-def]
    def boom(case_id: str, **kw: object) -> None:
        raise RuntimeError("transcript store down")

    svc, _ = build_with_calls(boom)
    assert isinstance(svc.ask(_req(CALL_Q)), Refusal)


def test_a_narration_with_an_invented_number_gets_one_retry(build) -> None:  # type: ignore[no-untyped-def]
    """The first narration states a difference that is not in the rows; told so, the second does not."""
    svc, llm = build(
        {
            Purpose.ASK_ROUTE: [LOOKUP_INTENT],
            Purpose.ASK_SQL: [GOOD_SQL],
            Purpose.ASK_NARRATE: [
                "Card has 30 cases, 12 more than nothing at all.",
                "Both products have 30 cases each.",
            ],
        }
    )
    a = svc.ask(_req("how many cases per product"))
    assert isinstance(a, AskAnswer) and a.narrative == "Both products have 30 cases each."
    second = [c for c in llm.calls if c["purpose"] == Purpose.ASK_NARRATE][1]
    assert "not in the data: 12" in second["user"].text


def test_nothing_to_show_with_rows_falls_back(build) -> None:  # type: ignore[no-untyped-def]
    svc, _ = build(
        {
            Purpose.ASK_ROUTE: [METRIC_INTENT],
            Purpose.ASK_NARRATE: ["There is nothing to show."],
        }
    )
    a = svc.ask(_req("promise kept rate by product"))
    assert isinstance(a, AskAnswer) and a.rows
    assert a.narrative == "The result is in the table below."


def test_metric_hint_names_the_product_family_values() -> None:
    from kept.ask.certified import CERTIFIED_QUERIES
    from kept.ask.metrics import MetricDefinition
    from kept.ask.service import _metric_hint

    d = MetricDefinition(
        "delinquency_rate", "Delinquency rate", "", "", "", "", "", "", "", (), (), "", "", True
    )
    assert "product_family = 'card'" in _metric_hint(d, CERTIFIED_QUERIES["delinquency_rate"])


def test_every_answer_carries_the_path_the_graph_took(build) -> None:  # type: ignore[no-untyped-def]
    svc, _ = build(
        {
            Purpose.ASK_ROUTE: [METRIC_INTENT],
            Purpose.ASK_NARRATE: ["Promise kept rate by product is shown in the table."],
        }
    )
    a = svc.ask(_req("promise kept rate by product"))
    assert a.trace[0] == "Safety rules: passed" and any(t.startswith("Route: metric") for t in a.trace)
    assert "SQL guard: allowed" in a.trace and a.trace[-1].startswith("Narration")
    refused = svc.ask(_req("promise kept rate by gender"))
    assert refused.kind == "refusal" and refused.trace[-1].startswith("Safety rules: refused")


def test_check_channel_adds_the_channel_the_question_names() -> None:
    from kept.ask.graph import check_channel
    from kept.contracts.ask import Intent, IntentKind

    i = Intent(
        kind=IntentKind.METRIC, metric_id="cost_per_rpc", filters={"direction": "outbound"}, confidence=1.0
    )
    fixed, note = check_channel(
        "cost per right-party contact on outbound calls last week", i, {"channel", "direction"}
    )
    assert fixed.filters == {"direction": "outbound", "channel": "call"} and note
    assert (
        check_channel("cost per contact by calls and emails", i, {"channel"})[1] is None
    )  # two channels: ask
    assert check_channel("cost per right-party contact on calls", i, {"direction"})[1] is None  # not allowed
    set_ = i.model_copy(update={"filters": {"channel": "sms"}})
    assert check_channel("outbound calls", set_, {"channel"})[0] is set_  # the router's choice stands


def test_ground_filters_maps_near_misses_and_drops_unknown_values() -> None:
    from kept.ask.graph import ground_filters
    from kept.contracts.ask import Intent, IntentKind

    known = {"ptp_type": ["single", "instalment_1_of_n"], "is_open": [True, False]}
    i = Intent(
        kind=IntentKind.METRIC,
        metric_id="promise_kept_rate",
        filters={"ptp_type": ["single", "instalment"], "is_open": True},
        group_by=["ptp_type"],
        confidence=0.9,
    )
    fixed, notes = ground_filters(i, known.get)
    assert fixed.filters == {"ptp_type": ["single", "instalment_1_of_n"], "is_open": True}
    assert notes == ["Value check: ptp_type 'instalment' -> instalment_1_of_n"]
    gone, _ = ground_filters(i.model_copy(update={"filters": {"ptp_type": "weekly"}}), known.get)
    assert "ptp_type" not in gone.filters  # matches nothing: the comparison covers every group
    same, n = ground_filters(i.model_copy(update={"filters": {"ptp_type": "single"}, "group_by": ()}), known.get)
    assert same.filters == {"ptp_type": "single"} and n == []
    one, _ = ground_filters(i.model_copy(update={"filters": {"ptp_type": "instalment"}}), known.get)
    assert "ptp_type" not in one.filters  # grouped by it: the question compares, so every group stays


def test_repair_intent_fits_loose_column_names_to_the_certified_query() -> None:
    from types import SimpleNamespace

    from kept.ask.graph import repair_intent
    from kept.contracts.ask import Intent, IntentKind

    q = SimpleNamespace(
        date_column="ptp_due_date",
        allowed_filters=frozenset({"site", "product", "ptp_type"}),
        allowed_group_by=frozenset({"site", "product", "ptp_type"}),
    )
    i = Intent(
        kind=IntentKind.METRIC,
        metric_id="broken_promise_rate",
        filters={"ptp_due_date": "2026-07", "is_open": True},
        group_by=["agent_site", "ptp_due_date"],
        confidence=0.9,
    )
    fixed, notes = repair_intent(i, q)
    assert fixed.filters == {} and fixed.group_by == ["site"]
    assert "Intent repair: grouping agent_site -> site" in notes and len(notes) == 4
    ok = i.model_copy(update={"filters": {"site": "Halifax"}, "group_by": ["product"]})
    assert repair_intent(ok, q) == (ok, [])


def test_check_open_drops_is_open_unless_the_question_asks_about_open_cases() -> None:
    from kept.ask.graph import check_open
    from kept.contracts.ask import Intent, IntentKind

    i = Intent(kind=IntentKind.METRIC, metric_id="hardship_rate", filters={"is_open": True}, confidence=0.9)
    assert check_open("hardship rate of cases opened in 2026, by product", i)[0].filters == {}
    assert check_open("hardship rate of open cases by product", i) == (i, None)


def test_relevance_check_catches_routes_with_nothing_in_common() -> None:
    from kept.ask.graph import relevant

    assert not relevant(
        "How many collections cases are open today, by current bucket?",
        "delinquency_rate",
        "Delinquency rate",
        ["delinquent share", "arrears rate"],
    )
    assert relevant(
        "What share of active card accounts are 1 or more days past due today?",
        "delinquency_rate",
        "Delinquency rate",
        ["delinquent share"],
    )
    assert relevant(
        "How much was paid against promises in September?",
        "collected_amount",
        "Amount collected",
        ["collections"],
    )


def test_a_can_we_question_is_a_policy_question() -> None:
    from kept.ask.graph import _POLICY

    assert _POLICY.search("How many call attempts can we make on a mid-stage account in a week?")
    assert _POLICY.search("Are collection calls allowed on Sundays?")
    assert not _POLICY.search("What share of outbound calls were outside permitted calling hours?")
