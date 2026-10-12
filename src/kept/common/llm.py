"""LiteLLM gateway (owner: Track B; used by A, B, C).

Every LLM call in the system goes through here so that:
  * the model is set by config (KEPT_ASK_LLM_MODEL hosted for the Ask, KEPT_TEXT_LLM_MODEL local for text),
  * the user content is a RedactedText (PII redaction before any LLM),
  * every call is written to the audit log (purpose, actor, model, latency, tokens).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections import OrderedDict
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from kept.contracts.audit import AuditEvent, AuditKind
from kept.contracts.features import RedactedText
from kept.contracts.interfaces import AuditLog, LLMResponse


class Purpose:
    """The `purpose` of every LLM call. Shown in the audit log; fakes route on it."""

    DATA_MAPPING = "data.mapping"  # Track A: source-to-target mapping drafts
    ASK_SCOPE = "ask.scope"  # Track B: scope classifier
    ASK_ROUTE = "ask.route"  # Track B: question -> Intent
    ASK_SQL = "ask.sql_candidate"  # Track B: one call per lookup SQL candidate
    ASK_NARRATE = "ask.narrate"  # Track B: explain the result rows
    ASK_CHART = "ask.chart"  # kept.app.charts: pick a chart for the result rows (#100)
    TEXT_EXTRACT = "text.extract"  # Track C: note/transcript extraction
    OPS_PREFLIGHT = "ops.preflight"  # kept preflight: one tiny call to prove a model answers before a demo


class LiteLLMGateway:
    """Implements kept.contracts.interfaces.LLMGateway."""

    def __init__(
        self,
        *,
        model: str,
        audit_log: AuditLog,
        timeout_s: float = 30.0,
        max_retries: int = 5,
        backoff_s: float = 2.0,
        cache_size: int = 512,
    ) -> None:
        self.model, self.audit_log, self.timeout_s = model, audit_log, timeout_s
        self.max_retries, self.backoff_s = max_retries, backoff_s  # 2+4+...+32 s: past a per-minute quota
        # temperature-0 replies by prompt: a repeated question costs no quota (each hit is still audited)
        self._cache: OrderedDict[str, tuple[str, Any, str]] = OrderedDict()
        self._cache_size = cache_size

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
        if not isinstance(user, RedactedText):
            raise TypeError("LLM input must be a RedactedText")
        import litellm  # lazy: core installs (contracts, Purpose) don't carry it
        from litellm.exceptions import (
            APIConnectionError,
            InternalServerError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
        )

        transient = (
            RateLimitError,
            ServiceUnavailableError,
            InternalServerError,
            APIConnectionError,
            Timeout,
        )

        if json_schema is not None:
            system += "\n\nReply with only a JSON object matching this JSON schema:\n" + json.dumps(
                json_schema
            )
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user.text}],
            "temperature": temperature,
            "timeout": self.timeout_s,
            "drop_params": True,  # free models differ in what they accept
        }
        if json_schema is not None:
            kwargs["response_format"] = {"type": "json_object"}

        call_id, t0, attempts = uuid.uuid4().hex, time.perf_counter(), 0
        payload: dict[str, Any] = {
            "purpose": purpose,
            "model": self.model,
            "redactor_version": user.redactor_version,
        }
        key = (
            hashlib.sha256(
                json.dumps([self.model, kwargs["messages"], json_schema], sort_keys=True).encode()
            ).hexdigest()
            if temperature == 0
            else None
        )
        try:
            if key is not None and key in self._cache:
                self._cache.move_to_end(key)
                text, parsed, model = self._cache[key]
                payload |= {"ok": True, "cached": True}
                return LLMResponse(text=text, parsed=parsed, model=model, call_id=call_id)
            while True:
                attempts += 1
                try:
                    reply = litellm.completion(**kwargs)
                    break
                except transient:
                    if attempts > self.max_retries:
                        raise
                    time.sleep(self.backoff_s * 2 ** (attempts - 1))
            text = reply.choices[0].message.content or ""
            parsed = _validated(text, json_schema) if json_schema is not None else None
            if key is not None:  # only a reply that validated is worth repeating
                self._cache[key] = (text, parsed, getattr(reply, "model", self.model))
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            usage = getattr(reply, "usage", None)
            payload |= {
                "ok": True,
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
            }
            return LLMResponse(
                text=text, parsed=parsed, model=getattr(reply, "model", self.model), call_id=call_id
            )
        except Exception as e:
            payload |= {"ok": False, "error": type(e).__name__}
            raise
        finally:
            payload |= {"attempts": attempts, "latency_ms": round((time.perf_counter() - t0) * 1000)}
            self.audit_log.append(
                AuditEvent(
                    event_id=call_id,
                    at=datetime.now(UTC),
                    kind=AuditKind.LLM_CALL,
                    actor_id=actor_id,
                    payload=payload,
                )
            )


def _validated(text: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    import jsonschema  # type: ignore[import-untyped]  # ships with litellm

    body = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text)  # models like to fence their JSON
    try:
        parsed = json.loads(body)
        jsonschema.validate(parsed, dict(schema))
    except (json.JSONDecodeError, jsonschema.ValidationError) as e:
        raise ValueError(f"LLM reply does not match the schema: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError("LLM reply is not a JSON object")
    return parsed
