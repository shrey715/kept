"""SQL guard: SELECT only on approved tables, no protected/personal columns, row limits.
The guard fails closed. Every case here is a way an LLM-written query could go wrong."""

from __future__ import annotations

import re
import time

import duckdb
import pytest

from kept.ask.sql_guard import execute_guarded, guard_sql
from kept.contracts import GuardResult, SqlPolicy


def _limit(sql: str) -> int | None:
    m = re.search(r"\bLIMIT\s+(\d+)\s*;?\s*$", sql, flags=re.IGNORECASE)
    return int(m.group(1)) if m else None


# ----------------------------------------------------------------- allowed
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT case_id, entry_dpd FROM silver.collections_cases",
        "select count(*) as n from SILVER.COLLECTIONS_CASES",
        "SELECT primary_product, avg(dpd_at_day_30) FROM silver.collections_cases GROUP BY primary_product",
        "WITH x AS (SELECT case_id FROM silver.collections_cases) SELECT count(*) FROM x",
        "SELECT c.primary_product, count(*) FROM silver.collections_cases c JOIN silver.promises_to_pay p ON c.case_id = p.case_id GROUP BY 1",
        "SELECT * FROM silver.promises_to_pay",  # star is fine: no blocked column in this table
        "SELECT case_id FROM silver.collections_cases WHERE case_id IN (SELECT case_id FROM silver.promises_to_pay WHERE ptp_status = 'broken')",
        "SELECT golden_customer_id, total_overdue FROM gold.c360_customer",
        "SELECT primary_product FROM silver.collections_cases UNION ALL SELECT ptp_status FROM silver.promises_to_pay",
    ],
)
def test_allowed_queries(policy: SqlPolicy, sql: str) -> None:
    r = guard_sql(sql, policy)
    assert r.allowed, r.reason
    assert r.sql is not None and _limit(r.sql) == policy.max_rows


def test_reports_tables_and_columns(policy: SqlPolicy) -> None:
    r = guard_sql(
        "SELECT c.primary_product, count(*) FROM silver.collections_cases c GROUP BY c.primary_product",
        policy,
    )
    assert r.tables == {"silver.collections_cases"}
    assert "primary_product" in r.columns


# ----------------------------------------------------------------- limits
@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT case_id FROM silver.collections_cases", 100),
        ("SELECT case_id FROM silver.collections_cases LIMIT 5", 5),
        ("SELECT case_id FROM silver.collections_cases LIMIT 100000", 100),
    ],
)
def test_row_limit_applied(policy: SqlPolicy, sql: str, expected: int) -> None:
    r = guard_sql(sql, policy)
    assert r.allowed and _limit(r.sql or "") == expected


# ----------------------------------------------------------------- refused
@pytest.mark.parametrize(
    "sql",
    [
        # writes and DDL
        "DELETE FROM silver.promises_to_pay",
        "UPDATE silver.collections_cases SET entry_dpd = 0",
        "INSERT INTO silver.promises_to_pay VALUES ('C-1', 'kept', 1)",
        "DROP TABLE silver.collections_cases",
        "CREATE TABLE gold.x AS SELECT 1",
        "ALTER TABLE silver.collections_cases ADD COLUMN x INT",
        # engine escape hatches
        "ATTACH 'other.duckdb' AS o",
        "COPY silver.collections_cases TO 'out.csv'",
        "PRAGMA database_list",
        "INSTALL httpfs",
        "LOAD httpfs",
        "SET threads = 1",
        "CALL pragma_version()",
        "SELECT * FROM read_csv('data/raw/crm.csv')",
        "SELECT * FROM read_parquet('data/exports/*.parquet')",
        "SELECT * FROM 'data/raw/crm.csv'",
        "SELECT * FROM glob('*')",
        # multiple statements / smuggling
        "SELECT 1 FROM silver.collections_cases; DROP TABLE silver.collections_cases",
        "SELECT 1 FROM silver.collections_cases; SELECT 2 FROM silver.collections_cases",
        # unapproved and restricted tables, wherever they hide
        "SELECT * FROM gold.c360_restricted",
        "SELECT gender_code FROM gold.c360_restricted",
        "SELECT * FROM silver.collections_cases c JOIN gold.c360_restricted r ON true",
        "WITH r AS (SELECT * FROM gold.c360_restricted) SELECT count(*) FROM r",
        "SELECT case_id FROM silver.collections_cases WHERE case_id IN (SELECT golden_customer_id FROM gold.c360_restricted)",
        "SELECT * FROM silver.customers",  # not an Ask table (raw CRM with PII)
        "SELECT first_name FROM silver.customers",
        "SELECT * FROM bronze.customers",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM duckdb_tables()",
        "SELECT * FROM collections_cases",  # unqualified: ambiguous, refuse
        # blocked columns anywhere
        "SELECT display_name FROM gold.c360_customer",
        "SELECT lower(email) AS e FROM gold.c360_customer",
        "SELECT golden_customer_id FROM gold.c360_customer WHERE primary_phone_e164 LIKE '+1416%'",
        "SELECT count(*) FROM gold.c360_customer GROUP BY display_name",
        "SELECT golden_customer_id FROM gold.c360_customer ORDER BY email",
        "SELECT row_number() OVER (PARTITION BY display_name) FROM gold.c360_customer",
        'SELECT "DISPLAY_NAME" FROM gold.c360_customer',
        "SELECT * FROM gold.c360_customer",  # star over a table with blocked columns
        "SELECT c.* FROM gold.c360_customer c",
        # junk
        "",
        "   ",
        "SELEKT nonsense",
        "-- just a comment",
    ],
)
def test_refused_queries(policy: SqlPolicy, sql: str) -> None:
    r = guard_sql(sql, policy)
    assert not r.allowed
    assert r.sql is None
    assert r.reason


