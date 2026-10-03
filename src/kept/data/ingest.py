"""Bronze: land the 31 source tables as they arrive, unchanged.

Formats (data dictionary, sheet About): CSV for small tables, Parquet partitioned by year
for history tables (loan_instalments, transactions, card_statements,
account_monthly_snapshot, bureau_history, salary_credit_history), JSON for
call_transcripts (turns nested), WAV + metadata for voice_samples.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

_READERS = {".csv": "read_csv({}, header=true, all_varchar=true)", ".json": "read_json({})"}


@dataclass(frozen=True, slots=True)
class LandedTable:
    source_file: Path
    table: str  # bronze.<name>
    row_count: int
    extracted_at: datetime  # source extract time, drives the freshness rule
    loaded_at: datetime


def land_file(conn: duckdb.DuckDBPyConnection, path: Path, *, extracted_at: datetime) -> LandedTable:
    """Load one raw file into bronze.<stem> with every column as VARCHAR plus
    _source_file, _extracted_at, _loaded_at. Re-landing the same file replaces it."""
    reader = _READERS.get(path.suffix.lower()) or (
        "read_parquet({})" if path.suffix.lower() == ".parquet" else None
    )
    if reader is None:
        raise ValueError(f"cannot land {path}: only CSV, Parquet and JSON are landed")
    return _land(conn, path.stem, reader.format(repr(str(path))), str(path), extracted_at, source=path)


def _land(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    source_sql: str,
    source_file: str | None,
    extracted_at: datetime,
    *,
    source: Path,
) -> LandedTable:
    rel = conn.sql(f"select * from {source_sql}")
    cols = [
        # nested values (call_transcripts.turns) stay readable as JSON text
        f'to_json("{c}")::varchar as "{c}"'
        if (t := str(ty)).startswith(("STRUCT", "MAP")) or t.endswith("]")
        else f'"{c}"::varchar as "{c}"'
        for c, ty in zip(rel.columns, rel.types, strict=True)
        if c != "filename" or source_file is not None
    ]
    file_col = "?" if source_file is not None else "filename"
    loaded_at = datetime.now(UTC)
    conn.execute("create schema if not exists bronze")
    conn.execute(
        f"create or replace table bronze.{name} as select {', '.join(cols)}, "
        f"{file_col}::varchar as _source_file, ?::timestamptz as _extracted_at, "
        f"?::timestamptz as _loaded_at from {source_sql}",
        ([source_file] if source_file is not None else []) + [extracted_at, loaded_at],
    )
    row = conn.execute(f"select count(*) from bronze.{name}").fetchone()
    assert row is not None
    return LandedTable(source, f"bronze.{name}", row[0], extracted_at, loaded_at)


def land_directory(
    conn: duckdb.DuckDBPyConnection, raw_dir: Path, *, extracted_at: datetime
) -> list[LandedTable]:
    """Land every table in raw_dir. A file lands as bronze.<stem>; a directory of Parquet
    files (any depth, e.g. transactions/year=2025/*.parquet) lands as ONE table named after
    the directory. WAV files are not landed (only voice_samples metadata). Sorted by table name."""
    landed: list[LandedTable] = []
    for entry in sorted(raw_dir.iterdir()):
        if entry.is_file() and entry.suffix.lower() in (*_READERS, ".parquet"):
            landed.append(land_file(conn, entry, extracted_at=extracted_at))
        elif entry.is_dir() and any(entry.rglob("*.parquet")):
            glob = repr(str(entry / "**" / "*.parquet"))
            # hive_partitioning off: year=2025 stays in _source_file, not a new column
            src = f"read_parquet({glob}, union_by_name=true, filename=true, hive_partitioning=false)"
            landed.append(_land(conn, entry.name, src, None, extracted_at, source=entry))
    return sorted(landed, key=lambda t: t.table)
