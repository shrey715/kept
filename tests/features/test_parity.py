"""Nightly offline/online parity (Track A owns this test; Track D owns the store)."""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb
import numpy as np
import pandas as pd
import pytest

from kept.contracts.feature_registry import FEATURES
from kept.contracts.features import FeatureVector
from kept.features.parity import parity_report, run_parity
from tests.fakes import StaticFeatureProvider

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


# ----------------------------------------------------------------- offline table vs the online store
def _warehouse(vectors: dict[str, FeatureVector]) -> duckdb.DuckDBPyConnection:
    """features.case_features with one row per vector, every registry feature a column."""
    rows = [
        {"case_id": v.case_id, "golden_customer_id": v.golden_customer_id, "as_of": v.as_of.replace(tzinfo=None),
         "feature_set_version": v.feature_set_version, **{f.name: getattr(v, f.name) for f in FEATURES}}
        for v in vectors.values()
    ]  # fmt: skip
    frame = pd.DataFrame(rows)
    conn = duckdb.connect()
    conn.execute("create schema features")
    conn.register("frame", frame)
    conn.execute("create table features.case_features as select * from frame")
    return conn


def _vectors(n: int = 5) -> dict[str, FeatureVector]:
    return {
        f"C-{i}": FeatureVector(
            case_id=f"C-{i}",
            golden_customer_id=f"G-00000{i}",
            as_of=datetime(2026, 9, 28, 6, tzinfo=UTC),
            feature_set_version="fs-0.1",
            max_dpd=10 * i,
            answer_rate=i / 10,
            contacts_last_7d=i,
        )
        for i in range(n)
    }


def test_run_parity_passes_when_the_online_store_serves_what_was_built() -> None:
    vectors = _vectors()
    r = run_parity(_warehouse(vectors), StaticFeatureProvider(vectors), sample=None)
    assert r.passed and r.n_mismatched == 0 and not r.missing_entities
    assert r.n_cells == 5 * (
        len(FEATURES) + 2
    )  # the features plus golden_customer_id and feature_set_version


def test_run_parity_names_the_feature_that_serves_a_different_value() -> None:
    vectors = _vectors()
    online = dict(vectors)
    online["C-3"] = vectors["C-3"].model_copy(update={"max_dpd": 999})
    r = run_parity(
        _warehouse(vectors),
        StaticFeatureProvider(online),
        sample=None,
    )
    assert r.n_mismatched == 1 and r.worst_features == (("max_dpd", 1),)
    assert not r.passed  # 1 cell in 5 * 38 is over 0.1%


def test_run_parity_fails_for_a_case_missing_from_the_online_store() -> None:
    vectors = _vectors()
    online = {k: v for k, v in vectors.items() if k != "C-2"}
    r = run_parity(_warehouse(vectors), StaticFeatureProvider(online), sample=None)
    assert not r.passed and r.missing_entities == ("C-2",)


def test_run_parity_sample_draws_the_same_cases_every_time() -> None:
    vectors = _vectors(20)
    a = run_parity(_warehouse(vectors), StaticFeatureProvider(vectors), sample=7, seed=3)
    b = run_parity(_warehouse(vectors), StaticFeatureProvider(vectors), sample=7, seed=3)
    assert a.n_cells == b.n_cells == 7 * (len(FEATURES) + 2) and a.passed
