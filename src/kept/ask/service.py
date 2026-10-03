"""Orchestrates scope -> route -> answer path -> guard -> grounding. Implements AskService."""

from __future__ import annotations

import json
import os
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
_NARRATE_POLICY = """You answer a collections agent's policy question from the excerpts below, in one to three
plain sentences.
Use only what the excerpts say, and only numbers that appear in them. If excerpts disagree, a policy or
procedure overrides an FAQ or a call script. Name the document and section you used, e.g. (POL-COLL-001 §5.2).
If the excerpts don't answer it, say so."""
_FALLBACK = "The result is in the table below."  # no numbers, so always grounded
_ROW_CAP = 50  # rows sent to the narrator


def _refuse(reason: RefusalReason, message: str) -> Refusal:
    return Refusal(reason=reason, message=message)


_CONVENTIONS = """Conventions (from the data dictionary):
- An open case has collections_cases.outcome IS NULL. A randomised case has assignment_method = 'random'.
- Delinquency buckets, from days past due (dpd / current_dpd): 'current' (0), '1-30', '31-60', '61-90',
  '91-120', '121-150', '151-180', '180+'. Use exactly these labels and compute them from dpd.
- A resolved promise has ptp_status in ('kept', 'partially_kept', 'broken'); open and cancelled are not
  resolved.
- An outbound call is direction = 'outbound' AND channel = 'call'; a right-party contact has rpc_flag.
- contact_history, promises_to_pay and collections_cases join on case_id; promises and contacts join agents on
  agent_id. province_code, queue and test_cell live on collections_cases.
- Dates and hours of contacts use the local time contact_ts_local (never contact_ts_utc); contact_hour_local
  is the hour 0-23. Disputes and complaints raised in a period are contacts with dispute_raised_flag or
  complaint_raised_flag; collections_cases.dispute_flag is only the case's current state."""


def _describe(conn: duckdb.DuckDBPyConnection, policy: SqlPolicy) -> str:
    """One line per allowed table: its non-blocked columns, and for text columns with at most 12 distinct
    values the values themselves, so the LLM writes `ptp_status = 'kept'` and not `= 'fulfilled'`."""
    types = {
        (f"{s}.{t}".lower(), c.lower()): d
        for s, t, c, d in conn.execute(
            "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns"
        ).fetchall()
    }
    lines = []
    for table, cols in sorted(policy.table_columns.items()):
        keep = sorted(cols - policy.blocked_columns)
        text = [c for c in keep if types.get((table, c)) == "VARCHAR"]
        values: dict[str, list[object]] = {}
        if text:
            counts = conn.execute(
                "SELECT " + ", ".join(f'approx_count_distinct("{c}")' for c in text) + f" FROM {table}"
            ).fetchone()
            for c, n in zip(text, counts or (), strict=False):
                if n <= 12:
                    got = conn.execute(
                        f'SELECT DISTINCT "{c}" FROM {table} WHERE "{c}" IS NOT NULL ORDER BY 1 LIMIT 13'
                    ).fetchall()
                    if len(got) <= 12:
                        values[c] = [r[0] for r in got]
        lines.append(
            f"{table}("
            + ", ".join(f"{c} {{{'|'.join(map(str, values[c]))}}}" if c in values else c for c in keep)
            + ")"
        )
    return "\n".join(lines)


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


