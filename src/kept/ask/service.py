"""Orchestrates scope -> route -> answer path -> guard -> grounding. Implements AskService."""

from __future__ import annotations

import importlib
import json
import os
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import duckdb

from kept.ask.graph import build_graph
from kept.ask.graph import run as run_graph
from kept.ask.grounding import extract_numbers, needs_clarification, ungrounded_numbers
from kept.ask.lookup import (
    draft_sql,
    generate_candidates,
    lint_sql,
    lookup_system,
    majority_result,
    normalize_result,
    pin_today,
    qualify_tables,
)
from kept.ask.metrics import CertifiedQuery, MetricDefinition
from kept.ask.policy import PolicyIndex, local_embedder
from kept.ask.privacy import suppress_small_groups
from kept.ask.scope import Classifier, refusal_for
from kept.ask.sql_guard import execute_guarded, guard_sql
from kept.ask.templates import date_hints, examples, resolve_dates
from kept.common.audit import new_event_id
from kept.common.llm import Purpose
from kept.config import ASK_SQL_TIMEOUT_S, SQL_CANDIDATES, SQL_EXTRA
from kept.contracts.ask import (
    AskAnswer,
    AskRequest,
    AskResponse,
    Citation,
    Clarification,
    GuardResult,
    Intent,
    IntentKind,
    Refusal,
    RefusalReason,
    ScopeDecision,
    SourceText,
    SqlPolicy,
)
from kept.contracts.audit import AuditEvent, AuditKind
from kept.contracts.data_contract import DataContract
from kept.contracts.enums import Role
from kept.contracts.features import RedactedText
from kept.contracts.interfaces import AuditLog, LLMGateway, Redactor

_NARRATE = """You explain a query result to a collections analyst in one to three plain sentences.
Use only numbers that appear in the data below. Never add, estimate or compute new numbers.
Only a column whose name ends in _rate, _share or _pct is a ratio (0 to 1) that may be written as a
percentage. Amounts and costs (cost_per_contact, amounts in CAD) are dollars: never turn them into
percentages. To compare two values, say which is higher or lower in words and do not state the
difference. Round a percentage to one decimal place (35.1%) and any other number to at most two.
Do not mention SQL.
No data? Say there is nothing to show."""
_NARRATE_POLICY = """You answer a collections agent's policy question from the excerpts below, in one to three
plain sentences.
Use only what the excerpts say, and only numbers that appear in them. If excerpts disagree, a policy or
procedure overrides an FAQ or a call script. Name the document and section you used, e.g. (POL-COLL-001 §5.2).
If the excerpts don't answer it, say so."""
# "Summarise the most recent (recorded) call on case CS-2026-614370 ...": answered from the call's redacted
# transcript (kept.text.calls), before the scope check, which sees "personal data" in it.
_CALL_SUMMARY = re.compile(
    r"\b(?:summari[sz]e|summary of)\b.*?\b(?:most recent|latest|last)\b.*?\bcall\b.*?\bcase\s+(CS?-\d[\w-]*)",
    re.I | re.S,
)
_FALLBACK = "The result is in the table below."  # no numbers, so always grounded
_ROW_CAP = 50  # rows sent to the narrator


def _refuse(reason: RefusalReason, message: str) -> Refusal:
    return Refusal(reason=reason, message=message)


_SECTION_NO = re.compile(r"§\s?\d+(?:\.\d+)*")


def tag_citations(found: list[Citation], narrative: str) -> tuple[Citation, ...]:
    """Mark which retrieved sections the answer actually names, and number them [1], [2]... in that order;
    the rest stay attached as "retrieved, not relied on". A section is named by "DOC §n.n"; a document
    without section numbers (an incident report) by its id alone."""

    def mention(c: Citation) -> str | None:
        if c.document_id not in narrative:
            return None
        sec = _SECTION_NO.match(c.section)
        if sec is None:
            return c.document_id
        for sep in (" ", ", "):
            if (m := f"{c.document_id}{sep}{sec[0]}") in narrative:
                return m
        named = any(f"{c.document_id} {n}" in narrative for n in _SECTION_NO.findall(narrative))
        return None if named else c.document_id  # the document, but no section of it: count it

    marked = [(c, mention(c)) for c in found]
    marked.sort(key=lambda cm: cm[1] is None)  # stable: retrieval order within each group
    return tuple(
        c.model_copy(update={"ref": i, "used": m is not None, "mention": m})
        for i, (c, m) in enumerate(marked, 1)
    )


