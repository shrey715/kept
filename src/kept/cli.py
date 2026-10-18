"""`uv run kept <command>`: the nightly pipeline and dev entry points."""

from __future__ import annotations

import argparse
import os
import shutil
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
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
    "train-promises": "Track D: P(kept | promise) model for the card's promise line (#79)",
    "train-best-hour": "Track D: P(right-party contact | hour, weekday, case inputs) for --best-hour booking",
    "score": "Track D: score every open case",
    "invariance": "Governance: scramble protected attributes on a warehouse copy; exit 1 if any card moves",
    "benchmark": "Track B: run the Ask scorecard",
    "serve": "Track D: run the API",
    "nightly": "Everyone: land -> silver -> match -> gold -> gate -> extract -> features -> parity -> score",
    "map": "Track A: schema drift of data/raw against the data dictionary; --draft: LLM mapping drafts",
    "drift": "Track D: feature drift (PSI) against training (PDF: scripts/drift_report.py)",
    "demo-reset": "Demo: delete notes typed during demos, so cards go back to their scored state",
    "preflight": "Demo: go/no-go check (API, warehouse lock, fresh features, the local models, web)",
    "audit-verify": "Governance: re-walk the audit log's hash chain and name the first altered event",
}


def serve(args: argparse.Namespace) -> int:
    """Track D. --demo: twelve in-memory cases. Otherwise the real services (kept.app.real) over
    the built warehouse, Feast and the trained model."""
    import uvicorn

    if not args.demo:
        from dotenv import load_dotenv

        from kept.app.api import create_app
        from kept.app.real import real_services

        load_dotenv()
        uvicorn.run(create_app(real_services()), host=args.host, port=args.port)
        return 0
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

    conn = connect(args.warehouse or WAREHOUSE_PATH)
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
    from kept.data.identity.pipeline import latest_crosswalk, run_matching, write_run

    conn = connect(args.warehouse or WAREHOUSE_PATH, read_only=True)
    try:
        previous_file = args.previous
        if previous_file is None and not args.no_previous and not args.sample_mod:
            # keep golden IDs from night to night: the newest full crosswalk is the previous one
            try:
                previous_file = latest_crosswalk(args.out_dir)
                print(f"keeping the golden IDs of {previous_file.name}")
            except FileNotFoundError:
                previous_file = None
        previous = pd.read_parquet(previous_file) if previous_file else None
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
    args.out.parent.mkdir(parents=True, exist_ok=True)
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
    """Track A: dbt silver (unless --gold-only), then (unless --silver-only) load the crosswalk, dbt gold,
    export c360 parquet. The nightly order is silver, `kept match`, gold: gold needs the crosswalk."""
    from kept.common.db import connect
    from kept.data.gold import GOLD_MODELS, build_gold, export_parquet, run_dbt

    warehouse = args.warehouse or WAREHOUSE_PATH
    connect(warehouse).close()  # creates the file and the schemas on a fresh warehouse
    if not args.gold_only:
        # the models gold is built from need the crosswalk: they wait for gold
        run_dbt(["silver"], warehouse=str(warehouse), exclude=GOLD_MODELS)
    if args.silver_only:
        print("silver built; run `kept match`, then `kept build --gold-only`")
        return 0
    conn = connect(warehouse)
    try:
        build_gold(conn, crosswalk=args.crosswalk, extractions=args.extractions)  # closes conn
    except FileNotFoundError as e:
        print(f"kept build: {e}")
        return 2
    conn = connect(warehouse)  # not read_only: dbt's connection in this process holds the file read-write
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
    conn = connect(args.warehouse or WAREHOUSE_PATH, read_only=True)
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
    if args.load_redacted is not None:
        from kept.text.store import load_redacted_notes

        files = (
            [args.load_redacted]
            if args.load_redacted
            else sorted((EXPORT_DIR / "redacted_notes").glob("*.parquet"))
        )
        if not files:
            print(f"kept extract: no redacted_notes parquet in {EXPORT_DIR / 'redacted_notes'}")
            return 2
        print(f"text.redacted_notes: {load_redacted_notes(files[-1], path):,} rows from {files[-1]}")
        return 0
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


