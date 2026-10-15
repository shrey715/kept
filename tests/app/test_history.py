"""Case history: contacts and promises newest first, month-end totals, promise counts, from silver tables."""

from datetime import date, datetime

import duckdb
import pytest

from kept.app.history import case_history, case_story, signed_payday


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


def test_signed_payday_counts_from_the_nearest_payday() -> None:
    pays = [date(2026, 7, 30), date(2026, 8, 29)]
    assert signed_payday(date(2026, 8, 29), pays) == 0
    assert signed_payday(date(2026, 8, 1), pays) == 2  # two days after the last one
    assert signed_payday(date(2026, 8, 26), pays) == -3  # three days before the next one
    assert signed_payday(date(2026, 9, 12), pays) == 14  # only the last one is recorded
    assert signed_payday(date(2026, 12, 1), pays) is None


def test_story_puts_every_lane_in_one_window() -> None:
    c = duckdb.connect()
    c.execute("create schema silver; create schema text")
    c.execute(
        "create table silver.collections_cases as select 'C-1' case_id, 'X-1' coll_customer_ref,"
        " date '2026-07-01' case_open_date, '[\"L-1\"]' account_ids"
    )
    c.execute(
        "create table silver.contact_history as select 'C-1' case_id, timestamp '2026-07-02 18:00' contact_ts_utc,"
        " 'call' channel, true rpc_flag, 20 dpd_at_contact"
    )
    c.execute(
        "create table silver.promises_to_pay as select * from (values"
        " ('C-1', timestamp '2026-07-02 18:05', date '2026-07-29', 'broken', 140.0, 0.0, null::date),"
        " ('C-1', timestamp '2026-07-31 10:00', date '2026-07-31', 'kept', 90.0, 90.0, date '2026-07-31'))"
        " t(case_id, ptp_created_ts, ptp_due_date, ptp_status, ptp_amount, amount_paid_against, paid_date)"
    )
    c.execute(
        "create table silver.transactions as select * from (values"
        " (date '2026-07-31', -90.0, 'card_payment', 'L-1', 'P-2'), (date '2026-01-05', -10.0, 'card_payment', 'L-1', null),"
        " (date '2026-07-31', -50.0, 'card_payment', 'L-9', null))"
        " t(value_date, amount, txn_type, target_account_id, ptp_id_matched)"
    )
    c.execute(
        "create table silver.salary_credit_history as select * from (values"
        " ('X-1', date '2026-06-30', date '2026-06-30'), ('X-1', date '2026-07-31', date '2026-07-31'),"
        " ('X-2', date '2026-07-15', date '2026-07-15')) t(crm_customer_id, first_credit_date, last_credit_date)"
    )
    c.execute(
        "create table text.text_signals as select 'N-1' source_id, 'C-1' case_id, 'note' source_type,"
        " timestamptz '2026-07-02 18:10:00+00' written_at, 'possible' hardship_signal"
    )
    c.execute(
        "create table text.extractions as select 'N-1' source_id, 'C-1' case_id, 'job_loss' stated_reason_value,"
        " 'lost my job' hardship_signal_quote, null::varchar stated_reason_quote"
    )
    c.execute(
        "create table text.redacted_notes as select 'N-1' source_id, 'C-1' case_id, 'cust lost my job, pays on payday' \"text\""
    )
    s = case_story(c, "C-1")
    assert (s.start, s.end) == (date(2026, 6, 24), date(2026, 8, 7))  # a week either side of the case
    assert [p.payday_days for p in s.promises] == [-2, 0]  # two days before payday, then on it
    ((pay),) = s.payments  # January's is outside the window, L-9 is another account
    assert (pay.amount, pay.against_promise) == (90, True)
    assert s.paydays == [date(2026, 6, 30), date(2026, 7, 31)]  # X-2's payday is someone else's
    (n,) = s.notes
    assert (n.hardship, n.reason, n.quote, n.at) == (
        "possible",
        "job_loss",
        "lost my job",
        datetime(2026, 7, 2, 18, 10),
    )
    assert s.contacts[0].reached and s.contacts[0].dpd == 20
    with pytest.raises(KeyError):
        case_story(c, "C-404")
