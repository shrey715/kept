"""A case's story from the warehouse, for the case page: every contact and promise, newest first, and the
customer's month-end balances, payments, days past due and salary. Read from silver, never stored again."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

import duckdb
from pydantic import BaseModel

Tone = Literal["good", "bad", "neutral"]
_CHANNEL = {"sms": "SMS", "ivr": "IVR", "email": "Email", "call": "Call", "push": "Push notification"}
_PROMISE_TONE: dict[str, Tone] = {"kept": "good", "partially_kept": "neutral", "broken": "bad"}


class TimelineEvent(BaseModel):
    at: datetime
    kind: Literal["contact", "promise"]
    title: str
    detail: str | None = None
    amount: Decimal | None = None
    tone: Tone = "neutral"


class MonthPoint(BaseModel):
    month: date
    balance: Decimal
    paid: Decimal
    dpd: int
    salary: Decimal | None = None


class CaseHistory(BaseModel):
    events: list[TimelineEvent]
    months: list[MonthPoint]
    promises_kept: int
    promises_broken: int
    promises_open: int
    contacts: int
    right_party_rate: float | None  # share of contacts that reached the customer


def _contact(r: tuple) -> TimelineEvent:  # type: ignore[type-arg]
    at, channel, direction, outcome, rpc, ptp, paid, amount, hardship = r
    flags = [
        x
        for x, on in (("reached the customer", rpc), ("promise made", ptp), ("hardship mentioned", hardship))
        if on
    ]
    return TimelineEvent(
        at=at,
        kind="contact",
        title=f"{_CHANNEL.get(str(channel), str(channel).replace('_', ' ').capitalize())}, {direction}",
        detail=" · ".join([str(outcome or "no outcome recorded"), *flags]),
        amount=amount if paid else None,
        tone="good" if paid or ptp else "neutral",
    )


def _promise(r: tuple) -> TimelineEvent:  # type: ignore[type-arg]
    at, amount, due, status, paid, paid_date = r
    status = str(status or "open")
    detail = f"due {due}" + (f" · paid ${paid:,.2f} on {paid_date}" if paid else "")
    return TimelineEvent(
        at=at,
        kind="promise",
        title=f"Promise {status.replace('_', ' ')}",
        detail=detail,
        amount=amount,
        tone=_PROMISE_TONE.get(status, "neutral"),
    )


def case_history(conn: duckdb.DuckDBPyConnection, case_id: str, *, limit: int = 150) -> CaseHistory:
    """Raises KeyError for an unknown case. A cursor per call: the API serves requests on threads."""
    cur = conn.cursor()
    try:
        row = cur.execute(
            "select coll_customer_ref from silver.collections_cases where case_id = ?", [case_id]
        ).fetchone()
        if row is None:
            raise KeyError(case_id)
        customer = row[0]
        contacts = cur.execute(
            "select contact_ts_utc, channel, direction, outcome_desc, rpc_flag, ptp_made_flag,"
            " payment_taken_flag, payment_amount, hardship_mentioned_flag"
            " from silver.contact_history where case_id = ? order by contact_ts_utc desc",
            [case_id],
        ).fetchall()
        promises = cur.execute(
            "select ptp_created_ts, ptp_amount, ptp_due_date, ptp_status, amount_paid_against, paid_date"
            " from silver.promises_to_pay where case_id = ? order by ptp_created_ts desc",
            [case_id],
        ).fetchall()
        months = cur.execute(
            "select month_end_date, sum(balance), sum(coalesce(payment_made, 0)), max(coalesce(dpd, 0)),"
            " max(salary_credit_amount) from silver.account_monthly_snapshot where crm_customer_id = ?"
            " group by 1 order by 1",
            [customer],
        ).fetchall()
    finally:
        cur.close()
    events = sorted([*map(_contact, contacts), *map(_promise, promises)], key=lambda e: e.at, reverse=True)
    status = [str(p[3] or "open") for p in promises]
    return CaseHistory(
        events=events[:limit],
        months=[MonthPoint(month=m, balance=b or 0, paid=p, dpd=d, salary=s) for m, b, p, d, s in months],
        promises_kept=status.count("kept"),
        promises_broken=status.count("broken"),
        promises_open=status.count("open"),
        contacts=len(contacts),
        right_party_rate=(sum(1 for c in contacts if c[4]) / len(contacts)) if contacts else None,
    )