@pytest.mark.parametrize("col", ["marital_status", "ccb_deposit_flag", "salutation", "age", "postal_code"])
def test_protected_and_proxy_columns_refused_even_if_present(policy: SqlPolicy, col: str) -> None:
    r = guard_sql(f"SELECT {col}, count(*) FROM silver.collections_cases GROUP BY 1", policy)
    assert not r.allowed and col in (r.reason or "")


def test_refusal_reason_names_the_blocked_column(policy: SqlPolicy) -> None:
    r = guard_sql("SELECT display_name FROM gold.c360_customer", policy)
    assert "display_name" in (r.reason or "")


def test_comments_cannot_hide_a_second_statement(policy: SqlPolicy) -> None:
    sql = "SELECT case_id FROM silver.collections_cases /* ; */ ; DELETE FROM silver.promises_to_pay -- "
    assert not guard_sql(sql, policy).allowed


def test_guard_is_pure(policy: SqlPolicy) -> None:
    sql = "SELECT case_id FROM silver.collections_cases"
    assert guard_sql(sql, policy) == guard_sql(sql, policy)


# ----------------------------------------------------------------- execution
def test_execute_refuses_unguarded_result(ask_db: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(PermissionError):
        execute_guarded(ask_db, GuardResult(allowed=False, sql=None, reason="x"), timeout_s=1)


def test_execute_returns_columns_and_rows(ask_db: duckdb.DuckDBPyConnection, policy: SqlPolicy) -> None:
    g = guard_sql(
        "SELECT primary_product, count(*) AS n FROM silver.collections_cases GROUP BY primary_product ORDER BY primary_product",
        policy,
    )
    cols, rows = execute_guarded(ask_db, g, timeout_s=5)
    assert cols == ("primary_product", "n")
    assert rows == (("credit_card", 30), ("personal_loan", 30))


def test_execute_times_out(ask_db: duckdb.DuckDBPyConnection) -> None:
    slow = SqlPolicy(
        allowed_tables=frozenset({"silver.collections_cases"}), blocked_columns=frozenset(), max_rows=10
    )
    g = guard_sql(
        "SELECT sum(a.entry_dpd * b.entry_dpd + c.entry_dpd * d.entry_dpd - e.entry_dpd * f.entry_dpd) "
        "FROM silver.collections_cases a, silver.collections_cases b, silver.collections_cases c, "
        "silver.collections_cases d, silver.collections_cases e, silver.collections_cases f",
        slow,
    )
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        execute_guarded(ask_db, g, timeout_s=0.2)
    assert time.monotonic() - start < 5


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT c FROM gold.c360_customer c",  # whole-row struct includes display_name
        "SELECT to_json(c) FROM gold.c360_customer c",
        "SELECT COLUMNS('.*name') FROM gold.c360_customer",  # regex column picker
        "SELECT p.ptp_id FROM silver.promises_to_pay p JOIN gold.c360_customer c USING (display_name)",
        "SELECT * EXCLUDE (ptp_id) FROM silver.customers_unlisted",
        "SELECT getenv('HOME')",
        "SELECT * FROM silver.promises_to_pay p, read_csv('x.csv')",
        "SELECT * INTO t FROM silver.promises_to_pay",
    ],
)
def test_extra_bypasses_refused(policy: SqlPolicy, sql: str) -> None:
    assert not guard_sql(sql, policy).allowed


def test_star_needs_listed_columns(policy: SqlPolicy) -> None:
    """A table whose columns the policy does not list can't be starred, fail closed."""
    bare = SqlPolicy(allowed_tables=policy.allowed_tables, blocked_columns=policy.blocked_columns)
    assert not guard_sql("SELECT * FROM silver.promises_to_pay", bare).allowed
    assert guard_sql("SELECT ptp_id FROM silver.promises_to_pay", bare).allowed
    assert guard_sql("SELECT count(*) FROM silver.promises_to_pay", bare).allowed  # count(*) is not a star
