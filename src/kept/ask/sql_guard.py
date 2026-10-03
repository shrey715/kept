"""Step 4: sqlglot AST guard. SELECT only on approved tables; no protected or
personal columns; row limit; timeout. Fail closed: anything we can't parse is refused."""

from __future__ import annotations

import threading
from typing import Any

import duckdb
import sqlglot
from sqlglot import exp

from kept.contracts.ask import GuardResult, SqlPolicy

# Functions that read files, the environment or the catalog. Prefixes and names, lower case.
_FORBIDDEN_FUNCTION_PREFIXES = ("read_", "write_", "pragma_", "duckdb_", "sniff_", "parquet_")
_FORBIDDEN_FUNCTIONS = frozenset({"glob", "query", "query_table", "getenv", "current_setting", "columns"})


def _refuse(reason: str) -> GuardResult:
    return GuardResult(allowed=False, sql=None, reason=reason)


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
    try:
        statements = [t for t in sqlglot.parse(sql, dialect=policy.dialect) if t is not None]
    except sqlglot.errors.SqlglotError as e:
        return _refuse(f"cannot parse the query: {str(e)[:120]}")
    if len(statements) != 1:
        return _refuse("exactly one statement is allowed")
    tree = statements[0]
    if not isinstance(tree, exp.Select | exp.SetOperation) or tree.args.get("into"):
        return _refuse("only SELECT is allowed")

    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables: set[str] = set()
    names_in_scope = set(ctes)  # table names and aliases: a bare one selects the whole row
    for t in tree.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            return _refuse("table functions and file readers are not allowed")
        names_in_scope |= {t.name.lower(), t.alias_or_name.lower()}
        if t.catalog:
            return _refuse(f"table {t.sql()} is not allowed")
        if not t.db:
            if t.name.lower() in ctes:
                continue
            return _refuse(f"table {t.name} must be schema-qualified")
        name = f"{t.db}.{t.name}".lower()
        if name not in policy.allowed_tables:
            return _refuse(f"table {name} is not allowed")
        tables.add(name)

    for f in tree.find_all(exp.Func):
        fn = (f.name if isinstance(f, exp.Anonymous) else f.sql_name()).lower()
        if fn in _FORBIDDEN_FUNCTIONS or fn.startswith(_FORBIDDEN_FUNCTION_PREFIXES):
            return _refuse(f"function {fn} is not allowed")

    # every identifier counts, not only columns: JOIN ... USING (col), quoted names, EXCLUDE (col)
    for ident in tree.find_all(exp.Identifier):
        if ident.name.lower() in policy.blocked_columns:
            return _refuse(f"column {ident.name.lower()} is blocked")
    columns = {c.name.lower() for c in tree.find_all(exp.Column) if not isinstance(c.this, exp.Star)}
    for c in tree.find_all(exp.Column):
        if not c.table and not isinstance(c.this, exp.Star) and c.name.lower() in names_in_scope:
            return _refuse(f"{c.name} selects a whole row, name the columns")

    # ponytail: a star anywhere checks every table in the query, not only the one it expands over
    if any(not isinstance(s.parent, exp.Count) for s in tree.find_all(exp.Star)):
        for name in sorted(tables):
            cols = policy.table_columns.get(name)
            if cols is None:
                return _refuse(f"SELECT * is not allowed on {name}: its columns are not listed")
            if hit := sorted(cols & policy.blocked_columns):
                return _refuse(f"SELECT * would return blocked column {hit[0]} from {name}")

    lim = tree.args.get("limit")
    try:
        existing = int(lim.expression.name) if lim is not None else policy.max_rows
    except ValueError:
        existing = policy.max_rows
    limited = tree.limit(min(existing, policy.max_rows)).sql(dialect=policy.dialect)
    return GuardResult(allowed=True, sql=limited, tables=frozenset(tables), columns=frozenset(columns))


def execute_guarded(
    conn: duckdb.DuckDBPyConnection,
    guarded: GuardResult,
    *,
    params: list[Any] | None = None,
    timeout_s: float,
) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]:
    """Run an allowed GuardResult on a read-only connection. Not allowed -> PermissionError.
    Exceeding timeout_s -> TimeoutError (query interrupted)."""
    if not guarded.allowed or guarded.sql is None:
        raise PermissionError(guarded.reason or "query was not allowed by the guard")
    cur = conn.cursor()  # interrupting the cursor leaves the shared connection alone
    timer = threading.Timer(timeout_s, cur.interrupt)
    timer.start()
    try:
        cur.execute(guarded.sql, params or [])
        return tuple(d[0] for d in cur.description), tuple(tuple(r) for r in cur.fetchall())
    except duckdb.InterruptException as e:
        raise TimeoutError(f"query exceeded {timeout_s}s") from e
    finally:
        timer.cancel()
        cur.close()