def _last_nightly() -> datetime:
    """The latest 06:00 UTC at or before now, naive UTC (the features' as_of convention)."""
    now = datetime.now(UTC).replace(tzinfo=None)
    run = now.replace(hour=6, minute=0, second=0, microsecond=0)
    return run if run <= now else run - timedelta(days=1)


def _drift_alarm(previous: Path, served: Path) -> None:
    """#86: tonight's model inputs against last night's -> drift_alarm.json next to the export.
    While it names a feature, the engine sends every Green card to a person (Amber)."""
    import json

    import pandas as pd

    from kept.contracts.feature_registry import model_inputs
    from kept.features.drift import ALARM_FILE, night_over_night

    if not previous.exists():
        alarm: dict[str, object] = {"previous_as_of": None, "drifted": [], "psi": {}}
    else:
        alarm = night_over_night(pd.read_parquet(previous), pd.read_parquet(served), list(model_inputs()))
    served.with_name(ALARM_FILE).write_text(json.dumps(alarm, indent=1))
    drifted = [str(f) for f in alarm["drifted"]]  # type: ignore[attr-defined]
    if drifted:
        print(f"kept features: DRIFT since last night in {', '.join(drifted)}: Green cards go to review")


def features(args: argparse.Namespace) -> int:
    """Track D: dbt feature models, then the Feast export + apply + materialize.
    --training builds the per-decision spine into features_train instead (for `kept train`)."""
    import json
    import subprocess
    import sys

    import duckdb
    from dbt.cli.main import dbtRunner

    from kept.data.gold import DBT_DIR
    from kept.features.store import export_features

    os.environ["KEPT_WAREHOUSE_PATH"] = str(WAREHOUSE_PATH)
    dbt_vars: dict[str, object] = {"features_as_of": str(args.as_of)}
    if args.training:
        dbt_vars = {"training_spine": True}
    res = dbtRunner().invoke(
        ["build", "--select", "text_signals", "path:models/features", "--threads", "1",
         "--vars", json.dumps(dbt_vars), "--profiles-dir", str(DBT_DIR), "--project-dir", str(DBT_DIR)]
    )  # fmt: skip
    if not res.success:
        print(f"kept features: dbt build failed: {res.exception or 'see the dbt log above'}")
        return 1
    if args.training:
        return 0
    served = EXPORT_DIR / "features" / "case_features.parquet"
    previous = served.with_name("case_features_prev.parquet")
    if served.exists():  # last night's, for the drift alarm; a copy, so a failed export keeps it served
        shutil.copy2(served, previous)
    conn = duckdb.connect(str(WAREHOUSE_PATH))  # not read_only: dbt's connection in this process is open
    try:
        n = export_features(conn, served)
    finally:
        conn.close()
    _drift_alarm(previous, served)
    feast = [str(Path(sys.executable).parent / "feast")]
    repo = Path(__file__).resolve().parents[2] / "feature_repo"
    start, end = args.as_of - timedelta(days=1), args.as_of + timedelta(seconds=1)
    subprocess.run([*feast, "apply"], cwd=repo, check=True)
    subprocess.run([*feast, "materialize", start.isoformat(), end.isoformat()], cwd=repo, check=True)
    print(f"{n:,} cases -> Feast online store (as_of {args.as_of})")
    return 0


def score(args: argparse.Namespace) -> int:
    """Track D: a card for every open case (G3) -> nba.cards; audit events in one write."""
    import time

    from dotenv import load_dotenv

    from kept.common.audit import DuckDBAuditLog
    from kept.nba.score import score as score_all

    load_dotenv()  # KEPT_HOLDOUT_SALT, KEPT_AUDIT_LOG_PATH
    t0 = time.perf_counter()
    audit = DuckDBAuditLog(os.environ.get("KEPT_AUDIT_LOG_PATH", str(WAREHOUSE_PATH.parent / "audit.duckdb")))
    cards = score_all(
        WAREHOUSE_PATH,
        model=args.model,
        holdout_salt=os.environ["KEPT_HOLDOUT_SALT"],
        now=args.now or datetime.now(UTC),
        audit_log=audit,
        best_hour=args.best_hour,
    )
    took = time.perf_counter() - t0
    print(f"{len(cards):,} cards -> nba.cards in {took:.0f}s")
    print(cards.groupby(cards.tier.fillna("no action"), dropna=False).size().to_string())
    return 0


