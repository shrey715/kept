"""The Ask as a LangGraph state machine.

The same steps as before, now explicit nodes and edges: safety rules, the call-summary shortcut, scope,
routing, then one grounded path (policy search, a certified metric, or a voted SQL lookup) and the grounded
narration.
Each node adds a line to the trace, so every answer says which path produced it. No step changed behaviour:
the graph calls the same functions the hand-written pipeline did (kept.ask.service), in the same order.
"""

from __future__ import annotations

import operator
import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from kept.ask.grounding import needs_clarification
from kept.ask.metrics import compile_metric
from kept.ask.router import route
from kept.ask.scope import check_scope, refusal_for, rule_check
from kept.ask.sql_guard import guard_sql
from kept.ask.templates import date_hints, resolve_dates
from kept.contracts import AskRequest, AskResponse, IntentKind, RedactedText, RefusalReason
from kept.contracts.ask import GuardResult, Intent

if TYPE_CHECKING:
    from kept.ask.service import CollectionsAsk


# words that name one contact channel; the router is told to filter on them, the check makes sure it did
_CHANNEL_WORDS = {
    "call": re.compile(r"\b(calls?|phone)\b", re.I),
    "sms": re.compile(r"\b(sms|texts?|text messages?)\b", re.I),
    "email": re.compile(r"\be-?mails?\b", re.I),
}


def check_channel(
    question: str, intent: Intent, allowed: frozenset[str] | set[str]
) -> tuple[Intent, str | None]:
    """A metric question that names exactly one channel gets that channel filter if the router left it out
    (the LLM sometimes keeps "outbound" and drops "calls"). Returns the intent and a trace note, or None."""
    if "channel" not in allowed or "channel" in intent.filters:
        return intent, None
    named = [c for c, w in _CHANNEL_WORDS.items() if w.search(question)]
    if len(named) != 1:
        return intent, None
    fixed = intent.model_copy(update={"filters": {**intent.filters, "channel": named[0]}})
    return fixed, f"Intent check: added channel = {named[0]} (the question names it)"


# what a question may ask about each metric beyond its name and synonyms (a domain glossary, not examples)
GLOSSARY = {
    "delinquency_rate": "past due delinquent arrears overdue",
    "collected_amount": "paid payment payments collected recovered",
    "roll_rate": "rolled roll worse bucket deteriorated",
    "average_dpd": "past due days",
    "promise_kept_rate": "promise promises kept",
    "broken_promise_rate": "promise promises broken",
    "cure_rate": "cured current",
    "hardship_rate": "hardship",
    "contact_attempts_per_case": "attempts contacts touches",
    "cost_per_contact": "cost",
    "cost_per_rpc": "cost right party",
    "rpc_rate": "right party reached",
    "ptp_rate": "promise promises",
    "write_off_rate": "written off write offs charged",
    "payroll_delay_share": "payroll pay late",
}
_STOP = {"rate", "share", "cases", "case", "what", "many", "much", "with", "from", "that", "this", "which"}
_STOP |= {"there", "were", "have", "does", "than", "more", "over", "last", "month", "today", "each"}
# function words share nothing about a metric ("the", "and" once matched charge-offs to a disputes question)
_STOP |= {"the", "and", "how", "for", "are", "was", "all", "any", "per", "did", "has", "its", "our", "you"}
_STOP |= {
    "day",
    "week",
    "year",
    "between",
    "before",
    "after",
    "during",
    "compared",
    "number",
    "total",
    "about",
}
_POLICY = re.compile(
    r"\b(can|may|must) (we|i|you|an agent|agents|collectors?|the bank)\b|\b(allowed|prohibited)\b"
    r"|\b(permise?s?|autoris[ée]e?s?|interdite?s?|peut-on|pouvons-nous|doit-on)\b",  # the bank is bilingual
    re.I,
)


def _words(text: str) -> set[str]:
    return {
        w.rstrip("s")
        for w in re.findall(r"[a-z]+", text.lower().replace("-", " "))
        if len(w) >= 3 and w not in _STOP
    }


def relevant(question: str, metric_id: str, name: str, synonyms: Any) -> bool:
    """The routed metric shares a meaningful word with the question (its name, synonyms or glossary). A route
    with nothing in common ("open cases by bucket" -> delinquency rate) goes to a lookup instead."""
    about = " ".join([name, *list(synonyms or ()), metric_id.replace("_", " "), GLOSSARY.get(metric_id, "")])
    return bool(_words(question) & _words(about))


_OPEN = re.compile(r"\b(open|still open|currently open|active|outstanding)\b", re.I)


