"""Orchestrates scope -> route -> answer path -> guard -> grounding. Implements AskService."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import duckdb

from kept.ask.grounding import extract_numbers, is_grounded, needs_clarification
from kept.ask.lookup import generate_candidates, majority_result, normalize_result
from kept.ask.metrics import CertifiedQuery, MetricDefinition, compile_metric
from kept.ask.policy import PolicyIndex
from kept.ask.privacy import suppress_small_groups
from kept.ask.router import route
from kept.ask.scope import Classifier, check_scope, refusal_for
from kept.ask.sql_guard import execute_guarded, guard_sql
from kept.common.audit import new_event_id
from kept.common.llm import Purpose
from kept.config import ASK_SQL_TIMEOUT_S, SQL_CANDIDATES
from kept.contracts.ask import (
    AskAnswer,
    AskRequest,
    AskResponse,
    Clarification,
    GuardResult,
    Intent,
    IntentKind,
    Refusal,
    RefusalReason,
    ScopeDecision,
    SqlPolicy,
)
from kept.contracts.audit import AuditEvent, AuditKind
from kept.contracts.data_contract import DataContract
from kept.contracts.enums import Role
from kept.contracts.features import RedactedText
from kept.contracts.interfaces import AuditLog, LLMGateway, Redactor

_NARRATE = """You explain a query result to a collections analyst in one to three plain sentences.
Use only numbers that appear in the data below. Never add, estimate or compute new numbers.
A column of ratios between 0 and 1 may be written as a percentage. Do not mention SQL.
No data? Say there is nothing to show."""
_FALLBACK = "The result is in the table below."  # no numbers, so always grounded
_ROW_CAP = 50  # rows sent to the narrator


def _refuse(reason: RefusalReason, message: str) -> Refusal:
    return Refusal(reason=reason, message=message)


def build_sql_policy(conn: duckdb.DuckDBPyConnection, contract: DataContract) -> SqlPolicy:
    """The guard's policy: the contract's Ask tables and blocked columns, plus the real columns of
    each allowed table (read from the warehouse) so the star rule knows what a star would return."""
    allowed = frozenset(t.lower() for t in contract.ask_allowed_tables)
    cols: dict[str, set[str]] = {}
    for schema, table, col in conn.execute(
        "SELECT table_schema, table_name, column_name FROM information_schema.columns"
    ).fetchall():
        if (name := f"{schema}.{table}".lower()) in allowed:
            cols.setdefault(name, set()).add(col.lower())
    return SqlPolicy(
        allowed_tables=allowed,
        blocked_columns=frozenset(c.lower() for c in contract.ask_blocked_columns()),
        table_columns={t: frozenset(c) for t, c in cols.items()},
    )


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
        self._conn, self._contract, self._llm, self._redactor = conn, contract, llm, redactor
        self._classifier, self._metrics, self._queries = classifier, metrics, certified_queries
        self._policy_index, self._audit = policy_index, audit_log
        self._known = frozenset(m for m, d in metrics.items() if d.certified_flag and m in certified_queries)
        self._allowed = frozenset(t.lower() for t in contract.ask_allowed_tables)
        self._blocked = frozenset(c.lower() for c in contract.ask_blocked_columns())

    # ------------------------------------------------------------------ public
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
        question = self._redactor.redact(request.question)
        seen: dict[str, Any] = {}
        try:
            response = self._answer(request, question, seen)
        except Exception as e:  # never raises: a bug here is a refusal, not a 500
            seen["error"] = type(e).__name__
            response = _refuse(RefusalReason.LOW_CONFIDENCE, "Something went wrong, so I didn't answer.")
        self._log(request, question, response, seen)
        return response

    # ------------------------------------------------------------------ pipeline
    def _answer(self, request: AskRequest, question: RedactedText, seen: dict[str, Any]) -> AskResponse:
        decision = check_scope(request, self._contract, self._classifier)
        if not decision.in_scope:
            return refusal_for(decision, suggestion=None)
        fresh = self._freshness()
        try:
            intent = route(
                question,
                self._llm,
                known_metric_ids=self._known,
                actor_id=request.user_id,
                as_of=fresh.date() if fresh else None,
            )
        except Exception:
            return self._unsure(request, "I couldn't work out what you're asking.")
        seen["intent"] = intent.kind.value
        if needs_clarification(router_confidence=intent.confidence, candidates_agree=None):
            return self._unsure(request, "I'm not sure what you mean.", intent)

        if intent.kind is IntentKind.POLICY:
            return self._policy(request, question, intent, fresh)
        if intent.kind is IntentKind.METRIC:
            try:
                sql, params = compile_metric(intent, self._metrics, self._queries)
            except ValueError as e:
                return self._unsure(request, f"I can't compute that as asked ({e}).", intent)
            guarded = guard_sql(sql, self._sql_policy())
            if not guarded.allowed:
                return _refuse(RefusalReason.SQL_GUARD, guarded.reason or "The query is not allowed.")
            ran = self._run(guarded, params)
        else:
            outcome = self._lookup(request, question, intent)
            if not isinstance(outcome, tuple):
                return outcome
            guarded, ran = outcome
        if ran is None:
            return _refuse(RefusalReason.DATA_UNAVAILABLE, "The query failed or took too long.")
        seen |= {"sql": guarded.sql, "rows": len(ran[1])}
        return self._finish(request, question, intent, guarded, *ran, fresh)

    def _lookup(
        self, request: AskRequest, question: RedactedText, intent: Intent
    ) -> AskResponse | tuple[GuardResult, tuple[tuple[str, ...], Any]]:
        policy = self._sql_policy()
        drafts = generate_candidates(
            intent,
            self._schema_doc(policy),
            self._llm,
            n=SQL_CANDIDATES,
            actor_id=request.user_id,
            question=question,
        )
        guards = [guard_sql(d, policy) for d in drafts]
        if guards and not any(g.allowed for g in guards):
            return _refuse(RefusalReason.SQL_GUARD, guards[0].reason or "The query is not allowed.")
        ran = [self._run(g) if g.allowed else None for g in guards]
        ran += [None] * (SQL_CANDIDATES - len(ran))  # drafts the LLM never produced vote for nothing
        winner = majority_result([r[1] if r else None for r in ran])
        if needs_clarification(router_confidence=intent.confidence, candidates_agree=winner is not None):
            return self._unsure(request, "I got different answers when I tried that a few ways.", intent)
        key = normalize_result(winner or ())
        return next((g, r) for g, r in zip(guards, ran, strict=False) if r and normalize_result(r[1]) == key)

    def _finish(
        self,
        request: AskRequest,
        question: RedactedText,
        intent: Intent,
        guarded: GuardResult,
        columns: tuple[str, ...],
        rows: Any,
        fresh: datetime | None,
    ) -> AskResponse:
        if request.role is Role.ANALYST:  # analysts see aggregates of 10 or more
            try:
                rows = suppress_small_groups(columns, rows, count_column="n")
            except ValueError:
                return _refuse(
                    RefusalReason.SMALL_GROUP, "Analysts can only see counted groups; I can't check this one."
                )
            if not rows:
                return refusal_for(
                    ScopeDecision(in_scope=False, reason=RefusalReason.SMALL_GROUP, decided_by="rules"),
                    suggestion=None,
                )
        data = json.dumps({"columns": columns, "rows": rows[:_ROW_CAP]}, default=str)
        narrative = self._narrate(
            request, question, data, rows, allow=frozenset(extract_numbers(request.question))
        )
        return AskAnswer(
            question=request.question,
            intent=intent,
            sql=guarded.sql,
            tables_used=tuple(sorted(guarded.tables)),
            data_freshness=fresh,
            columns=columns,
            rows=rows,
            narrative=narrative,
        )

    def _policy(
        self, request: AskRequest, question: RedactedText, intent: Intent, fresh: datetime | None
    ) -> AskResponse:
        if self._policy_index is None:
            return _refuse(RefusalReason.DATA_UNAVAILABLE, "Policy search isn't available right now.")
        found = self._policy_index.search(request.question, as_of=(fresh or datetime.now(UTC)).date())
        if not found:
            return _refuse(RefusalReason.DATA_UNAVAILABLE, "I found no current policy section on that.")
        rows = tuple((c.snippet,) for c in found)  # grounding reads numbers out of the snippets
        data = "\n".join(f"{c.document_id} {c.section}: {c.snippet}" for c in found)
        narrative = self._narrate(
            request, question, data, rows, allow=frozenset(extract_numbers(request.question))
        )
        return AskAnswer(
            question=request.question,
            intent=intent,
            sql=None,
            tables_used=(),
            data_freshness=None,
            narrative=narrative,
            citations=tuple(found),
        )

    # ------------------------------------------------------------------ helpers
    def _unsure(self, request: AskRequest, why: str, intent: Intent | None = None) -> AskResponse:
        """One clarifying question, then refuse."""
        if request.clarification_round == 0:
            return Clarification(
                question=f"{why} Which metric, product or date range do you mean?", intent=intent
            )
        return _refuse(RefusalReason.LOW_CONFIDENCE, f"{why} I still can't answer it, so I stopped.")

    def _narrate(
        self, request: AskRequest, question: RedactedText, data: str, rows: Any, *, allow: frozenset[Decimal]
    ) -> str:
        try:
            reply = self._llm.complete(
                system=_NARRATE,
                user=self._redactor.redact(f"Question: {question.text}\nData: {data}"),
                purpose=Purpose.ASK_NARRATE,
                actor_id=request.user_id,
            )
            if reply.text.strip() and is_grounded(reply.text, rows, allow=allow):
                return reply.text.strip()
        except Exception:
            pass
        return _FALLBACK  # numbers only from rows: an ungrounded or missing narration is dropped

    def _sql_policy(self) -> SqlPolicy:
        return build_sql_policy(self._conn, self._contract)

    def _schema_doc(self, policy: SqlPolicy) -> str:
        return "\n".join(
            f"{t}({', '.join(sorted(c - policy.blocked_columns))})"
            for t, c in sorted(policy.table_columns.items())
        )

    def _run(
        self, guarded: GuardResult, params: list[object] | None = None
    ) -> tuple[tuple[str, ...], Any] | None:
        try:
            return execute_guarded(self._conn, guarded, params=params, timeout_s=ASK_SQL_TIMEOUT_S)
        except Exception:  # timeout, missing table, bad SQL: this candidate has no result
            return None

    def _freshness(self) -> datetime | None:
        try:
            row = self._conn.execute("SELECT max(refreshed_at) FROM gold.c360_customer").fetchone()
        except duckdb.Error:
            return None
        return row[0] if row else None

    def _log(
        self, request: AskRequest, question: RedactedText, response: AskResponse, seen: dict[str, Any]
    ) -> None:
        payload = {
            "question": question.text,
            "response": response.kind,
            "round": request.clarification_round,
            **seen,
        }
        if isinstance(response, Refusal):
            payload["reason"] = response.reason.value
        self._audit.append(
            AuditEvent(
                event_id=new_event_id(),
                at=datetime.now(UTC),
                kind=AuditKind.ASK_QUERY,
                actor_id=request.user_id,
                actor_role=request.role,
                payload=payload,
            )
        )