# The nightly run, in order (A's order for land..gate, docs/team/tracks/Track_A.md). Each step is its own
# `kept` process, so its memory is freed before the next (land peaks at 7 GB), and the run stops at
# the first failure: a blocked quality gate must not publish features or cards.
NIGHTLY = (
    ("land", ["land"]),
    ("silver", ["build", "--silver-only"]),
    # train Splink on a 1-in-5 DOB-hash sample, score every key (as the crosswalk in use was built):
    # training on all 3.84M keys ran out of RAM on a 30 GB machine
    ("match", ["match", "--train-sample-mod", "5"]),
    ("gold", ["build", "--gold-only"]),
    ("gate", ["gate"]),
    ("extract", ["extract", "--new"]),  # C: tonight's notes -> text.extractions
    ("features", ["features"]),  # rebuilds text_signals, then features, Feast
    ("parity", ["parity"]),
    # the call booking's model (`kept score` uses it when it exists): retrained when missing or a week old
    ("train-best-hour", ["train-best-hour", "--if-older-than", "7"]),
    ("score", ["score"]),
    ("invariance", ["invariance"]),  # 0 of tonight's cards may change when protected attributes are scrambled
)


def nightly(
    args: argparse.Namespace, run: Callable[[list[str]], int] | None = None, exports: Path = EXPORT_DIR
) -> int:
    """Everyone's steps in order (S6). --from STEP resumes; --skip STEP (repeatable) leaves one out,
    e.g. `--skip extract` on a machine without C's model. Exit code = the failing step's.
    After each step it rewrites reports/nightly_run.json (#114): each step's start, seconds and exit
    code, plus the gate result, parity mismatch rate and drift alarm those steps wrote."""
    import subprocess
    import sys
    import time

    exe = str(Path(sys.executable).parent / "kept")
    run = run or (lambda argv: subprocess.run([exe, *argv]).returncode)
    names = [n for n, _ in NIGHTLY]
    if args.start and args.start not in names:
        print(f"kept nightly: unknown step {args.start}; steps: {', '.join(names)}")
        return 2
    steps = NIGHTLY[names.index(args.start) :] if args.start else NIGHTLY
    done: list[dict[str, object]] = []
    beat: dict[str, object] = {
        "started": datetime.now(UTC).isoformat(),
        "finished": None,
        "exit": None,  # None while the run is going
        "planned": [n for n, _ in steps if n not in args.skip],
        "steps": done,
        "gate": None,
        "parity": None,
        "drift_alarm": None,
    }
    for name, argv in steps:
        if name in args.skip:
            print(f"== {name}: skipped")
            continue
        print(f"== {name}: kept {' '.join(argv)}", flush=True)
        start, t0 = datetime.now(UTC), time.perf_counter()
        code = run(argv)
        took = time.perf_counter() - t0
        print(f"== {name}: exit {code} in {took:.0f}s", flush=True)
        done.append({"name": name, "start": start.isoformat(), "seconds": round(took, 1), "exit": code})
        _badges(beat, name, code, exports)
        if code != 0:
            print(f"kept nightly: stopped at {name}; nothing after it ran (resume with --from {name})")
            return _heartbeat(beat, code, exports)
        _heartbeat(beat, None, exports)
    return _heartbeat(beat, 0, exports)


