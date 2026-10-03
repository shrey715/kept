"""Registers the cleaning rules of kept.data.clean as DuckDB functions for dbt (silver).

dbt-duckdb loads this module through the `plugins:` entry in dbt/profiles.yml and calls
`Plugin.configure_connection` on every connection, so models can write `kept_dob(dob_raw)`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import duckdb
from duckdb import sqltypes as T

from kept.data.clean import (
    first_name_key,
    match_first_name,
    match_name,
    match_name_parts,
    name_match_key,
    normalize_name,
    normalize_phone_e164,
    normalize_postal_code,
    parse_date,
    parse_dob,
)

SNAPSHOT_DATE = date(2026, 9, 28)  # release README: "snapshot date 2026-09-28"; DOBs after it are future


def _dob(raw: str | None) -> date | None:
    return parse_dob(raw, today=SNAPSHOT_DATE)


def _dob_day_first(raw: str | None) -> date | None:
    return parse_dob(raw, today=SNAPSHOT_DATE, day_first=True)


FUNCTIONS: dict[str, tuple[Any, Any]] = {
    "kept_name": (normalize_name, T.VARCHAR),
    "kept_name_key": (name_match_key, T.VARCHAR),
    "kept_dob": (_dob, T.DATE),  # ambiguous 03/04/1990 -> null (quarantine)
    "kept_dob_dmy": (_dob_day_first, T.DATE),  # for a source the dictionary fixes as DD-MM-YYYY (cards)
    "kept_match_name_first_last": (lambda raw: match_name(raw, style="first_last"), T.VARCHAR),
    "kept_match_name_last_initials": (lambda raw: match_name(raw, style="last_first_initials"), T.VARCHAR),
    "kept_match_name_last_comma": (lambda raw: match_name(raw, style="last_comma_first"), T.VARCHAR),
    "kept_match_name_card": (lambda raw: match_name(raw, style="card"), T.VARCHAR),
    "kept_first_name": (first_name_key, T.VARCHAR),  # CRM first_name
    "kept_first_name_first_last": (lambda raw: match_first_name(raw, style="first_last"), T.VARCHAR),
    "kept_first_name_last_comma": (lambda raw: match_first_name(raw, style="last_comma_first"), T.VARCHAR),
    "kept_first_name_card": (lambda raw: match_first_name(raw, style="card"), T.VARCHAR),
    "kept_date": (lambda raw: parse_date(raw), T.DATE),  # any column typed DATE that arrives in mixed formats
    "kept_phone": (lambda raw: normalize_phone_e164(raw), T.VARCHAR),  # one argument: DuckDB counts them
    "kept_postal": (normalize_postal_code, T.VARCHAR),
}


def register(conn: duckdb.DuckDBPyConnection) -> None:
    conn.create_function(
        "kept_match_name_parts",
        match_name_parts,
        [T.VARCHAR, T.VARCHAR],
        T.VARCHAR,
        null_handling="special",  # type: ignore[call-overload]
    )
    for name, (fn, returns) in FUNCTIONS.items():
        # SPECIAL: the functions return None for input they can't parse (that row goes to quarantine)
        conn.create_function(name, fn, [T.VARCHAR], returns, null_handling="special")  # type: ignore[call-overload]


try:
    from dbt.adapters.duckdb.plugins import BasePlugin
except ImportError:  # core install without dbt: the functions above still work

    class Plugin:  # type: ignore[no-redef]
        pass

else:

    class Plugin(BasePlugin):  # type: ignore[no-redef]
        def configure_connection(self, conn: duckdb.DuckDBPyConnection) -> None:
            register(conn)