def check_open(question: str, intent: Intent) -> tuple[Intent, str | None]:
    """An is_open filter needs the question to ask about open cases; "cases opened in 2026" is about when
    cases started, not whether they're open (a slip smaller models make)."""
    if not intent.filters.get("is_open") or _OPEN.search(question):
        return intent, None
    filters = {k: v for k, v in intent.filters.items() if k != "is_open"}
    return intent.model_copy(
        update={"filters": filters}
    ), "Intent check: dropped is_open (the question doesn't ask about open cases)"


def as_lookup(intent: Intent) -> Intent:
    """A rerouted question goes to the lookup as a lookup, without the metric the router wrongly named (it
    would pull every SQL draft toward it). Dates and filters stay as hints."""
    return intent.model_copy(update={"kind": IntentKind.LOOKUP, "metric_id": None})


def ground_filters(intent: Intent, values: Any) -> tuple[Intent, list[str]]:
    """Check each text filter value against the column's real values (`values(col)`: a list, or None when
    unknown). A near miss maps to what's stored ("instalment" -> "instalment_1_of_n"); a value matching
    nothing is dropped, and a filter left empty goes (the question then covers every group, which a
    comparison wants)."""
    filters: dict[str, Any] = dict(intent.filters)
    notes: list[str] = []
    for col, v in intent.filters.items():
        vals: list[Any] = list(v) if isinstance(v, list) else [v]
        if not all(isinstance(x, str) for x in vals):
            continue
        known = values(col)
        if not known:
            continue
        lower = {str(k).lower(): k for k in known}
        out: list[Any] = []
        for x in vals:
            if x.lower() in lower:
                out.append(lower[x.lower()])
                continue
            near = [k for low, k in lower.items() if low.startswith(x.lower()) or x.lower() in low]
            out += near
            notes.append(
                f"Value check: {col} '{x}' -> {', '.join(map(str, near)) or 'no such value, dropped'}"
            )
        out = list(dict.fromkeys(out))
        if not out:
            filters.pop(col)
        else:
            filters[col] = out if isinstance(v, list) or len(out) > 1 else out[0]
    for col in intent.group_by:  # grouped and filtered to one value: the question compares, keep every group
        v = filters.get(col)
        if v is not None and (not isinstance(v, list) or len(v) == 1):
            filters.pop(col)
            notes.append(f"Value check: dropped the one-value filter on {col} (the answer groups by it)")
    if filters == intent.filters:
        return intent, []
    return intent.model_copy(update={"filters": filters}), notes


def _closest(name: str, allowed: frozenset[str] | set[str]) -> str | None:
    """The one allowed column a misnamed one most likely means: shared name parts ("agent_site" -> "site",
    "product" -> "product_type" when that's the only product column). None when nothing or several fit."""
    if name in allowed:
        return name
    parts = set(name.lower().split("_"))
    scored = [(len(parts & set(a.split("_"))), a) for a in allowed]
    best = max((s for s, _ in scored), default=0)
    hits = [a for s, a in scored if s == best and s > 0]
    return hits[0] if len(hits) == 1 else None


def repair_intent(intent: Intent, q: Any) -> tuple[Intent, list[str]]:
    """Make the router's intent fit the certified query: a date column belongs in the date range, not in the
    filters or groups; a misnamed column maps to the one it means; what still doesn't fit is dropped. Smaller
    local models name columns loosely; every change is written to the trace."""
    notes: list[str] = []
    filters: dict[str, Any] = {}
    for col, v in intent.filters.items():
        to = None if col == q.date_column else _closest(col, q.allowed_filters)
        if to is None:
            notes.append(f"Intent repair: dropped filter {col}")
        else:
            if to != col:
                notes.append(f"Intent repair: filter {col} -> {to}")
            filters[to] = v
    groups: list[str] = []
    for col in intent.group_by:
        to = None if col == q.date_column else _closest(col, q.allowed_group_by)
        if to is None:
            notes.append(f"Intent repair: dropped grouping {col}")
        elif to not in groups:
            if to != col:
                notes.append(f"Intent repair: grouping {col} -> {to}")
            groups.append(to)
    if not notes:
        return intent, []
    return intent.model_copy(update={"filters": filters, "group_by": groups}), notes


class AskState(TypedDict, total=False):
    request: AskRequest
    question: RedactedText
    seen: dict[str, Any]
    fresh: datetime | None
    as_of: date | None
    intent: Intent
    guarded: GuardResult
    ran: tuple[tuple[str, ...], Any] | None
    reroute: bool
    response: AskResponse
    trace: Annotated[list[str], operator.add]  # each node appends; LangGraph concatenates


