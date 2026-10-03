"""Known data traps (design §3)."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from kept.contracts import DpdBucket
from kept.data.traps import (
    bureau_percentile,
    card_dpd,
    coalesce_renamed,
    current_scd2_rows,
    dpd_bucket,
    has_transaction_coverage,
    latest_snapshot,
)


# ----------------------------------------------------------------- snapshots
def test_latest_snapshot_keeps_one_row_per_key() -> None:
    df = pd.DataFrame(
        {
            "account_id": ["A", "A", "A", "B", "B"],
            "snapshot_at": pd.to_datetime(
                ["2026-08-31", "2026-09-30", "2026-07-31", "2026-09-30", "2026-08-31"]
            ),
            "dpd": [10, 40, 5, 0, 12],
        }
    )
    out = latest_snapshot(df, key="account_id", ts="snapshot_at").set_index("account_id")
    assert len(out) == 2
    assert out.loc["A", "dpd"] == 40
    assert out.loc["B", "dpd"] == 0


def test_latest_snapshot_tie_goes_to_later_row_and_null_ts_loses() -> None:
    df = pd.DataFrame(
        {
            "account_id": ["A", "A", "B", "B"],
            "snapshot_at": pd.to_datetime(["2026-09-30", "2026-09-30", None, "2026-01-01"]),
            "dpd": [1, 2, 99, 3],
        }
    )
    out = latest_snapshot(df, key="account_id", ts="snapshot_at").set_index("account_id")
    assert out.loc["A", "dpd"] == 2
    assert out.loc["B", "dpd"] == 3


def test_latest_snapshot_composite_key_and_no_mutation() -> None:
    df = pd.DataFrame(
        {
            "system": ["card", "card", "loan"],
            "account_id": ["1", "1", "1"],
            "snapshot_at": pd.to_datetime(["2026-01-01", "2026-02-01", "2026-01-01"]),
        }
    )
    before = df.copy()
    out = latest_snapshot(df, key=["system", "account_id"], ts="snapshot_at")
    assert len(out) == 2
    pd.testing.assert_frame_equal(df, before)


# ----------------------------------------------------------------- card dpd
def test_card_dpd_uses_dpd_not_cycles() -> None:
    df = pd.DataFrame({"dpd": [45, 0, None], "cycles_delinquent": [1, 3, 2]})
    out = card_dpd(df)
    assert out.iloc[0] == 45
    assert out.iloc[1] == 0
    assert pd.isna(out.iloc[2])  # missing stays missing; never cycles * 30


# ----------------------------------------------------------------- buckets
@pytest.mark.parametrize(
    "dpd,bucket",
    [
        (0, DpdBucket.CURRENT),
        (1, DpdBucket.B1_30),
        (30, DpdBucket.B1_30),
        (31, DpdBucket.B31_60),
        (60, DpdBucket.B31_60),
        (61, DpdBucket.B61_90),
        (90, DpdBucket.B61_90),
        (91, DpdBucket.B91_120),
        (120, DpdBucket.B91_120),
        (121, DpdBucket.B121_PLUS),
        (10_000, DpdBucket.B121_PLUS),
    ],
)
def test_dpd_bucket_edges(dpd: int, bucket: DpdBucket) -> None:
    assert dpd_bucket(dpd) is bucket


def test_dpd_bucket_none_and_negative() -> None:
    assert dpd_bucket(None) is None
    with pytest.raises(ValueError):
        dpd_bucket(-1)


@given(st.integers(min_value=0, max_value=5000), st.integers(min_value=0, max_value=5000))
def test_dpd_bucket_is_monotone(a: int, b: int) -> None:
    order = list(DpdBucket)
    lo, hi = sorted((a, b))
    assert order.index(dpd_bucket(lo)) <= order.index(dpd_bucket(hi))  # type: ignore[arg-type]


# ----------------------------------------------------------------- bureau
def test_bureau_percentiles_within_scale() -> None:
    df = pd.DataFrame(
        {
            "risk_score": [300, 600, 900, 1, 5, 9, None, 600],
            "risk_score_model": [
                "RS-3.0",
                "RS-3.0",
                "RS-3.0",
                "RS-2.1",
                "RS-2.1",
                "RS-2.1",
                "RS-3.0",
                "RS-3.0",
            ],
        }
    )
    p = bureau_percentile(df)
    assert ((p.dropna() >= 0) & (p.dropna() <= 1)).all()
    assert p.iloc[0] < p.iloc[1] < p.iloc[2]
    assert p.iloc[3] < p.iloc[4] < p.iloc[5]
    assert p.iloc[1] == p.iloc[7]  # ties share a percentile
    assert pd.isna(p.iloc[6])
    # top of each scale lands in the same place regardless of raw scale
    assert math.isclose(p.iloc[2], 1.0) and math.isclose(p.iloc[5], 1.0)


# ----------------------------------------------------------------- customers SCD2 / CDC
OPEN = pd.Timestamp("9999-12-31")


def test_scd2_keeps_current_version_only() -> None:
    df = pd.DataFrame(
        {
            "crm_customer_id": ["RYM-1", "RYM-1", "RYM-2", "RYM-3"],
            "effective_from_ts": pd.to_datetime(["2020-01-01", "2025-06-01", "2021-01-01", "2022-01-01"]),
            "effective_to_ts": [pd.Timestamp("2025-06-01"), OPEN, OPEN, OPEN],
            "is_deleted": [False, False, False, True],
            "email": ["old@x.com", "new@x.com", "b@x.com", "gone@x.com"],
        }
    )
    before = df.copy()
    out = current_scd2_rows(df).set_index("crm_customer_id")
    assert set(out.index) == {"RYM-1", "RYM-2"}  # RYM-3's current version is deleted
    assert out.loc["RYM-1", "email"] == "new@x.com"
    pd.testing.assert_frame_equal(df, before)


def test_scd2_null_end_counts_as_current_and_latest_start_wins() -> None:
    df = pd.DataFrame(
        {
            "crm_customer_id": ["RYM-1", "RYM-1"],
            "effective_from_ts": pd.to_datetime(["2024-01-01", "2025-01-01"]),
            "effective_to_ts": [OPEN, None],
            "is_deleted": [False, None],
            "v": [1, 2],
        }
    )
    assert current_scd2_rows(df)["v"].tolist() == [2]


# ----------------------------------------------------------------- schema drift
def test_coalesce_renamed_channel() -> None:
    df = pd.DataFrame({"channel": ["call", None, "sms"], "channel_v2": [None, "email", "push"]})
    assert coalesce_renamed(df, new="channel_v2", old="channel").tolist() == ["call", "email", "push"]


def test_coalesce_renamed_tolerates_one_missing_column() -> None:
    assert coalesce_renamed(
        pd.DataFrame({"channel": ["call"]}), new="channel_v2", old="channel"
    ).tolist() == ["call"]
    assert coalesce_renamed(
        pd.DataFrame({"channel_v2": ["sms"]}), new="channel_v2", old="channel"
    ).tolist() == ["sms"]
    with pytest.raises(KeyError):
        coalesce_renamed(pd.DataFrame({"x": [1]}), new="channel_v2", old="channel")


# ----------------------------------------------------------------- transactions sample
def test_transaction_coverage_flags_sampled_customers_only() -> None:
    df = pd.DataFrame({"customer": ["a", "b", "c"]})
    assert has_transaction_coverage(df, customer="customer", sample_customers={"a", "c"}).tolist() == [
        True,
        False,
        True,
    ]
