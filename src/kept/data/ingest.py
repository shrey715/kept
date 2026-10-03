"""Bronze: land the 31 source tables as they arrive, unchanged.

Formats (data dictionary, sheet About): CSV for small tables, Parquet partitioned by year
for history tables (loan_instalments, transactions, card_statements,
account_monthly_snapshot, bureau_history, salary_credit_history), JSON for
call_transcripts (turns nested), WAV + metadata for voice_samples.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb


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
    raise NotImplementedError("Track A")


def land_directory(
    conn: duckdb.DuckDBPyConnection, raw_dir: Path, *, extracted_at: datetime
) -> list[LandedTable]:
    """Land every table in raw_dir. A file lands as bronze.<stem>; a directory of Parquet
    files (any depth, e.g. transactions/year=2025/*.parquet) lands as ONE table named after
    the directory. WAV files are not landed (only voice_samples metadata). Sorted by table name."""
    raise NotImplementedError("Track A")
