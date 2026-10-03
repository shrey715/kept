"""`uv run kept <command>`: the nightly pipeline and dev entry points."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from kept.config import EXPORT_DIR, RAW_DIR

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


def serve(args: argparse.Namespace) -> int:
    """Track D. Until the real services are wired (G4), only --demo runs."""
    import uvicorn

    if not args.demo:
        print("kept serve: the real services are wired at G4; use `kept serve --demo` until then.")
        return 2
    if args.reload:  # restarts on any change under src/ (demo state resets with it)
        src = Path(__file__).resolve().parents[1]
        uvicorn.run(
            "kept.app.demo:demo_app",
            factory=True,
            reload=True,
            reload_dirs=[str(src)],
            host=args.host,
            port=args.port,
        )
        return 0
    from kept.app.demo import demo_app

    uvicorn.run(demo_app(), host=args.host, port=args.port)
    return 0


def land(args: argparse.Namespace) -> int:
    """Track A: land data/raw into bronze."""
    from kept.common.db import connect
    from kept.data.ingest import land_directory

    conn = connect()
    try:
        extracted_at = args.extracted_at or datetime.now(UTC)
        for t in land_directory(conn, args.raw_dir, extracted_at=extracted_at):
            print(f"{t.table:<40} {t.row_count:>12,}")
    finally:
        conn.close()
    return 0


def match(args: argparse.Namespace) -> int:
    """Track A: exact links + Splink on silver -> clusters -> golden IDs; writes parquet files."""
    import subprocess

    import pandas as pd

    from kept.common.db import connect
    from kept.data.identity.pipeline import run_matching, write_run

    conn = connect(read_only=True)
    try:
        previous = pd.read_parquet(args.previous) if args.previous else None
        run = run_matching(
            conn, sample_mod=args.sample_mod, train_sample_mod=args.train_sample_mod, previous=previous
        )
    finally:
        conn.close()
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    scope = f"sample{args.sample_mod}" if args.sample_mod else "full"
    scope += f"-train{args.train_sample_mod}" if args.train_sample_mod else ""
    tag = f"{commit or 'nogit'}-{datetime.now(UTC):%Y%m%d}-{scope}"
    for path in write_run(run, args.out_dir, tag=tag):
        print(path)
    print({k: v for k, v in run.summary.items() if k != "splink_settings"})
    return 0


# Each track adds its own handler here when its step works (plan K9).
HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {"serve": serve, "land": land, "match": match}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kept")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in COMMANDS.items():
        p = sub.add_parser(name, help=help_text)
        if name == "serve":
            p.add_argument(
                "--demo", action="store_true", help="twelve in-memory demo cases, no warehouse needed"
            )
            p.add_argument("--host", default="127.0.0.1")
            p.add_argument("--port", type=int, default=8000)
            p.add_argument("--reload", action="store_true", help="restart when code under src/ changes")
        if name == "land":
            p.add_argument("--raw-dir", type=Path, default=RAW_DIR)
            p.add_argument(
                "--extracted-at",
                type=datetime.fromisoformat,
                default=None,
                help="source extract time, ISO 8601 with offset (default: now, UTC)",
            )
        if name == "match":
            p.add_argument(
                "--sample-mod", type=int, default=None, help="tune on 1/N of the records (hash of DOB)"
            )
            p.add_argument(
                "--train-sample-mod",
                type=int,
                default=None,
                help="train Splink on 1/N of the records (hash of DOB), score all of them",
            )
            p.add_argument("--out-dir", type=Path, default=EXPORT_DIR / "identity_crosswalk")
            p.add_argument(
                "--previous", type=Path, default=None, help="earlier crosswalk parquet: keep its golden IDs"
            )
    args = parser.parse_args(argv)
    handler = HANDLERS.get(args.command)
    if handler is None:
        raise NotImplementedError(f"kept {args.command}: {COMMANDS[args.command]}")
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
