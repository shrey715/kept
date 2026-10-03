"""Label SQL reference: outcomes for training and the north-star metric.

paid_14d payments come from loan_instalments (paid), card_statements / card last_payment_*,
account_monthly_snapshot.payment_made and contact_history.payment_taken_flag; transactions
only covers a sample (13 months), so it can confirm but never deny a payment. TBC with Track A
which source is authoritative per product. The frame given to paid_within has columns
paid_at (tz-aware), amount, reversed.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from kept.contracts.enums import DpdBucket


def paid_within(
    payments: pd.DataFrame, *, decision_at: datetime, days: int = 14, min_amount: float = 0.01
) -> bool:
    """paid_14d: any payment with paid_at in (decision_at, decision_at + days] and
    amount >= min_amount. Reversed payments (reversed == True) don't count."""
    if payments.empty:
        return False
    end = decision_at + timedelta(days=days)
    hit = (
        (payments["paid_at"] > decision_at)
        & (payments["paid_at"] <= end)
        & (payments["amount"] >= min_amount)
        & (payments["reversed"] != True)  # noqa: E712 - null reversed counts as not reversed
    )
    return bool(hit.any())


def rolled_forward(entry_bucket: DpdBucket, bucket_at_day_30: DpdBucket) -> bool:
    """True when bucket_at_day_30 is worse than entry_bucket (design §2)."""
    order = list(DpdBucket)  # declaration order is severity order
    return order.index(bucket_at_day_30) > order.index(entry_bucket)


def roll_forward_rate(cases: pd.DataFrame) -> float:
    """Share of cases entering at 1-30 DPD (entry_dpd in [1, 30]) whose dpd_at_day_30 lands
    in a worse bucket. Cases outside the entry cohort, or not yet 30 days old (null
    dpd_at_day_30), are ignored. Empty cohort -> ValueError."""
    cohort = cases[cases["entry_dpd"].between(1, 30) & cases["dpd_at_day_30"].notna()]
    if cohort.empty:
        raise ValueError("no cases entered at 1-30 DPD")
    # for a 1-30 entry, "worse bucket" is exactly dpd_at_day_30 > 30
    return float((cohort["dpd_at_day_30"] > 30).mean())
