"""Certified metric SQL: every query compiles and parses. (Numbers were checked by hand against the
release's dev gold answers on the real tables; those tables are not in the repo.)"""

from __future__ import annotations

from datetime import date

import pytest

from kept.ask.certified import CERTIFIED_QUERIES
from kept.ask.metrics import MetricDefinition, compile_metric
from kept.contracts import Intent, IntentKind, SqlPolicy

pytestmark = pytest.mark.track_b

DEFS = {
    m: MetricDefinition(m, m, "", "", "", "", "", "", "", (), (), "", "", True) for m in CERTIFIED_QUERIES
}


def _compile(metric_id: str, **kw: object) -> tuple[str, list[object]]:
    return compile_metric(
        Intent(kind=IntentKind.METRIC, metric_id=metric_id, confidence=0.9, **kw), DEFS, CERTIFIED_QUERIES
    )  # type: ignore[arg-type]


@pytest.mark.parametrize("metric_id", sorted(CERTIFIED_QUERIES))
def test_compiles_and_parses_with_every_filter_group_and_date(metric_id: str) -> None:
    sqlglot = pytest.importorskip("sqlglot")
    q = CERTIFIED_QUERIES[metric_id]
    filters = {c: "x" for c in sorted(q.allowed_filters)}
    group_by = tuple(sorted(q.allowed_group_by))
    dates = {"date_from": date(2026, 1, 1), "date_to": date(2026, 6, 30)} if q.date_column else {}
    sql, params = _compile(metric_id, filters=filters, group_by=group_by, **dates)
    assert "{" not in sql and sql.count("?") == len(params)
    sqlglot.parse_one(sql, dialect="duckdb")


def test_no_certified_query_for_write_off_rate() -> None:
    assert "write_off_rate" not in CERTIFIED_QUERIES


_ASK_TABLES = frozenset(
    f"silver.{t}"
    for t in (
        "collections_cases",
        "promises_to_pay",
        "agents",
        "contact_history",
        "account_monthly_snapshot",
        "card_accounts",
        "loan_accounts",
        "deposit_accounts",
    )
)


@pytest.mark.parametrize("metric_id", sorted(CERTIFIED_QUERIES))
def test_certified_sql_passes_the_guard_on_the_ask_table_list(metric_id: str) -> None:
    """The service sends compiled metric SQL through guard_sql too: it must be allowed."""
    pytest.importorskip("sqlglot")  # Track B's `ask` extra; CI installs core only
    from kept.ask.sql_guard import guard_sql

    policy = SqlPolicy(
        allowed_tables=_ASK_TABLES, blocked_columns=frozenset({"gender_code", "age", "postal_code"})
    )
    sql, _ = _compile(metric_id)
    g = guard_sql(sql, policy)
    assert g.allowed, g.reason
