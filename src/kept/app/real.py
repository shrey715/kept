"""Real services for `kept serve` (Track D, S6): A's golden records, D's features (Feast) and
uplift model, C's extraction store and live extraction, B's Ask.

The API process holds one read-write connection to the warehouse and every reader takes a cursor
from it. DuckDB refuses a read-only and a read-write connection to one file in the same process,
and C's store and live extraction write; one connection also saves ~60 ms of connect per read.
The API owns the file while it runs (K5: no batch jobs against the warehouse it serves).
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path

import duckdb

from kept.app.api import Services
from kept.common.audit import DuckDBAuditLog
from kept.common.db import connect
from kept.config import EXPORT_DIR, REPO_ROOT, WAREHOUSE_PATH
from kept.contracts.interfaces import AuditLog
from kept.data.c360_reader import DuckDBC360Reader
from kept.features.store import FeastFeatureProvider
from kept.nba.context import KeptContextBuilder, duckdb_case_reader
from kept.nba.engine import KeptEngine
from kept.nba.release import Releaser
from kept.text.store import DuckDBExtractionStore


class SharedC360Reader(DuckDBC360Reader):
    """A's reader, through a cursor on the API's connection instead of a read-only one per call."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        super().__init__()
        self._conn = conn

    def _query(self, sql: str, params: list[str]) -> list[dict[str, object]]:
        with self._conn.cursor() as c:
            cursor = c.execute(sql, params)
            names = [d[0] for d in cursor.description]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def real_services(
    *,
    warehouse: Path = WAREHOUSE_PATH,
    feature_repo: Path = REPO_ROOT / "feature_repo",
    model: Path = EXPORT_DIR / "models" / "uplift.pkl",
) -> Services:
    """Needs a built warehouse (kept build), materialised features (kept features) and a trained
    model (kept train). Live extraction needs C's text extra (Presidio); without it the card's
    add-note path answers 503 and everything else works."""
    conn = connect(warehouse)
    audit_log = DuckDBAuditLog(os.environ.get("KEPT_AUDIT_LOG_PATH", str(warehouse.parent / "audit.duckdb")))
    c360 = SharedC360Reader(conn)
    features = FeastFeatureProvider(feature_repo)
    store = DuckDBExtractionStore(warehouse)
    context = KeptContextBuilder(
        c360=c360,
        features=features,
        cases=duckdb_case_reader(warehouse, conn=conn),
        holdout_salt=os.environ["KEPT_HOLDOUT_SALT"],
        extractions=store,
    )
    proposals: dict = {}  # type: ignore[type-arg]
    engine = KeptEngine(
        context=context,
        features=features,
        scorer=pickle.loads(model.read_bytes()),  # our own file, written by kept train
        audit_log=audit_log,
        proposals=proposals,
    )
    typed: dict[str, str] = {}  # notes typed in this session: source_id -> text

    def note_text(source_id: str) -> str | None:
        if source_id in typed:
            return typed[source_id]
        with conn.cursor() as c:
            row = c.execute(
                "select note_text from silver.agent_notes where note_id = ?", [source_id]
            ).fetchone()
        return row[0] if row else None

    from kept.ask.service import build_ask

    return Services(
        engine=engine,
        release_gate=Releaser(proposals=proposals, context=context, audit_log=audit_log),
        ask=build_ask(conn.cursor(), audit_log),
        c360=c360,
        audit_log=audit_log,
        proposals=proposals,
        add_note=_live_extraction(warehouse, audit_log, typed),
        extractions=store,
        note_text=note_text,
    )


def _live_extraction(warehouse: Path, audit_log: AuditLog, typed: dict[str, str]):  # type: ignore[no-untyped-def]
    """The card's add-note path: C's live extraction, redactor and model built once here (about
    5 s a note warm vs 12 s built per call). None without C's text extra installed."""
    try:
        from kept.text.redact import PresidioRedactor
    except ImportError:
        print("kept serve: Presidio is not installed (make setup-c), so notes can't be added")
        return None
    from kept.common.llm import LiteLLMGateway
    from kept.text.live import DEFAULT_MODEL, extract_into, typed_note

    redactor = PresidioRedactor()
    llm = LiteLLMGateway(
        model=os.environ.get("KEPT_TEXT_LLM_MODEL", DEFAULT_MODEL), audit_log=audit_log, timeout_s=120
    )

    def add(case_id: str, text: str, user_id: str, now: object) -> None:
        source = typed_note(text, case_id=case_id)
        (result,) = extract_into(warehouse, [source], redactor=redactor, llm=llm)
        if result.extraction is None:
            raise RuntimeError(f"extraction failed: {result.error}")
        typed[source.source_id] = text

    return add
