"""Insights: every area or point is a group of 50 or more; Kept's out-of-hours count reads the cards' own checks."""

from dataclasses import replace

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from kept.app.api import create_app
from kept.app.demo import demo_services
from kept.app.insights import Insights, calling_hours, collections_map, held_inputs, uplift_landscape

OK = '{"checks":[{"check":"calling_hours","passed":true}]}'
LATE = '{"checks":[{"check":"calling_hours","passed":false}]}'


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    c.execute("create schema nba; create schema silver; create schema gold; create schema features")
    # 60 customers in ON (shown), 10 in PE (under 50: left out)
    c.execute(
        "create table gold.c360_customer as select 'G-' || i as golden_customer_id,"
        " case when i < 60 then 'ON' else 'PE' end as province_code,"
        " case when i < 60 then 'America/Toronto' else 'America/Halifax' end as time_zone,"
        " time '07:00' as permitted_call_start_local, time '21:00' as permitted_call_end_local,"
        " i % 4 <> 0 as sunday_contact_permitted from range(70) t(i)"
    )
    c.execute(
        "create table silver.collections_cases as select 'CS-' || i as case_id, 'K-' || i as coll_customer_ref,"
        " case when i < 60 then 'ON' else 'PE' end as province_code, date '2026-01-01' + i::int as case_open_date,"
        " 1 as entry_dpd, case when i % 2 = 0 then 31 else 0 end as dpd_at_day_30 from range(70) t(i)"
    )
    c.execute(
        "create table silver.contact_history as select 'CS-' || (i % 70) as case_id, 'Sun' as day_of_week,"
        " 8 as contact_hour_local, i % 7 <> 0 as within_permitted_hours_flag from range(140) t(i)"
    )
    c.execute(
        "create table nba.cards as select 'CS-' || i as case_id, 'G-' || i as golden_customer_id,"
        " 100.0 as total_overdue, i % 3 = 0 as hardship, case when i % 5 = 0 then null else 'green' end as tier,"
        " case when i % 5 = 0 then null when i = 1 then 'call' else 'email' end as action,"
        f" case when i = 1 then '{LATE}' else '{OK}' end::json as card, now() as scored_at from range(70) t(i)"
    )
    c.execute(
        "create table gold.identity_crosswalk as select 'G-' || i as golden_customer_id, s as source_system,"
        " case s when 'crm' then 'R-' || i else 'K-' || i end as source_key, null::timestamptz as valid_to"
        " from range(70) t(i), (values ('crm'), ('collections')) v(s)"
    )
    c.execute(
        "create table silver.customers as select 'R-' || i as crm_customer_id,"
        " case when i < 55 then 'M5V' else 'B3H' end as fsa from range(70) t(i)"
    )
    c.execute(
        "create table silver.geo_reference as select * from (values ('M5V', 'ON', 'Toronto', 43.64, -79.39),"
        " ('B3H', 'NS', 'Halifax', 44.64, -63.58)) v(fsa, province_code, city, centroid_lat, centroid_lon)"
    )
    c.execute(
        "create table features.case_features as select 'CS-' || i as case_id, timestamp '2026-10-14 06:00' as as_of,"
        " i * 2 as max_dpd, case when i < 66 then (i % 10) / 10 end as answer_rate, 'biweekly' as pay_frequency"
        " from range(70) t(i)"
    )
    return c


def test_calling_hours_drops_small_provinces_and_counts_cards_outside_hours(conn: duckdb.DuckDBPyConnection) -> None:
    h = calling_hours(conn)
    (on,) = h.provinces
    assert (on.province, on.time_zone, on.start, on.end, on.customers) == ("ON", "America/Toronto", "07:00", "21:00", 60)
    assert on.sunday_share == 45 / 60
    assert h.bank_contacts == 20 and h.cases == 70 and {b.province for b in h.bank} == {"ON"}
    assert (h.kept_cards, h.kept_outside) == (56, 1)  # the one card whose own check failed


def test_map_keeps_only_fsas_of_50_or_more(conn: duckdb.DuckDBPyConnection) -> None:
    m = collections_map(conn)
    (t,) = m.towers
    assert (t.fsa, t.cases, t.overdue, t.city) == ("M5V", 55, 5500.0, "Toronto")
    assert (m.hidden_fsas, m.hidden_cases) == (1, 15)
    assert t.roll_rate is None  # the 12-month roll window holds under 50 cases
    assert t.green + t.amber + t.red + t.none == 55


class FakeModel:
    model_version = "fake"
    _columns = ["max_dpd", "answer_rate", "pay_frequency"]

    def uplift(self, X: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"call": X["answer_rate"].astype(float) - X["max_dpd"].astype(float) / 1000})


def test_uplift_grid_holds_other_inputs_and_groups_tonight(conn: duckdb.DuckDBPyConnection) -> None:
    u = uplift_landscape(conn, FakeModel())
    assert len(u.uplift) == len(u.answer_rate) and len(u.uplift[0]) == len(u.dpd)
    assert u.uplift[-1][0] == 1.0 and u.held == {"pay_frequency": "biweekly"}
    assert u.cases == 66 and all(g.cases >= 50 for g in u.groups)
    assert held_inputs(pd.DataFrame({"a": [1.0, 3.0, None], "b": [None, None, None]})) == {"a": 2.0, "b": None}


def test_routes_are_aggregates_for_analysts_not_agents(conn: duckdb.DuckDBPyConnection) -> None:
    client = TestClient(create_app(replace(demo_services(), insights=Insights(conn))))
    ok = client.get("/insights/calling-hours", params={"user_id": "an-1", "role": "analyst"})
    assert ok.status_code == 200 and ok.json()["kept_outside"] == 1
    assert client.get("/insights/map", params={"user_id": "agent-7", "role": "agent"}).status_code == 403
    assert client.get("/insights/uplift", params={"user_id": "an-1", "role": "analyst"}).status_code == 503
