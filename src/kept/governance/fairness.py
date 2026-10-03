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
    skipped (reported). All-zero rates -> min_ratio 1.0. Lengths differ -> ValueError."""
    raise NotImplementedError("Track C")
