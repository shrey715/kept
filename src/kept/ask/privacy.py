"""Analysts see aggregates of 10 or more (design §9)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from kept.config import ANALYST_MIN_GROUP_SIZE


def suppress_small_groups(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    count_column: str,
    k: int = ANALYST_MIN_GROUP_SIZE,
) -> tuple[tuple[Any, ...], ...]:
    """Drop rows whose count_column < k. Missing count_column -> ValueError
    (an analyst query without a count can't be checked, so the caller refuses)."""
    i = list(columns).index(count_column)  # ValueError when missing
    return tuple(tuple(r) for r in rows if (r[i] or 0) >= k)  # a NULL count is treated as small
