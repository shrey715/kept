"""What's coming up, for the calendar page: promise due dates (kept or broken once past), proposed contacts
with their send windows, approval deadlines, customers' paydays and hardship plan ends. Read from tonight's
cards (nba.cards) and silver; nothing stored again.

Scope: an agent sees their own cases; case-wide roles the same 500 cases as their queue; every other role
(analysts, stewards) only counts per day, with groups under 10 left out. Names are masked except for
compliance.
"""

from __future__ import annotations

import calendar as cal
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

import duckdb
from pydantic import BaseModel

from kept.contracts.enums import ReleaseTier, Role
from kept.governance.access import mask_name

Kind = Literal["promise_due", "contact", "approval_deadline", "payday", "hardship_review"]
CASE_WIDE = frozenset({Role.HARDSHIP_SPECIALIST, Role.TEAM_LEAD, Role.COMPLIANCE})  # as api.CASE_WIDE_ROLES
QUEUE_SIZE = 500  # the same cases /queue shows a case-wide role
MIN_GROUP = 10  # aggregate counts below this are left out (the analysts' rule)


class CalendarEvent(BaseModel):
    id: str  # stable across fetches: the ICS UID is built from it
    kind: Kind
    start: datetime  # UTC; an all-day event starts at 00:00 UTC of its date
    end: datetime | None = None
    all_day: bool
    title: str
    detail: str | None = None
    case_id: str | None = None  # None on an aggregate (count) event
    display_name: str | None = None  # masked unless compliance
    tier: ReleaseTier | None = None
    status: str | None = None  # promise: open/kept/broken/...; contact: pending/approved/released/...
    amount: Decimal | None = None
    proposal_id: str | None = None
    count: int | None = None  # aggregate events: how many


class CalendarFeed(BaseModel):
    start: date
    end: date
    scope: Literal["own", "queue", "aggregate"]
    events: list[CalendarEvent]
    truncated: bool = False


