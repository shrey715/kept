"""Protocols at every track boundary. Code against these, not against each other's modules.

    Track A ──C360Reader──────────────▶ B, C, D
    Track C ──Redactor, TextExtractor─▶ D (features), A/B (LLM inputs)
    Track D ──FeatureProvider─────────▶ D (model), A (parity test)
    Track D ──NBAEngine, ReleaseGate──▶ app
    Track B ──AskService──────────────▶ app
    shared  ──LLMGateway, AuditLog────▶ everyone

tests/fakes.py has an in-memory fake of each so tracks can test without each other.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import pandas as pd
from pydantic import BaseModel

from kept.contracts.ask import AskRequest, AskResponse
from kept.contracts.audit import AuditEvent, AuditKind
from kept.contracts.enums import Action
from kept.contracts.features import FeatureVector, RedactedText, TextExtraction
from kept.contracts.identity import GoldenCustomer, SourceKey
from kept.contracts.nba import CaseContext, NBACard, ReleaseDecision, ReleaseResult


# ------------------------------------------------------------------ Track A
@runtime_checkable
class C360Reader(Protocol):
    def get_customer(self, golden_customer_id: str) -> GoldenCustomer:
        """Raise KeyError if unknown."""
        ...

    def resolve(self, key: SourceKey) -> str | None:
        """Golden ID for a source key, or None if the key is unknown."""
        ...

    def customer_for_case(self, case_id: str) -> GoldenCustomer:
        """Every open case resolves to a golden ID (quality rule 2). Raise KeyError if not."""
        ...


# ------------------------------------------------------------------ Track C
@runtime_checkable
class Redactor(Protocol):
    def redact(self, text: str) -> RedactedText: ...


@runtime_checkable
class TextExtractor(Protocol):
    def extract(
        self, text: RedactedText, *, source_id: str, case_id: str, written_at: datetime | None = None
    ) -> TextExtraction: ...


# ------------------------------------------------------------------ Track D
@runtime_checkable
class FeatureProvider(Protocol):
    def get_online(self, case_id: str) -> FeatureVector:
        """Latest values from the online store (live scoring)."""
        ...

    def get_historical(self, entity_rows: pd.DataFrame) -> pd.DataFrame:
        """Point-in-time join. entity_rows has columns case_id, as_of (tz-aware).

        Returns one row per input row with every FeatureVector.feature_names() column,
        and never any column in OUTCOME_DENY_LIST.
        """
        ...


@runtime_checkable
class UpliftScorer(Protocol):
    model_version: str

    def predict_proba(self, features: pd.DataFrame) -> pd.DataFrame:
        """P(paid_14d | action) per row; one column per Action value, in [0, 1]."""
        ...


@runtime_checkable
class CaseContextBuilder(Protocol):
    def build(self, case_id: str, now: datetime) -> CaseContext: ...


@runtime_checkable
class NBAEngine(Protocol):
    def recommend(self, case_id: str, now: datetime) -> NBACard: ...


@runtime_checkable
class ReleaseGate(Protocol):
    def release(self, decision: ReleaseDecision, now: datetime) -> ReleaseResult: ...


# ------------------------------------------------------------------ Track B
@runtime_checkable
class AskService(Protocol):
    def ask(self, request: AskRequest) -> AskResponse: ...


# ------------------------------------------------------------------ shared
class LLMResponse(BaseModel):
    text: str
    parsed: dict[str, Any] | None = None  # set when a json_schema was requested and validated
    model: str
    call_id: str  # audit event id


@runtime_checkable
class LLMGateway(Protocol):
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
        """One logged LLM call. `system` is a static template from our code; `user` must be redacted."""
        ...


@runtime_checkable
class ExtractionStore(Protocol):
    """text.extractions (Track C): one row per source_id (note_id or call_id)."""

    def get(self, source_id: str) -> TextExtraction | None: ...

    def for_case(self, case_id: str) -> Sequence[TextExtraction]:
        """Every extraction for the case, newest first (the case card's confirm panel)."""
        ...

    def put(self, extraction: TextExtraction) -> None:
        """Insert, or replace the row with the same source_id (re-extraction, agent confirm)."""
        ...


@runtime_checkable
class AuditLog(Protocol):
    def append(self, event: AuditEvent) -> None:
        """Append only. Raise ValueError on a duplicate event_id."""
        ...

    def read(
        self,
        *,
        kind: AuditKind | None = None,
        subject_id: str | None = None,
        since: datetime | None = None,
    ) -> Sequence[AuditEvent]:
        """Events in append order."""
        ...


__all__ = [
    "Action",
    "AskService",
    "AuditLog",
    "C360Reader",
    "CaseContextBuilder",
    "ExtractionStore",
    "FeatureProvider",
    "LLMGateway",
    "LLMResponse",
    "NBAEngine",
    "Redactor",
    "ReleaseGate",
    "TextExtractor",
    "UpliftScorer",
]
