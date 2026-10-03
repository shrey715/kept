"""Orchestrates scope -> route -> answer path -> guard -> grounding. Implements AskService."""

from __future__ import annotations

import duckdb

from kept.ask.metrics import CertifiedQuery, MetricDefinition
from kept.ask.policy import PolicyIndex
from kept.ask.scope import Classifier
from kept.contracts.ask import AskRequest, AskResponse
from kept.contracts.data_contract import DataContract
from kept.contracts.interfaces import AuditLog, LLMGateway, Redactor


class CollectionsAsk:
    def __init__(
        self,
        *,
        conn: duckdb.DuckDBPyConnection,
        contract: DataContract,
        llm: LLMGateway,
        redactor: Redactor,
        classifier: Classifier,
        metrics: dict[str, MetricDefinition],
        certified_queries: dict[str, CertifiedQuery],
        policy_index: PolicyIndex | None,
        audit_log: AuditLog,
    ) -> None:
        raise NotImplementedError("Track B")

    def ask(self, request: AskRequest) -> AskResponse:
        """Always returns AskAnswer, Refusal or Clarification; never raises for user input
        or LLM failure. Logs one AuditKind.ASK_QUERY event per call.

        * rules refuse before any LLM call; the question is redacted before any LLM call;
        * LLM purposes: Purpose.ASK_SCOPE (via classifier), ASK_ROUTE, ASK_SQL (x3 for
          lookups), ASK_NARRATE;
        * no SQL runs unless guard_sql allowed it;
        * disagreement or low confidence -> Clarification on round 0, Refusal(LOW_CONFIDENCE)
          on round >= 1;
        * the returned narrative is always grounded in the returned rows;
        * data_freshness = max(refreshed_at) of gold.c360_customer;
        * analysts get small groups suppressed (privacy.suppress_small_groups)."""
        raise NotImplementedError("Track B")
