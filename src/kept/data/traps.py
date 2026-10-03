"""Silver: fixes for the known traps in this dataset (design §3 + data dictionary).

1. Account tables have one row per snapshot_date (daily or month-end): take the latest.
2. Card cycles_delinquent counts cycles, not days: use dpd.
3. Bureau scores come from different models (external.risk_score_model, e.g. RS-3.0):
   convert to percentiles within model.
4. Transactions cover the last 13 months for a customer sample: missing stays missing.
5. customers is SCD2 with CDC: keep the current version (effective_to_ts 9999-12-31,
   not is_deleted); duplicate_of_crm_id is CRM's own incomplete duplicate pointer.
6. contact_history.channel was renamed channel_v2 upstream on 26 Sep: coalesce them.
"""

from __future__ import annotations

import pandas as pd

from kept.contracts.enums import DpdBucket

_DPD_EDGES = (
    (30, DpdBucket.B1_30),
    (60, DpdBucket.B31_60),
    (90, DpdBucket.B61_90),
    (120, DpdBucket.B91_120),
)


def latest_snapshot(df: pd.DataFrame, *, key: str | list[str], ts: str) -> pd.DataFrame:
    """One row per key: the row with the greatest `ts`. Ties broken by the later
    row in input order. Rows with null `ts` lose to any non-null `ts`."""
    return (
        df.sort_values(ts, kind="stable", na_position="first").drop_duplicates(key, keep="last").sort_index()
    )


def card_dpd(df: pd.DataFrame) -> pd.Series:
    """Days past due for card accounts. Uses the `dpd` column; never derives
    days from `cycles_delinquent`. Null dpd stays null."""
    return pd.to_numeric(df["dpd"], errors="coerce")


def dpd_bucket(dpd: int | None) -> DpdBucket | None:
    """0 -> CURRENT, 1-30, 31-60, 61-90, 91-120, 121+. Negative -> ValueError. None -> None."""
    if dpd is None:
        return None
    if dpd < 0:
        raise ValueError(f"dpd cannot be negative: {dpd}")
    if dpd == 0:
        return DpdBucket.CURRENT
    for upper, bucket in _DPD_EDGES:
        if dpd <= upper:
            return bucket
    return DpdBucket.B121_PLUS


def bureau_percentile(
    df: pd.DataFrame, *, score: str = "risk_score", scale: str = "risk_score_model"
) -> pd.Series:
    """Percentile rank in [0, 1] of each score within its scale. Monotone within a
    scale, ties share a percentile, null score -> null, scales never mixed."""
    scores = pd.to_numeric(df[score], errors="coerce")
    return scores.groupby(df[scale], dropna=False).rank(pct=True, method="max")


def current_scd2_rows(df: pd.DataFrame, *, key: str = "crm_customer_id") -> pd.DataFrame:
    """Current version per key: effective_to_ts is 9999-12-31 (or null) and is_deleted is not
    True. If a key has several current rows, keep the greatest effective_from_ts. A key whose
    current version is deleted disappears. Never mutates input."""
    to = df["effective_to_ts"]
    current = df[to.isna() | (to.astype(str).str[:10] == "9999-12-31")]
    latest = latest_snapshot(current, key=key, ts="effective_from_ts")
    # bronze/silver may carry is_deleted as text, so compare as lower-case string
    deleted = latest["is_deleted"].astype("string").str.lower().eq("true").fillna(False)
    return latest[~deleted]


def coalesce_renamed(df: pd.DataFrame, *, new: str, old: str, out: str | None = None) -> pd.Series:
    """Values from `new` where present, else `old` (schema drift: channel -> channel_v2).
    Either column may be missing from df entirely; both missing -> KeyError."""
    if new not in df and old not in df:
        raise KeyError(f"neither {new!r} nor {old!r} is in the frame")
    if new not in df:
        merged = df[old]
    elif old not in df:
        merged = df[new]
    else:
        merged = df[new].where(df[new].notna(), df[old])
    return merged.rename(out or new)


def has_transaction_coverage(df: pd.DataFrame, *, customer: str, sample_customers: set[str]) -> pd.Series:
    """True when the customer is in the transactions sample. Features computed from
    transactions must be null (not 0) for customers outside it."""
    return df[customer].isin(sample_customers)
