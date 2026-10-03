"""build_gold, export_parquet and the gate's gather_results, on a tiny warehouse (dbt is stubbed)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from kept.common.db import connect
from kept.data import gate, gold
from kept.data.quality import Status


# ----------------------------------------------------------------- build_gold
def _crosswalk(path: Path) -> Path:
    duckdb.connect().execute(
        "copy (select 'G-000001' as golden_customer_id, 'crm' as source_system, 'C1' as source_key) "
        f"to '{path}' (format parquet)"
    )
    return path


def test_build_gold_loads_the_crosswalk_runs_dbt_and_closes_the_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[tuple[str, ...], str]] = []
    monkeypatch.setattr(
        gold, "run_dbt", lambda select, *, warehouse: calls.append((tuple(select), warehouse))
    )
    warehouse = tmp_path / "w.duckdb"
    conn = connect(warehouse)
    gold.build_gold(conn, crosswalk=_crosswalk(tmp_path / "xw.parquet"))
    assert calls == [(gold.GOLD_MODELS, str(warehouse))]
    with pytest.raises(duckdb.ConnectionException):  # dbt needs the file to itself (K5)
        conn.execute("select 1")
    check = connect(warehouse, read_only=True)
    assert check.execute("select count(*) from silver.int_crosswalk").fetchone() == (1,)


def test_build_gold_refuses_an_in_memory_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "run_dbt", lambda *a, **k: None)
    with pytest.raises(ValueError):
        gold.build_gold(duckdb.connect(), crosswalk=Path("unused.parquet"))


# ----------------------------------------------------------------- export_parquet
def test_export_parquet_writes_the_hive_partition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kept.config.EXPORT_DIR", tmp_path)
    conn = duckdb.connect()
    conn.execute("create schema gold")
    conn.execute("create table gold.c360_customer as select 'G-000001' as golden_customer_id, [1, 2] as xs")
    gold.export_parquet(conn, as_of_date="2026-09-28")
    out = tmp_path / "c360_customer" / "as_of_date=2026-09-28" / "part-000.parquet"
    assert pd.read_parquet(out)["golden_customer_id"].tolist() == ["G-000001"]


@pytest.mark.parametrize("bad", ["../../etc", "2026-09-28'; drop table x; --", "yesterday"])
def test_export_parquet_only_accepts_a_real_date(bad: str) -> None:
    with pytest.raises(ValueError):
        gold.export_parquet(duckdb.connect(), as_of_date=bad)


# ----------------------------------------------------------------- gather_results
NOW = datetime(2026, 10, 3, 4, 0, tzinfo=UTC)


def _gate_warehouse(*, ceased_flag_reaches_gold: bool, auto_score: float = 0.99) -> duckdb.DuckDBPyConnection:
    """Two customers: G-1 (a CRM key with a national ID, a card account, a case) and G-2 (bureau only)."""
    conn = duckdb.connect()
    for schema in ("gold", "silver"):
        conn.execute(f"create schema {schema}")
    conn.execute(
        f"""create table gold.c360_customer as select * from (values
            ('G-1', {str(ceased_flag_reaches_gold).lower()}, false, timestamptz '2026-10-03 04:00:00+00'),
            ('G-2', false, false, timestamptz '2026-10-03 04:00:00+00'))
            t(golden_customer_id, do_not_contact, collections_hold, refreshed_at)"""
    )
    conn.execute("alter table gold.c360_customer add column hardship_source varchar")
    conn.execute(
        f"""create table gold.identity_crosswalk as select * from (values
            ('G-1', 'crm', 'C1', null::double, 'exact:case_crm_ref', 'auto', null::timestamptz),
            ('G-1', 'collections', 'C1', null, 'exact:case_crm_ref', 'auto', null),
            ('G-1', 'card', 'CX1', {auto_score}, 'splink', 'auto', null),
            ('G-2', 'bureau', 'B2', null, 'singleton', 'unlinked', null))
            t(golden_customer_id, source_system, source_key, match_score, match_rule, match_review_status, valid_to)"""
    )
    conn.execute(
        "create table silver.int_identity_records as select * from (values ('crm', 'C1', 'h1')) "
        "t(source_system, source_key, national_id_hash)"
    )
    conn.execute(
        "create table silver.collections_cases as select 'CS-1' as case_id, 'C1' as coll_customer_ref, null::varchar as outcome"
    )
    for table, key in (("card_accounts", "CX1"), ("loan_accounts", "L9"), ("deposit_accounts", "D9")):
        conn.execute(f"create table silver.{table} as select '{key}' as src_customer_ref")
    conn.execute(
        "create table silver.int_flag_events as select 'crm' as source_system, 'C1' as source_key, "
        "'cease_communication_flag' as flag"
    )
    conn.execute(f"create table silver.customers as select timestamptz '{NOW.isoformat()}' as _extracted_at")
    return conn


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(gate, "REVIEWED_PAIRS", tmp_path / "no_such_file.csv")


def _by_rule(conn: duckdb.DuckDBPyConnection) -> dict[str, Status]:
    return {r.rule: r.status for r in gate.gather_results(conn, published_at=NOW)}


def test_gate_runs_every_rule_and_reports_partial_linkage() -> None:
    results = _by_rule(_gate_warehouse(ceased_flag_reaches_gold=True))
    assert set(results) == {
        "Q1-unique-ids",
        "Q2-linkage",
        "Q3-match-safety",
        "Q4-contact-safety",
        "Q5-freshness",
        "Q5-row-count",
        "hardship-text",
    }
    # linkage: the card key's golden ID holds a CRM record, the loan and deposit keys have no golden ID
    assert results["Q4-contact-safety"] is Status.PASS and results["Q1-unique-ids"] is Status.PASS
    assert results["Q2-linkage"] is Status.BLOCK  # 1 of 3 account keys linked: 33%


def test_gate_warns_until_text_extractions_exist_then_passes() -> None:
    conn = _gate_warehouse(ceased_flag_reaches_gold=True)
    assert _by_rule(conn)["hardship-text"] is Status.WARN
    conn.execute("create schema text")
    conn.execute("create table text.extractions as select 'N-1' as source_id")
    assert _by_rule(conn)["hardship-text"] is Status.PASS


def test_gate_blocks_a_ceased_customer_that_gold_still_contacts() -> None:
    assert _by_rule(_gate_warehouse(ceased_flag_reaches_gold=False))["Q4-contact-safety"] is Status.BLOCK


def test_gate_blocks_a_weak_auto_link() -> None:
    assert (
        _by_rule(_gate_warehouse(ceased_flag_reaches_gold=True, auto_score=0.90))["Q3-match-safety"]
        is Status.BLOCK
    )


def test_gate_remembers_the_row_count_between_runs() -> None:
    conn = _gate_warehouse(ceased_flag_reaches_gold=True)
    assert _by_rule(conn)["Q5-row-count"] is Status.PASS  # first load
    conn.execute(
        "insert into gold.c360_customer (golden_customer_id, do_not_contact, collections_hold, refreshed_at) "
        "values ('G-3', false, false, now()), ('G-4', false, false, now())"
    )
    assert _by_rule(conn)["Q5-row-count"] is Status.WARN  # 2 -> 4 rows


# ----------------------------------------------------------------- loading Track C's extractions
def _extractions_parquet(
    path: Path,
    rows: list[tuple[str, str, str]],
    *,
    at: str = "2026-09-25 12:00:00+00",
    confirmed: str = "null",
) -> Path:
    conn = duckdb.connect()
    values = ", ".join(f"('{sid}', 'CS-1', '{signal}', 'llm:{tag}')" for sid, signal, tag in rows)
    conn.execute(
        f"copy (select source_id, case_id, hardship_signal_value, extractor, timestamptz '{at}' as extracted_at, "
        f"{confirmed}::varchar as confirmed_by_agent_id from (values {values}) "
        f"t(source_id, case_id, hardship_signal_value, extractor)) to '{path}' (format parquet)"
    )
    return path


def _row(conn: duckdb.DuckDBPyConnection, source_id: str) -> tuple[object, ...]:
    return conn.execute(
        "select hardship_signal_value, extractor, confirmed_by_agent_id from text.extractions where source_id = ?",
        [source_id],
    ).fetchone()  # type: ignore[return-value]


def test_load_extractions_keeps_the_primary_key_and_a_newer_file_replaces_an_older_row(
    tmp_path: Path,
) -> None:
    old = _extractions_parquet(
        tmp_path / "backfill.parquet", [("N-1", "none", "setfit"), ("N-2", "possible", "x")]
    )
    new = _extractions_parquet(
        tmp_path / "live.parquet", [("N-1", "possible", "llm")], at="2026-09-26 12:00:00+00"
    )
    conn = duckdb.connect()
    assert gold.load_extractions(conn, [old, new]) == 2
    assert _row(conn, "N-1") == ("possible", "llm:llm", None)
    conn.execute(  # C's live upsert still works: it needs the primary key
        "insert or replace into text.extractions (source_id, case_id, extractor, extracted_at) "
        "values ('N-3', 'CS-1', 'llm:x', now())"
    )


def test_reloading_the_backfill_cannot_undo_a_live_extraction(tmp_path: Path) -> None:
    conn = duckdb.connect()
    live = _extractions_parquet(
        tmp_path / "live.parquet", [("N-1", "possible", "live")], at="2026-10-03 21:00:00+00"
    )
    gold.load_extractions(conn, [live])
    backfill = _extractions_parquet(
        tmp_path / "backfill.parquet", [("N-1", "none", "setfit")], at="2026-10-03 20:32:00+00"
    )
    gold.load_extractions(conn, [backfill])  # a nightly rebuild loads the same backfill file again
    assert _row(conn, "N-1") == ("possible", "llm:live", None)


def test_an_agent_confirmation_is_not_overwritten_by_an_unconfirmed_row(tmp_path: Path) -> None:
    conn = duckdb.connect()
    confirmed = _extractions_parquet(
        tmp_path / "confirmed.parquet",
        [("N-1", "possible", "live")],
        at="2026-10-03 21:00:00+00",
        confirmed="'AG-7'",
    )
    gold.load_extractions(conn, [confirmed])
    later_unconfirmed = _extractions_parquet(
        tmp_path / "later.parquet", [("N-1", "none", "setfit")], at="2026-10-04 08:00:00+00"
    )
    gold.load_extractions(conn, [later_unconfirmed])
    assert _row(conn, "N-1") == ("possible", "llm:live", "AG-7")  # newer, but it would drop the confirmation
    later_confirmed = _extractions_parquet(
        tmp_path / "later_confirmed.parquet",
        [("N-1", "none", "edited")],
        at="2026-10-04 09:00:00+00",
        confirmed="'AG-8'",
    )
    gold.load_extractions(conn, [later_confirmed])  # a newer confirmation does replace it
    assert _row(conn, "N-1") == ("none", "llm:edited", "AG-8")


def test_find_extractions_lists_both_folder_names_oldest_first(tmp_path: Path) -> None:
    import os

    for folder, name, mtime in (("extractions", "b.parquet", 200), ("text_extractions", "a.parquet", 100)):
        (tmp_path / folder).mkdir(exist_ok=True)
        f = tmp_path / folder / name
        f.write_bytes(b"x")
        os.utime(f, (mtime, mtime))
    assert [p.name for p in gold.find_extractions(tmp_path)] == ["a.parquet", "b.parquet"]
    assert gold.find_extractions(tmp_path / "missing") == []