def _badges(beat: dict[str, object], name: str, code: int, exports: Path) -> None:
    """The heartbeat's badges, from what the gate, parity and features steps already wrote."""
    import re

    from kept.features.drift import load_alarm

    if name == "gate":
        beat["gate"] = "pass" if code == 0 else "block"
    elif name == "parity":
        report = exports / "quality" / "parity_report.md"
        m = re.search(r"cells differ \(([\d.]+)%", report.read_text()) if report.exists() else None
        beat["parity"] = {"passed": code == 0, "mismatch_rate": float(m[1]) / 100 if m else None}
    elif name == "features" and code == 0:
        beat["drift_alarm"] = load_alarm(exports / "features")  # model inputs that moved since last night


def _heartbeat(beat: dict[str, object], code: int | None, exports: Path) -> int:
    """Write the run so far, whole, then swap it in: the API never reads half a file. Returns code."""
    import json

    if code is not None:
        beat["finished"], beat["exit"] = datetime.now(UTC).isoformat(), code
    out = exports / "reports" / "nightly_run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(beat, indent=1))
    tmp.replace(out)
    return code or 0


def invariance(args: argparse.Namespace) -> int:
    """#92: scripts/invariance_test.py on copies of tonight's warehouse (two rebuilds and two scorings, side
    by side). Writes data/exports/reports/invariance_protected.json; the fairness card shows it."""
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[2] / "scripts" / "invariance_test.py"
    return subprocess.run([sys.executable, str(script), "protected"]).returncode


def train_promises(args: argparse.Namespace) -> int:
    """#79: P(kept | promise) on resolved promises, time split; explains sized promises on the card."""
    import duckdb

    from kept.nba import promise_model as pm

    with duckdb.connect(str(WAREHOUSE_PATH), read_only=True) as conn:
        conn.execute("set memory_limit = '3GB'; set threads = 2")
        rows = pm.load(conn)
    model, metrics = pm.train(rows)
    pm.save(model, args.out)
    for k, v in metrics.items():
        print(f"{k:>22}  {v:.4f}")
    print(f"model -> {args.out}")
    return 0


def train_best_hour(args: argparse.Namespace) -> int:
    """P(right-party contact | local hour, weekday, case inputs): behind `kept score --best-hour`."""
    import time

    import duckdb

    from kept.nba import best_hour as bh

    if args.if_older_than is not None and args.out.exists():
        age = (time.time() - args.out.stat().st_mtime) / 86400
        if age < args.if_older_than:
            print(f"{args.out} is {age:.1f} days old (limit {args.if_older_than:g}): not retraining")
            return 0
    with duckdb.connect(str(WAREHOUSE_PATH), read_only=True) as conn:
        conn.execute("set memory_limit = '3GB'; set threads = 2")
        rows = bh.load(conn)
    model, metrics = bh.train(rows, cutoff=args.cutoff)
    bh.save(model, args.out)
    for k, v in metrics.items():
        print(f"{k:>22}  {v:.4f}")
    print(f"model -> {args.out}")
    return 0


def train(args: argparse.Namespace) -> int:
    """Track D: fit the uplift model on features_train (see kept.nba.train), log to MLflow."""
    import json

    import duckdb
    from dotenv import load_dotenv

    from kept.nba.train import run

    load_dotenv()  # MLFLOW_TRACKING_URI
    conn = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    conn.execute("set memory_limit = '3GB'; set threads = 2")  # 14 GB laptops
    try:
        result = run(
            conn,
            cutoff=args.cutoff,
            out=args.out,
            seed=args.seed,
            force=args.promote,
            pooled=args.pool_nudges,
            champion=args.champion,
            seeds=args.seeds,
            policy=not args.no_policy_value,
        )
    finally:
        conn.close()
    for k, v in result.items():
        print(f"{k:>24}  {v:.4f}" if isinstance(v, float) else f"{k:>24}  {v}")
    report = EXPORT_DIR / "reports" / "train_gate.json"  # the gate's numbers, for reports and the deck
    report.parent.mkdir(parents=True, exist_ok=True)
    meta = {"cutoff": args.cutoff.isoformat(), "out": str(args.out)}
    report.write_text(json.dumps({**result, **meta}, indent=1))
    held = args.champion or args.out
    print(f"model -> {args.out}" if result["promoted"] else f"champion kept at {held}")
    return 0


