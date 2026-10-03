"""G2 joint check (Q6, A + C): does gold hardship_status reflect Track C's inputs?

    uv run python scripts/g2_hardship_check.py

Run after A loads the extractions (`kept build --extractions ...`) and rebuilds gold with the
cash-flow branch. Read-only. Prints the gold hardship_status distribution and checks:
  1. every open case with a text hardship signal on its notes/calls has gold status >= possible;
  2. every golden customer with a cash-flow observation has gold status >= possible;
  3. cease from text never reaches gold unless an agent confirmed it.
Exit code 1 if a check fails.
"""

from __future__ import annotations

import sys

import duckdb

from kept.config import WAREHOUSE_PATH

CHECKS = {
    "text hardship reaches gold": """
        select count(*) from (
            select distinct oc.golden_customer_id
            from text.extractions e
            join silver.int_open_case oc on oc.open_case_id = e.case_id
            where e.hardship_signal_value <> 'none'
        ) t
        join gold.c360_customer g using (golden_customer_id)
        where g.hardship_status = 'none'""",
    "cash-flow hardship reaches gold": """
        select count(*) from hardship.cashflow_observations o
        join gold.c360_customer g using (golden_customer_id)
        where g.hardship_status = 'none'""",
    "unconfirmed text cease never a hard stop": """
        select count(*) from text.text_signals where cease_request_flag and confirmed_by_agent_id is null""",
}


def main() -> int:
    c = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    print(
        "gold hardship_status:",
        c.execute(
            "select hardship_status, count(*) from gold.c360_customer group by 1 order by 1"
        ).fetchall(),
    )
    print(
        "text.extractions:",
        c.execute(
            "select count(*), count(*) filter (where hardship_signal_value <> 'none') from text.extractions"
        ).fetchone(),
        "| cash-flow observations:",
        c.execute("select count(*) from hardship.cashflow_observations").fetchone()[0],
    )  # type: ignore[index]
    failed = 0
    for name, sql in CHECKS.items():
        bad = c.execute(sql).fetchone()[0]  # type: ignore[index]
        failed += bad > 0
        print(f"{'PASS' if bad == 0 else 'FAIL'}  {name}  ({bad} violations)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
