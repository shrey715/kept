"""The calendar: an agent sees their own cases' promise dues, send windows, deadlines, paydays and hardship
plan ends, names masked; aggregate-only roles see counts per day, small groups left out."""

import json
from datetime import date

import duckdb
import pytest

from kept.app.calendar_events import calendar_feed, paydays
from kept.contracts.enums import Role

PROPOSAL = {
    "proposal_id": "P-1",
    "action": "call",
    "status": "pending",
    "window_start": "2026-10-14T22:00:00Z",
    "window_end": "2026-10-15T00:00:00Z",
    "expires_at": "2026-10-14T20:00:00Z",
}


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    for s in ("nba", "silver", "gold"):
        c.execute(f"create schema {s}")
    c.execute(
        "create table nba.cards (case_id varchar, golden_customer_id varchar, assigned_agent_id varchar,"
        " display_name varchar, tier varchar, card json, action varchar, expected_value decimal(12,2))"
    )
    c.execute(
        "insert into nba.cards values ('C-1', 'G-1', 'AG-1', 'Jane Doe', 'red', ?, 'call', 50),"
        " ('C-2', 'G-2', 'AG-2', 'Sam Roe', null, '{}', null, 0)",
        [json.dumps({"proposal": PROPOSAL})],
    )
    c.execute(
        "create table silver.promises_to_pay (ptp_id varchar, case_id varchar, ptp_due_date date,"
        " ptp_status varchar, ptp_amount decimal(12,2), amount_paid_against decimal(12,2))"
    )
    c.execute(
        "insert into silver.promises_to_pay values ('T-1', 'C-1', '2026-10-03', 'kept', 140, 140),"
        " ('T-2', 'C-2', '2026-10-05', 'open', 90, null)"
    )
    c.execute(
        "insert into silver.promises_to_pay select 'T-x' || i, 'C-x', '2026-10-20', 'open', 10, null"
        " from range(12) t(i)"
    )
    c.execute(
        "create table gold.c360_customer (golden_customer_id varchar, expected_next_payroll_date date,"
        " payroll_frequency_detected varchar)"
    )
    c.execute("insert into gold.c360_customer values ('G-1', '2026-10-09', 'biweekly')")
    c.execute(
        "create table silver.collections_cases (case_id varchar, hardship_plan_type varchar,"
        " hardship_plan_end date)"
    )
    c.execute("insert into silver.collections_cases values ('C-1', 'skip_payment', '2026-10-31')")
    return c


def test_an_agent_sees_their_own_cases_coming_up(conn: duckdb.DuckDBPyConnection) -> None:
    f = calendar_feed(conn, start=date(2026, 10, 1), end=date(2026, 10, 31), user_id="AG-1", role=Role.AGENT)
    assert f.scope == "own" and {e.case_id for e in f.events} == {"C-1"}  # not AG-2's case
    kinds = [e.kind for e in f.events]
    assert kinds.count("payday") == 2  # biweekly from 9 Oct: 9 and 23 Oct
    assert {"promise_due", "contact", "approval_deadline", "hardship_review"} <= set(kinds)
    kept = next(e for e in f.events if e.kind == "promise_due")
    assert (kept.status, kept.all_day, kept.display_name, kept.tier) == ("kept", True, "Jane D.", "red")
    window = next(e for e in f.events if e.kind == "contact")
    assert window.end is not None and window.end > window.start and window.proposal_id == "P-1"


def test_aggregate_roles_get_counts_without_small_groups(conn: duckdb.DuckDBPyConnection) -> None:
    f = calendar_feed(
        conn, start=date(2026, 10, 1), end=date(2026, 10, 31), user_id="an-1", role=Role.ANALYST
    )
    assert f.scope == "aggregate" and all(e.case_id is None and e.display_name is None for e in f.events)
    assert [(e.kind, e.count, e.start.date()) for e in f.events] == [("promise_due", 12, date(2026, 10, 20))]


def test_paydays_project_each_frequency() -> None:
    oct_ = (date(2026, 10, 1), date(2026, 10, 31))
    assert paydays(date(2026, 9, 25), "weekly", *oct_) == [date(2026, 10, d) for d in (2, 9, 16, 23, 30)]
    assert paydays(date(2026, 10, 9), "semi_monthly", *oct_) == [date(2026, 10, 15), date(2026, 10, 31)]
    assert paydays(date(2026, 9, 30), "monthly", date(2026, 10, 1), date(2026, 11, 30)) == [
        date(2026, 10, 30),
        date(2026, 11, 30),
    ]
    assert paydays(date(2026, 10, 9), "unknown", *oct_) == []
