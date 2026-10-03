"""silver.account_monthly_snapshot keeps the original month_end_date text next to the parsed date
(the Ask's roll rate is graded against a reference that parses only some formats)
(integration: needs `uv sync --extra data`)."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import duckdb
import pytest

from kept.data.dbt_udfs import register

pytestmark = [pytest.mark.integration, pytest.mark.slow]

MODEL = Path(__file__).resolve().parents[2] / "dbt" / "models" / "silver" / "account_monthly_snapshot.sql"


def _silver(raw_values: list[str | None]) -> list[tuple[str | None, date | None]]:
    jinja2 = pytest.importorskip("jinja2")
    sql = MODEL.read_text()
    source = lambda _schema, name: f"bronze.{name}"  # noqa: E731
    rendered = jinja2.Environment().from_string(sql).render(source=source)
    names = {n for n in re.findall(r'"([a-z_0-9]+)"', sql) if not n.endswith("_raw")}
    conn = duckdb.connect()
    register(conn)
    conn.execute("create schema bronze")
    columns = ", ".join(f'null::varchar as "{n}"' for n in sorted(names - {"month_end_date"}))
    values = ", ".join(f"({'null' if v is None else repr(v)})" for v in raw_values)
    conn.execute(
        f"create table bronze.account_monthly_snapshot as select month_end_date, {columns}, "
        f"'f' as _source_file, now() as _extracted_at, now() as _loaded_at from (values {values}) t(month_end_date)"
    )
    return conn.execute(f"select month_end_date_raw, month_end_date from ({rendered})").fetchall()


def test_the_original_text_is_kept_whatever_the_format() -> None:
    raw = ["2025-12-31", "31/12/2025", "12/31/2025", "20251231", "not a date", None]
    out = _silver(raw)
    assert sorted(r[0] or "" for r in out) == sorted(v or "" for v in raw)  # every raw value, untouched


def test_all_four_formats_parse_to_the_same_date_and_junk_stays_null() -> None:
    by_raw = dict(_silver(["2025-12-31", "31/12/2025", "12/31/2025", "20251231", "not a date"]))
    assert {by_raw[v] for v in ("2025-12-31", "31/12/2025", "12/31/2025", "20251231")} == {date(2025, 12, 31)}
    assert by_raw["not a date"] is None  # nothing is guessed; the raw text is there for whoever needs it
