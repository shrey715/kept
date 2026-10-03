"""Fairlearn checks: recommendation rates across groups. Compliance-only inputs
(protected attributes come from gold.c360_restricted, read by compliance)."""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import dataclass

FOUR_FIFTHS = 0.8  # TBC alarm threshold


@dataclass(frozen=True, slots=True)
class FairnessReport:
    rates: dict[Hashable, float]
    min_ratio: float  # min rate / max rate
    flagged: bool  # min_ratio < threshold
    groups_skipped: tuple[Hashable, ...]  # groups below min_group_size


def recommendation_rates(
    recommended: Sequence[bool], groups: Sequence[Hashable], *, min_group_size: int = 10
) -> FairnessReport:
    """Rate of recommended == True per group; groups smaller than min_group_size are
    skipped (reported). All-zero rates -> min_ratio 1.0. Lengths differ -> ValueError.
    ponytail: plain Python (the same numbers as Fairlearn's selection_rate by group), so it runs without
    the torch-sized `text` extra; the real-data report can cross-check with fairlearn.MetricFrame."""
    if len(recommended) != len(groups):
        raise ValueError("recommended and groups must be the same length")
    counts: dict[Hashable, list[int]] = {}  # group -> [members, recommended]
    for rec, group in zip(recommended, groups, strict=True):
        c = counts.setdefault(group, [0, 0])
        c[0] += 1
        c[1] += bool(rec)
    rates = {g: pos / n for g, (n, pos) in counts.items() if n >= min_group_size}
    best = max(rates.values(), default=0.0)
    ratio = min(rates.values()) / best if best else 1.0
    skipped = tuple(g for g, (n, _) in counts.items() if n < min_group_size)
    return FairnessReport(rates, ratio, ratio < FOUR_FIFTHS, skipped)
