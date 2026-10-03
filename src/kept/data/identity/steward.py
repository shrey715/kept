"""Data steward review queue (0.80-0.95 pairs and unsafe clusters)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from kept.contracts.identity import MatchDecision


class StewardVerdict(StrEnum):
    SAME_PERSON = "same_person"
    DIFFERENT_PEOPLE = "different_people"
    UNSURE = "unsure"


@dataclass(frozen=True, slots=True)
class ReviewItem:
    item_id: str
    decision: MatchDecision
    reasons: tuple[str, ...]
    created_at: datetime


class StewardQueue:
    def __init__(self) -> None:
        raise NotImplementedError("Track A")

    def enqueue(self, decision: MatchDecision, *, reasons: tuple[str, ...], at: datetime) -> ReviewItem:
        """Idempotent per unordered pair: re-enqueuing returns the existing item."""
        raise NotImplementedError("Track A")

    def pending(self) -> list[ReviewItem]:
        """Oldest first."""
        raise NotImplementedError("Track A")

    def resolve(self, item_id: str, verdict: StewardVerdict, *, steward_id: str, at: datetime) -> None:
        """Record the verdict (audit: STEWARD_DECISION). UNSURE keeps it pending.
        Unknown item -> KeyError; resolving twice -> ValueError."""
        raise NotImplementedError("Track A")


def precision(predicted_link: list[bool], is_true_match: list[bool]) -> float:
    """TP / (TP + FP) over predicted links. Lengths differ -> ValueError.
    No predicted links -> ValueError."""
    raise NotImplementedError("Track A")
