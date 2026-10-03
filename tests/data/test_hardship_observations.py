"""silver.int_hardship_observations + the combine macro on a tiny warehouse, with the dbt Jinja
(ref, source, var, text_extractions) filled in by hand (integration: needs `uv sync --extra data`)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from kept.data.hardship_sql import register

pytestmark = [pytest.mark.integration, pytest.mark.slow]

SQL = Path(__file__).resolve().parents[2] / "dbt" / "models" / "silver" / "int_hardship_observations.sql"


def _render() -> str:
    jinja2 = pytest.importorskip("jinja2")
    env = jinja2.Environment()
    ctx = {
        "ref": lambda name: f"silver.{name}",
        "source": lambda _source, name: f"silver.{name}",
        "var": lambda _name, default: default,
        "text_extractions": lambda: "text.extractions",
    }
    return env.from_string(SQL.read_text()).render(**ctx)


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    from kept.text.store import DDL

    c = duckdb.connect()
    register(c)
    for schema in ("silver", "text"):
        c.execute(f"create schema {schema}")
    c.execute(DDL)
    c.execute(
        """create table silver.int_crosswalk as select * from (values
            ('G-1', 'card', 'K-ACTIVE'), ('G-2', 'loan', 'L-ENDED'), ('G-3', 'crm', 'C-RECENT'),
            ('G-4', 'crm', 'C-OLD'), ('G-5', 'card', 'K-NONE'))
            t(golden_customer_id, source_system, source_key)"""
    )
    c.execute("alter table silver.int_crosswalk add column valid_to timestamp")
    c.execute(
        """create table silver.int_open_case as select * from (values
            ('G-6', 'CS-6', true, 'agent_coded', timestamp '2026-09-20'),
            ('G-7', 'CS-7', false, null, timestamp '2026-09-20'),
            ('G-8', 'CS-8', false, null, timestamp '2026-09-20'),
            ('G-9', 'CS-9', false, null, timestamp '2026-09-20'))
            t(golden_customer_id, open_case_id, hardship_flag, hardship_source, observed_at)"""
    )
    for table, key, end in (
        ("card_accounts", "K-ACTIVE", "null::date"),
        ("loan_accounts", "L-ENDED", "date '2026-08-01'"),
    ):
        c.execute(
            f"create table silver.{table} as select '{key}' as src_customer_ref, true as hardship_program_flag, "
            f"date '2026-07-01' as hardship_start_date, {end} as hardship_end_date"
        )
    c.execute(
        """create table silver.contact_history as select * from (values
            ('C-RECENT', true, timestamp '2026-09-20 10:00:00'), ('C-OLD', true, timestamp '2026-06-01 10:00:00'))
            t(crm_customer_id, hardship_mentioned_flag, contact_ts_utc)"""
    )
    for sid, case, signal, agent in (
        ("N-7", "CS-7", "possible", None),  # a new note on the open case: "lost shifts"
        ("N-8", "CS-8", "possible", "AG-1"),  # the agent confirmed it
        ("N-9", "CS-OLD", "possible", None),  # a note on a closed case: not this case's hardship
    ):
        c.execute(
            "insert into text.extractions (source_id, case_id, hardship_signal_value, extractor, extracted_at, "
            "confirmed_by_agent_id) values (?, ?, ?, 'llm:test', timestamptz '2026-09-25 12:00:00+00', ?)",
            [sid, case, signal, agent],
        )
    # Track C's cash-flow model, as it would be built: one 'possible' row per customer whose payroll fired
    c.execute(
        """create table silver.cashflow_observations as select * from (values
            ('G-10', 'cash_flow', 'possible', timestamp '2026-09-25', null::varchar, null::varchar))
            t(golden_customer_id, source, signal, observed_at, confirmed_by, cleared_by)"""
    )
    c.execute(f"create table silver.int_hardship_observations as {_render()}")
    return c


def test_each_source_sets_the_expected_status(conn: duckdb.DuckDBPyConnection) -> None:
    got = {
        g: (status, source)
        for g, status, source in conn.execute(
            "select * from kept_combine_hardship('silver.int_hardship_observations')"
        ).fetchall()
    }
    assert got == {
        "G-1": ("confirmed", "account_programme"),  # an active programme
        "G-3": ("possible", "agent"),  # hardship mentioned to an agent this month
        "G-6": ("confirmed", "agent"),  # agent-coded case flag
        "G-7": ("possible", "llm"),  # a new note flips it to possible; the LLM alone cannot confirm
        "G-8": ("confirmed", "llm"),  # the agent confirmed the note
        "G-10": ("possible", "cash_flow"),  # late payroll (Track C's rule): protects, never confirms
    }
    # not present: G-2 (programme ended), G-4 (mention older than 30 days), G-5 (nothing), G-9 (note on a closed case)
