"""Gold: build gold.c360_customer, gold.identity_crosswalk, gold.c360_restricted."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path

import duckdb

from kept.contracts.enums import HardStop
from kept.contracts.identity import ContactPermissions

# Source flags (data dictionary names) behind each derived field. A flag on ANY linked
# record counts. national_dncl_flag is deliberately absent: the National DNCL covers
# telemarketing, not collections (design §9).
DO_NOT_CONTACT_FLAGS = (
    "internal_do_not_call_flag",  # customers
    "cease_communication_flag",  # customers
    "cease_contact_flag",  # collections_cases
    "cease_request_flag",  # contact_history
)
HARD_STOP_FLAGS: dict[HardStop, tuple[str, ...]] = {
    HardStop.CEASE: ("cease_communication_flag", "cease_contact_flag", "cease_request_flag"),
    HardStop.INSOLVENCY: ("consumer_proposal_flag", "insolvency_hold_flag", "consumer_proposal_on_file_flag"),
    HardStop.BANKRUPTCY: ("bankruptcy_flag", "bankruptcy_on_file_flag"),
    HardStop.DECEASED: ("deceased_flag", "deceased_hold_flag", "deceased_indicator"),
}
COLLECTIONS_HOLD_STOPS = (HardStop.INSOLVENCY, HardStop.BANKRUPTCY, HardStop.DECEASED)

# customers consent column behind each channel. Calls need consent_call (primary phone).
CONSENT_COLUMNS = {
    "call": "consent_call",
    "sms": "consent_sms",
    "email": "consent_email",
    "push": "consent_push",
}


def _on(value: object) -> bool:
    """True only for a real true: None, NaN and pd.NA (an unknown flag) never count."""
    try:
        return value is not None and bool(value == 1)
    except TypeError:  # bool(pd.NA)
        return False


def merge_contact_permissions(records: Iterable[ContactPermissions | None]) -> ContactPermissions:
    """Most restrictive across duplicate CRM records (built from CONSENT_COLUMNS): a channel
    is allowed only if every record allows it. A None record (unknown consent) blocks every
    channel. No records -> all False."""
    permissions = list(records)
    if not permissions or any(p is None for p in permissions):
        return ContactPermissions()
    return ContactPermissions(
        **{ch: all(getattr(p, ch) for p in permissions) for ch in CONSENT_COLUMNS}  # type: ignore[union-attr]
    )


def derive_contact_flags(source_flags: Iterable[Mapping[str, bool | None]]) -> tuple[bool, bool]:
    """(do_not_contact, collections_hold) across all source records for one customer.

    do_not_contact: any DO_NOT_CONTACT_FLAGS column true on any record.
    collections_hold: any HARD_STOP_FLAGS column for COLLECTIONS_HOLD_STOPS true on any record.
    Null flags and missing keys are ignored (not treated as true). national_dncl_flag never counts.
    """
    records = list(source_flags)
    hold_flags = [f for stop in COLLECTIONS_HOLD_STOPS for f in HARD_STOP_FLAGS[stop]]
    return (
        any(_on(r.get(f)) for r in records for f in DO_NOT_CONTACT_FLAGS),
        any(_on(r.get(f)) for r in records for f in hold_flags),
    )


def hard_stop_flags(source_flags: Iterable[Mapping[str, bool | None]]) -> frozenset[HardStop]:
    """Which hard stops fired across all source records, using HARD_STOP_FLAGS."""
    records = list(source_flags)
    return frozenset(
        stop for stop, flags in HARD_STOP_FLAGS.items() if any(_on(r.get(f)) for r in records for f in flags)
    )


DBT_DIR = Path(__file__).resolve().parents[3] / "dbt"
# the models that turn silver + the crosswalk into the three gold tables (tests/data/test_gold_sql.py
# checks this list against dbt/models)
GOLD_MODELS = (
    "int_golden_clusters",
    "int_flag_events",
    "int_source_flags",
    "int_crm_current",
    "int_account_delinquency",
    "int_open_case",
    "int_hardship_observations",
    "int_hardship",
    "int_payroll",
    "int_restricted",
    "c360_customer",
    "c360_restricted",
    "identity_crosswalk",
)


def _warehouse_path(conn: duckdb.DuckDBPyConnection) -> str:
    row = conn.execute(
        "select path from duckdb_databases() where not internal and not readonly limit 1"
    ).fetchone()
    if row is None or row[0] is None:
        raise ValueError("build_gold needs a connection to the warehouse file, not an in-memory database")
    return str(row[0])


def run_dbt(select: Iterable[str], *, warehouse: str) -> None:
    """`dbt build --select ...` against `warehouse`. Raises RuntimeError if any model or test fails."""
    from dbt.cli.main import dbtRunner

    os.environ["KEPT_WAREHOUSE_PATH"] = warehouse
    # --threads 1: four wide builds at once ran a 16 GB laptop out of memory
    args = [
        "build",
        "--select",
        *select,
        "--threads",
        "1",
        "--profiles-dir",
        str(DBT_DIR),
        "--project-dir",
        str(DBT_DIR),
    ]
    result = dbtRunner().invoke(args)
    if not result.success:
        raise RuntimeError(f"dbt build failed: {result.exception or 'see the dbt log above'}")


def find_extractions(directory: Path) -> list[Path]:
    """Track C's text.extractions parquet files (the SetFit backfill, then live runs), oldest first."""
    found = [p for d in ("extractions", "text_extractions") for p in (directory / d).glob("*.parquet")]
    return sorted(found, key=lambda p: p.stat().st_mtime)


