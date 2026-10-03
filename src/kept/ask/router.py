"""Step 2: the LLM turns the question into an Intent (metric, filters, dates)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kept.contracts.ask import Intent
from kept.contracts.features import RedactedText
from kept.contracts.interfaces import LLMGateway

INTENT_JSON_SCHEMA: Mapping[str, Any] = Intent.model_json_schema()


def route(
    question: RedactedText, llm: LLMGateway, *, known_metric_ids: frozenset[str], actor_id: str
) -> Intent:
    """Ask the LLM for an Intent. Reject (ValueError) a METRIC intent whose metric_id is
    not in known_metric_ids, or any reply that fails Intent validation."""
    raise NotImplementedError("Track B")
