"""Step 2: the LLM turns the question into an Intent (metric, filters, dates)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from kept.common.llm import Purpose
from kept.contracts.ask import Intent, IntentKind
from kept.contracts.features import RedactedText
from kept.contracts.interfaces import LLMGateway

INTENT_JSON_SCHEMA: Mapping[str, Any] = Intent.model_json_schema()


_SYSTEM = """You turn a collections analyst's question into a JSON intent.
kind: "metric" when the question asks for one of the certified metrics below, "policy" when it asks what a
policy, procedure or script says, otherwise "lookup" (a custom query over the data).
For a metric set metric_id to exactly one of: {metrics}. filters maps column names to values; group_by lists
column names; date_from and date_to are ISO dates (inclusive). Leave out what the question does not say.
confidence is 0 to 1: how sure you are of the whole intent.{as_of}"""


def route(
    question: RedactedText,
    llm: LLMGateway,
    *,
    known_metric_ids: frozenset[str],
    actor_id: str,
    as_of: date | None = None,
) -> Intent:
    """Ask the LLM for an Intent. Reject (ValueError) a METRIC intent whose metric_id is
    not in known_metric_ids, or any reply that fails Intent validation.
    `as_of` is the data's snapshot date, so "last month" means the same thing every time."""
    system = _SYSTEM.format(
        metrics=", ".join(sorted(known_metric_ids)),
        as_of=f" Relative dates (today, this month, last quarter) are relative to {as_of}." if as_of else "",
    )
    reply = llm.complete(
        system=system,
        user=question,
        purpose=Purpose.ASK_ROUTE,
        actor_id=actor_id,
        json_schema=INTENT_JSON_SCHEMA,
    )
    if reply.parsed is None:
        raise ValueError("router reply is not a JSON object")
    intent = Intent.model_validate(reply.parsed)  # pydantic's ValidationError is a ValueError
    if intent.kind is IntentKind.METRIC and intent.metric_id not in known_metric_ids:
        raise ValueError(f"unknown metric {intent.metric_id!r}")
    return intent