def build_graph(ask: CollectionsAsk) -> Any:
    """Compile the Ask's graph over one CollectionsAsk (its LLM, warehouse, indexes and helpers)."""
    from kept.ask import service as svc  # the pipeline's helpers live there; imported late (no cycle)

    def rules(s: AskState) -> AskState:
        r = s["request"]
        if (rule := rule_check(r, ask._contract)) is not None:  # protected, bulk, write, other people's cases
            return {
                "response": refusal_for(rule, suggestion=svc.nearest_question(r.question, ask._metrics)),
                "trace": [f"Safety rules: refused ({rule.reason})"],
            }
        return {"trace": ["Safety rules: passed"]}

    def call_summary(s: AskState) -> AskState:
        case_id = svc._CALL_SUMMARY.search(s["request"].question)[1].upper()  # type: ignore[index]
        s["seen"]["intent"] = "call_summary"
        return {"response": ask._call_summary(s["request"], case_id), "trace": [f"Call summary: {case_id}"]}

    def scope(s: AskState) -> AskState:
        r = s["request"]
        decision = check_scope(r, ask._contract, ask._classifier)
        if not decision.in_scope:
            return {
                "response": refusal_for(decision, suggestion=svc.nearest_question(r.question, ask._metrics)),
                "trace": [f"Scope: out ({decision.reason}, by {decision.decided_by})"],
            }
        return {"trace": [f"Scope: in (by {decision.decided_by})"]}

    def route_node(s: AskState) -> AskState:
        r, q = s["request"], s["question"]
        fresh = ask._freshness()
        as_of = ask._as_of(fresh)
        intent = None
        for _ in range(2):  # a reply that fails validation, or a busy local server: one more try
            try:
                intent = route(
                    q,
                    ask._llm,
                    known_metric_ids=ask._known,
                    actor_id=r.user_id,
                    as_of=as_of,
                    metric_hints=ask._hints,
                    date_hints=date_hints(q.text, as_of),
                )
                break
            except Exception:
                continue
        if intent is None:
            return {
                "response": ask._unsure(r, "I couldn't work out what you're asking."),
                "trace": ["Route: failed twice"],
            }
        if intent.kind is not IntentKind.POLICY and _POLICY.search(r.question):  # "can we ...?" asks a rule
            intent = intent.model_copy(update={"kind": IntentKind.POLICY, "metric_id": None})
            policy_note = ["Intent check: the question asks what we may do, so policy"]
        else:
            policy_note = []
        s["seen"]["intent"] = intent.kind.value
        spans = resolve_dates(q.text, as_of)
        filled = (
            intent.kind is IntentKind.METRIC
            and intent.date_from is None
            and intent.date_to is None
            and len(spans) == 1
        )
        if filled:  # the question names one period and the router left the range empty: fill it
            intent = intent.model_copy(update={"date_from": spans[0][1], "date_to": spans[0][2]})
        out: AskState = {"fresh": fresh, "as_of": as_of, "intent": intent}
        label = f"Route: {intent.kind.value}" + (f" {intent.metric_id}" if intent.metric_id else "")
        if needs_clarification(router_confidence=intent.confidence, candidates_agree=None):
            return out | {
                "response": ask._unsure(r, "I'm not sure what you mean.", intent),
                "trace": [f"{label} (confidence {intent.confidence:.2f}: too low)"],
            }
        dates = [f"Date check: {spans[0][0]!r} -> {spans[0][1]} to {spans[0][2]}"] if filled else []
        return out | {"trace": [f"{label} (confidence {intent.confidence:.2f})", *policy_note, *dates]}

    def policy(s: AskState) -> AskState:
        resp = ask._policy(s["request"], s["question"], s["intent"], s["as_of"])
        n = len(getattr(resp, "citations", ()) or ())
        return {"response": resp, "trace": [f"Policy search: {n} section(s) cited, narrated from their text"]}

    def metric(s: AskState) -> AskState:
        query = ask._queries.get(s["intent"].metric_id or "")
        if query is None:  # the router named a metric we don't certify: a lookup can still answer
            return {
                "reroute": True,
                "intent": as_lookup(s["intent"]),
                "trace": [f"Certified metric: {s['intent'].metric_id} isn't certified"],
            }
        d = ask._metrics.get(s["intent"].metric_id or "")
        if d is not None and not relevant(s["request"].question, d.metric_id, d.metric_name, d.synonyms):
            return {
                "reroute": True,
                "intent": as_lookup(s["intent"]),
                "trace": [f"Relevance check: the question names nothing of {d.metric_name}; trying a lookup"],
            }
        intent, repaired = repair_intent(s["intent"], query)
        intent, note = check_channel(s["request"].question, intent, query.allowed_filters)
        intent, open_note = check_open(s["request"].question, intent)
        intent, grounded = ground_filters(intent, lambda col: column_values(intent.metric_id or "", col))
        notes = [*repaired, *([note] if note else []), *([open_note] if open_note else []), *grounded]
        try:
            sql, params = compile_metric(intent, ask._metrics, ask._queries)
        except ValueError as e:  # still doesn't fit the certified query: a voted SQL lookup can try
            return {
                "reroute": True,
                "intent": as_lookup(s["intent"]),
                "trace": [*notes, f"Certified metric: can't compile ({e}); trying a lookup"],
            }
        guarded = guard_sql(sql, ask._sql_policy())
        if not guarded.allowed:
            return {
                "response": svc._refuse(
                    RefusalReason.SQL_GUARD, guarded.reason or "The query is not allowed."
                ),
                "trace": [*notes, "SQL guard: blocked"],
            }
        return {
            "intent": intent,
            "guarded": guarded,
            "ran": ask._run(guarded, params),
            "trace": [*notes, f"Certified metric: {intent.metric_id}", "SQL guard: allowed"],
        }

    seen_values: dict[tuple[str, str], list[Any] | None] = {}

    def column_values(metric_id: str, col: str) -> list[Any] | None:
        """The values a certified metric's column takes (the metric grouped by it), cached; None: unknown."""
        key = (metric_id, col)
        if key not in seen_values:
            seen_values[key] = None
            q = ask._queries.get(metric_id)
            if q is not None and col in q.allowed_group_by:
                try:
                    probe = Intent(
                        kind=IntentKind.METRIC, metric_id=metric_id, group_by=[col], confidence=1.0
                    )
                    sql, params = compile_metric(probe, ask._metrics, ask._queries)
                    guarded = guard_sql(sql, ask._sql_policy())
                    ran = ask._run(guarded, params) if guarded.allowed else None
                    if ran is not None and len(ran[1]) <= 200:
                        seen_values[key] = [r[0] for r in ran[1] if r[0] is not None]
                except Exception:  # unknown values: the filter is left as the router wrote it
                    pass
        return seen_values[key]

    def lookup(s: AskState) -> AskState:
        outcome = ask._lookup(s["request"], s["question"], s["intent"], s["as_of"])
        if not isinstance(outcome, tuple):
            return {
                "response": outcome,
                "trace": ["Lookup: the SQL drafts disagreed or were blocked"],
            }
        guarded, ran, how = outcome
        return {"guarded": guarded, "ran": ran, "trace": [f"Lookup: {how}; every draft guarded"]}

    def finish(s: AskState) -> AskState:
        ran = s.get("ran")
        if ran is None:
            return {
                "response": svc._refuse(RefusalReason.DATA_UNAVAILABLE, "The query failed or took too long."),
                "trace": ["Warehouse: the query failed"],
            }
        s["seen"] |= {"sql": s["guarded"].sql, "rows": len(ran[1])}
        resp = ask._finish(s["request"], s["question"], s["intent"], s["guarded"], *ran, s["fresh"])
        return {
            "response": resp,
            "trace": [f"Warehouse: {len(ran[1])} row(s)", "Narration: every number checked against the rows"],
        }

    def after(key: str) -> Any:
        """Stop when a node has answered (a refusal or clarification); else go on to `key`."""
        return lambda s: END if "response" in s else key

    def after_rules(s: AskState) -> str:
        if "response" in s:
            return END
        return "call_summary" if svc._CALL_SUMMARY.search(s["request"].question) else "scope"

    def by_intent(s: AskState) -> str:
        if "response" in s:
            return END
        return {IntentKind.POLICY: "policy", IntentKind.METRIC: "metric"}.get(s["intent"].kind, "lookup")

    g = StateGraph(AskState)
    for name, fn in [
        ("rules", rules),
        ("call_summary", call_summary),
        ("scope", scope),
        ("route", route_node),
        ("policy", policy),
        ("metric", metric),
        ("lookup", lookup),
        ("finish", finish),
    ]:
        g.add_node(name, fn)  # type: ignore[call-overload]
    g.add_edge(START, "rules")
    g.add_conditional_edges("rules", after_rules, ["call_summary", "scope", END])
    g.add_edge("call_summary", END)
    g.add_conditional_edges("scope", after("route"), ["route", END])
    g.add_conditional_edges("route", by_intent, ["policy", "metric", "lookup", END])
    g.add_edge("policy", END)
    g.add_conditional_edges(
        "metric",
        lambda s: END if "response" in s else "lookup" if s.get("reroute") else "finish",
        ["finish", "lookup", END],
    )
    g.add_conditional_edges("lookup", after("finish"), ["finish", END])
    g.add_edge("finish", END)
    return g.compile()


def run(graph: Any, request: AskRequest, question: RedactedText, seen: dict[str, Any]) -> AskResponse:
    """One question through the graph; the answer carries the path it took."""
    out = graph.invoke({"request": request, "question": question, "seen": seen, "trace": []})
    seen["trace"] = out["trace"]
    resp: AskResponse = out["response"]
    return resp.model_copy(update={"trace": tuple(out["trace"])})
