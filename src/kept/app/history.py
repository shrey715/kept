"""A case's story from the warehouse, for the case page: every contact and promise, newest first, and the
customer's month-end balances, payments, days past due and salary. Read from silver, never stored again."""

from __future__ import annotations

from datetime import date, datetime, timedelta
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


# ---------------------------------------------------------------- the story timeline (#106)

PAYDAY_REACH = 40  # days either side of a due date to look for a recorded payday (scripts/evidence_report.py)


def signed_payday(due: date, paydays: list[date]) -> int | None:
    """Signed days from the nearest recorded payday within 40 days: 0 = due on payday, -3 = three days
    before the next one, +2 = two days after the last one; None without one. The payday clock
    (portfolio.payday_clock) and the evidence (scripts/evidence_report.py) count a promise only with a
    payday on both sides; a case's timeline also answers with one side, since the data ends before the
    latest promises' next payday."""
    last = max((d for d in paydays if 0 <= (due - d).days <= PAYDAY_REACH), default=None)
    nxt = min((d for d in paydays if 0 < (d - due).days <= PAYDAY_REACH), default=None)
    after = (due - last).days if last else None
    before = (nxt - due).days if nxt else None
    if after is None:
        return None if before is None else -before
    return after if before is None or after <= before else -before


class StoryContact(BaseModel):
    at: datetime
    channel: str
    reached: bool
    dpd: int | None


class StoryPromise(BaseModel):
    made: datetime
    due: date
    status: str  # kept, partially_kept, broken, open
    amount: Decimal
    paid: Decimal | None
    paid_date: date | None
    payday_days: int | None  # signed_payday of the due date


class StoryPayment(BaseModel):
    on: date
    amount: Decimal
    against_promise: bool


class StoryNote(BaseModel):
    at: datetime
    source: str  # note or transcript
    hardship: str  # none, possible, clear (the text model's reading)
    reason: str | None
    quote: str | None  # the words the model read it from, when it kept them
    text: str | None  # redacted, cut to 280 characters


class CaseStory(BaseModel):
    start: date
    end: date
    contacts: list[StoryContact]
    promises: list[StoryPromise]
    payments: list[StoryPayment]
    notes: list[StoryNote]
    paydays: list[date]


def case_story(conn: duckdb.DuckDBPyConnection, case_id: str) -> CaseStory:
    """Every contact, promise, payment and note on one case, and the customer's recorded paydays, for the
    swim-lane timeline. The window runs from a week before the first thing on the case to a week after the
    last; payments and paydays are cut to it. Raises KeyError for an unknown case."""
    cur = conn.cursor()
    try:
        row = cur.execute(
            "select coll_customer_ref, case_open_date from silver.collections_cases where case_id = ?",
            [case_id],
        ).fetchone()
        if row is None:
            raise KeyError(case_id)
        customer, opened = row
        contacts = cur.execute(
            "select contact_ts_utc, channel, coalesce(rpc_flag, false), dpd_at_contact"
            " from silver.contact_history where case_id = ? and contact_ts_utc is not null order by 1",
            [case_id],
        ).fetchall()
        promises = cur.execute(
            "select ptp_created_ts, ptp_due_date, coalesce(ptp_status, 'open'), ptp_amount,"
            " amount_paid_against, paid_date from silver.promises_to_pay"
            " where case_id = ? and ptp_due_date is not null order by 2",
            [case_id],
        ).fetchall()
        payments = cur.execute(
            "select value_date, abs(amount), ptp_id_matched is not null from silver.transactions"
            " where txn_type in ('loan_payment', 'card_payment') and target_account_id in"
            " (select unnest(from_json(account_ids, '[\"VARCHAR\"]')) from silver.collections_cases"
            " where case_id = ?) order by 1",
            [case_id],
        ).fetchall()
        notes = cur.execute(
            "select s.written_at at time zone 'UTC', s.source_type, coalesce(s.hardship_signal, 'none'),"
            " nullif(e.stated_reason_value, 'none'),"
            " coalesce(e.hardship_signal_quote, e.stated_reason_quote), left(r.text, 280)"
            " from text.text_signals s"  # the case filter on each table keeps a cold read near 10 ms
            " left join (from text.extractions where case_id = $1) e using (source_id)"
            " left join (from text.redacted_notes where case_id = $1) r using (source_id)"
            " where s.case_id = $1 order by 1",
            [case_id],
        ).fetchall()
        paydays = [
            d
            for (d,) in cur.execute(
                "select distinct unnest([first_credit_date, last_credit_date]) d"
                " from silver.salary_credit_history where crm_customer_id = ? order by 1",
                [customer],
            ).fetchall()
            if d is not None
        ]
    finally:
        cur.close()
    days = [
        *(c[0].date() for c in contacts),
        *(p[0].date() for p in promises if p[0]),
        *(p[1] for p in promises),
        *(n[0].date() for n in notes),
        *([opened] if opened else []),
    ]
    start, end = (min(days), max(days)) if days else (date.today(), date.today())
    week = timedelta(days=7)  # room for the payday before the first event
    start, end = start - week, end + week
    return CaseStory(
        start=start,
        end=end,
        contacts=[StoryContact(at=a, channel=str(ch), reached=r, dpd=d) for a, ch, r, d in contacts],
        promises=[
            StoryPromise(
                made=m or datetime.combine(due, datetime.min.time()),
                due=due,
                status=s,
                amount=amt or 0,
                paid=paid,
                paid_date=pd,
                payday_days=signed_payday(due, paydays),
            )
            for m, due, s, amt, paid, pd in promises
        ],
        payments=[
            StoryPayment(on=d, amount=a, against_promise=p) for d, a, p in payments if d and start <= d <= end
        ],
        notes=[
            StoryNote(at=a, source=s, hardship=h, reason=r, quote=q, text=t) for a, s, h, r, q, t in notes
        ],
        paydays=[d for d in paydays if start <= d <= end],
    )
