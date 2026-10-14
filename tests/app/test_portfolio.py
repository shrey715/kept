"""Portfolio: tonight's cards and the bank's randomised test, summarised; analysts never see a single case."""

from dataclasses import replace
from datetime import datetime

import duckdb
import pytest
from fastapi.testclient import TestClient

from kept.app.api import create_app
from kept.app.demo import demo_services
from kept.app.portfolio import case_page, overview, wilson


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