def _day(d: date) -> datetime:
    return datetime.combine(d, time(), tzinfo=UTC)


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def paydays(next_pay: date, frequency: str, start: date, end: date) -> list[date]:
    """Every expected payday in [start, end], projected from the next one the bank detected."""
    if frequency in ("weekly", "biweekly"):
        step = timedelta(days=7 if frequency == "weekly" else 14)
        d = next_pay + step * ((start - next_pay) // step if start > next_pay else 0)
        out = []
        while d <= end:
            if d >= start:
                out.append(d)
            d += step
        return out
    if frequency in ("monthly", "semi_monthly"):
        out, y, m = [], start.year, start.month
        while date(y, m, 1) <= end:
            last = cal.monthrange(y, m)[1]
            days = [min(next_pay.day, last)] if frequency == "monthly" else [15, last]
            out += [date(y, m, x) for x in days if start <= date(y, m, x) <= end]
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out
    return []  # unknown frequency: no guess


def _scope_cases(cur: duckdb.DuckDBPyConnection, user_id: str, role: Role) -> list[tuple]:  # type: ignore[type-arg]
    where, params = ("where assigned_agent_id = ?", [user_id]) if role is Role.AGENT else ("", [])
    return cur.execute(
        "select case_id, golden_customer_id, display_name, tier, card from nba.cards"
        f" {where} order by action is null, expected_value desc, case_id limit {QUEUE_SIZE}",
        params,
    ).fetchall()


def calendar_feed(
    conn: duckdb.DuckDBPyConnection, *, start: date, end: date, user_id: str, role: Role, limit: int = 3000
) -> CalendarFeed:
    """Events overlapping [start, end] (dates, inclusive) that this person may see. A cursor per call."""
    cur = conn.cursor()
    try:
        if not cur.execute(
            "select count(*) from duckdb_tables() where schema_name = 'nba' and table_name = 'cards'"
        ).fetchone()[0]:  # type: ignore[index]
            return CalendarFeed(start=start, end=end, scope="aggregate", events=[])  # kept score hasn't run
        if role is not Role.AGENT and role not in CASE_WIDE:
            return CalendarFeed(start=start, end=end, scope="aggregate", events=_counts(cur, start, end))
        rows = _scope_cases(cur, user_id, role)
        events = _case_events(cur, rows, start, end, unmasked=role is Role.COMPLIANCE)
    finally:
        cur.close()
    events.sort(key=lambda e: (e.start, e.kind, e.case_id or ""))
    return CalendarFeed(
        start=start,
        end=end,
        scope="own" if role is Role.AGENT else "queue",
        events=events[:limit],
        truncated=len(events) > limit,
    )


def _case_events(
    cur: duckdb.DuckDBPyConnection,
    rows: list[tuple],  # type: ignore[type-arg]
    start: date,
    end: date,
    *,
    unmasked: bool,
) -> list[CalendarEvent]:
    names = {r[0]: (r[2] if unmasked else mask_name(r[2])) for r in rows}
    tiers = {r[0]: ReleaseTier(r[3]) if r[3] else None for r in rows}
    cases = list(names)
    lo, hi = _day(start), _day(end + timedelta(days=1))
    out: list[CalendarEvent] = []

    def base(case_id: str) -> dict[str, object]:
        return {"case_id": case_id, "display_name": names.get(case_id), "tier": tiers.get(case_id)}

    for case_id, _, _, _, card in rows:  # the proposal on each card: its send window and its deadline
        p = (json.loads(card) if isinstance(card, str) else card or {}).get("proposal") or {}
        ws, we, exp = _ts(p.get("window_start")), _ts(p.get("window_end")), _ts(p.get("expires_at"))
        action = str(p.get("action") or "contact").replace("_", " ")
        if ws and ws < hi and (we or ws) >= lo:
            out.append(
                CalendarEvent(
                    id=f"contact-{p['proposal_id']}",
                    kind="contact",
                    start=ws,
                    end=we,
                    all_day=False,
                    title=f"Send window: {action}",
                    detail=p.get("rationale") or None,
                    status=p.get("status"),
                    proposal_id=p.get("proposal_id"),
                    **base(case_id),  # type: ignore[arg-type]
                )
            )
        if exp and lo <= exp < hi and p.get("status") in ("pending", "approved"):
            out.append(
                CalendarEvent(
                    id=f"deadline-{p['proposal_id']}",
                    kind="approval_deadline",
                    start=exp,
                    all_day=False,
                    title=f"Approval expires: {action}",
                    detail="Unreleased approvals lapse 4 hours after they're proposed.",
                    status=p.get("status"),
                    proposal_id=p.get("proposal_id"),
                    **base(case_id),  # type: ignore[arg-type]
                )
            )
    for ptp_id, case_id, due, status, amount, paid in cur.execute(
        "select ptp_id, case_id, ptp_due_date, ptp_status, ptp_amount, amount_paid_against"
        " from silver.promises_to_pay where list_contains(?, case_id) and ptp_due_date between ? and ?",
        [cases, start, end],
    ).fetchall():
        status = str(status or "open")
        out.append(
            CalendarEvent(
                id=f"ptp-{ptp_id}",
                kind="promise_due",
                start=_day(due),
                all_day=True,
                title=f"Promise due: ${amount:,.2f}" if amount is not None else "Promise due",
                detail=f"{status.replace('_', ' ')}" + (f" · ${paid:,.2f} paid" if paid else ""),
                status=status,
                amount=amount,
                **base(case_id),  # type: ignore[arg-type]
            )
        )
    by_customer = {r[1]: r[0] for r in rows}
    for gid, next_pay, freq in cur.execute(
        "select golden_customer_id, expected_next_payroll_date, payroll_frequency_detected"
        " from gold.c360_customer where list_contains(?, golden_customer_id) and expected_next_payroll_date"
        " is not null",
        [list(by_customer)],
    ).fetchall():
        for d in paydays(next_pay, str(freq), start, end):
            out.append(
                CalendarEvent(
                    id=f"pay-{gid}-{d.isoformat()}",
                    kind="payday",
                    start=_day(d),
                    all_day=True,
                    title="Expected payday",
                    detail=f"{str(freq).replace('_', ' ')} pay, detected from deposits",
                    **base(by_customer[gid]),  # type: ignore[arg-type]
                )
            )
    for case_id, plan, plan_end in cur.execute(
        "select case_id, hardship_plan_type, hardship_plan_end from silver.collections_cases"
        " where list_contains(?, case_id) and hardship_plan_end between ? and ?",
        [cases, start, end],
    ).fetchall():
        out.append(
            CalendarEvent(
                id=f"hardship-{case_id}-{plan_end.isoformat()}",
                kind="hardship_review",
                start=_day(plan_end),
                all_day=True,
                title="Hardship plan ends: review",
                detail=str(plan or "plan").replace("_", " "),
                **base(case_id),  # type: ignore[arg-type]
            )
        )
    return out


def _counts(cur: duckdb.DuckDBPyConnection, start: date, end: date) -> list[CalendarEvent]:
    """Aggregate-only roles: how many of each kind fall on each day, every group of 10 or more."""
    rows = cur.execute(
        """
        select 'promise_due', ptp_due_date, ptp_status, count(*) from silver.promises_to_pay
         where ptp_due_date between $1 and $2 group by all
        union all
        select 'hardship_review', hardship_plan_end, null, count(*) from silver.collections_cases
         where hardship_plan_end between $1 and $2 group by all
        union all
        select 'contact', d, tier, count(*) from (
            select tier,
               cast(cast(json_extract_string(card, '$.proposal.window_start') as timestamptz) as date) as d
              from nba.cards)
         where d between $1 and $2 group by all
        union all
        select 'payday', expected_next_payroll_date, null, count(*) from gold.c360_customer
         where expected_next_payroll_date between $1 and $2 group by all
        """,
        [start, end],
    ).fetchall()
    label = {
        "promise_due": "promises due",
        "hardship_review": "hardship plans end",
        "contact": "contacts proposed",
        "payday": "customers' next payday",
    }
    return [
        CalendarEvent(
            id=f"n-{kind}-{d.isoformat()}-{extra or 'all'}",
            kind=kind,
            start=_day(d),
            all_day=True,
            title=f"{n:,} {label[kind]}" + (f" ({str(extra).replace('_', ' ')})" if extra else ""),
            status=str(extra) if extra and kind == "promise_due" else None,
            tier=ReleaseTier(extra) if extra and kind == "contact" else None,
            count=n,
        )
        for kind, d, extra, n in sorted(rows, key=lambda r: (r[1], r[0]))
        if n >= MIN_GROUP
    ]


# ---------------------------------------------------------------- the subscription feed (RFC 5545)
_LABEL = {
    "promise_due": "Promise due",
    "contact": "Send window",
    "approval_deadline": "Approval deadline",
    "payday": "Payday",
    "hardship_review": "Hardship review",
}


def _esc(t: str) -> str:
    return (
        t.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Lines are at most 75 octets (UTF-8); a continuation line starts with one space."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode()
        if len(cur) + len(b) > (74 if out else 75):
            out.append(cur.decode())
            cur = b
        else:
            cur += b
    out.append(cur.decode())
    return "\r\n ".join(out)


def to_ics(events: list[CalendarEvent], web: str, name: str, now: datetime) -> str:
    """A calendar file Google, Outlook and Apple Calendar subscribe to: all-day events as dates (DTEND the
    next day), timed ones in UTC (30 minutes when there's no end), each linking back to its case."""
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Kept//Collections calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(name)}",
        "X-PUBLISHED-TTL:PT1H",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
    ]
    for e in events:
        start = e.start.astimezone(UTC)
        if e.all_day:
            when = [
                f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
                f"DTEND;VALUE=DATE:{start + timedelta(days=1):%Y%m%d}",
            ]
        else:
            end = (e.end or start + timedelta(minutes=30)).astimezone(UTC)
            when = [f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}"]
        who = " · ".join(x for x in (e.display_name, e.case_id) if x)
        link = f"{web.rstrip('/')}/cases/{e.case_id}" if e.case_id else None
        text = "\n".join(x for x in (e.detail, who, link) if x)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{e.id}@kept",
            f"DTSTAMP:{stamp}",
            *when,
            f"SUMMARY:{_esc(e.title)}",
            *([f"DESCRIPTION:{_esc(text)}"] if text else []),
            *([f"URL:{link}"] if link else []),
            f"CATEGORIES:{_esc(_LABEL.get(e.kind, e.kind))}",
            *(
                [f"STATUS:{'CANCELLED' if e.status in ('expired', 'rejected') else 'CONFIRMED'}"]
                if e.status
                else []
            ),
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"