_JUDGE_OPTIONS = 3
_JUDGE = """Several SQL queries were written for one collections question and gave different results.
Pick the option that answers the question exactly as asked: the right table and rows (the filters the question
states, and no others), the right period, grouped the way the question asks, and the measure it asks for.
Think it through in "why" (one or two sentences), then give "pick": the option's number, or 0 if none fits."""

_CONVENTIONS = """Conventions (from the data dictionary):
- An open case has collections_cases.outcome IS NULL. A randomised case has assignment_method = 'random'.
- Delinquency buckets are 'current', '1-30', '31-60', '61-90', '91-120', '121-150', '151-180', '180+'.
  When the question asks "by bucket", group by the stored bucket column (current_bucket, dpd_bucket) as it
  is. Work a bucket out from dpd / current_dpd only when the question gives a days-past-due range.
- Disputes (any kind, late-fee ones included) raised in a period are counted in contact_history: one row
  per contact with dispute_raised_flag, by contact_ts_local. collections_cases.dispute_type keeps only a
  case's latest dispute, so never count disputes raised from collections_cases.
- A resolved promise has ptp_status in ('kept', 'partially_kept', 'broken'); open and cancelled are not
  resolved.
- An outbound call is direction = 'outbound' AND channel = 'call'; a right-party contact has rpc_flag.
- Charge-offs: rows of card_accounts and loan_accounts with chargeoff_flag = TRUE, dated by chargeoff_date,
  amount in chargeoff_amount. "By product": cards are one product, 'card'; loans use product_type.
- "The N months to <date>" is the N months ending on that date: after the date N months earlier, up to and
  including <date>. The 12 months to 28 September 2026 is chargeoff_date > DATE '2025-09-28' AND
  chargeoff_date <= DATE '2026-09-28' (the start day is not included).
- Write every date bound as a literal DATE 'YYYY-MM-DD' worked out in advance; never add or subtract an
  INTERVAL to a date in the query.
- Give a share or rate as a percentage with two decimals,
  round(100.0 * avg(CASE WHEN ... THEN 1 ELSE 0 END), 2) AS <name>_pct, plus count(*) AS n.
- contact_history, promises_to_pay and collections_cases join on case_id; promises and contacts join agents on
  agent_id. province_code, queue and test_cell live on collections_cases.
- Dates and hours of contacts use the local time contact_ts_local (never contact_ts_utc); contact_hour_local
  is the hour 0-23.
- A reviewed (QA) call is a contact_history row with qa_selected_flag and a qa_score; its site is
  contact_history.agent_site (the agent's site at the time of the call).
- Disputes and complaints raised in a date range are events: count contact_history rows with
  dispute_raised_flag (or complaint_raised_flag), dated by contact_ts_local, with no other filter (the type
  exists only on collections_cases). collections_cases.dispute_date is just the latest dispute on a case."""


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


def _kept_summarise_call() -> Callable[..., Any]:
    """Track C's summariser, imported on first use so the Ask still loads without it."""
    fn: Callable[..., Any] = importlib.import_module("kept.text.calls").summarise_call
    return fn


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


_WORD = re.compile(r"[a-z]+")
_STOP = frozenset(
    {
        "customer",
        "customers",
        "more",
        "much",
        "many",
        "should",
        "we",
        "so",
        "first",
        "because",
        "they",
        "every",
        "a",
        "an",
        "and",
        "are",
        "by",
        "can",
        "did",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "last",
        "list",
        "me",
        "of",
        "on",
        "or",
        "our",
        "per",
        "show",
        "the",
        "their",
        "them",
        "this",
        "to",
        "was",
        "were",
        "what",
        "which",
        "who",
        "why",
        "with",
    }
)


