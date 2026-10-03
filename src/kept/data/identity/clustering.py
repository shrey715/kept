"""Thresholds, cluster safety rules, and permanent golden IDs with a reversible log."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from kept.contracts.enums import MatchRoute
from kept.contracts.identity import CandidatePair, ClusterEvent, MatchDecision, SourceKey


def route_score(score: float) -> MatchRoute:
    """>= 0.95 AUTO_LINK; [0.80, 0.95) STEWARD_REVIEW; < 0.80 PROVISIONAL.
    Score outside [0, 1] or NaN -> ValueError."""
    raise NotImplementedError("Track A")


def decide(pair: CandidatePair) -> MatchDecision:
    """Route one pair. Exact rules (rule starts with 'exact:') always AUTO_LINK."""
    raise NotImplementedError("Track A")


@dataclass(frozen=True, slots=True)
class Cluster:
    keys: frozenset[SourceKey]
    national_id_hashes: frozenset[str] = field(default_factory=frozenset)  # non-null values only
    min_score: float | None = None


def cluster_review_reasons(cluster: Cluster) -> tuple[str, ...]:
    """Reasons the cluster must go to review regardless of scores:
    'two_national_ids' when > 1 distinct national ID, 'too_many_keys' when > 12 keys.
    Empty tuple when safe."""
    raise NotImplementedError("Track A")


def connected_components(keys: Iterable[SourceKey], links: Iterable[CandidatePair]) -> list[Cluster]:
    """Union-find over AUTO_LINK pairs. Every key appears in exactly one cluster;
    unlinked keys become singleton clusters. Output sorted by min key."""
    raise NotImplementedError("Track A")


class GoldenIdRegistry:
    """Assigns permanent golden IDs and logs every merge and split so any link can be undone.

    Invariants (tested):
      * the same cluster gets the same golden ID on every rerun;
      * IDs are never reused, even after a merge retires one;
      * on merge, the surviving ID is the oldest (lowest) of the merged IDs;
      * on split, the largest part keeps the ID, the others get new IDs;
      * undo(event) restores the exact previous key -> ID mapping.
    """

    def __init__(self, *, prefix: str = "G-", width: int = 6) -> None:
        raise NotImplementedError("Track A")

    def assign(self, clusters: Iterable[Cluster], *, actor_id: str, at: datetime) -> dict[SourceKey, str]:
        raise NotImplementedError("Track A")

    def golden_id(self, key: SourceKey) -> str | None:
        raise NotImplementedError("Track A")

    def events(self) -> list[ClusterEvent]:
        raise NotImplementedError("Track A")

    def undo(self, event_id: str, *, actor_id: str, reason: str, at: datetime) -> ClusterEvent:
        raise NotImplementedError("Track A")
