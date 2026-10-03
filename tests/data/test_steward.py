"""StewardQueue beyond the basics in test_identity.py: stable IDs, restarts, loading review pairs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from kept.common.db import connect
from kept.contracts import CandidatePair, SourceKey, SourceSystem
from kept.data.identity.clustering import decide
from kept.data.identity.steward import (
    StewardQueue,
    StewardVerdict,
    enqueue_review_pairs,
    load_steward_queue,
    read_verdicts,
)

AT = datetime(2026, 10, 3, 2, 0, tzinfo=UTC)


def _decision(
    left: tuple[str, str] = ("crm", "1"), right: tuple[str, str] = ("loan", "2"), score: float = 0.9
):
    pair = CandidatePair(
        left=SourceKey(system=SourceSystem(left[0]), key=left[1]),
        right=SourceKey(system=SourceSystem(right[0]), key=right[1]),
        score=score,
        rule="splink",
    )
    return decide(pair)


def test_item_id_is_stable_and_ignores_the_order_of_the_pair() -> None:
    a = StewardQueue().enqueue(_decision(), reasons=(), at=AT)
    b = StewardQueue().enqueue(_decision(("loan", "2"), ("crm", "1")), reasons=(), at=AT)
    assert a.item_id == b.item_id and a.item_id.startswith("SI-")


def test_a_resolved_verdict_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "w.duckdb"
    first = StewardQueue(path=path)
    item = first.enqueue(_decision(), reasons=("score_0.80_0.95",), at=AT)
    other = first.enqueue(_decision(("crm", "7"), ("card", "8")), reasons=(), at=AT)
    first.resolve(item.item_id, StewardVerdict.SAME_PERSON, steward_id="s1", at=AT)
    first.resolve(other.item_id, StewardVerdict.UNSURE, steward_id="s1", at=AT)  # unsure is not stored

    second = StewardQueue(path=path)  # the queue is rebuilt from the review pairs on every start
    second.enqueue(_decision(), reasons=("score_0.80_0.95",), at=AT)
    second.enqueue(_decision(("crm", "7"), ("card", "8")), reasons=(), at=AT)
    assert [i.item_id for i in second.pending()] == [other.item_id]
    check = connect(path, read_only=True)
    assert check.execute("select verdict, steward_id from steward.verdicts").fetchall() == [
        ("same_person", "s1")
    ]


def test_enqueue_review_pairs_takes_the_review_band_and_held_clusters() -> None:
    pairs = pd.DataFrame(
        [
            ("crm", "1", "loan", "2", "splink", 0.88, "score_0.80_0.95"),
            ("crm", "3", "crm", "4", "held_cluster", 0.97, "two_national_ids"),
            (
                "crm",
                "5",
                "crm",
                "6",
                "held_cluster",
                float("nan"),
                "too_many_keys",
            ),  # an older file: no score
        ],
        columns=["left_system", "left_key", "right_system", "right_key", "rule", "score", "reason"],
    )
    queue = StewardQueue()
    assert enqueue_review_pairs(queue, pairs, at=AT) == 3
    assert enqueue_review_pairs(queue, pairs, at=AT) == 3  # loading again adds nothing
    items = queue.pending()
    assert len(items) == 3
    assert {i.reasons for i in items} == {("score_0.80_0.95",), ("two_national_ids",), ("too_many_keys",)}
    assert all(0.0 <= i.decision.pair.score <= 1.0 for i in items)


def test_read_verdicts_is_empty_before_anyone_resolves_anything() -> None:
    import duckdb

    assert read_verdicts(duckdb.connect()).empty


def test_load_steward_queue_uses_the_review_pairs_of_the_loaded_crosswalk(tmp_path: Path) -> None:
    duckdb_dir = tmp_path / "xw"
    duckdb_dir.mkdir()
    pairs = pd.DataFrame(
        [
            ("crm", "1", "loan", "2", "splink", 0.88, "score_0.80_0.95"),
            ("crm", "3", "crm", "4", "held_cluster", 0.97, "two_national_ids"),
        ],
        columns=["left_system", "left_key", "right_system", "right_key", "rule", "score", "reason"],
    )
    for run in ("old", "new"):
        (duckdb_dir / f"identity_crosswalk_{run}-full.parquet").write_bytes(b"x")
        (pairs if run == "new" else pairs.iloc[:1]).to_parquet(
            duckdb_dir / f"review_pairs_{run}-full.parquet"
        )
    import os

    os.utime(duckdb_dir / "identity_crosswalk_new-full.parquet", (9e9, 9e9))  # newest crosswalk = "new"
    queue = load_steward_queue(warehouse=tmp_path / "w.duckdb", directory=duckdb_dir)
    assert len(queue.pending()) == 2  # the "new" run's two pairs, not the old run's one
    first = queue.pending()[0]
    queue.resolve(first.item_id, StewardVerdict.DIFFERENT_PEOPLE, steward_id="s1", at=AT)
    again = load_steward_queue(warehouse=tmp_path / "w.duckdb", directory=duckdb_dir)  # a restart
    assert [i.item_id for i in again.pending()] != [i.item_id for i in queue.pending()] or len(
        again.pending()
    ) == 1
    assert first.item_id not in [i.item_id for i in again.pending()]
