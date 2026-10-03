"""Reference semantics for SQL features (oracle for dbt). Point in time: every
function sees only events at or before `as_of`. Missing stays missing (None)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd


def broken_promises_90d(promises: pd.DataFrame, *, as_of: datetime) -> int:
    """Promises with ptp_due_date in (as_of.date() - 90 days, as_of.date()] and ptp_status ==
    'broken', counting only rows with status_ts <= as_of. Columns (promises_to_pay):
    ptp_due_date (date), ptp_status (open / kept / partially_kept / broken / cancelled),
    status_ts (tz-aware)."""
    if promises.empty:
        return 0
    today = as_of.date()
    due = promises["ptp_due_date"]
    hit = (
        (due > today - timedelta(days=90))
        & (due <= today)
        & (promises["ptp_status"] == "broken")
        & (promises["status_ts"] <= as_of)
    )
    return int(hit.sum())


def kept_promise_ratio(promises: pd.DataFrame, *, as_of: datetime) -> float | None:
    """kept / (kept + partially_kept + broken) over promises resolved by as_of
    (status_ts <= as_of). partially_kept is not kept. 'open' and 'cancelled' ignored.
    No resolved promises -> None."""
    if promises.empty:
        return None
    known = promises[promises["status_ts"] <= as_of]["ptp_status"]
    resolved = known[known.isin(["kept", "partially_kept", "broken"])]
    return None if resolved.empty else float((resolved == "kept").mean())


def days_to_next_payroll(expected_next_payroll_date: date | None, *, as_of: datetime, tz: str) -> int | None:
    """Calendar days from as_of's local date (in tz) to the payroll date. Past date -> negative.
    None -> None."""
    if expected_next_payroll_date is None:
        return None
    return (expected_next_payroll_date - as_of.astimezone(ZoneInfo(tz)).date()).days


def contacts_last_7d(contacts: pd.DataFrame, *, as_of: datetime) -> int:
    """Contact attempts with contact_ts_utc in (as_of - 7d, as_of]. Column: contact_ts_utc (tz-aware)."""
    if contacts.empty:
        return 0
    ts = contacts["contact_ts_utc"]
    return int(((ts > as_of - timedelta(days=7)) & (ts <= as_of)).sum())


def answer_rate(
    contacts: pd.DataFrame, *, as_of: datetime, after_local_hour: int | None = None, tz: str | None = None
) -> float | None:
    """answered / attempted calls at or before as_of: channel == 'call', answered means
    dial_result == 'answered'. Columns: contact_ts_utc, channel, dial_result. If
    after_local_hour is set, only attempts at or after that local hour in tz.
    No attempts -> None."""
    if contacts.empty:
        return None
    calls = contacts[(contacts["channel"] == "call") & (contacts["contact_ts_utc"] <= as_of)]
    if after_local_hour is not None:
        if tz is None:
            raise ValueError("after_local_hour needs tz")
        calls = calls[calls["contact_ts_utc"].dt.tz_convert(tz).dt.hour >= after_local_hour]
    return None if calls.empty else float((calls["dial_result"] == "answered").mean())


def cohort_rate(successes: int, n: int, *, min_group: int = 50) -> float | None:
    """successes / n, or None if n < min_group (groups of 50+ only). successes > n -> ValueError."""
    if not 0 <= successes <= n:
        raise ValueError(f"successes {successes} not in [0, {n}]")
    return None if n < min_group else successes / n
