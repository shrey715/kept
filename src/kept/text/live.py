"""Live extraction (`kept extract`): notes and calls from silver, or a note typed in now,
-> redact -> LLM extract -> text.extractions. One bad source never stops the batch."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from kept.common.db import connect
from kept.config import RAW_DIR, WAREHOUSE_PATH
from kept.contracts.features import TextExtraction
from kept.contracts.interfaces import LLMGateway, Redactor
from kept.text.extract import LLMExtractor, transcript_text
from kept.text.store import DuckDBExtractionStore

DEFAULT_MODEL = "ollama/gemma3:12b-it-qat"  # .env.example KEPT_TEXT_LLM_MODEL


@dataclass(frozen=True, slots=True)
class Source:
    source_id: str
    case_id: str
    text: str
    written_at: datetime | None


@dataclass(frozen=True, slots=True)
class Result:
    source_id: str
    extraction: TextExtraction | None
    error: str | None
    seconds: float


def warehouse_path() -> Path:
    return Path(os.environ.get("KEPT_WAREHOUSE_PATH", WAREHOUSE_PATH))


def read_sources(
    path: Path | str,
    *,
    note_ids: Sequence[str] = (),
    transcript_ids: Sequence[str] = (),
    new: bool = False,
    limit: int | None = None,
    raw_dir: Path = RAW_DIR,
) -> list[Source]:
    """Notes by id, calls by id, and (new=True) every note with no text.extractions row yet,
    newest first. One read-only connection, closed before any write (K5)."""
    DuckDBExtractionStore(path)  # creates text.extractions, so the anti-join below works
    with connect(path, read_only=True) as c:
        rows = []
        if note_ids:
            rows += c.execute(
                "select note_id, case_id, note_text, note_ts from silver.agent_notes where note_id in ?",
                [list(note_ids)],
            ).fetchall()
        if new:
            rows += c.execute(
                "select note_id, case_id, note_text, note_ts from silver.agent_notes n where not exists "
                "(select 1 from text.extractions x where x.source_id = n.note_id) "
                "order by note_ts desc, note_id limit ?",
                [limit],
            ).fetchall()
        calls = (
            c.execute(
                "select transcript_id, case_id, file_path, call_start_ts from silver.call_transcripts "
                "where transcript_id in ?",
                [list(transcript_ids)],
            ).fetchall()
            if transcript_ids
            else []
        )
    out = [Source(i, case, text or "", ts) for i, case, text, ts in rows]
    for i, case, file_path, ts in calls:
        turns = json.loads((raw_dir / "files" / file_path).read_text())["turns"]
        out.append(Source(i, case, transcript_text(turns), ts))
    return out


def typed_note(text: str, *, case_id: str, source_id: str | None = None) -> Source:
    """A note typed in now (not in silver): written_at is the local time now."""
    return Source(source_id or f"N-LIVE-{uuid.uuid4().hex[:8]}", case_id, text, datetime.now().astimezone())


def extract_into(
    path: Path | str,
    sources: Sequence[Source],
    *,
    redactor: Redactor | None = None,
    llm: LLMGateway | None = None,
    batch: int = 50,
) -> Iterator[Result]:
    """Redact, extract and write each source; yields one Result per source as it finishes.
    Writes every `batch` extractions (and at the end) through the store, which opens its
    own connection per write. A source that fails is yielded with its error and skipped."""
    if redactor is None:
        from kept.text.redact import PresidioRedactor

        redactor = PresidioRedactor()
    if llm is None:
        from kept.common.audit import DuckDBAuditLog
        from kept.common.llm import LiteLLMGateway

        audit = Path(os.environ.get("KEPT_AUDIT_LOG_PATH", WAREHOUSE_PATH.parent / "audit.duckdb"))
        llm = LiteLLMGateway(
            model=os.environ.get("KEPT_TEXT_LLM_MODEL", DEFAULT_MODEL),
            audit_log=DuckDBAuditLog(audit),
            timeout_s=120,  # the first call loads the model onto the GPU
        )
    extractor, store = LLMExtractor(llm), DuckDBExtractionStore(path)
    pending: list[TextExtraction] = []
    # ponytail: one source at a time; a thread pool (as in scripts/eval_extraction.py) if the
    # nightly --new volume outgrows it
    for s in sources:
        t0 = time.perf_counter()
        try:
            x = extractor.extract(
                redactor.redact(s.text), source_id=s.source_id, case_id=s.case_id, written_at=s.written_at
            )
        except Exception as e:  # a bad reply or a bad note counts as an error; keep going
            yield Result(s.source_id, None, f"{type(e).__name__}: {e}", time.perf_counter() - t0)
            continue
        pending.append(x)
        if len(pending) >= batch:
            store.put_many(pending)
            pending = []
        yield Result(s.source_id, x, None, time.perf_counter() - t0)
    if pending:
        store.put_many(pending)
