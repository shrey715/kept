"""`uv run kept <command>`: the nightly pipeline and dev entry points."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from kept.config import EXPORT_DIR, RAW_DIR, WAREHOUSE_PATH

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


def benchmark(args: argparse.Namespace) -> int:
    """Track B: ask every benchmark question, write the answers CSV, score the dev split."""
    import csv

    from dotenv import load_dotenv

    from kept.ask.benchmark import (
        BenchmarkOutcome,
        answer_row,
        apply_gold,
        is_correct,
        load_benchmark,
        run_benchmark,
        score,
        scorecard_markdown,
        write_answers,
    )
    from kept.ask.service import build_ask
    from kept.common.audit import DuckDBAuditLog
    from kept.common.db import connect
    from kept.contracts.ask import AskAnswer
    from kept.contracts.audit import AuditKind

    load_dotenv()
    with open(args.questions, encoding="utf-8", newline="") as f:
        cases = load_benchmark(list(csv.DictReader(f)))
    gold: dict[str, dict[str, str]] = {}
    if args.dev_answers.exists():
        with open(args.dev_answers, encoding="utf-8", newline="") as f:
            gold = {r["question_id"]: r for r in csv.DictReader(f)}
    cases = apply_gold(cases, gold)
    if args.only:
        cases = [c for c in cases if c.question_id in args.only]
    audit = DuckDBAuditLog(os.environ.get("KEPT_AUDIT_LOG_PATH", str(WAREHOUSE_PATH.parent / "audit.duckdb")))
    started = datetime.now(UTC)
    conn = connect(read_only=True)
    try:
        responses = run_benchmark(build_ask(conn, audit), cases)
    finally:
        conn.close()
    write_answers(
        str(args.out), [answer_row(c.question_id, r) for c, r in zip(cases, responses, strict=True)]
    )
    calls = len(audit.read(kind=AuditKind.LLM_CALL, since=started))
    per = calls / max(len(cases), 1)
    print(f"{len(cases)} questions, {calls} LLM calls ({per:.1f} per question) -> {args.out}")
    dev = [(c, r) for c, r in zip(cases, responses, strict=True) if c.question_id in gold]
    if dev:
        outcomes = [
            BenchmarkOutcome(
                c.question_id,
                refused=not isinstance(r, AskAnswer),
                correct=None if c.should_refuse else is_correct(c, gold[c.question_id], r),
            )
            for c, r in dev
        ]
        card = score([c for c, _ in dev], outcomes)
        text = scorecard_markdown([c for c, _ in dev], [r for _, r in dev], gold, card)
        print(text)
        if args.scorecard:
            args.scorecard.write_text(text, encoding="utf-8")
    return 0


def build(args: argparse.Namespace) -> int:
    """Track A: dbt silver (unless --gold-only), load the crosswalk, dbt gold, export c360 parquet."""
    from kept.common.db import connect
    from kept.data.gold import build_gold, export_parquet, run_dbt

    conn = connect()
    warehouse = str(args.warehouse or WAREHOUSE_PATH)
    conn.close()
    if not args.gold_only:
        run_dbt(["silver"], warehouse=warehouse)
    conn = connect()
    build_gold(conn, crosswalk=args.crosswalk)  # closes conn
    conn = connect()  # not read_only: dbt's connection in this process holds the file read-write
    try:
        export_parquet(conn, as_of_date=args.as_of_date)
        row = conn.execute("select count(*) from gold.c360_customer").fetchone()
        print(f"gold.c360_customer: {row[0] if row else 0:,} rows -> {EXPORT_DIR / 'c360_customer'}")
    finally:
        conn.close()
    return 0


def gate(args: argparse.Namespace) -> int:
    """Track A: Q1-Q5 on the warehouse -> data quality report + Soda checks. Exit 1 if the gate blocks."""
    from kept.common.db import connect
    from kept.contracts.data_contract import load_data_contract
    from kept.data.gate import gather_results, write_soda_checks
    from kept.data.quality import Status, quality_report, run_gate

    write_soda_checks()
    conn = connect(read_only=True)
    try:
        results = gather_results(conn)
    finally:
        conn.close()
    report = quality_report(results, contract_version=load_data_contract().version, as_of=datetime.now(UTC))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report)
    print(report)
    return 1 if run_gate(results) is Status.BLOCK else 0


def extract(args: argparse.Namespace) -> int:
    """Track C: notes/calls (or a note typed in now) -> redact -> LLM -> text.extractions."""
    import time

    from kept.text.live import extract_into, read_sources, typed_note, warehouse_path

    path = warehouse_path()
    if args.text is not None:
        if not args.case_id:
            print("kept extract: --text needs --case-id")
            return 2
        sources = [typed_note(args.text, case_id=args.case_id, source_id=args.source_id)]
    else:
        sources = read_sources(
            path, note_ids=args.note_id, transcript_ids=args.transcript_id, new=args.new, limit=args.limit
        )
        missing = set(args.note_id) | set(args.transcript_id)
        missing -= {s.source_id for s in sources}
        for i in sorted(missing):
            print(f"{i}  not found in silver")
    t0, ok, errors = time.perf_counter(), 0, 0
    for r in extract_into(path, sources):
        if r.extraction is None:
            errors += 1
            print(f"{r.source_id}  error: {r.error}  {r.seconds:.1f}s")
            continue
        ok += 1
        x = r.extraction
        promise = "no"
        if x.promise_intent.value:
            promise = " ".join(str(v) for v in ("yes", x.promised_amount.value, x.promised_date.value) if v)
        print(
            f"{r.source_id}  hardship={x.hardship_signal.value.value}  promise={promise}  "
            f"cease-suggested={'yes' if x.cease_request.value else 'no'}  {r.seconds:.1f}s"
        )
    print(f"{ok} extracted, {errors} errors, {time.perf_counter() - t0:.1f}s -> text.extractions in {path}")
    return 1 if errors and not ok else 0


# Each track adds its own handler here when its step works (plan K9).
HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "serve": serve,
    "land": land,
    "match": match,
    "build": build,
    "gate": gate,
    "benchmark": benchmark,
    "extract": extract,
}


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
        if name == "build":
            p.add_argument("--gold-only", action="store_true", help="skip the silver build (about 3 min)")
            p.add_argument("--crosswalk", type=Path, default=None, help="crosswalk parquet (default: newest)")
            p.add_argument("--warehouse", type=Path, default=None)
            p.add_argument("--as-of-date", default="2026-09-28", help="snapshot date of the load")
        if name == "benchmark":
            p.add_argument("--questions", type=Path, default=Path("data/benchmark/benchmark_questions.csv"))
            p.add_argument(
                "--dev-answers", type=Path, default=Path("data/benchmark/benchmark_dev_answers.csv")
            )
            p.add_argument("--out", type=Path, default=Path("data/benchmark/answers.csv"))
            p.add_argument("--scorecard", type=Path, default=None, help="write the dev scorecard (markdown)")
            p.add_argument(
                "--only", nargs="+", default=None, metavar="ID", help="ask only these question ids"
            )
        if name == "gate":
            p.add_argument("--report", type=Path, default=EXPORT_DIR / "quality" / "quality_report.md")
        if name == "extract":
            p.add_argument("--note-id", action="append", default=[], help="silver.agent_notes note_id")
            p.add_argument(
                "--transcript-id", action="append", default=[], help="silver.call_transcripts transcript_id"
            )
            p.add_argument("--new", action="store_true", help="every note with no text.extractions row")
            p.add_argument(
                "--limit", type=int, default=None, help="with --new: at most N notes, newest first"
            )
            p.add_argument("--text", default=None, help="a new note typed in now (not in silver)")
            p.add_argument("--case-id", default=None, help="with --text: the note's case")
            p.add_argument("--source-id", default=None, help="with --text: its id (default N-LIVE-<random>)")
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
