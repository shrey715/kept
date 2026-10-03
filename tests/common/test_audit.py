"""Append-only audit log (Track D)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kept.common.audit import DuckDBAuditLog, new_event_id
from kept.contracts import AuditEvent, AuditKind, Role

T0 = datetime(2026, 10, 2, 22, 0, tzinfo=UTC)


def ev(i: int, kind: AuditKind = AuditKind.RECOMMENDATION, subject: str = "C-1", dt: int = 0) -> AuditEvent:
    return AuditEvent(
        event_id=f"E-{i:04d}",
        at=T0 + timedelta(minutes=dt),
        kind=kind,
        actor_id="system:test",
        actor_role=Role.ENGINEER,
        subject_id=subject,
        payload={"n": i, "nested": {"ok": True}},
    )


def test_append_and_read_in_order() -> None:
    log = DuckDBAuditLog()
    for i in (3, 1, 2):
        log.append(ev(i))
    assert [e.event_id for e in log.read()] == ["E-0003", "E-0001", "E-0002"]


def test_round_trip_is_lossless() -> None:
    log = DuckDBAuditLog()
    e = ev(1)
    log.append(e)
    assert log.read()[0] == e


def test_duplicate_event_id_rejected() -> None:
    log = DuckDBAuditLog()
    log.append(ev(1))
    with pytest.raises(ValueError):
        log.append(ev(1))
    assert len(log.read()) == 1


def test_filters_combine() -> None:
    log = DuckDBAuditLog()
    log.append(ev(1, AuditKind.LLM_CALL, "C-1", 0))
    log.append(ev(2, AuditKind.RELEASE, "P-1", 5))
    log.append(ev(3, AuditKind.LLM_CALL, "C-2", 10))
    assert [e.event_id for e in log.read(kind=AuditKind.LLM_CALL)] == ["E-0001", "E-0003"]
    assert [e.event_id for e in log.read(subject_id="P-1")] == ["E-0002"]
    assert [e.event_id for e in log.read(since=T0 + timedelta(minutes=5))] == ["E-0002", "E-0003"]
    assert [e.event_id for e in log.read(kind=AuditKind.LLM_CALL, since=T0 + timedelta(minutes=1))] == [
        "E-0003"
    ]


def test_persists_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "audit.duckdb"
    log = DuckDBAuditLog(path)
    log.append(ev(1))
    del log
    assert [e.event_id for e in DuckDBAuditLog(path).read()] == ["E-0001"]


def test_no_update_or_delete_api() -> None:
    log = DuckDBAuditLog()
    public = {n for n in dir(log) if not n.startswith("_")}
    assert public == {"append", "append_many", "read"}  # append-only: no update or delete


def test_event_ids_unique_and_sortable() -> None:
    ids = [new_event_id() for _ in range(1000)]
    assert len(set(ids)) == 1000
    assert ids == sorted(ids)


def test_append_many_is_all_or_nothing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    log = DuckDBAuditLog(tmp_path / "audit.duckdb")
    first = [ev(i) for i in range(3)]
    log.append_many(first)
    with pytest.raises(ValueError, match="duplicate"):
        log.append_many([ev(10), first[0]])  # one duplicate: nothing from this batch lands
    assert [e.event_id for e in log.read()] == [e.event_id for e in first]
