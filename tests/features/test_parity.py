"""Nightly offline/online parity (Track A owns this test; Track D owns the store)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from kept.features.parity import parity_report

pytestmark = pytest.mark.track_a


def _frame(n: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "case_id": [f"C-{i}" for i in range(n)],
            "max_dpd": rng.integers(0, 120, n),
            "answer_rate": rng.random(n),
            "pay_frequency": ["monthly"] * n,
            "promised_amount": [None] * n,
        }
    )


def test_identical_frames_pass() -> None:
    off = _frame()
    r = parity_report(off, off.copy())
    assert r.passed and r.n_mismatched == 0 and r.mismatch_rate == 0.0
    assert r.n_cells == 100 * 4  # key column is not a cell


def test_row_order_does_not_matter() -> None:
    off = _frame()
    assert parity_report(off, off.sample(frac=1, random_state=1)).passed


def test_float_noise_within_tolerance_passes() -> None:
    off = _frame()
    on = off.copy()
    on["answer_rate"] = on["answer_rate"] * (1 + 1e-12)
    assert parity_report(off, on).passed


def test_none_and_nan_are_equal_but_none_vs_value_is_not() -> None:
    off = _frame(10)
    on = off.copy()
    on["promised_amount"] = np.nan
    assert parity_report(off, on).passed
    on.loc[0, "promised_amount"] = 100.0
    r = parity_report(off, on, max_mismatch_rate=0.0)
    assert r.n_mismatched == 1 and not r.passed


def test_threshold_is_point_one_percent() -> None:
    off = _frame(1000)  # 4000 cells; 0.1% = 4 cells
    on = off.copy()
    on.loc[:3, "max_dpd"] = -1  # 4 mismatches -> exactly 0.1% -> pass
    assert parity_report(off, on).passed
    on.loc[:4, "max_dpd"] = -1  # 5 mismatches -> fail
    r = parity_report(off, on)
    assert not r.passed and r.worst_features[0] == ("max_dpd", 5)


def test_missing_entities_fail_regardless_of_rate() -> None:
    off = _frame(1000)
    r = parity_report(off, off.iloc[1:])
    assert not r.passed and r.missing_entities == ("C-0",)


def test_different_columns_raise() -> None:
    off = _frame()
    with pytest.raises(ValueError):
        parity_report(off, off.drop(columns=["answer_rate"]))
