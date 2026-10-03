"""Append-only audit log (owner: Track D).

Every query, recommendation, override and LLM call goes here (design §9).
Dev: a DuckDB table with no UPDATE/DELETE path. Prod: append-only storage.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from kept.contracts.audit import AuditEvent, AuditKind

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_US = timedelta(microseconds=1)
_DDL = """
create sequence if not exists audit_seq;
create table if not exists audit_events (
    seq       bigint default nextval('audit_seq'),
    event_id  varchar primary key,
    at_us     bigint not null,   -- UTC microseconds since epoch
    kind      varchar not null,
    subject_id varchar,
    body      varchar not null   -- the full event as JSON, so reads are lossless
);
"""


def _micros(at: datetime) -> int:
    return (at - _EPOCH) // _ONE_US


class DuckDBAuditLog:
    """Implements kept.contracts.interfaces.AuditLog. Exposes no update or delete.

    A file-backed log opens a connection per call (K5: DuckDB allows one writer, so
    the API and a batch job must not hold it open). ":memory:" keeps one connection.
    """

    def __init__(self, path: Path | str = ":memory:") -> None:
        self._path = str(path)
        self._mem = duckdb.connect() if self._path == ":memory:" else None
        with self._conn() as c:
            c.execute(_DDL)

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

    def append(self, event: AuditEvent) -> None:
        """Persist the event. Raise ValueError if event_id was already appended."""
        self.append_many([event])

    def append_many(self, events: Sequence[AuditEvent]) -> None:
        """Persist events in order, in one connection (a batch job's thousands of events).
        All or none: a duplicate event_id raises ValueError and nothing is written."""
        rows = [[e.event_id, _micros(e.at), e.kind.value, e.subject_id, e.model_dump_json()] for e in events]
        try:
            with self._conn() as c:
                c.execute("begin")
                try:
                    c.executemany(
                        "insert into audit_events (event_id, at_us, kind, subject_id, body)"
                        " values (?, ?, ?, ?, ?)",
                        rows,
                    )
                except Exception:
                    c.execute("rollback")
                    raise
                c.execute("commit")
        except duckdb.ConstraintException as e:
            raise ValueError(f"duplicate event_id in {len(rows)} events") from e

    def read(
        self,
        *,
        kind: AuditKind | None = None,
        subject_id: str | None = None,
        since: datetime | None = None,
    ) -> Sequence[AuditEvent]:
        """Events matching every given filter, in append order. `since` is inclusive."""
        where: list[str] = ["true"]
        params: list[object] = []
        if kind is not None:
            where.append("kind = ?")
            params.append(kind.value)
        if subject_id is not None:
            where.append("subject_id = ?")
            params.append(subject_id)
        if since is not None:
            where.append("at_us >= ?")
            params.append(_micros(since))
        with self._conn() as c:
            rows = c.execute(
                f"select body from audit_events where {' and '.join(where)} order by seq", params
            )
            return [AuditEvent.model_validate_json(b) for (b,) in rows.fetchall()]


_id_lock = threading.Lock()
_last_ns = 0


def new_event_id() -> str:
    """Unique, sortable event ID: 20-digit nanosecond clock (strictly increasing in this
    process) plus 8 random hex characters so two processes never collide."""
    global _last_ns
    with _id_lock:
        _last_ns = max(time.time_ns(), _last_ns + 1)
        ns = _last_ns
    return f"{ns:020d}{secrets.token_hex(4)}"
