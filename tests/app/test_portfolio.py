"""Portfolio: tonight's cards and the bank's randomised test, summarised; analysts never see a single case."""

from dataclasses import replace
from datetime import datetime

import duckdb
import pytest
from fastapi.testclient import TestClient

from kept.app.api import create_app
from kept.app.demo import demo_services
from kept.app.history import CaseStory
from kept.app.portfolio import PaydayClock, case_page, overview, payday_clock, wilson


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    c.execute("create schema nba; create schema silver")
    c.execute(
        "create table nba.cards (case_id varchar, display_name varchar, current_bucket varchar, max_dpd int,"
        " total_overdue decimal(12,2), action varchar, tier varchar, p_paid_14d double, expected_value decimal(12,2),"
        " hardship boolean, hard_stop boolean, features_as_of timestamptz)"
    )
    c.execute(
        "insert into nba.cards values"
        " ('C-1', 'Ann Lee', '31-60', 40, 1000, 'call', 'red', 0.5, 200, true, false, '2026-10-14 06:00:00+00'),"
        " ('C-2', 'Bo Kim', '31-60', 35, 500, 'sms_payment_link', 'green', 0.3, 50, false, false, '2026-10-14 06:00:00+00'),"
        " ('C-3', 'Cy Doe', '61-90', 70, 300, null, null, null, 0, false, true, '2026-10-14 06:00:00+00')"
    )
    c.execute(
        "create table silver.collections_cases (test_cell varchar, outcome varchar, promises_kept int,"
        " promises_broken int, cure_flag boolean, case_open_date date, primary_product varchar)"
    )
    c.execute(
        "insert into silver.collections_cases values"
        " ('champion', 'cured', 60, 40, true, '2026-08-01', 'card'),"
        " ('challenger_A', 'cured', 30, 20, true, '2026-08-02', 'card'),"
        " ('champion', null, 1, 1, false, '2026-09-01', 'card')"  # open: not in the A/B
    )
    return c


def test_wilson_matches_the_textbook_interval() -> None:
    p, lo, hi = wilson(60, 100)
    assert p == 0.6 and round(lo, 4) == 0.5020 and round(hi, 4) == 0.6906
    assert wilson(0, 0) == (0.0, 0.0, 0.0)


def test_overview_counts_slices_ab_and_insights(conn: duckdb.DuckDBPyConnection) -> None:
    p = overview(conn)
    assert (p.cases, p.balance, p.expected, p.actionable, p.red, p.hard_stops) == (3, 1800, 250, 2, 1, 1)
    assert [s.key for s in p.by_bucket] == ["31-60", "61-90"] and p.by_tier[-1].key in ("none", "green")
    champ = next(c for c in p.ab_test if c.test_cell == "champion")
    assert (champ.cases, champ.promises, champ.kept_rate) == (1, 100, 0.6)
    assert {i.id for i in p.insights} == {"ab", "red", "bucket", "stops"} and all(i.sql for i in p.insights)
    assert p.as_of == datetime.fromisoformat("2026-10-14T06:00:00+00:00")
    (cohort,) = p.cohorts
    assert cohort.product == "card" and cohort.kept_rate == 91 / 152  # 60+30+1 kept of 152 promises


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
