"""Append-only audit log (owner: Track D).

Every query, recommendation, override and LLM call goes here (design §9).
Dev: a DuckDB table with no UPDATE/DELETE path. Prod: append-only storage.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from kept.contracts.audit import AuditEvent, AuditKind


class DuckDBAuditLog:
    """Implements kept.contracts.interfaces.AuditLog. Exposes no update or delete."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        raise NotImplementedError("Track D")

    def append(self, event: AuditEvent) -> None:
        """Persist the event. Raise ValueError if event_id was already appended."""
        raise NotImplementedError("Track D")

    def read(
        self,
        *,
        kind: AuditKind | None = None,
        subject_id: str | None = None,
        since: datetime | None = None,
    ) -> Sequence[AuditEvent]:
        """Events matching every given filter, in append order. `since` is inclusive."""
        raise NotImplementedError("Track D")


def new_event_id() -> str:
    """Unique, sortable event ID (e.g. ULID/uuid7)."""
    raise NotImplementedError("Track D")
