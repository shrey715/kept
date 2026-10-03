"""Step 2: the LLM turns the question into an Intent (metric, filters, dates)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from kept.common.llm import Purpose
from kept.contracts.ask import Intent, IntentKind
from kept.contracts.features import RedactedText
from kept.contracts.interfaces import LLMGateway


def _lenient_schema() -> dict[str, Any]:
    """Intent's JSON schema, but a filter may be null: smaller models write {"queue": null} for "no filter".
    route() drops those before the Intent is validated."""
    schema = Intent.model_json_schema()
    schema["properties"]["filters"]["additionalProperties"]["anyOf"].append({"type": "null"})
    return schema


INTENT_JSON_SCHEMA: Mapping[str, Any] = _lenient_schema()


_SYSTEM = """You turn a collections analyst's question into a JSON intent.
kind: "metric" when the question asks for one of the certified metrics below, "policy" when it asks what a
policy, procedure or script says, otherwise "lookup" (a custom query over the data).
For a metric set metric_id to exactly one of the metrics below. filters maps column names to values;
group_by lists only the columns the question breaks the result down by ("by card product" is
product_code, nothing else); date_from and date_to are ISO dates (inclusive). Leave out what the question
does not say. For a metric use only the filter and group_by columns listed for it, and never repeat its
default filters (they are already applied). A question about randomised cases needs the filter
assignment_method = "random" where the metric allows it.
{metrics}
confidence is 0 to 1: how sure you are of the whole intent.{as_of}"""


def route(
    question: RedactedText,
    llm: LLMGateway,
    *,
    known_metric_ids: frozenset[str],
    actor_id: str,
    as_of: date | None = None,
    metric_hints: Mapping[str, str] | None = None,
) -> Intent:
    """Ask the LLM for an Intent. Reject (ValueError) a METRIC intent whose metric_id is
    not in known_metric_ids, or any reply that fails Intent validation.
    `as_of` is the data's snapshot date, so "last month" means the same thing every time.
    `metric_hints` maps metric_id to a one-line description (what it is, allowed filters and group-bys)."""
    system = _SYSTEM.format(
        metrics="\n".join(
            f"- {m}: {(metric_hints or {}).get(m, '')}".rstrip(": ") for m in sorted(known_metric_ids)
        ),
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
    parsed = {
        **reply.parsed,
        "filters": {k: v for k, v in (reply.parsed.get("filters") or {}).items() if v is not None},
    }
    intent = Intent.model_validate(parsed)  # pydantic's ValidationError is a ValueError
    if intent.kind is IntentKind.METRIC and intent.metric_id not in known_metric_ids:
        raise ValueError(f"unknown metric {intent.metric_id!r}")
    return intent
