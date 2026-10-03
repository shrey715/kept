"""Append-only audit log entries (design §9: every query, recommendation, override, LLM call)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kept.contracts.enums import Role


class AuditKind(StrEnum):
    ASK_QUERY = "ask_query"
    RECOMMENDATION = "recommendation"
    RELEASE = "release"
    OVERRIDE = "override"
    LLM_CALL = "llm_call"
    MATCH_MERGE = "match_merge"
    MATCH_SPLIT = "match_split"
    STEWARD_DECISION = "steward_decision"
    HARDSHIP_CHANGE = "hardship_change"
    KILL_SWITCH = "kill_switch"
    PROPOSAL_CANCELLED = "proposal_cancelled"


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    at: datetime
    kind: AuditKind
    actor_id: str  # user ID or "system:<component>"
    actor_role: Role | None = None
    subject_id: str | None = None  # case_id, proposal_id, golden_customer_id ...
    payload: dict[str, Any] = Field(default_factory=dict)  # must not hold unredacted PII

    @field_validator("at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("at must be timezone-aware")
        return v
