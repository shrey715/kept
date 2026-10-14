"""The bell: what each person should know now, built from the audit log and the live approvals queue.

Nothing is stored twice: a notification is a view of an audit event (or of the approvals waiting at
your stage), so it is as trustworthy as the log. The only state is how far each person has read (DuckDB).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

import duckdb
from pydantic import BaseModel

from kept.contracts import AuditEvent, AuditKind, Role

Severity = Literal["critical", "action", "success", "info"]

# which audit events each role hears about
KINDS: dict[Role, tuple[AuditKind, ...]] = {
    Role.AGENT: (AuditKind.RELEASE, AuditKind.HARDSHIP_CHANGE, AuditKind.PROPOSAL_CANCELLED),
    Role.HARDSHIP_SPECIALIST: (AuditKind.RELEASE, AuditKind.HARDSHIP_CHANGE),
    Role.TEAM_LEAD: (AuditKind.RELEASE, AuditKind.OVERRIDE, AuditKind.HARDSHIP_CHANGE),
    Role.COMPLIANCE: (AuditKind.RELEASE, AuditKind.OVERRIDE, AuditKind.PROPOSAL_CANCELLED),
    Role.DATA_STEWARD: (AuditKind.STEWARD_DECISION,),
    Role.ANALYST: (),
    Role.ENGINEER: (AuditKind.OVERRIDE,),
}
STAGE_LABEL = {
    "specialist": "Red cases waiting for your first approval",
    "second_person": "Red cases waiting for a second person",
    "green_batch": "Green batch waiting for release",
    "assigned_agent": "Amber cases of yours waiting for release",
}


class Notification(BaseModel):
    id: str
    at: datetime
    severity: Severity
    title: str
    body: str
    href: str | None = None


class NotificationFeed(BaseModel):
    items: list[Notification]
    unread: int
    read_upto: datetime | None


def _case_link(case_id: str | None) -> str | None:
    return f"/cases/{case_id}" if case_id else None


def from_event(e: AuditEvent, *, role: Role, my_cases: set[str] | None) -> Notification | None:
    """One audit event as one notification for this role, or None if it isn't theirs to hear about.
    my_cases: an agent's own cases (None = every case, for case-wide roles)."""
    p = e.payload
    case = p.get("case_id") or (e.subject_id if e.kind is AuditKind.HARDSHIP_CHANGE else None)
    if my_cases is not None and case not in my_cases:
        return None
    action = str(p.get("action") or "").replace("_", " ")
    n = {"id": e.event_id, "at": e.at, "href": _case_link(case)}
    match e.kind:
        case AuditKind.RELEASE if p.get("source") == "customer":
            return Notification(
                **n,
                severity="success",
                title=f"Customer chose a plan on {case}",
                body=f"{p.get('installments')} × ${p.get('amount')}, first due {p.get('due_date')}",
            )
        case AuditKind.RELEASE if p.get("released"):
            return Notification(
                **n,
                severity="success",
                title=f"Released: {action or 'action'} on {case}",
                body=f"Tier {p.get('tier')}",
            )
        case AuditKind.RELEASE if p.get("status") == "approved":
            if role not in (Role.TEAM_LEAD, Role.COMPLIANCE):
                return None
            return Notification(
                **n, severity="action", title=f"First approval on {case}", body="Needs a second person"
            )
        case AuditKind.RELEASE if p.get("decision") == "reject":
            return Notification(
                **n, severity="info", title=f"Rejected: {action} on {case}", body=str(p.get("reason") or "")
            )
        case AuditKind.RELEASE:
            return Notification(
                **n, severity="action", title=f"Refused at release on {case}", body=str(p.get("reason") or "")
            )
        case AuditKind.OVERRIDE:
            return Notification(
                **n,
                severity="action",
                title=f"Override on {case}",
                body=str(p.get("override_reason") or p.get("reason") or "Reviewer chose a different action"),
            )
        case AuditKind.HARDSHIP_CHANGE:
            to = str(p.get("to", ""))
            return Notification(
                **n,
                severity="action" if to not in ("", "none") else "info",
                title=f"Hardship {'flagged' if to not in ('', 'none') else 'cleared'} on {case}",
                body=f"{p.get('from')} → {to} · {p.get('source', '')}".strip(" ·"),
            )
        case AuditKind.PROPOSAL_CANCELLED:
            return Notification(
                **n, severity="info", title=f"Proposal cancelled on {case}", body=str(p.get("reason") or "")
            )
        case AuditKind.STEWARD_DECISION:
            return Notification(
                **n,
                severity="info",
                title=f"Match {p.get('verdict', 'decided')} by {e.actor_id}",
                body=str(p.get("item_id") or e.subject_id or ""),
                href="/steward",
            )
    return None


def build(
    events: Iterable[AuditEvent],
    *,
    user_id: str,
    role: Role,
    my_cases: set[str] | None,
    waiting: dict[str, tuple[int, datetime]],
    limit: int = 30,
) -> list[Notification]:
    """Newest first. Your own actions never notify you. waiting: stage -> (count, newest proposal time)."""
    out = [
        Notification(
            id=f"waiting:{stage}:{count}",  # a new count is a new notification
            at=at,
            severity="action",
            title=f"{count} {STAGE_LABEL.get(stage, stage)}",
            body="Open Approvals to review them",
            href="/approvals",
        )
        for stage, (count, at) in waiting.items()
        if count
    ]
    out += [
        n
        for e in events
        if e.actor_id != user_id and (n := from_event(e, role=role, my_cases=my_cases)) is not None
    ]
    return sorted(out, key=lambda n: n.at, reverse=True)[:limit]


class ReadState:
    """How far each person has read their notifications, in DuckDB (one connection per call: K5)."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self._path = str(path)
        self._mem = duckdb.connect() if self._path == ":memory:" else None
        with self._conn() as c:
            c.execute(
                "create table if not exists notification_reads"
                " (user_id varchar primary key, read_upto timestamptz)"
            )

    @contextmanager
    def _conn(self) -> Iterator[duckdb.DuckDBPyConnection]:
        if self._mem is not None:
            yield self._mem
            return
        c = duckdb.connect(self._path)
        try:
            yield c
        finally:
            c.close()

    def get(self, user_id: str) -> datetime | None:
        with self._conn() as c:
            row = c.execute(
                "select read_upto from notification_reads where user_id = ?", [user_id]
            ).fetchone()
        return row[0] if row else None

    def mark(self, user_id: str, upto: datetime) -> None:
        """Never moves backwards: an older tab can't un-read what a newer one read."""
        with self._conn() as c:
            c.execute(
                "insert into notification_reads values (?, ?) on conflict (user_id)"
                " do update set read_upto = greatest(notification_reads.read_upto, excluded.read_upto)",
                [user_id, upto],
            )
