"""Run the generated Soda checks on a tiny warehouse: clean data passes, every kind of break fails
(integration: needs `uv sync --extra data`)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from kept.contracts.data_contract import load_data_contract
from kept.data.quality import generate_soda_checks

pytestmark = [pytest.mark.integration, pytest.mark.slow]

REQUIRED = (
    "source_keys", "match_review_status", "total_overdue", "max_dpd", "current_bucket", "contact_permissions",
    "do_not_contact", "collections_hold", "hardship_status", "payroll_frequency_detected", "as_of_date",
    "refreshed_at",
)  # fmt: skip


def _warehouse(path: Path, *, broken: bool) -> None:
    conn = duckdb.connect(str(path))
    for schema in ("gold", "silver"):
        conn.execute(f"create schema {schema}")
    ids = "['G-000001', 'G-000001']" if broken else "['G-000001', 'G-000002']"
    cols = ", ".join(
        f"1 as {c}" for c in REQUIRED if c not in ("do_not_contact", "collections_hold", "refreshed_at")
    )
    conn.execute(
        f"create table gold.c360_customer as select unnest({ids}) as golden_customer_id, {cols}, "
        f"false as do_not_contact, false as collections_hold, now() as refreshed_at"
    )
    score = "0.90" if broken else "0.99"
    conn.execute(
        f"""create table gold.identity_crosswalk as select * from (values
            ('G-000001', 'crm', 'C1', {score}, 'splink', 'auto', null::timestamp),
            ('G-000002', 'collections', 'C2', null, 'exact:case_crm_ref', 'auto', null::timestamp))
            t(golden_customer_id, source_system, source_key, match_score, match_rule, match_review_status, valid_to)"""
    )
    # an open case whose customer key is in the crosswalk, or (broken) is not
    case_ref = "'NOBODY'" if broken else "'C2'"
    conn.execute(
        f"create table silver.collections_cases as select 'CS-1' as case_id, {case_ref} as coll_customer_ref, null::varchar as outcome"
    )
    nid = "('crm', 'C1', 'h1'), ('crm', 'C1', 'h2')" if broken else "('crm', 'C1', 'h1')"
    conn.execute(
        f"create table silver.int_identity_records as select * from (values {nid}) t(source_system, source_key, national_id_hash)"
    )
    flags = (
        "true" if broken else "false"
    )  # a source do-not-call that never reached gold (do_not_contact is false)
    conn.execute(
        f"create table silver.int_source_flags as select 'G-000001' as golden_customer_id, "
        f"{flags} as any_do_not_contact, false as any_collections_hold"
    )
    conn.close()


def _scan(path: Path) -> tuple[list[str], list[str]]:
    from soda.scan import Scan

    scan = Scan()
    scan.set_scan_definition_name("test")
    scan.set_data_source_name("kept")
    scan.add_configuration_yaml_str(f"data_source kept:\n  type: duckdb\n  path: {path}\n")
    scan.add_sodacl_yaml_str(generate_soda_checks(load_data_contract()))
    scan.execute()
    names = [c.name for c in scan._checks]
    failed = [c.name for c in scan._checks if c.outcome is not None and c.outcome.value == "fail"]
    return names, failed


def test_clean_data_passes_every_check(tmp_path: Path) -> None:
    pytest.importorskip("soda.scan")
    _warehouse(tmp_path / "ok.duckdb", broken=False)
    names, failed = _scan(tmp_path / "ok.duckdb")
    assert len(names) >= 20 and failed == []


def test_each_kind_of_break_fails_its_rule(tmp_path: Path) -> None:
    pytest.importorskip("soda.scan")
    _warehouse(tmp_path / "bad.duckdb", broken=True)
    _, failed = _scan(tmp_path / "bad.duckdb")
    for rule in (
        "Q1-unique-ids: no duplicated",
        "Q2-linkage",
        "Q3-match-safety: an auto link",
        "Q3-match-safety: a cluster",
        "Q4-contact-safety",
    ):
        assert any(f.startswith(rule) for f in failed), rule
