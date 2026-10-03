"""Label SQL reference: outcomes for training and the north-star metric.

paid_14d payments come from loan_instalments (paid), card_statements / card last_payment_*,
account_monthly_snapshot.payment_made and contact_history.payment_taken_flag; transactions
only covers a sample (13 months), so it can confirm but never deny a payment. TBC with Track A
which source is authoritative per product. The frame given to paid_within has columns
paid_at (tz-aware), amount, reversed.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from kept.contracts.enums import DpdBucket


def paid_within(
    payments: pd.DataFrame, *, decision_at: datetime, days: int = 14, min_amount: float = 0.01
) -> bool:
    """paid_14d: any payment with paid_at in (decision_at, decision_at + days] and
    amount >= min_amount. Reversed payments (reversed == True) don't count."""
    raise NotImplementedError("Track D")


def rolled_forward(entry_bucket: DpdBucket, bucket_at_day_30: DpdBucket) -> bool:
    """True when bucket_at_day_30 is worse than entry_bucket (design §2)."""
    raise NotImplementedError("Track D")


def roll_forward_rate(cases: pd.DataFrame) -> float:
    """Share of cases entering at 1-30 DPD (entry_dpd in [1, 30]) whose dpd_at_day_30 lands
    in a worse bucket. Cases outside the entry cohort are ignored. Empty cohort -> ValueError."""
    raise NotImplementedError("Track D")
