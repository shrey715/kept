"""Portfolio: tonight's cards and the bank's randomised test, summarised; analysts never see a single case."""

from dataclasses import replace
from datetime import date, datetime

import duckdb
import pytest
from fastapi.testclient import TestClient

from kept.app.api import create_app
from kept.app.demo import demo_services
from kept.app.history import CaseStory
from kept.app.portfolio import PaydayClock, case_page, money_flow, overview, payday_clock, wilson, workload


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    c.execute("create schema nba; create schema silver")
    c.execute(
        "create table nba.cards (case_id varchar, display_name varchar, current_bucket varchar, max_dpd int,"
        " total_overdue decimal(12,2), action varchar, tier varchar, p_paid_14d double, expected_value decimal(12,2),"
        " hardship boolean, hard_stop boolean, features_as_of timestamptz, no_action_reason varchar, card json)"
    )
    c.execute(
        "insert into nba.cards values"
        " ('C-1', 'Ann Lee', '31-60', 40, 1000, 'call', 'red', 0.5, 200, true, false, '2026-10-14 06:00:00+00', null, '{}'),"
        " ('C-2', 'Bo Kim', '31-60', 35, 500, 'sms_payment_link', 'green', 0.3, 50, false, false, '2026-10-14 06:00:00+00',"
        " null, '{}'),"
        " ('C-3', 'Cy Doe', '61-90', 70, 300, null, null, null, 0, false, true, '2026-10-14 06:00:00+00', 'No contact.',"
        """ '{"hard_stop": {"fired": ["cease", "insolvency"]}}'),"""
        " ('C-4', 'Di Ray', '1-30', 9, 200, null, null, null, 0, false, false, '2026-10-14 06:00:00+00',"
        " 'Best action is to wait: no contact beats waiting today.', '{}')"
    )
    c.execute(
        "create table silver.collections_cases (test_cell varchar, outcome varchar, promises_kept int,"
        " promises_broken int, cure_flag boolean, case_open_date date, primary_product varchar, entry_dpd int,"
        " dpd_at_day_30 int)"
    )
    c.execute(
        "insert into silver.collections_cases values"
        " ('champion', 'cured', 60, 40, true, '2026-08-01', 'card', 10, 0),"
        " ('challenger_A', 'cured', 30, 20, true, '2026-08-02', 'card', 20, 12),"
        " ('champion', null, 1, 1, false, '2026-09-01', 'card', 5, 45)"  # open: not in the A/B
    )
    return c


def test_wilson_matches_the_textbook_interval() -> None:
    p, lo, hi = wilson(60, 100)
    assert p == 0.6 and round(lo, 4) == 0.5020 and round(hi, 4) == 0.6906
    assert wilson(0, 0) == (0.0, 0.0, 0.0)


def test_overview_counts_slices_ab_and_insights(conn: duckdb.DuckDBPyConnection) -> None:
    p = overview(conn)
    assert (p.cases, p.balance, p.expected, p.actionable, p.red, p.hard_stops) == (4, 2000, 250, 2, 1, 1)
    assert [s.key for s in p.by_bucket] == ["31-60", "61-90", "1-30"] and p.by_tier[-1].key in (
        "none",
        "green",
    )
    champ = next(c for c in p.ab_test if c.test_cell == "champion")
    assert (champ.cases, champ.promises, champ.kept_rate) == (1, 100, 0.6)
    assert {i.id for i in p.insights} == {"ab", "red", "bucket", "stops"} and all(i.sql for i in p.insights)
    assert p.as_of == datetime.fromisoformat("2026-10-14T06:00:00+00:00")
    (cohort,) = p.cohorts
    assert cohort.product == "card" and cohort.kept_rate == 91 / 152  # 60+30+1 kept of 152 promises


def test_flow_takes_every_case_through_each_gate_to_one_card(conn: duckdb.DuckDBPyConnection) -> None:
    bands = {(f.source, f.target): f.cases for f in overview(conn).flow}
    assert bands == {
        ("open", "contactable"): 3,
        ("open", "hard_stop"): 1,
        ("hard_stop", "insolvency"): 1,  # the strongest of the stops that fired
        ("contactable", "hardship"): 1,
        ("contactable", "no_hardship"): 2,
        ("hardship", "red"): 1,
        ("no_hardship", "green"): 1,
        ("no_hardship", "wait"): 1,
    }


def test_money_flow_keeps_the_overdue_and_moves_the_payday_gain(conn: duckdb.DuckDBPyConnection) -> None:
    roll = {
        "inflow_cases": 100,
        "inflow_overdue": 1000.0,
        "rate": 0.5,
        "chargeoff_if_rolled": 0.1,
        "avg_chargeoff": 50.0,
    }
    base = {
        "Promises dated to payday": 40.0,
        "Roll-rate cut: charge-offs avoided": 0.0,
        "_rolled_per_pt": 5.0,
    }
    business = {"roll": roll, "scenarios": {"Base": base}}
    m = money_flow(conn, business)
    today, kept = ({(f.source, f.target): f.amount for f in fs} for fs in (m.today, m.with_kept))
    assert today[("entered", "rolled")] == 500 and kept[("entered", "rolled")] == 460
    assert (
        today[("entered", "cured")] == 250 and today[("entered", "partly_paid")] == 250
    )  # 1 cured, 1 partly
    for bands in (today, kept):
        assert sum(v for (s, _), v in bands.items() if s == "entered") == 1000
        assert (
            bands[("rolled", "charged_off")] + bands[("rolled", "not_charged_off")]
            == bands[("entered", "rolled")]
        )
    assert today[("rolled", "charged_off")] == kept[("rolled", "charged_off")] == 50  # base: no roll-rate cut
    assert m.written_off == m.written_off_kept == 100 * 0.5 * 0.1 * 50
    base["Roll-rate cut: charge-offs avoided"] = 5.0  # one point
    assert money_flow(conn, business).written_off_kept == 100 * 0.49 * 0.1 * 50


