"""LiteLLM gateway (owner: Track B; used by A, B, C).

Every LLM call in the system goes through here so that:
  * the hosted model can be swapped for a local one by config (KEPT_LLM_MODEL),
  * the user content is a RedactedText (PII redaction before any LLM),
  * every call is written to the audit log (purpose, actor, model, latency, tokens).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kept.contracts.features import RedactedText
from kept.contracts.interfaces import AuditLog, LLMResponse


class Purpose:
    """The `purpose` of every LLM call. Shown in the audit log; fakes route on it."""

    DATA_MAPPING = "data.mapping"  # Track A: source-to-target mapping drafts
    ASK_SCOPE = "ask.scope"  # Track B: scope classifier
    ASK_ROUTE = "ask.route"  # Track B: question -> Intent
    ASK_SQL = "ask.sql_candidate"  # Track B: one call per lookup SQL candidate
    ASK_NARRATE = "ask.narrate"  # Track B: explain the result rows
    TEXT_EXTRACT = "text.extract"  # Track C: note/transcript extraction


class LiteLLMGateway:
    """Implements kept.contracts.interfaces.LLMGateway."""

    def __init__(self, *, model: str, audit_log: AuditLog, timeout_s: float = 30.0) -> None:
        raise NotImplementedError("Track B")

    def complete(
        self,
        *,
        system: str,
        user: RedactedText,
        purpose: str,
        actor_id: str,
        json_schema: Mapping[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Raise TypeError if `user` is not a RedactedText.

        If json_schema is given, validate the reply against it and set `parsed`;
        raise ValueError if the reply does not validate. Log one AuditKind.LLM_CALL
        event per call, including failed calls.
        """
        raise NotImplementedError("Track B")
