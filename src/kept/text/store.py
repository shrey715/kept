"""text.extractions in the warehouse: one row per source_id (shape: dbt/models/text/sources.yml).
Implements kept.contracts.interfaces.ExtractionStore. Opens a connection per call (K5)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from kept.common.db import connect
from kept.config import WAREHOUSE_PATH
from kept.contracts.features import TextExtraction
from kept.text.extract import FIELDS

_TYPES = {
    "hardship_signal": "varchar",
    "stated_reason": "varchar",
    "promise_intent": "boolean",
    "promised_date": "date",
    "promised_amount": "decimal(12,2)",
    "dispute": "boolean",
    "cease_request": "boolean",
    "third_party_present": "boolean",
}
_PARTS = ("value", "quote", "char_start", "char_end", "confidence")
COLUMNS = (
    "source_id",
    "case_id",
    *(f"{f}_{p}" for f in FIELDS for p in _PARTS),
    "extractor",
    "extracted_at",
    "confirmed_by_agent_id",
)
DDL = (
    "create table if not exists text.extractions (source_id varchar primary key, case_id varchar not null, "
    + ", ".join(
        f"{f}_value {_TYPES[f]}, {f}_quote varchar, {f}_char_start integer, {f}_char_end integer, "
        f"{f}_confidence double"
        for f in FIELDS
    )
    + ", extractor varchar not null, extracted_at timestamptz not null, confirmed_by_agent_id varchar)"
)


def to_row(x: TextExtraction) -> tuple[Any, ...]:
    row: list[Any] = [x.source_id, x.case_id]
    for f in FIELDS:
        v = getattr(x, f)
        ev = v.evidence
        value = v.value.value if hasattr(v.value, "value") else v.value  # enums -> their string
        row += [value, ev and ev.quote, ev and ev.char_start, ev and ev.char_end, v.confidence]
    return (*row, x.extractor, x.extracted_at, x.confirmed_by_agent_id)


def from_row(row: Sequence[Any]) -> TextExtraction:
    r = dict(zip(COLUMNS, row, strict=True))
    data: dict[str, Any] = {k: r[k] for k in ("source_id", "case_id", "extractor", "extracted_at")}
    data["confirmed_by_agent_id"] = r["confirmed_by_agent_id"]
    for f in FIELDS:
        quote = r[f"{f}_quote"]
        evidence = quote and {
            "quote": quote,
            "source_id": r["source_id"],
            "char_start": r[f"{f}_char_start"],
            "char_end": r[f"{f}_char_end"],
        }
        data[f] = {"value": r[f"{f}_value"], "evidence": evidence, "confidence": r[f"{f}_confidence"]}
    return TextExtraction.model_validate(data)


class DuckDBExtractionStore:
    def __init__(self, path: Path | str = WAREHOUSE_PATH) -> None:
        self.path = path
        with connect(path) as c:
            c.execute(DDL)

    def put(self, extraction: TextExtraction) -> None:
        self.put_many([extraction])

    def put_many(self, extractions: Sequence[TextExtraction]) -> None:
        """Insert or replace by source_id (the backfill writes in batches)."""
        marks = ", ".join("?" * len(COLUMNS))
        with connect(self.path) as c:
            c.executemany(
                f"insert or replace into text.extractions values ({marks})", [to_row(x) for x in extractions]
            )

    def get(self, source_id: str) -> TextExtraction | None:
        with connect(self.path) as c:
            row = c.execute("select * from text.extractions where source_id = ?", [source_id]).fetchone()
        return from_row(row) if row else None

    def for_case(self, case_id: str) -> Sequence[TextExtraction]:
        with connect(self.path) as c:
            rows = c.execute(
                "select * from text.extractions where case_id = ? order by extracted_at desc", [case_id]
            ).fetchall()
        return [from_row(r) for r in rows]