def nearest_question(question: str, metrics: dict[str, MetricDefinition]) -> str | None:
    """The certified metric's example question that shares the most words with `question` (its name, synonyms
    and example count), for "Try: ..." on a refusal. None when nothing overlaps (weather, sports)."""
    words = set(_WORD.findall(question.lower())) - _STOP
    best, score = None, 0
    for d in metrics.values():
        if not d.certified_flag or not d.example_question:
            continue
        text = " ".join((d.metric_name, *d.synonyms, d.example_question)).lower().replace("-", " ")
        overlap = len(words & set(_WORD.findall(text)))
        if overlap > score:
            best, score = d.example_question, overlap
    return best


def policy_as_of(question: str, as_of: date | None) -> date:
    """The day whose documents answer a policy question: the day before a date the question asks about with
    "before" ("before the March 2026 change" -> 28 Feb 2026: the superseded version), else as_of or today."""
    today = as_of or datetime.now(UTC).date()
    q = question.lower()
    for phrase, start, _ in resolve_dates(question, today):
        if re.search(rf"\bbefore\b[^.?!]{{0,40}}{re.escape(phrase.lower())}", q):
            return start - timedelta(days=1)
    return today


def _metric_hint(d: MetricDefinition, q: CertifiedQuery) -> str:
    """What the router needs to know about a metric: its names, defaults, allowed filters and group-bys."""
    return (
        f"{d.metric_name} ({', '.join(d.synonyms)}). Default filters already applied: {d.default_filters}. "
        f"Filters: {sorted(q.allowed_filters) or 'none'}. Group by: {sorted(q.allowed_group_by) or 'none'}. "
        f"Dates apply to {q.date_column or 'nothing (no date range)'}."
        + (
            " product_family is 'card' or 'loan': a question about card accounts or card products filters "
            "product_family = 'card', one about loans 'loan'."
            if "product_family" in q.allowed_filters
            else ""
        )
        + (" is_open = true when the question is about open cases." if "is_open" in q.allowed_filters else "")
        + (
            " A question about calls filters channel = 'call'; outbound or inbound filters direction."
            if "direction" in q.allowed_filters
            else ""
        )
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
        summarise_call: Callable[..., Any] | None = None,
    ) -> None:
        self._summarise_call = summarise_call
        self._conn, self._contract, self._llm, self._redactor = conn, contract, llm, redactor
        self._classifier, self._metrics, self._queries = classifier, metrics, certified_queries
        self._policy_index, self._audit = policy_index, audit_log
        self._known = frozenset(m for m, d in metrics.items() if d.certified_flag and m in certified_queries)
        self._hints = {m: _metric_hint(metrics[m], certified_queries[m]) for m in self._known}
        self._schema_cache: str | None = None
        self._allowed = frozenset(t.lower() for t in contract.ask_allowed_tables)
        self._graph = build_graph(self)  # kept.ask.graph: the pipeline below as LangGraph nodes and edges
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
            response = run_graph(self._graph, request, question, seen)
        except Exception as e:  # never raises: a bug here is a refusal, not a 500
            seen["error"] = type(e).__name__
            response = _refuse(RefusalReason.LOW_CONFIDENCE, "Something went wrong, so I didn't answer.")
        self._log(request, question, response, seen)
        return response

    # ------------------------------------------------------------------ pipeline
    def _lookup(
        self, request: AskRequest, question: RedactedText, intent: Intent, as_of: date | None
    ) -> AskResponse | tuple[GuardResult, tuple[tuple[str, ...], Any], str]:
        """Draft SQL three ways and keep the majority result. When the drafts disagree, two more drafts get a
        vote; when there's still no majority, the model reads the competing results and picks the one that
        answers the question (a refusal costs the user as much as a wrong answer, and the pick is traced)."""
        policy = self._sql_policy()
        schema = self._schema_doc(policy, as_of)
        spec = schema + date_hints(question.text, as_of) + examples(question.text)
        guards, ran = self._drafts(request, question, intent, spec, schema, policy, as_of, SQL_CANDIDATES)
        if guards and not any(g.allowed for g in guards):
            return _refuse(RefusalReason.SQL_GUARD, guards[0].reason or "The query is not allowed.")
        votes = SQL_CANDIDATES
        winner = majority_result([r[1] if r else None for r in ran] + [None] * (votes - len(ran)))
        how = f"{votes} SQL drafts, majority result kept"
        if winner is None:
            more_g, more_r = self._drafts(request, question, intent, spec, schema, policy, as_of, SQL_EXTRA)
            guards, ran, votes = guards + more_g, ran + more_r, votes + SQL_EXTRA
            winner = majority_result([r[1] if r else None for r in ran] + [None] * (votes - len(ran)))
            how = f"{votes} SQL drafts (the first {SQL_CANDIDATES} disagreed), majority result kept"
            if winner is None:
                winner = self._judge(request, question, guards, ran)
                how = f"{votes} SQL drafts disagreed; the model compared the results and picked one"
        if needs_clarification(router_confidence=intent.confidence, candidates_agree=winner is not None):
            return self._unsure(request, "I got different answers when I tried that a few ways.", intent)
        key = normalize_result(winner or ())
        g, r = next((g, r) for g, r in zip(guards, ran, strict=False) if r and normalize_result(r[1]) == key)
        return g, r, how

    def _drafts(
        self,
        request: AskRequest,
        question: RedactedText,
        intent: Intent,
        spec: str,
        schema: str,
        policy: SqlPolicy,
        as_of: date | None,
        n: int,
    ) -> tuple[list[GuardResult], list[tuple[tuple[str, ...], Any] | None]]:
        """n drafts, guarded and run; a draft that fails to run gets one repair round with its error."""
        drafts = generate_candidates(
            intent, spec, self._llm, n=n, actor_id=request.user_id, question=question
        )
        drafts = [qualify_tables(pin_today(d, as_of), policy.allowed_tables) for d in drafts]
        dates = resolve_dates(question.text, as_of)
        guards = [guard_sql(d, policy) for d in drafts]
        results = [self._try(g) if g.allowed else (None, None) for g in guards]
        ran = [r for r, _ in results]
        for i, (r, error) in enumerate(results):
            if r is not None and (issues := lint_sql(question.text, guards[i].sql, dates)):
                error = "it ran, but it doesn't follow the conventions: " + " ".join(issues)
            if error and (
                fixed := self._repair(request, question, intent, schema, drafts[i], error, policy, as_of)
            ):
                guards[i], ran[i] = fixed  # a lint-failing draft that can't be fixed keeps its own result
        return guards, ran

    def _judge(
        self,
        request: AskRequest,
        question: RedactedText,
        guards: list[GuardResult],
        ran: list[tuple[tuple[str, ...], Any] | None],
    ) -> Any:
        """The drafts disagree: show the model each distinct result (its SQL and first rows, most-voted first)
        and let it pick the one that answers the question. None when it picks none or the call fails."""
        groups: dict[Any, list[int]] = {}
        for i, r in enumerate(ran):
            if r is not None:
                groups.setdefault(normalize_result(r[1]), []).append(i)
        options = sorted(groups.values(), key=len, reverse=True)
        if any(ran[ix[0]][1] for ix in options):  # an empty result never beats one with rows
            options = [ix for ix in options if ran[ix[0]][1]]  # type: ignore[index]
        options = options[:_JUDGE_OPTIONS]
        if len(options) < 2:
            return ran[options[0][0]][1] if options else None  # type: ignore[index]
        shown = []
        for k, ix in enumerate(options, 1):
            cols, rows = ran[ix[0]]  # type: ignore[misc]
            table = "\n".join([",".join(cols), *(",".join(map(str, row)) for row in rows[:8])])
            shown.append(
                f"Option {k} ({len(ix)} of the drafts, {len(rows)} rows):\nSQL:\n{guards[ix[0]].sql}\n"
                f"Result:\n{table}"
            )
        user = self._redactor.redact(f"Question: {question.text}\n\n" + "\n\n".join(shown))
        try:
            reply = self._llm.complete(
                system=_JUDGE,
                user=user,
                purpose=Purpose.ASK_SQL,
                actor_id=request.user_id,
                json_schema={
                    "type": "object",
                    "properties": {"why": {"type": "string"}, "pick": {"type": "integer"}},
                    "required": ["why", "pick"],
                },
            )
            pick = int((reply.parsed or {}).get("pick", 0))
        except Exception:
            return None
        return ran[options[pick - 1][0]][1] if 1 <= pick <= len(options) else None  # type: ignore[index]

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

    def _call_summary(self, request: AskRequest, case_id: str) -> AskResponse:
        """The newest recorded call on a case, summarised by kept.text.calls from its redacted transcript.
        No recorded call is an answer, not a refusal."""
        try:
            summarise = self._summarise_call or _kept_summarise_call()
            result = summarise(case_id, llm=self._llm, conn=self._conn, actor_id=request.user_id)
        except Exception:
            return _refuse(RefusalReason.DATA_UNAVAILABLE, "I couldn't read that call just now.")
        citations: tuple[Citation, ...] = ()
        if result is None:
            summary = f"There is no recorded call on case {case_id}."
        else:
            try:
                day = date.fromisoformat(str(result.call_start)[:10])
            except ValueError:
                day = datetime.now(UTC).date()
            summary = result.summary
            citations = (
                Citation(
                    document_id="text.redacted_notes",
                    section=f"transcript {result.transcript_id}",
                    effective_from=day,
                    snippet=result.summary,
                    kind="transcript",
                    ref=1,
                    source_id=result.transcript_id,
                ),
            )
        return AskAnswer(
            question=request.question,
            intent=Intent(kind=IntentKind.LOOKUP, confidence=1.0),
            sql=None,
            tables_used=("text.redacted_notes",),
            data_freshness=None,
            narrative=summary,
            citations=citations,
        )

    def _policy(
        self, request: AskRequest, question: RedactedText, intent: Intent, as_of: date | None
    ) -> AskResponse:
        if self._policy_index is None:
            return _refuse(RefusalReason.DATA_UNAVAILABLE, "Policy search isn't available right now.")
        found = self._policy_index.search(request.question, as_of=policy_as_of(question.text, as_of))
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
            citations=tag_citations(found, narrative),
        )

    def policy_source(self, citation: Citation) -> SourceText | None:
        """The document version a policy citation came from, with the cited passage located."""
        if self._policy_index is None:
            return None
        return self._policy_index.source(
            citation.document_id, citation.section, citation.effective_from, citation.snippet
        )

    def transcript_source(self, source_id: str) -> tuple[str, SourceText] | None:
        """(case_id, redacted transcript) for a call citation. The caller checks the user may see the case."""
        with self._conn.cursor() as c:
            row = c.execute(
                "select case_id, text, written_at_local from text.redacted_notes "
                "where source_id = ? and source_type = 'transcript'",
                [source_id],
            ).fetchone()
        if row is None:
            return None
        day = date.fromisoformat(str(row[2])[:10]) if row[2] else None
        return str(row[0]), SourceText(
            title=f"Call transcript {source_id} (redacted)", text=str(row[1]), effective_from=day
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
        text = f"Question: {question.text}\nData: {data}"
        for _ in range(2):  # a second try when the first used a number the data does not hold
            try:
                reply = self._llm.complete(
                    system=system,
                    user=self._redactor.redact(text),
                    purpose=Purpose.ASK_NARRATE,
                    actor_id=request.user_id,
                )
            except Exception:
                break
            said = reply.text.strip()
            if not said or (len(rows) and "nothing to show" in said.lower()):  # it misread a non-empty result
                break
            if not (extra := ungrounded_numbers(said, rows, allow=allow)):
                return said
            text += (
                f"\n\nYour answer used numbers that are not in the data: {', '.join(map(str, extra))}. "
                "Answer again with only numbers that appear in the data. To compare, say higher or lower "
                "in words; do not state a difference."
            )
        return _FALLBACK  # numbers only from rows: an ungrounded or missing narration is dropped

    def _sql_policy(self) -> SqlPolicy:
        return build_sql_policy(self._conn, self._contract)

    def _schema_doc(self, policy: SqlPolicy, as_of: date | None) -> str:
        if self._schema_cache is None:  # the warehouse is rebuilt nightly, so describe it once per service
            self._schema_cache = _describe(self._conn, policy)
        today = f" The data's as-of date is {as_of}." if as_of else ""
        return f"{self._schema_cache}\n\n{_CONVENTIONS}{today}"

    def _try(
        self, guarded: GuardResult, params: list[object] | None = None
    ) -> tuple[tuple[tuple[str, ...], Any] | None, str | None]:
        """(result, None) on success; (None, error) if the query would not run; (None, None) on a timeout."""
        try:
            return execute_guarded(self._conn, guarded, params=params, timeout_s=ASK_SQL_TIMEOUT_S), None
        except TimeoutError:
            return None, None
        except Exception as e:  # a missing column or table, a type error: the model can fix this
            return None, str(e)[:300]

    def _run(
        self, guarded: GuardResult, params: list[object] | None = None
    ) -> tuple[tuple[str, ...], Any] | None:
        return self._try(guarded, params)[0]

    def _repair(
        self,
        request: AskRequest,
        question: RedactedText,
        intent: Intent,
        schema: str,
        sql: str,
        error: str,
        policy: SqlPolicy,
        as_of: date | None = None,
    ) -> tuple[GuardResult, tuple[tuple[str, ...], Any]] | None:
        """One repair round for a draft that failed to run: show the model its query and the error."""
        user = self._redactor.redact(
            f"{question.text}\n\nYour previous query:\n{sql}\n\nIt failed with: {error}\n"
            "Write a corrected query. Join tables on case_id when you need columns from another table."
        )
        fixed = draft_sql(self._llm, lookup_system(intent, schema), user, request.user_id)
        guarded = (
            guard_sql(qualify_tables(pin_today(fixed, as_of), policy.allowed_tables), policy)
            if fixed
            else None
        )
        if guarded is None or not guarded.allowed:
            return None
        result = self._run(guarded)
        return (guarded, result) if result else None

    def _as_of(self, fresh: datetime | None) -> date | None:
        """The data's snapshot date, the 'today' of every relative date. Not refreshed_at: that is when gold
        was built (3 Oct), and a snapshot-dated table has no rows on a day after its snapshot."""
        try:
            row = self._conn.execute("SELECT max(as_of_date) FROM gold.c360_customer").fetchone()
        except duckdb.Error:
            row = None
        return row[0] if row and row[0] else (fresh.date() if fresh else None)

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
    the local model (KEPT_ASK_LLM_MODEL, default Gemma 3 12B on Ollama) through the gateway, Presidio
    redaction, and the policy index when one is built (KEPT_LANCEDB_DIR, default data/policy/lancedb)."""
    from pathlib import Path

    from kept.ask.certified import CERTIFIED_QUERIES
    from kept.ask.metrics import load_metric_definitions
    from kept.ask.scope import make_classifier
    from kept.ask.templates import TEMPLATES
    from kept.common.llm import LiteLLMGateway
    from kept.contracts.data_contract import load_data_contract

    llm = llm or LiteLLMGateway(
        model=os.environ.get("KEPT_ASK_LLM_MODEL", "ollama/gemma3:12b-it-qat"),  # local models only
        audit_log=audit_log,
        max_retries=6,
        backoff_s=4.0,
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
        metrics=metrics | {k: d for k, (d, _) in TEMPLATES.items()},
        certified_queries=CERTIFIED_QUERIES | {k: q for k, (_, q) in TEMPLATES.items()},
        policy_index=PolicyIndex(index_dir, local_embedder()) if index_dir.exists() else None,
        audit_log=audit_log,
    )
