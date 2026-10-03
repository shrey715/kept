"""`uv run kept <command>`: the nightly pipeline and dev entry points."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from kept.config import RAW_DIR

COMMANDS = {
    "land": "Track A: land data/raw into bronze",
    "build": "Track A: dbt build bronze -> silver -> gold",
    "match": "Track A: exact links + Splink on changed rows",
    "gate": "Track A: run the quality gate",
    "features": "Track D: dbt features + feast materialize",
    "parity": "Track A: offline/online parity test",
    "extract": "Track C: text extraction on new notes",
    "train": "Track D: train uplift models, log to MLflow",
    "score": "Track D: score every open case",
    "benchmark": "Track B: run the Ask scorecard",
    "serve": "Track D: run the API",
    "nightly": "Everyone: build -> match -> gate -> features -> parity -> score (by 06:00 ET)",
}


def _land(raw_dir: Path, extracted_at: datetime) -> int:
    from kept.common.db import connect
    from kept.data.ingest import land_directory

    conn = connect()
    try:
        for t in land_directory(conn, raw_dir, extracted_at=extracted_at):
            print(f"{t.table:<40} {t.row_count:>12,}")
    finally:
        conn.close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kept")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in COMMANDS.items():
        p = sub.add_parser(name, help=help_text)
        if name == "land":
            p.add_argument("--raw-dir", type=Path, default=RAW_DIR)
            p.add_argument(
                "--extracted-at",
                type=datetime.fromisoformat,
                default=None,
                help="source extract time, ISO 8601 with offset (default: now, UTC)",
            )
    args = parser.parse_args(argv)
    if args.command == "land":
        return _land(args.raw_dir, args.extracted_at or datetime.now(UTC))
    raise NotImplementedError(f"kept {args.command}: {COMMANDS[args.command]}")


if __name__ == "__main__":
    raise SystemExit(main())
