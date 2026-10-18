# ruff: noqa: E501  (the context oracle mirrors the SQL line by line)
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


def bank_context(
    case_outbound: pd.DataFrame, customer_contacts: pd.DataFrame, customer_promises: pd.DataFrame, *, as_of: datetime
) -> dict[str, object]:
    """The ten context inputs (dbt context_features.sql) at as_of, which is the instant just before the decision.
    case_outbound: the case's outbound contacts (contact_ts_utc tz-aware, rpc_flag, ptp_made_flag). customer_contacts:
    the customer's contacts (contact_ts_utc, payment_taken_flag, link_payment_flag, app_payment_after_contact_flag).
    customer_promises: ptp_created_ts, ptp_due_date, ptp_status, status_ts (NaT: unresolved), paid_date (date or None).
    Contacts are counted at or before as_of, within 30 days (7 for n_out_7d and the payment flags). The decision's day is
    that of as_of + 1 second (UTC)."""
    day = (as_of + timedelta(seconds=1)).date()
    out = case_outbound[
        (case_outbound["contact_ts_utc"] <= as_of) & (case_outbound["contact_ts_utc"] > as_of - timedelta(days=30))
    ].sort_values("contact_ts_utc")
    last = out.iloc[-1] if len(out) else None
    p = customer_promises
    status = pd.to_datetime(p["status_ts"], utc=True)  # all-NaT columns arrive naive
    open_ = p[(p["ptp_created_ts"] <= as_of) & (status.isna() | (status > as_of))]
    week = as_of - timedelta(days=7)
    c = customer_contacts
    flags = c[["payment_taken_flag", "link_payment_flag", "app_payment_after_contact_flag"]].fillna(False).any(axis=1)
    paid_contact = ((c["contact_ts_utc"] <= as_of) & (c["contact_ts_utc"] > week) & flags).any()
    noon = pd.to_datetime(p["paid_date"]) + pd.Timedelta(hours=12)
    noon = noon.dt.tz_localize("UTC")
    paid_promise = (p["ptp_status"].isin(["kept", "partially_kept"]) & (noon <= as_of) & (noon > week)).any()
    return {
        "pending_ptp": bool(len(open_)),
        "ptp_due_in_days": (open_["ptp_due_date"].min() - day).days if len(open_) else None,
        "n_out_7d": int((out["contact_ts_utc"] > week).sum()),
        "n_out_30d": len(out),
        "n_rpc_30d": int(out["rpc_flag"].fillna(False).astype(bool).sum()),
        "days_since_contact": (as_of - last["contact_ts_utc"]).total_seconds() / 86400 if last is not None else None,
        "last_rpc": bool(last["rpc_flag"]) if last is not None and pd.notna(last["rpc_flag"]) else None,
        "last_ptp_made": bool(last["ptp_made_flag"]) if last is not None and pd.notna(last["ptp_made_flag"]) else None,
        "paid_prev7": bool(paid_contact or paid_promise),
        "weekday": (day.isoweekday() % 7),  # duckdb dayofweek: Sunday 0
    }