def parity(args: argparse.Namespace) -> int:
    """Track A: offline features (warehouse) against the online store (Feast). Exit 1 if parity fails."""
    from kept.common.db import connect
    from kept.config import PARITY_MAX_MISMATCH_RATE
    from kept.features.parity import _COLUMNS as FEATURES_COLUMNS
    from kept.features.parity import parity_markdown, run_parity
    from kept.features.store import FeastFeatureProvider

    repo = Path(__file__).resolve().parents[2] / "feature_repo"
    conn = connect(read_only=True)
    try:
        report = run_parity(
            conn, FeastFeatureProvider(repo), sample=None if args.all else args.sample, seed=args.seed
        )
    finally:
        conn.close()
    out = EXPORT_DIR / "quality" / "parity_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    cases = report.n_cells // (len(FEATURES_COLUMNS) - 1)  # the key is not a cell if report.n_cells else 0
    out.write_text(
        parity_markdown(
            report,
            cases=cases,
            as_of=str(args.as_of),
            generated=datetime.now(UTC).isoformat(timespec="minutes"),
        )
    )
    worst = ", ".join(f"{f}: {n}" for f, n in report.worst_features[:5]) or "none"
    print(
        f"parity {'PASS' if report.passed else 'FAIL'}: {report.n_mismatched:,} of {report.n_cells:,} cells "
        f"differ ({report.mismatch_rate:.4%}, limit {PARITY_MAX_MISMATCH_RATE:.1%}); worst: {worst}; "
        f"missing online: {len(report.missing_entities)}"
    )
    return 0 if report.passed else 1


# Each track adds its own handler here when its step works (plan K9).
def map_(args: argparse.Namespace) -> int:
    """Track A. Compare the columns each raw table arrived with to the data dictionary (schema drift). With
    --draft the local LLM proposes which dictionary column each new column feeds, from column names and
    types only, as a dbt select for an engineer to review. Exit 1 when anything drifted."""
    import os

    from kept.config import DATA_DIR, REPO_ROOT
    from kept.data.mapping_assistant import dictionary_columns, draft_mapping, raw_columns, schema_drift

    expected = dictionary_columns(REPO_ROOT / "docs" / "brief" / "CIBC Hackathon - Data Dictionary.xlsx")
    drifts = schema_drift(expected, raw_columns(DATA_DIR / "raw", sorted(expected)))
    if not drifts:
        print("kept map: every raw table matches the data dictionary")
        return 0
    llm = redactor = None
    if args.draft:
        from kept.common.audit import DuckDBAuditLog
        from kept.common.llm import LiteLLMGateway
        from kept.config import WAREHOUSE_PATH
        from kept.text.redact import PresidioRedactor

        audit = os.environ.get("KEPT_AUDIT_LOG_PATH", str(WAREHOUSE_PATH.parent / "audit.duckdb"))
        llm = LiteLLMGateway(
            model=os.environ.get("KEPT_TEXT_LLM_MODEL", "llamacpp/qwen3.8-27b"),
            audit_log=DuckDBAuditLog(audit),
            timeout_s=120,
        )
        redactor = PresidioRedactor()
    for d in drifts:
        print(f"\n{d.table}: new {list(d.new) or '-'}; missing {list(d.missing) or '-'}")
        if llm is not None and redactor is not None and d.new:
            targets = list(d.missing) or expected[d.table]
            try:
                draft = draft_mapping(d.table, d.new, d.table, targets, llm=llm, redactor=redactor)
            except ValueError as e:  # an invented column or a bad reply: nothing is drafted
                print(f"  no draft: {e}")
                continue
            print(f"  draft (for an engineer to review): {draft.rationale}")
            print(
                "  "
                + (
                    draft.sql().replace("\n", "\n  ")
                    if draft.column_map
                    else "no column maps to the dictionary"
                )
            )
    return 1