def test_case_page_filters_sorts_and_rejects_unknown_sorts(conn: duckdb.DuckDBPyConnection) -> None:
    page = case_page(conn, bucket="31-60", sort="total_overdue")
    assert page.total == 2 and [r.case_id for r in page.rows] == ["C-1", "C-2"]
    assert case_page(conn, tier="none").rows[0].case_id == "C-3"
    assert case_page(conn, q="bo").rows[0].case_id == "C-2"
    with pytest.raises(ValueError):
        case_page(conn, sort="case_id; drop table x")  # type: ignore[arg-type]


def test_routes_keep_single_cases_from_analysts_and_mask_names(conn: duckdb.DuckDBPyConnection) -> None:
    services = replace(
        demo_services(), portfolio=lambda: overview(conn), portfolio_cases=lambda **kw: case_page(conn, **kw)
    )
    client = TestClient(create_app(services))
    assert client.get("/portfolio", params={"user_id": "an-1", "role": "analyst"}).status_code == 200
    assert client.get("/portfolio/cases", params={"user_id": "an-1", "role": "analyst"}).status_code == 403
    tl = client.get("/portfolio/cases", params={"user_id": "tl-1", "role": "team_lead"}).json()
    co = client.get("/portfolio/cases", params={"user_id": "c-1", "role": "compliance"}).json()
    assert tl["rows"][0]["display_name"] != "Ann Lee" and co["rows"][0]["display_name"] == "Ann Lee"


def test_payday_clock_buckets_by_days_from_payday_and_drops_small_buckets() -> None:
    c = duckdb.connect()
    c.execute("create schema silver")
    # 70 customers paid on the 1st of each month; 60 each has one promise due on payday (kept) and one 2 days before
    # it (broken); 10 more have a promise 5 days after payday, too few customers to show
    c.execute(
        "create table silver.salary_credit_history as select 'X-' || i crm_customer_id,"
        " d first_credit_date, d last_credit_date from range(70) r(i), (values (date '2026-07-01'), (date '2026-08-01'), (date '2026-09-01')) v(d)"
    )
    c.execute(
        "create table silver.promises_to_pay as"
        " select 'P-a' || i ptp_id, 'X-' || i crm_customer_id, date '2026-08-01' ptp_due_date, 'kept' ptp_status,"
        " 100.0 ptp_amount, 100.0 amount_paid_against from range(60) r(i)"
        " union all select 'P-b' || i, 'X-' || i, date '2026-07-30', 'broken', 100.0, 25.0 from range(60) r(i)"
        " union all select 'P-c' || i, 'X-' || i, date '2026-07-06', 'kept', 100.0, 100.0 from range(60, 70) r(i)"
    )
    clock = payday_clock(c)
    assert [(b.days, b.promises, b.kept_rate, b.money_rate) for b in clock.buckets] == [
        (-2, 60, 0.0, 0.25),
        (0, 60, 1.0, 1.0),
    ]
    assert clock.kept_rate == 0.5 and "salary_credit_history" in clock.sql


def test_story_and_clock_routes_follow_the_role_rules() -> None:
    def no_case(case_id: str) -> CaseStory:
        raise KeyError(case_id)

    services = replace(
        demo_services(), payday_clock=lambda: PaydayClock(buckets=[], kept_rate=0.0, sql=""), story=no_case
    )
    client = TestClient(create_app(services))
    assert client.get("/portfolio/payday", params={"user_id": "an-1", "role": "analyst"}).status_code == 200
    assert client.get("/portfolio/payday", params={"user_id": "agent-7", "role": "agent"}).status_code == 403
    story = "/cases/CS-2026-118204/story"
    assert (
        client.get(story, params={"user_id": "agent-8", "role": "agent"}).status_code == 403
    )  # not their case
    assert (
        client.get(story, params={"user_id": "agent-7", "role": "agent"}).status_code == 404
    )  # theirs, not in silver


def test_workload_counts_call_windows_in_toronto_time_against_hourly_capacity() -> None:
    c = duckdb.connect()
    c.execute("create schema nba; create schema silver")
    c.execute("create table nba.cards (card json)")
    c.execute(
        "insert into nba.cards values"
        """ ('{"proposal": {"channel": "call", "window_start": "2026-10-14T13:00:00Z"}}'),"""  # Wed 09:00 EDT
        """ ('{"proposal": {"channel": "call", "window_start": "2026-10-14T13:30:00Z"}}'),"""
        """ ('{"proposal": {"channel": "email", "window_start": "2026-10-14T13:00:00Z"}}'),"""  # not a call
        " ('{\"proposal\": null}')"
    )
    c.execute(
        "create table silver.channel_capacity (date date, channel varchar, time_band varchar,"
        " capacity_units bigint, used_units bigint)"
    )
    c.execute(
        "insert into silver.channel_capacity values"
        " ('2026-10-07', 'call', '08-12', 9, 1),"  # Wed: 8 units over 4 hours
        " ('2026-10-07', 'email', 'all_day', 1000, 0),"
        " ('2026-09-30', 'call', '08-12', 400, 0)"  # an older Wednesday: not this week
    )
    w = workload(c)
    assert (w.time_zone, w.calls, w.capacity_from, w.capacity_to) == (
        "America/Toronto",
        2,
        date(2026, 10, 7),
        date(2026, 10, 7),
    )
    cells = {(x.weekday, x.hour): (x.calls, x.capacity) for x in w.cells}
    assert cells == {(2, 8): (0, 2.0), (2, 9): (2, 2.0), (2, 10): (0, 2.0), (2, 11): (0, 2.0)}
