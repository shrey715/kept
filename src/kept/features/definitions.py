"""Reference semantics for SQL features (oracle for dbt). Point in time: every
function sees only events at or before `as_of`. Missing stays missing (None)."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd


def broken_promises_90d(promises: pd.DataFrame, *, as_of: datetime) -> int:
    """Promises with ptp_due_date in (as_of.date() - 90 days, as_of.date()] and ptp_status ==
    'broken', counting only rows with status_ts <= as_of. Columns (promises_to_pay):
    ptp_due_date (date), ptp_status (open / kept / partially_kept / broken / cancelled),
    status_ts (tz-aware)."""
    raise NotImplementedError("Track D")


def kept_promise_ratio(promises: pd.DataFrame, *, as_of: datetime) -> float | None:
    """kept / (kept + partially_kept + broken) over promises resolved by as_of
    (status_ts <= as_of). partially_kept is not kept. 'open' and 'cancelled' ignored.
    No resolved promises -> None."""
    raise NotImplementedError("Track D")


def days_to_next_payroll(expected_next_payroll_date: date | None, *, as_of: datetime, tz: str) -> int | None:
    """Calendar days from as_of's local date (in tz) to the payroll date. Past date -> negative.
    None -> None."""
    raise NotImplementedError("Track D")


def contacts_last_7d(contacts: pd.DataFrame, *, as_of: datetime) -> int:
    """Contact attempts with contact_ts_utc in (as_of - 7d, as_of]. Column: contact_ts_utc (tz-aware)."""
    raise NotImplementedError("Track D")


def answer_rate(
    contacts: pd.DataFrame, *, as_of: datetime, after_local_hour: int | None = None, tz: str | None = None
) -> float | None:
    """answered / attempted calls at or before as_of: channel == 'call', answered means
    dial_result == 'answered'. Columns: contact_ts_utc, channel, dial_result. If
    after_local_hour is set, only attempts at or after that local hour in tz.
    No attempts -> None."""
    raise NotImplementedError("Track D")


def cohort_rate(successes: int, n: int, *, min_group: int = 50) -> float | None:
    """successes / n, or None if n < min_group (groups of 50+ only). successes > n -> ValueError."""
    raise NotImplementedError("Track D")