def _metric_hint(d: MetricDefinition, q: CertifiedQuery) -> str:
    """What the router needs to know about a metric: its names, defaults, allowed filters and group-bys."""
    return (
        f"{d.metric_name} ({', '.join(d.synonyms)}). Default filters already applied: {d.default_filters}. "
        f"Filters: {sorted(q.allowed_filters) or 'none'}. Group by: {sorted(q.allowed_group_by) or 'none'}. "
        f"Dates apply to {q.date_column or 'nothing (no date range)'}."
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
        self._hints = {m: _metric_hint(metrics[m], certified_queries[m]) for m in self._known}
        self._schema_cache: str | None = None
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
                metric_hints=self._hints,
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
            outcome = self._lookup(request, question, intent, fresh)
            if not isinstance(outcome, tuple):
                return outcome
            guarded, ran = outcome
        if ran is None:
            return _refuse(RefusalReason.DATA_UNAVAILABLE, "The query failed or took too long.")
        seen |= {"sql": guarded.sql, "rows": len(ran[1])}
        return self._finish(request, question, intent, guarded, *ran, fresh)

    def _lookup(
        self, request: AskRequest, question: RedactedText, intent: Intent, fresh: datetime | None
    ) -> AskResponse | tuple[GuardResult, tuple[tuple[str, ...], Any]]:
        policy = self._sql_policy()
        drafts = generate_candidates(
            intent,
            self._schema_doc(policy, fresh),
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
        # grounding reads numbers out of the snippets and the cited ids and sections (POL-COLL-001 §5.2)
        rows = tuple((c.document_id, c.section, c.snippet) for c in found)
        data = "\n".join(f"{c.document_id} {c.section}: {c.snippet}" for c in found)
        narrative = self._narrate(
            request,
            question,
            data,
            rows,
            allow=frozenset(extract_numbers(request.question)),
            system=_NARRATE_POLICY,
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
        self,
        request: AskRequest,
        question: RedactedText,
        data: str,
        rows: Any,
        *,
        allow: frozenset[Decimal],
        system: str = _NARRATE,
    ) -> str:
        try:
            reply = self._llm.complete(
                system=system,
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

    def _schema_doc(self, policy: SqlPolicy, fresh: datetime | None) -> str:
        if self._schema_cache is None:  # the warehouse is rebuilt nightly, so describe it once per service
            self._schema_cache = _describe(self._conn, policy)
        today = f" The data's as-of date is {fresh.date()}." if fresh else ""
        return f"{self._schema_cache}\n\n{_CONVENTIONS}{today}"

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


def build_ask(
    conn: duckdb.DuckDBPyConnection,
    audit_log: AuditLog,
    *,
    llm: LLMGateway | None = None,
    redactor: Redactor | None = None,
    policy_dir: str | None = None,
) -> CollectionsAsk:
    """The real Ask: certified metrics from silver.metric_definitions, the contract's table list,
    the hosted free model (KEPT_ASK_LLM_MODEL) through the gateway, Presidio redaction, and the policy
    index when one is built (KEPT_LANCEDB_DIR, default data/policy/lancedb)."""
    from pathlib import Path

    from kept.ask.certified import CERTIFIED_QUERIES
    from kept.ask.metrics import load_metric_definitions
    from kept.ask.scope import make_classifier
    from kept.common.llm import LiteLLMGateway
    from kept.contracts.data_contract import load_data_contract

    llm = llm or LiteLLMGateway(
        model=os.environ["KEPT_ASK_LLM_MODEL"], audit_log=audit_log, max_retries=6, backoff_s=4.0
    )
    if redactor is None:
        from kept.text.redact import PresidioRedactor

        redactor = PresidioRedactor()
    cur = conn.execute("SELECT * FROM silver.metric_definitions")
    names = [d[0] for d in cur.description]
    metrics = load_metric_definitions([dict(zip(names, r, strict=True)) for r in cur.fetchall()])
    index_dir = Path(policy_dir or os.environ.get("KEPT_LANCEDB_DIR", "data/policy/lancedb"))
    return CollectionsAsk(
        conn=conn,
        contract=load_data_contract(),
        llm=llm,
        redactor=redactor,
        classifier=make_classifier(llm, redactor, actor_id="system:ask-scope"),
        metrics=metrics,
        certified_queries=CERTIFIED_QUERIES,
        policy_index=PolicyIndex(index_dir) if index_dir.exists() else None,
        audit_log=audit_log,
    )
