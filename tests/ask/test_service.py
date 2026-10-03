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
    assert r.suggestion is None or r.suggestion.startswith("Try: ")
    assert llm.calls == []


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
