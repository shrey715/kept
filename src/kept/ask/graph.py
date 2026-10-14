"""The Ask as a LangGraph state machine.

The same steps as before, now explicit nodes and edges: safety rules, the call-summary shortcut, scope,
routing, then one grounded path (policy search, a certified metric, or a voted SQL lookup) and the grounded
narration.
Each node adds a line to the trace, so every answer says which path produced it. No step changed behaviour:
the graph calls the same functions the hand-written pipeline did (kept.ask.service), in the same order.
"""

from __future__ import annotations

import operator
from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from kept.ask.grounding import needs_clarification
from kept.ask.metrics import compile_metric
from kept.ask.router import route
from kept.ask.scope import check_scope, refusal_for, rule_check
from kept.ask.sql_guard import guard_sql
from kept.ask.templates import date_hints
from kept.config import SQL_CANDIDATES
from kept.contracts import AskRequest, AskResponse, IntentKind, RedactedText, RefusalReason
from kept.contracts.ask import GuardResult, Intent

if TYPE_CHECKING:
    from kept.ask.service import CollectionsAsk


class AskState(TypedDict, total=False):
    request: AskRequest
    question: RedactedText
    seen: dict[str, Any]
    fresh: datetime | None
    as_of: date | None
    intent: Intent
    guarded: GuardResult
    ran: tuple[tuple[str, ...], Any] | None
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
        except Exception:
            return {
                "response": ask._unsure(r, "I couldn't work out what you're asking."),
                "trace": ["Route: failed"],
            }
        s["seen"]["intent"] = intent.kind.value
        out: AskState = {"fresh": fresh, "as_of": as_of, "intent": intent}
        label = f"Route: {intent.kind.value}" + (f" {intent.metric_id}" if intent.metric_id else "")
        if needs_clarification(router_confidence=intent.confidence, candidates_agree=None):
            return out | {
                "response": ask._unsure(r, "I'm not sure what you mean.", intent),
                "trace": [f"{label} (confidence {intent.confidence:.2f}: too low)"],
            }
        return out | {"trace": [f"{label} (confidence {intent.confidence:.2f})"]}

    def policy(s: AskState) -> AskState:
        resp = ask._policy(s["request"], s["question"], s["intent"], s["as_of"])
        n = len(getattr(resp, "citations", ()) or ())
        return {"response": resp, "trace": [f"Policy search: {n} section(s) cited, narrated from their text"]}

    def metric(s: AskState) -> AskState:
        try:
            sql, params = compile_metric(s["intent"], ask._metrics, ask._queries)
        except ValueError as e:
            return {
                "response": ask._unsure(s["request"], f"I can't compute that as asked ({e}).", s["intent"]),
                "trace": ["Certified metric: can't compile"],
            }
        guarded = guard_sql(sql, ask._sql_policy())
        if not guarded.allowed:
            return {
                "response": svc._refuse(
                    RefusalReason.SQL_GUARD, guarded.reason or "The query is not allowed."
                ),
                "trace": ["SQL guard: blocked"],
            }
        return {
            "guarded": guarded,
            "ran": ask._run(guarded, params),
            "trace": [f"Certified metric: {s['intent'].metric_id}", "SQL guard: allowed"],
        }

    def lookup(s: AskState) -> AskState:
        outcome = ask._lookup(s["request"], s["question"], s["intent"], s["as_of"])
        if not isinstance(outcome, tuple):
            return {
                "response": outcome,
                "trace": [f"Lookup: {SQL_CANDIDATES} SQL drafts disagreed or were blocked"],
            }
        guarded, ran = outcome
        return {
            "guarded": guarded,
            "ran": ran,
            "trace": [f"Lookup: {SQL_CANDIDATES} SQL drafts, guarded, majority result kept"],
        }

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
    g.add_conditional_edges("metric", after("finish"), ["finish", END])
    g.add_conditional_edges("lookup", after("finish"), ["finish", END])
    g.add_edge("finish", END)
    return g.compile()


def run(graph: Any, request: AskRequest, question: RedactedText, seen: dict[str, Any]) -> AskResponse:
    """One question through the graph; the answer carries the path it took."""
    out = graph.invoke({"request": request, "question": question, "seen": seen, "trace": []})
    seen["trace"] = out["trace"]
    resp: AskResponse = out["response"]
    return resp.model_copy(update={"trace": tuple(out["trace"])})
