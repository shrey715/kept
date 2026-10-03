"""Step 4: sqlglot AST guard. SELECT only on approved tables; no protected or
personal columns; row limit; timeout. Fail closed: anything we can't parse is refused."""

from __future__ import annotations

from typing import Any

import duckdb

from kept.contracts.ask import GuardResult, SqlPolicy


def guard_sql(sql: str, policy: SqlPolicy) -> GuardResult:
    """Allowed only if ALL hold:
      * exactly one statement, and it is a SELECT (CTEs/UNION/subqueries allowed);
      * every table referenced anywhere (incl. CTE bodies, subqueries, joins) is in
        policy.allowed_tables; CTE names don't count as tables;
      * no table functions or file readers (read_csv, read_parquet, glob, httpfs ...);
      * no column in policy.blocked_columns is referenced anywhere (SELECT, WHERE,
        GROUP BY, ORDER BY, JOIN ON, window), and no SELECT * / t.* over a table that
        has a blocked column;
      * no PRAGMA/ATTACH/COPY/INSTALL/LOAD/SET/CALL.
    When allowed, the returned sql has LIMIT min(existing, policy.max_rows), or
    LIMIT policy.max_rows if none. Comparisons are case-insensitive.
    """
    raise NotImplementedError("Track B")


def execute_guarded(
    conn: duckdb.DuckDBPyConnection,
    guarded: GuardResult,
    *,
    params: list[Any] | None = None,
    timeout_s: float,
) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]:
    """Run an allowed GuardResult on a read-only connection. Not allowed -> PermissionError.
    Exceeding timeout_s -> TimeoutError (query interrupted)."""
    raise NotImplementedError("Track B")
