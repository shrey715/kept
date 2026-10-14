"""Case history: contacts and promises newest first, month-end totals, promise counts, from silver tables."""

from datetime import date, datetime

import duckdb
import pytest

from kept.app.history import case_history


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    c.execute("create schema silver")
    c.execute("create table silver.collections_cases (case_id varchar, coll_customer_ref varchar)")
    c.execute("insert into silver.collections_cases values ('C-1', 'X-1')")
    c.execute(
        "create table silver.contact_history (case_id varchar, contact_ts_utc timestamp, channel varchar,"
        " direction varchar, outcome_desc varchar, rpc_flag boolean, ptp_made_flag boolean,"
        " payment_taken_flag boolean, payment_amount decimal(12,2), hardship_mentioned_flag boolean)"
    )
    c.execute(
        "insert into silver.contact_history values"
        " ('C-1', '2026-09-01 18:00', 'call', 'outbound', 'Promise taken', true, true, false, null, false),"
        " ('C-1', '2026-09-03 10:00', 'sms', 'outbound', 'Message sent', false, false, false, null, false)"
    )
    c.execute(
        "create table silver.promises_to_pay (case_id varchar, ptp_created_ts timestamp, ptp_amount decimal(12,2),"
        " ptp_due_date date, ptp_status varchar, amount_paid_against decimal(12,2), paid_date date)"
    )
    c.execute(
        "insert into silver.promises_to_pay values ('C-1', '2026-09-01 18:05', 140, '2026-09-12', 'kept', 140, '2026-09-12')"
    )
    c.execute(
        "create table silver.account_monthly_snapshot (crm_customer_id varchar, month_end_date date,"
        " balance decimal(12,2), payment_made decimal(12,2), dpd integer, salary_credit_amount decimal(12,2))"
    )
    c.execute(
        "insert into silver.account_monthly_snapshot values ('X-1', '2026-08-31', 1000, 50, 30, 2400),"
        " ('X-1', '2026-08-31', 500, null, 45, null), ('X-2', '2026-08-31', 9, 9, 9, 9)"
    )
    return c


def test_history_reads_a_case_newest_first(conn: duckdb.DuckDBPyConnection) -> None:
    h = case_history(conn, "C-1")
    assert [e.kind for e in h.events] == ["contact", "promise", "contact"]
    assert h.events[1].tone == "good" and "paid $140.00" in (h.events[1].detail or "")
    assert h.events[2].tone == "good" and "promise made" in (h.events[2].detail or "")
    assert (h.promises_kept, h.promises_broken, h.contacts, h.right_party_rate) == (1, 0, 2, 0.5)
    (m,) = h.months  # X-2 is someone else
    assert (m.month, m.balance, m.paid, m.dpd, m.salary) == (date(2026, 8, 31), 1500, 50, 45, 2400)
    assert h.events[0].at == datetime(2026, 9, 3, 10, 0)


def test_unknown_case_is_a_key_error(conn: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(KeyError):
        case_history(conn, "C-404")