def load_extractions(conn: duckdb.DuckDBPyConnection, files: Iterable[Path]) -> int:
    """Load extraction parquet files into text.extractions, oldest first, so a re-extraction of the same
    source_id replaces the older row. The table keeps C's DDL (primary key on source_id): the live
    extractor upserts into it. Returns the row count."""
    from kept.text.store import DDL

    conn.execute("create schema if not exists text")
    conn.execute(DDL)
    for path in files:
        conn.execute(
            "insert or replace into text.extractions by name select * from read_parquet(?)", [str(path)]
        )
    row = conn.execute("select count(*) from text.extractions").fetchone()
    assert row is not None
    return int(row[0])


def build_gold(
    conn: duckdb.DuckDBPyConnection,
    *,
    crosswalk: Path | None = None,
    extractions: Iterable[Path] | None = None,
) -> None:
    """Materialise the three gold tables from silver + the current crosswalk.
    Normally run through dbt; this wraps `dbt build --select gold`.

    Loads the newest crosswalk parquet (or `crosswalk`) into silver.int_crosswalk and Track C's extractions
    (`extractions`, else the files under data/exports/extractions/, if any) into text.extractions, then
    closes `conn`: dbt needs the warehouse file to itself (K5, one writer)."""
    from kept.config import EXPORT_DIR
    from kept.data.identity.pipeline import latest_crosswalk, load_crosswalk

    warehouse = _warehouse_path(conn)
    load_crosswalk(conn, crosswalk or latest_crosswalk(EXPORT_DIR / "identity_crosswalk"))
    files = list(extractions) if extractions is not None else find_extractions(EXPORT_DIR)
    if files:
        load_extractions(conn, files)
    conn.close()
    run_dbt(GOLD_MODELS, warehouse=warehouse)


def export_parquet(conn: duckdb.DuckDBPyConnection, *, as_of_date: str) -> None:
    """Write gold.c360_customer to data/exports/c360_customer/as_of_date=<date>/."""
    from kept.config import EXPORT_DIR

    date.fromisoformat(as_of_date)  # a path component: only ever a real date
    out = EXPORT_DIR / "c360_customer" / f"as_of_date={as_of_date}"
    out.mkdir(parents=True, exist_ok=True)
    conn.execute(f"copy (select * from gold.c360_customer) to '{out / 'part-000.parquet'}' (format parquet)")
