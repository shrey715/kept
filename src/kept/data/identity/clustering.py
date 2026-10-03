"""Thresholds, cluster safety rules, and permanent golden IDs with a reversible log."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from kept.config import (
    AUTO_LINK_THRESHOLD,
    GOLDEN_ID_PATTERN,
    MAX_KEYS_PER_CLUSTER,
    STEWARD_REVIEW_THRESHOLD,
)
from kept.contracts.enums import MatchRoute
from kept.contracts.identity import CandidatePair, ClusterEvent, MatchDecision, SourceKey


def _sort_key(key: SourceKey) -> tuple[str, str]:
    return (key.system.value, key.key)


def route_score(score: float) -> MatchRoute:
    """>= 0.95 AUTO_LINK; [0.80, 0.95) STEWARD_REVIEW; < 0.80 PROVISIONAL.
    Score outside [0, 1] or NaN -> ValueError."""
    if math.isnan(score) or not 0.0 <= score <= 1.0:
        raise ValueError(f"match score must be in [0, 1], got {score}")
    if score >= AUTO_LINK_THRESHOLD:
        return MatchRoute.AUTO_LINK
    return MatchRoute.STEWARD_REVIEW if score >= STEWARD_REVIEW_THRESHOLD else MatchRoute.PROVISIONAL


def decide(pair: CandidatePair) -> MatchDecision:
    """Route one pair. Exact rules (rule starts with 'exact:') always AUTO_LINK."""
    if pair.rule.startswith("exact:"):
        return MatchDecision(pair=pair, route=MatchRoute.AUTO_LINK)
    return MatchDecision(pair=pair, route=route_score(pair.score))


@dataclass(frozen=True, slots=True)
class Cluster:
    keys: frozenset[SourceKey]
    national_id_hashes: frozenset[str] = field(default_factory=frozenset)  # non-null values only
    min_score: float | None = None


def cluster_review_reasons(cluster: Cluster) -> tuple[str, ...]:
    """Reasons the cluster must go to review regardless of scores:
    'two_national_ids' when > 1 distinct national ID, 'too_many_keys' when > 12 keys.
    Empty tuple when safe."""
    reasons = []
    if len(cluster.national_id_hashes) > 1:
        reasons.append("two_national_ids")
    if len(cluster.keys) > MAX_KEYS_PER_CLUSTER:
        reasons.append("too_many_keys")
    return tuple(reasons)


def connected_components(keys: Iterable[SourceKey], links: Iterable[CandidatePair]) -> list[Cluster]:
    """Union-find over AUTO_LINK pairs. Every key appears in exactly one cluster;
    unlinked keys become singleton clusters. Output sorted by min key."""
    parent: dict[SourceKey, SourceKey] = {k: k for k in keys}

    def find(k: SourceKey) -> SourceKey:
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]  # path halving
            k = parent[k]
        return k

    auto = [p for p in links if decide(p).route is MatchRoute.AUTO_LINK]
    for p in auto:
        parent[find(p.left)] = find(p.right)

    members: dict[SourceKey, set[SourceKey]] = {}
    for k in list(parent):
        members.setdefault(find(k), set()).add(k)
    weakest: dict[SourceKey, float] = {}
    for p in auto:
        root = find(p.left)
        weakest[root] = min(weakest.get(root, 1.0), p.score)
    clusters = [Cluster(keys=frozenset(m), min_score=weakest.get(root)) for root, m in members.items()]
    return sorted(clusters, key=lambda c: min(map(_sort_key, c.keys)))


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
        self._prefix, self._width = prefix, width
        self._ids: dict[SourceKey, str] = {}
        self._issued = 0  # IDs handed out so far; only ever grows, so none is reused
        self._events: list[ClusterEvent] = []
        self._before: dict[str, dict[SourceKey, str | None]] = {}  # event_id -> mapping to restore on undo

    def _new_id(self) -> str:
        self._issued += 1
        gid = f"{self._prefix}{self._issued:0{self._width}d}"
        assert re.fullmatch(GOLDEN_ID_PATTERN, gid), gid
        return gid

    def _log(
        self,
        kind: str,
        before: tuple[str, ...],
        after: tuple[str, ...],
        keys: Iterable[SourceKey],
        *,
        actor_id: str,
        reason: str,
        at: datetime,
        undoes: str | None = None,
    ) -> ClusterEvent:
        event = ClusterEvent(
            event_id=f"CE-{len(self._events) + 1:06d}",
            kind=kind,
            golden_ids_before=before,
            golden_ids_after=after,
            source_keys=tuple(sorted(keys, key=_sort_key)),
            actor_id=actor_id,
            reason=reason,
            at=at,
            undoes_event_id=undoes,
        )
        self._events.append(event)
        return event

    def assign(self, clusters: Iterable[Cluster], *, actor_id: str, at: datetime) -> dict[SourceKey, str]:
        clusters = sorted(clusters, key=lambda c: min(map(_sort_key, c.keys)))
        # Each existing ID has one home: the cluster holding most of its keys (ties: the first by key).
        home: dict[str, int] = {}
        for gid in {self._ids[k] for c in clusters for k in c.keys if k in self._ids}:
            counts = [sum(self._ids.get(k) == gid for k in c.keys) for c in clusters]
            home[gid] = counts.index(max(counts))

        result: dict[SourceKey, str] = {}
        pending: list[tuple[str, tuple[str, ...], tuple[str, ...], list[SourceKey]]] = []
        for i, cluster in enumerate(clusters):
            owners = sorted(gid for gid, h in home.items() if h == i)
            gid = owners[0] if owners else self._new_id()
            result.update(dict.fromkeys(cluster.keys, gid))
            if len(owners) > 1:
                pending.append(("merge", tuple(owners), (gid,), list(cluster.keys)))
        # a split: an ID whose keys now sit in several clusters (only the home cluster keeps it)
        for gid in sorted(home):
            moved = [k for k, g in self._ids.items() if g == gid and result.get(k, gid) != gid]
            if moved:
                after = tuple(sorted({gid, *(result[k] for k in moved)}))
                pending.append(("split", (gid,), after, [k for k, g in self._ids.items() if g == gid]))

        for kind, before, after, keys in pending:
            event = self._log(kind, before, after, keys, actor_id=actor_id, reason=f"cluster {kind}", at=at)
            self._before[event.event_id] = {k: self._ids.get(k) for k in keys}
        self._ids.update(result)
        return result

    def golden_id(self, key: SourceKey) -> str | None:
        return self._ids.get(key)

    def events(self) -> list[ClusterEvent]:
        return list(self._events)

    def undo(self, event_id: str, *, actor_id: str, reason: str, at: datetime) -> ClusterEvent:
        if event_id not in self._before:
            raise KeyError(event_id)
        original = next(e for e in self._events if e.event_id == event_id)
        for key, gid in self._before[event_id].items():
            if gid is None:
                self._ids.pop(key, None)
            else:
                self._ids[key] = gid
        return self._log(
            "undo",
            original.golden_ids_after,
            original.golden_ids_before,
            original.source_keys,
            actor_id=actor_id,
            reason=reason,
            at=at,
            undoes=event_id,
        )
