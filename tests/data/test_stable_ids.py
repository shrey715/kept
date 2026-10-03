"""The vectorised golden-ID assignment (kept match --previous) gives the same IDs as GoldenIdRegistry."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from kept.contracts import SourceKey, SourceSystem
from kept.data.identity.clustering import Cluster, GoldenIdRegistry
from kept.data.identity.pipeline import _assign_stable

AT = datetime(2026, 10, 4, tzinfo=UTC)


def _partition(rng: random.Random, items: list[str], max_groups: int) -> list[list[str]]:
    groups: list[list[str]] = [[] for _ in range(rng.randint(1, max_groups))]
    for item in items:
        rng.choice(groups).append(item)
    return [g for g in groups if g]


def _registry(partitions: list[list[list[str]]]) -> dict[str, int]:
    """Assign the partitions one after another with the registry; the golden number of every key at the end."""
    registry = GoldenIdRegistry()
    for clusters in partitions:
        registry.assign(
            [Cluster(keys=frozenset(SourceKey(system=SourceSystem.CRM, key=k) for k in c)) for c in clusters],
            actor_id="t",
            at=AT,
        )
    return {
        k: int(g.removeprefix("G-"))
        for c in partitions[-1]
        for k in c
        if (g := registry.golden_id(SourceKey(system=SourceSystem.CRM, key=k)))
    }


def _vectorised(first: list[list[str]], second: list[list[str]]) -> tuple[dict[str, int], int, int]:
    """IDs for `second` that keep those the registry gave `first` (as a crosswalk) ."""
    registry = GoldenIdRegistry()
    ids = registry.assign(
        [Cluster(keys=frozenset(SourceKey(system=SourceSystem.CRM, key=k) for k in c)) for c in first],
        actor_id="t",
        at=AT,
    )
    previous = pd.DataFrame(
        [("crm", k.key, g) for k, g in ids.items()],
        columns=["source_system", "source_key", "golden_customer_id"],
    )
    keys = pd.MultiIndex.from_tuples(sorted(("crm", k) for c in second for k in c))
    group_of = {k: i for i, c in enumerate(sorted(second, key=min)) for k in c}
    # the group of a cluster is the position of its smallest key, as in run_matching
    smallest = {i: min(c) for i, c in enumerate(sorted(second, key=min))}
    position = {k: i for i, (_, k) in enumerate(keys)}
    group = np.array([position[smallest[group_of[k]]] for _, k in keys])
    numbers, merges, splits = _assign_stable(keys, group, previous)
    return {k: int(n) for (_, k), n in zip(keys, numbers, strict=True)}, merges, splits


def test_matches_the_registry_on_random_merges_splits_and_new_keys() -> None:
    for seed in range(200):
        rng = random.Random(seed)
        universe = [f"K{i:02d}" for i in range(rng.randint(4, 30))]
        first_keys = rng.sample(universe, rng.randint(2, len(universe)))
        first = _partition(rng, first_keys, 6)
        second_keys = rng.sample(universe, rng.randint(2, len(universe)))  # some keys leave, some arrive
        second = _partition(rng, second_keys, 6)
        got, _, _ = _vectorised(first, second)
        assert got == _registry([first, second]), seed


def test_an_unchanged_run_changes_nothing_and_counts_no_merge_or_split() -> None:
    clusters = [["K1", "K2"], ["K3"], ["K4", "K5", "K6"]]
    got, merges, splits = _vectorised(clusters, clusters)
    assert got == _registry([clusters, clusters]) and merges == 0 and splits == 0


def test_a_merge_keeps_the_older_id_and_a_split_gives_the_rest_a_new_one() -> None:
    merged, merges, _ = _vectorised([["K1"], ["K2"], ["K3"]], [["K1", "K2"], ["K3"]])
    assert merged["K1"] == merged["K2"] == 1 and merged["K3"] == 3 and merges == 1  # the oldest, 1, survives
    split, _, splits = _vectorised([["K1", "K2", "K3"]], [["K1", "K2"], ["K3"]])
    assert split["K1"] == split["K2"] == 1 and split["K3"] == 2 and splits == 1  # 2 is new, never 1 again