def drift(args: argparse.Namespace) -> int:
    """Feature drift report: PSI per registered feature, training rows against tonight's served features.
    Reads the warehouse, so run it with `kept serve` stopped. Exit 1 if any feature drifted."""
    import duckdb
    import pandas as pd

    from kept.config import EXPORT_DIR, REPO_ROOT, WAREHOUSE_PATH
    from kept.contracts.feature_registry import FEATURES
    from kept.features.drift import drift_report, to_markdown

    live = pd.read_parquet(EXPORT_DIR / "features" / "case_features.parquet")
    with duckdb.connect(str(WAREHOUSE_PATH), read_only=True) as con:
        train = con.execute("select * from features_train.case_features").df()
    rows = drift_report(train, live, [f.name for f in FEATURES])
    out = REPO_ROOT / "data" / "exports" / "reports" / "drift_report.md"  # the PDF: scripts/drift_report.py
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        to_markdown(rows, train_rows=len(train), live_rows=len(live), live_as_of=str(live["as_of"].max()))
    )
    print(f"kept drift: {out} ({sum(r.status == 'drift' for r in rows)} drifted of {len(rows)})")
    return 1 if any(r.status == "drift" for r in rows) else 0


LIVE_NOTE = "N-LIVE-%"  # source_id of a note typed into kept serve (kept.text.live.typed_note)


def reset_demo_notes(warehouse: Path | str, case_id: str | None = None) -> int:
    """Delete the extractions of notes typed during demos (and only those), so each card goes back to
    what the nightly data says. The note text itself only lived in kept serve's memory. Returns the count."""
    import duckdb

    where, params = "source_id like ?", [LIVE_NOTE]
    if case_id:
        where, params = where + " and case_id = ?", [*params, case_id]
    with duckdb.connect(str(warehouse)) as c:
        if not c.execute(
            "select count(*) from duckdb_tables() where schema_name = 'text' and table_name = 'extractions'"
        ).fetchone()[0]:  # type: ignore[index]
            return 0
        n = c.execute(f"select count(*) from text.extractions where {where}", params).fetchone()[0]  # type: ignore[index]
        c.execute(f"delete from text.extractions where {where}", params)
    return int(n)


def demo_reset(args: argparse.Namespace) -> int:
    """Demo notes off every card (or one with --case). kept serve must be stopped: DuckDB has one writer."""
    import duckdb

    try:
        n = reset_demo_notes(WAREHOUSE_PATH, args.case)
    except duckdb.IOException as e:
        print(f"kept demo-reset: the warehouse is in use (stop kept serve first): {str(e).splitlines()[0]}")
        return 1
    where = f" on {args.case}" if args.case else ""
    print(f"kept demo-reset: removed {n} demo note(s){where}; restart kept serve")
    return 0


def preflight(args: argparse.Namespace) -> int:
    """Everything a live demo needs, checked in about a minute. Exit 1 if anything fails."""
    import json
    import urllib.request

    import pandas as pd
    from dotenv import load_dotenv

    from kept.common.audit import DuckDBAuditLog
    from kept.common.llm import LiteLLMGateway, Purpose
    from kept.config import FEATURE_MAX_STALENESS
    from kept.text.live import DEFAULT_MODEL
    from kept.text.redact import fixed_text

    load_dotenv()
    checks: list[tuple[str, bool, str]] = []

    def get(url: str) -> str | None:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return str(r.read().decode())
        except Exception:
            return None

    health = get(f"{args.api}/health")
    checks.append(
        ("API", health is not None, json.loads(health)["now"] if health else f"nothing on {args.api}")
    )
    if health is None:  # nothing serving: is a stale process holding the warehouse?
        import duckdb

        try:
            duckdb.connect(str(WAREHOUSE_PATH), read_only=True).close()
            checks.append(("warehouse lock", True, "free"))
        except duckdb.IOException as e:
            checks.append(("warehouse lock", False, str(e).splitlines()[0][-120:]))
    served = EXPORT_DIR / "features" / "case_features.parquet"
    if served.exists():
        as_of = pd.read_parquet(served, columns=["as_of"])["as_of"].max()
        as_of = as_of.tz_localize("UTC") if as_of.tzinfo is None else as_of
        age = datetime.now(UTC) - as_of.to_pydatetime()
        checks.append(
            (
                "features fresh",
                age < FEATURE_MAX_STALENESS,
                f"as of {as_of:%d %b %H:%M} UTC, {age.total_seconds() / 3600:.0f} h old (fix: kept features)",
            )
        )
    else:
        checks.append(("features fresh", False, f"no {served}"))
    audit = DuckDBAuditLog(os.environ.get("KEPT_AUDIT_LOG_PATH", str(WAREHOUSE_PATH.parent / "audit.duckdb")))
    for label, model in (
        ("Ask LLM", os.environ.get("KEPT_ASK_LLM_MODEL", "")),
        ("text LLM (warm-up)", os.environ.get("KEPT_TEXT_LLM_MODEL", DEFAULT_MODEL)),
    ):
        if not model:
            checks.append((label, False, "no model set in .env"))
            continue
        try:
            gw = LiteLLMGateway(model=model, audit_log=audit, timeout_s=180, max_retries=1)
            gw.complete(
                system="Reply with OK.",
                user=fixed_text("OK?"),
                purpose=Purpose.OPS_PREFLIGHT,
                actor_id="preflight",
            )
            checks.append((label, True, model))
        except Exception as e:
            checks.append((label, False, f"{model}: {str(e).splitlines()[0][:140]}"))
    checks.append(("web", get(args.web) is not None, args.web))
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<20} {detail}")
    failed = [n for n, ok, _ in checks if not ok]
    print("kept preflight: GO" if not failed else f"kept preflight: NO GO ({', '.join(failed)})")
    return 1 if failed else 0


