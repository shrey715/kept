"""Data steward review queue (0.80-0.95 pairs and unsafe clusters).

Item IDs come from the pair's two keys, so the same pair always has the same ID: the queue can be
rebuilt from the review_pairs parquet on every start. Verdicts (not "unsure") are kept in
steward.verdicts when the queue is given a warehouse path, so a restart does not reopen them.
The route logs the STEWARD_DECISION audit event (kept.app.api).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

import pandas as pd

from kept.common.db import connect
from kept.contracts.enums import SourceSystem
from kept.contracts.identity import CandidatePair, MatchDecision, SourceKey
from kept.data.identity.clustering import decide


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


def _label(key: SourceKey) -> str:
    return f"{key.system.value}:{key.key}"


class StewardQueue:
    def __init__(self, *, path: Path | str | None = None) -> None:
        self._items: dict[str, ReviewItem] = {}
        self._resolved: dict[str, StewardVerdict] = {}
        self._path = path
        if path is not None:
            conn = connect(path)
            try:
                conn.execute(
                    "create table if not exists steward.verdicts "
                    "(item_id varchar primary key, verdict varchar, steward_id varchar, "
                    "resolved_at timestamptz)"
                )
                self._resolved = {
                    item_id: StewardVerdict(v)
                    for item_id, v in conn.execute("select item_id, verdict from steward.verdicts").fetchall()
                }
            finally:
                conn.close()

    def enqueue(self, decision: MatchDecision, *, reasons: tuple[str, ...], at: datetime) -> ReviewItem:
        """Idempotent per unordered pair: re-enqueuing returns the existing item."""
        pair = sorted((_label(decision.pair.left), _label(decision.pair.right)))
        item_id = "SI-" + hashlib.sha1("|".join(pair).encode()).hexdigest()[:12]
        if item_id not in self._items:
            self._items[item_id] = ReviewItem(item_id, decision, reasons, at)
        return self._items[item_id]

    def pending(self) -> list[ReviewItem]:
        """Oldest first."""
        open_items = [i for i in self._items.values() if i.item_id not in self._resolved]
        return sorted(open_items, key=lambda i: (i.created_at, i.item_id))

    def resolve(self, item_id: str, verdict: StewardVerdict, *, steward_id: str, at: datetime) -> None:
        """Record the verdict (audit: STEWARD_DECISION). UNSURE keeps it pending.
        Unknown item -> KeyError; resolving twice -> ValueError."""
        if item_id not in self._items:
            raise KeyError(item_id)
        if item_id in self._resolved:
            raise ValueError(f"{item_id} is already resolved: {self._resolved[item_id].value}")
        if verdict is StewardVerdict.UNSURE:
            return
        self._resolved[item_id] = verdict
        if self._path is not None:
            conn = connect(self._path)
            try:
                conn.execute(
                    "insert or replace into steward.verdicts values (?, ?, ?, ?)",
                    [item_id, verdict.value, steward_id, at],
                )
            finally:
                conn.close()


def enqueue_review_pairs(queue: StewardQueue, pairs: pd.DataFrame, *, at: datetime) -> int:
    """Queue the rows of a review_pairs parquet (kept match): Splink pairs in the review band and the
    pairs inside held clusters. Columns: left/right_system/_key, rule, score, reason. Returns the count."""
    for row in pairs.to_dict("records"):
        # a held cluster's score is its weakest link; files from before that was recorded have none
        score = 0.0 if pd.isna(row["score"]) else float(row["score"])
        pair = CandidatePair(
            left=SourceKey(system=SourceSystem(row["left_system"]), key=row["left_key"]),
            right=SourceKey(system=SourceSystem(row["right_system"]), key=row["right_key"]),
            score=score,
            rule=row["rule"],
        )
        queue.enqueue(decide(pair), reasons=(str(row["reason"]),), at=at)
    return len(pairs)


def precision(predicted_link: list[bool], is_true_match: list[bool]) -> float:
    """TP / (TP + FP) over predicted links. Lengths differ -> ValueError.
    No predicted links -> ValueError."""
    if len(predicted_link) != len(is_true_match):
        raise ValueError("predicted_link and is_true_match must have the same length")
    verdicts = [truth for predicted, truth in zip(predicted_link, is_true_match, strict=True) if predicted]
    if not verdicts:
        raise ValueError("no predicted links: precision is undefined")
    return sum(verdicts) / len(verdicts)
