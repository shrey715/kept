"""The match step end to end on a tiny silver (integration: needs `uv sync --extra data`)."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from kept.data.identity.pipeline import run_matching

pytestmark = [pytest.mark.integration, pytest.mark.slow]

COLS = ["source_system", "source_key", "name_key", "first_name_key", "dob", "phone_e164", "postal_code"]


def _person(
    system: str, key: str, name: str, dob: str, phone: str, postal: str, nid: str | None = None
) -> dict:
    return {
        "source_system": system,
        "source_key": key,
        "name_key": name,
        "first_name_key": None,
        "dob": dob,
        "phone_e164": phone,
        "postal_code": postal,
        "national_id_hash": nid,
    }


def _evidence(records: pd.DataFrame) -> pd.DataFrame:
    ev = records[["source_system", "source_key", "national_id_hash"]].copy()
    for col in (
        "crm_ref",
        "payment_source_account",
        "deposit_account_id",
        "duplicate_of_crm_id",
        "core_banking_cif",
    ):
        ev[col] = None
    return ev


@pytest.fixture
def silver() -> duckdb.DuckDBPyConnection:
    rows = [
        # one person in two systems, no exact key: only Splink can link them
        _person("crm", "C1", "doe j", "1990-04-03", "+14165550123", "M5V 3L9"),
        _person("loan", "L1", "doe j", "1990-04-03", "+14165550123", "M5V 3L9"),
        # twins: same surname, DOB, postal code and phone, two national IDs -> held, never auto-linked
        _person("crm", "T1", "kim a", "1985-06-01", "+16045550100", "V6B 1A1", "nid-a"),
        _person("crm", "T2", "kim a", "1985-06-01", "+16045550100", "V6B 1A1", "nid-b"),
    ]
    rows += [
        _person(
            "crm",
            f"F{i}",
            f"person{i} a",
            f"19{50 + i % 40}-0{1 + i % 9}-1{i % 9}",
            f"+1416555{1000 + i}",
            "K1A 0B1",
        )
        for i in range(200)
    ]
    records = pd.DataFrame(rows)
    ev = _evidence(records)
    ev.loc[ev.source_key == "T1", "duplicate_of_crm_id"] = (
        "T2"  # an exact link: the cluster has two national IDs
    )
    conn = duckdb.connect()
    conn.execute("create schema silver")
    conn.register("records_df", records[[*COLS, "national_id_hash"]])
    conn.register("evidence_df", ev)
    conn.execute("create table silver.int_identity_records as select * from records_df")
    conn.execute("create table silver.int_identity_evidence as select * from evidence_df")
    return conn


def test_match_run_links_holds_and_assigns_ids(silver: duckdb.DuckDBPyConnection) -> None:
    pytest.importorskip("splink")
    run = run_matching(silver)
    cw = run.crosswalk.set_index(["source_system", "source_key"])
    assert list(run.crosswalk.columns) == [
        "golden_customer_id", "source_system", "source_key", "match_score",
        "match_rule", "match_review_status", "linked_at", "valid_to",
    ]  # fmt: skip
    assert cw.loc[("crm", "C1"), "golden_customer_id"] == cw.loc[("loan", "L1"), "golden_customer_id"]
    assert (
        cw.loc[("loan", "L1"), "match_rule"] == "splink"
        and cw.loc[("loan", "L1"), "match_review_status"] == "auto"
    )
    t1, t2 = cw.loc[("crm", "T1")], cw.loc[("crm", "T2")]
    assert t1["golden_customer_id"] != t2["golden_customer_id"]  # two national IDs: not merged
    assert t1["match_review_status"] == t2["match_review_status"] == "unlinked"
    assert run.summary["held_clusters"] == 1
    assert (run.review_pairs["rule"] == "held_cluster").sum() == 1
    held = run.review_pairs[run.review_pairs["rule"] == "held_cluster"]
    assert held["score"].notna().all() and held["score"].between(0, 1).all()  # the cluster's weakest link


def test_previous_crosswalk_keeps_golden_ids(silver: duckdb.DuckDBPyConnection) -> None:
    pytest.importorskip("splink")
    first = run_matching(silver)
    second = run_matching(silver, previous=first.crosswalk)
    assert first.crosswalk["golden_customer_id"].tolist() == second.crosswalk["golden_customer_id"].tolist()
