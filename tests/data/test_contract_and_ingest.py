"""Data contract loader, bronze landing, and Soda check generation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml

from kept.common.db import SCHEMAS, connect
from kept.contracts import Sensitivity
from kept.contracts.data_contract import load_data_contract
from kept.data.ingest import land_directory, land_file
from kept.data.quality import generate_soda_checks

EXTRACTED = datetime(2026, 10, 2, 23, 0, tzinfo=UTC)


# ----------------------------------------------------------------- contract
def test_contract_lists_all_twelve_protected_attributes(contract_yaml: dict[str, Any]) -> None:
    """Day-1 task: copy the 12 protected attributes from the data dictionary."""
    attrs = next(
        p["value"] for p in contract_yaml["customProperties"] if p["property"] == "protectedAttributes"
    )
    assert len(attrs) == 12 and len(set(attrs)) == 12


def test_load_contract_round_trip(contract_path: Path, contract_yaml: dict[str, Any]) -> None:
    c = load_data_contract(contract_path)
    assert c.version == contract_yaml["version"]
    assert "gender_code" in c.protected_attributes
    assert "gold.c360_restricted" in c.restricted_tables
    assert "gold.c360_customer" in c.ask_allowed_tables
    names = [col.name for col in c.table_columns("gold.c360_customer")]
    assert names[0] == "golden_customer_id" and "hardship_status" in names


def test_contract_sensitivity_queries(contract_path: Path) -> None:
    c = load_data_contract(contract_path)
    assert c.columns_with(Sensitivity.DIRECT_PII) == {"display_name", "primary_phone_e164", "email"}
    assert len(c.protected_attributes) == 12
    assert "customers.first_name" in c.direct_pii_columns and "agent_notes.note_text" in c.direct_pii_columns
    assert "customers.postal_code" in c.quasi_identifier_columns
    blocked = c.ask_blocked_columns()
    assert {
        "gender_code",
        "ccb_deposit_flag",
        "salutation",
        "display_name",
        "email",
        "first_name",
        "note_text",
        "sms_reply_text",
        "national_id_hash",
    } <= blocked
    assert not {"total_overdue", "current_dpd", "ptp_status", "primary_product"} & blocked


def test_contract_loader_rejects_malformed(tmp_path: Path, contract_yaml: dict[str, Any]) -> None:
    bad = dict(contract_yaml)
    bad.pop("schema")
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(bad))
    with pytest.raises(ValueError):
        load_data_contract(p)


def test_contract_loader_rejects_unknown_classification(
    tmp_path: Path, contract_yaml: dict[str, Any]
) -> None:
    bad = yaml.safe_load(yaml.safe_dump(contract_yaml))
    bad["schema"][0]["properties"][0]["classification"] = "top_secret"
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(bad))
    with pytest.raises(ValueError):
        load_data_contract(p)


def test_soda_checks_cover_every_rule_and_are_deterministic(contract_path: Path) -> None:
    c = load_data_contract(contract_path)
    a, b = generate_soda_checks(c), generate_soda_checks(c)
    assert a == b
    doc = yaml.safe_load(a)
    assert any("c360_customer" in k for k in doc)
    for rule in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        assert rule in a


# ----------------------------------------------------------------- db + bronze
def test_connect_creates_schemas(tmp_path: Path) -> None:
    conn = connect(tmp_path / "w.duckdb")
    have = {r[0] for r in conn.execute("select schema_name from information_schema.schemata").fetchall()}
    assert set(SCHEMAS) <= have


def test_land_file_keeps_raw_values_as_text(tmp_path: Path) -> None:
    raw = tmp_path / "crm_customers.csv"
    raw.write_text("customer_id,dob,phone\n001,03/04/1990,416-555-0123\n002,,\n")
    conn = duckdb.connect()
    landed = land_file(conn, raw, extracted_at=EXTRACTED)
    assert landed.table == "bronze.crm_customers" and landed.row_count == 2
    rows = conn.execute(
        "select customer_id, dob, _extracted_at from bronze.crm_customers order by 1"
    ).fetchall()
    assert rows[0][0] == "001"  # leading zeros preserved: everything lands as VARCHAR
    assert rows[0][1] == "03/04/1990"  # untouched; cleaning is silver's job
    types = dict(
        conn.execute(
            "select column_name, data_type from information_schema.columns where table_name = 'crm_customers'"
        ).fetchall()
    )
    assert types["customer_id"] == "VARCHAR" and "_source_file" in types and "_loaded_at" in types


def test_relanding_replaces_not_appends(tmp_path: Path) -> None:
    raw = tmp_path / "notes.csv"
    raw.write_text("note_id,text\n1,hello\n")
    conn = duckdb.connect()
    land_file(conn, raw, extracted_at=EXTRACTED)
    land_file(conn, raw, extracted_at=EXTRACTED)
    assert conn.execute("select count(*) from bronze.notes").fetchone() == (1,)


def test_parquet_by_year_lands_as_one_table(tmp_path: Path) -> None:
    conn = duckdb.connect()
    for year, n in ((2025, 2), (2026, 3)):
        d = tmp_path / "transactions" / f"year={year}"
        d.mkdir(parents=True)
        conn.execute(
            f"copy (select 'T' || i as txn_id, {year} as y from range({n}) r(i)) to '{d}/part.parquet' (format parquet)"
        )
    (tmp_path / "agents.csv").write_text("agent_id\nA-1\n")
    landed = {t.table: t.row_count for t in land_directory(conn, tmp_path, extracted_at=EXTRACTED)}
    assert landed == {"bronze.agents": 1, "bronze.transactions": 5}


def test_wav_files_are_not_landed(tmp_path: Path) -> None:
    (tmp_path / "voice_samples").mkdir()
    (tmp_path / "voice_samples" / "v1.wav").write_bytes(b"RIFF....WAVE")
    (tmp_path / "voice_samples.csv").write_text("voice_sample_id,file_path\nV-1,voice_samples/v1.wav\n")
    conn = duckdb.connect()
    assert [t.table for t in land_directory(conn, tmp_path, extracted_at=EXTRACTED)] == [
        "bronze.voice_samples"
    ]


def test_land_directory_sorted(tmp_path: Path) -> None:
    for name in ("b_table", "a_table"):
        (tmp_path / f"{name}.csv").write_text("x\n1\n")
    conn = duckdb.connect()
    assert [t.table for t in land_directory(conn, tmp_path, extracted_at=EXTRACTED)] == [
        "bronze.a_table",
        "bronze.b_table",
    ]
