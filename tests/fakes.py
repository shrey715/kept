"""In-memory test doubles for every cross-track interface.

These are deliberately dumb. They let each track test against the contract in
kept.contracts.interfaces without waiting for the other tracks. If you change a
Protocol, update its fake here (tests/contracts/test_fakes_conform.py checks it).
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from kept.contracts import (
    AuditEvent,
    AuditKind,
    CaseContext,
    FeatureVector,
    GoldenCustomer,
    RedactedText,
    SourceKey,
)
from kept.contracts.interfaces import LLMResponse


class ScriptedLLM:
    """LLMGateway fake: returns queued replies in order and records every call."""

    def __init__(self, replies: Sequence[str | Mapping[str, Any] | Exception] = ()) -> None:
        self._replies: deque[str | Mapping[str, Any] | Exception] = deque(replies)
        self.calls: list[dict[str, Any]] = []

    def queue(self, *replies: str | Mapping[str, Any] | Exception) -> ScriptedLLM:
        self._replies.extend(replies)
        return self

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
        if not isinstance(user, RedactedText):
            raise TypeError("LLM user content must be RedactedText")
        self.calls.append({"system": system, "user": user, "purpose": purpose, "actor_id": actor_id})
        if not self._replies:
            raise AssertionError(f"ScriptedLLM ran out of replies (purpose={purpose!r})")
        reply = self._replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        text = reply if isinstance(reply, str) else json.dumps(reply, default=str)
        parsed = dict(reply) if isinstance(reply, Mapping) else None
        return LLMResponse(text=text, parsed=parsed, model="scripted", call_id=f"llm-{len(self.calls)}")


class PurposeLLM:
    """LLMGateway fake that answers by `purpose`. Each purpose has a list of replies used
    in order; the last reply repeats once the list runs out."""

    def __init__(self, replies: Mapping[str, Sequence[str | Mapping[str, Any] | Exception]]) -> None:
        self._replies = {k: list(v) for k, v in replies.items()}
        self._used: dict[str, int] = {}
        self.calls: list[dict[str, Any]] = []

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
        if not isinstance(user, RedactedText):
            raise TypeError("LLM user content must be RedactedText")
        self.calls.append({"system": system, "user": user, "purpose": purpose, "actor_id": actor_id})
        options = self._replies.get(purpose)
        if not options:
            raise AssertionError(f"PurposeLLM has no reply for purpose {purpose!r}")
        i = self._used.get(purpose, 0)
        self._used[purpose] = i + 1
        reply = options[min(i, len(options) - 1)]
        if isinstance(reply, Exception):
            raise reply
        text = reply if isinstance(reply, str) else json.dumps(reply, default=str)
        parsed = dict(reply) if isinstance(reply, Mapping) else None
        return LLMResponse(text=text, parsed=parsed, model="purpose-fake", call_id=f"llm-{len(self.calls)}")

    def purposes(self) -> list[str]:
        return [c["purpose"] for c in self.calls]


class PassThroughRedactor:
    """Redactor fake: wraps text unchanged. Use only where redaction is not under test."""

    version = "fake"

    def redact(self, text: str) -> RedactedText:
        return RedactedText(text=text, redactor_version=self.version)


class InMemoryAuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        if any(e.event_id == event.event_id for e in self._events):
            raise ValueError(f"duplicate event_id {event.event_id}")
        self._events.append(event)

    def read(
        self,
        *,
        kind: AuditKind | None = None,
        subject_id: str | None = None,
        since: datetime | None = None,
    ) -> Sequence[AuditEvent]:
        return [
            e
            for e in self._events
            if (kind is None or e.kind == kind)
            and (subject_id is None or e.subject_id == subject_id)
            and (since is None or e.at >= since)
        ]


@dataclass
class DictC360Reader:
    customers: dict[str, GoldenCustomer] = field(default_factory=dict)
    keys: dict[SourceKey, str] = field(default_factory=dict)

    def get_customer(self, golden_customer_id: str) -> GoldenCustomer:
        return self.customers[golden_customer_id]

    def resolve(self, key: SourceKey) -> str | None:
        return self.keys.get(key)

    def customer_for_case(self, case_id: str) -> GoldenCustomer:
        for c in self.customers.values():
            if c.open_case_id == case_id:
                return c
        raise KeyError(case_id)


@dataclass
class StaticFeatureProvider:
    vectors: dict[str, FeatureVector] = field(default_factory=dict)
    error: Exception | None = None

    def get_online(self, case_id: str) -> FeatureVector:
        if self.error is not None:
            raise self.error
        return self.vectors[case_id]

    def get_historical(self, entity_rows: pd.DataFrame) -> pd.DataFrame:
        rows = [self.vectors[c].model_dump() for c in entity_rows["case_id"]]
        return pd.DataFrame(rows)


@dataclass
class FixedContextBuilder:
    contexts: dict[str, CaseContext] = field(default_factory=dict)
    error: Exception | None = None

    def build(self, case_id: str, now: datetime) -> CaseContext:
        if self.error is not None:
            raise self.error
        return self.contexts[case_id].model_copy(update={"now": now})


class ConstantScorer:
    """UpliftScorer fake: the same probabilities for every row."""

    def __init__(self, probs: Mapping[str, float], model_version: str = "fake-0") -> None:
        self.probs = dict(probs)
        self.model_version = model_version

    def predict_proba(self, features: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame([self.probs] * len(features), index=features.index)
