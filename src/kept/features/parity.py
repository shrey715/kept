"""Nightly offline/online parity test (owner: Track A). Blocks deploys if the two
differ by more than 0.1% (share of mismatched cells)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from kept.config import PARITY_MAX_MISMATCH_RATE


@dataclass(frozen=True, slots=True)
class ParityReport:
    n_cells: int
    n_mismatched: int
    mismatch_rate: float
    worst_features: tuple[tuple[str, int], ...]  # (feature, mismatches) descending
    missing_entities: tuple[str, ...]  # in one frame but not the other
    passed: bool


def parity_report(
    offline: pd.DataFrame,
    online: pd.DataFrame,
    *,
    key: str = "case_id",
    rel_tol: float = 1e-9,
    abs_tol: float = 1e-9,
    max_mismatch_rate: float = PARITY_MAX_MISMATCH_RATE,
) -> ParityReport:
    """Compare the same entities' features cell by cell. Floats compare with
    math.isclose(rel_tol, abs_tol); None == None and NaN == NaN count as equal; None vs
    a value is a mismatch. Missing entities fail parity regardless of rate.
    Different column sets -> ValueError."""
    raise NotImplementedError("Track A")
