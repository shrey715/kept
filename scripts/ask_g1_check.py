"""G1 check for Track B: the real contract + the real silver + the SQL guard, on benchmark questions.

No hosted LLM key needed: the dev answers' reference SQL stands in for the LLM's SQL. Each query gets
`silver.` added to its tables, goes through guard_sql with the real policy, runs, and is compared with the
gold answer. Prints one line per question. Usage: uv run python scripts/ask_g1_check.py
"""

from __future__ import annotations

import csv
import io
import sys

import duckdb
import sqlglot
from sqlglot import exp

from kept.ask.service import build_sql_policy
from kept.ask.sql_guard import execute_guarded, guard_sql
from kept.contracts.data_contract import load_data_contract

WAREHOUSE = "data/warehouse/kept.duckdb"
DEV_ANSWERS = "data/benchmark/benchmark_dev_answers.csv"


def qualify(sql: str) -> str:
    """Bare table names -> silver.<table> (the reference SQL was written against the raw release)."""
    tree = sqlglot.parse_one(sql, dialect="duckdb")
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if not t.db and t.name not in ctes:
            t.set("db", exp.to_identifier("silver"))
    return tree.sql(dialect="duckdb")


def same(rows: tuple[tuple, ...], gold: str) -> bool:
    """Gold is CSV text with a header; compare cell by cell, numbers to 0.01."""
    want = list(csv.reader(io.StringIO(gold)))[1:]
    if len(want) != len(rows):
        return False

    def eq(a: object, b: str) -> bool:
        try:
            return abs(float(a) - float(b)) < 0.01  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return str(a) == b

    key = lambda r: tuple(str(c) for c in r)  # noqa: E731
    return all(
        eq(a, b)
        for ra, rb in zip(sorted(rows, key=key), sorted(want, key=key), strict=True)
        for a, b in zip(ra, rb, strict=True)
    )


def main() -> int:
    conn = duckdb.connect(WAREHOUSE, read_only=True)
    policy = build_sql_policy(conn, load_data_contract())
    print(f"allowed tables in the warehouse: {len(policy.table_columns)} of {len(policy.allowed_tables)}")
    bad = 0
    with open(DEV_ANSWERS, encoding="utf-8") as f:
        dev = list(csv.DictReader(f))
    for r in dev:
        if not r["gold_sql_reference"]:
            continue
        g = guard_sql(qualify(r["gold_sql_reference"]), policy)
        if not g.allowed:
            print(f"{r['question_id']}: GUARD REFUSED  {g.reason}")
            bad += 1
            continue
        try:
            _, rows = execute_guarded(conn, g, timeout_s=policy.timeout_s)
        except Exception as e:
            print(f"{r['question_id']}: guard ok, run failed: {type(e).__name__}: {str(e)[:90]}")
            bad += 1
            continue
        ok = same(rows, r["gold_answer"])
        print(
            f"{r['question_id']}: guard ok, {len(rows)} rows, {'matches gold' if ok else 'DIFFERS from gold'}"
        )
        bad += not ok
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
