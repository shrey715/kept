"""DuckDB connection helpers (owner: Track A)."""

from __future__ import annotations

from pathlib import Path

import duckdb

from kept.config import WAREHOUSE_PATH

SCHEMAS = ("bronze", "silver", "gold", "features", "quarantine", "steward")


def connect(path: Path | str = WAREHOUSE_PATH, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the warehouse and make sure every schema in SCHEMAS exists (unless read_only)."""
    raise NotImplementedError("Track A")