def audit_verify(args: argparse.Namespace) -> int:
    """Each audit event carries sha256(previous hash + event): an edited or deleted event breaks it."""
    from kept.common.audit import DuckDBAuditLog, verify_chain

    path = os.environ.get("KEPT_AUDIT_LOG_PATH", str(WAREHOUSE_PATH.parent / "audit.duckdb"))
    checked, legacy, broken = verify_chain(DuckDBAuditLog(path))
    before = f" ({legacy:,} older events from before the chain began)" if legacy else ""
    if broken:
        print(f"kept audit-verify: BROKEN at {broken}, after {checked:,} intact events{before}")
        return 1
    print(f"kept audit-verify: intact, {checked:,} events chained{before}")
    return 0


HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "serve": serve,
    "land": land,
    "match": match,
    "build": build,
    "gate": gate,
    "benchmark": benchmark,
    "extract": extract,
    "train": train,
    "features": features,
    "parity": parity,
    "score": score,
    "invariance": invariance,
    "train-promises": train_promises,
    "train-best-hour": train_best_hour,
    "nightly": nightly,
    "map": map_,
    "drift": drift,
    "demo-reset": demo_reset,
    "preflight": preflight,
    "audit-verify": audit_verify,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kept")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in COMMANDS.items():
        p = sub.add_parser(name, help=help_text)
        if name == "demo-reset":
            p.add_argument("--case", default=None, help="only this case (default: every case)")
        if name == "preflight":
            p.add_argument("--api", default="http://localhost:8000")
            p.add_argument("--web", default="http://localhost:3000")
        if name == "serve":
            p.add_argument(
                "--demo", action="store_true", help="twelve in-memory demo cases, no warehouse needed"
            )
            p.add_argument("--host", default="127.0.0.1")
            p.add_argument("--port", type=int, default=8000)
            p.add_argument("--reload", action="store_true", help="restart when code under src/ changes")
        if name in ("land", "match", "gate"):
            p.add_argument(
                "--warehouse", type=Path, default=None, help="warehouse file (default: the project's)"
            )
        if name == "map":
            p.add_argument(
                "--draft", action="store_true", help="ask the local LLM for a mapping draft per drift"
            )
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
            p.add_argument("--silver-only", action="store_true", help="stop after silver (then: kept match)")
            p.add_argument("--crosswalk", type=Path, default=None, help="crosswalk parquet (default: newest)")
            p.add_argument(
                "--extractions",
                type=Path,
                nargs="*",
                default=None,
                help="Track C's text.extractions parquet files (default: data/exports/extractions/*.parquet)",
            )
            p.add_argument("--warehouse", type=Path, default=None)
            p.add_argument("--as-of-date", default="2026-09-28", help="snapshot date of the load")
        if name == "benchmark":
            p.add_argument("--questions", type=Path, default=Path("data/benchmark/benchmark_questions.csv"))
            p.add_argument(
                "--dev-answers", type=Path, default=Path("data/benchmark/benchmark_dev_answers.csv")
            )
            p.add_argument("--out", type=Path, default=Path("submission/benchmark_answers.csv"))
            p.add_argument("--scorecard", type=Path, default=None, help="write the dev scorecard (markdown)")
            p.add_argument(
                "--only", nargs="+", default=None, metavar="ID", help="ask only these question ids"
            )
        if name == "features":
            p.add_argument(
                "--as-of",
                type=datetime.fromisoformat,
                default=_last_nightly(),
                help="serving as_of, naive UTC (default: the latest 06:00 UTC, the nightly run)",
            )
            p.add_argument("--training", action="store_true", help="per-decision spine for kept train")
        if name == "nightly":
            p.add_argument("--from", dest="start", default=None, help="resume at this step")
            p.add_argument("--skip", action="append", default=[], help="leave a step out (repeatable)")
        if name == "score":
            p.add_argument("--model", type=Path, default=EXPORT_DIR / "models" / "uplift.pkl")
            p.add_argument(
                "--now", type=datetime.fromisoformat, default=None, help="with a UTC offset (default: now)"
            )
            p.add_argument(
                "--best-hour",
                action=argparse.BooleanOptionalAction,
                default={"0": False, "1": True}.get(os.environ.get("KEPT_BEST_HOUR", "")),
                help="book calls into the likeliest-to-answer hour of their day. Default: on when "
                "models/best_hour.pkl exists. --no-best-hour (or KEPT_BEST_HOUR=0) books the earliest slot",
            )
        if name == "train-promises":
            p.add_argument("--out", type=Path, default=EXPORT_DIR / "models" / "promise.pkl")
        if name == "train-best-hour":
            p.add_argument("--out", type=Path, default=EXPORT_DIR / "models" / "best_hour.pkl")
            p.add_argument("--cutoff", type=datetime.fromisoformat, default=datetime(2026, 8, 15))
            p.add_argument(
                "--if-older-than",
                type=float,
                default=None,
                metavar="DAYS",
                help="do nothing when --out exists and is newer than this (the nightly passes 7)",
            )
        if name == "train":
            p.add_argument(
                "--cutoff",
                type=datetime.fromisoformat,
                default=datetime(2026, 8, 15),
                help="fit on decisions before this (naive UTC), Qini on the rest (default: about 70/30)",
            )
            p.add_argument("--out", type=Path, default=EXPORT_DIR / "models" / "uplift.pkl")
            p.add_argument("--seed", type=int, default=0)
            p.add_argument(
                "--promote", action="store_true", help="make the new model the champion without the gate"
            )
            p.add_argument("--pool-nudges", action="store_true", help="one arm for email, push and SMS (#80)")
            p.add_argument(
                "--champion",
                type=Path,
                default=None,
                help="judge against this model instead of --out, so --out can be a scratch path",
            )
            p.add_argument("--seeds", type=int, default=3, help="seeds each side is averaged over")
            p.add_argument("--no-policy-value", action="store_true", help="skip the value against the bank")
        if name == "parity":
            p.add_argument("--sample", type=int, default=2000, help="random cases to compare")
            p.add_argument("--all", action="store_true", help="every case in features.case_features")
            p.add_argument("--seed", type=int, default=7)
            p.add_argument("--as-of", default="2026-09-28 06:00 UTC", help="shown in the report")
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
            p.add_argument(
                "--load-redacted",
                nargs="?",
                const="",
                default=None,
                help="load the newest exports/redacted_notes/*.parquet into text.redacted_notes",
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
            p.add_argument("--no-previous", action="store_true", help="do not reuse the last crosswalk's IDs")
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
