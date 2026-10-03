"""Fairness report on the scored cards: who gets which recommendation, by protected attribute.

Reads nba.cards (D's `kept score`) and gold.c360_restricted (A's gold build), from the warehouse or from
exported Parquet files, and writes docs/fairness_report.md. Compliance-only inputs: run it on a machine
that is allowed to read gold.c360_restricted.

    uv run python scripts/fairness_report.py
    uv run python scripts/fairness_report.py --cards cards.parquet --restricted c360_restricted.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

from kept.config import WAREHOUSE_PATH
from kept.contracts.data_contract import load_data_contract
from kept.governance.fairness import fairness_report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", type=Path, default=WAREHOUSE_PATH)
    ap.add_argument("--cards", type=Path, help="nba.cards as Parquet (default: read it from the warehouse)")
    ap.add_argument(
        "--restricted", type=Path, help="gold.c360_restricted as Parquet (default: the warehouse)"
    )
    ap.add_argument("--out", type=Path, default=Path("docs/fairness_report.md"))
    args = ap.parse_args()

    conn = duckdb.connect(str(args.warehouse), read_only=True)
    cards = conn.execute(
        f"select * from read_parquet('{args.cards}')" if args.cards else "select * from nba.cards"
    ).df()
    restricted = conn.execute(
        f"select * from read_parquet('{args.restricted}')"
        if args.restricted
        else "select * from gold.c360_restricted"
    ).df()
    contract = load_data_contract()
    attributes = sorted((contract.protected_attributes | contract.proxy_attributes) & set(restricted.columns))
    report = fairness_report(cards, restricted, attributes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("# Fairness report (Track B)\n\n" + report, encoding="utf-8")
    print(f"{len(cards):,} cards, {len(attributes)} attributes -> {args.out}")


if __name__ == "__main__":
    main()
