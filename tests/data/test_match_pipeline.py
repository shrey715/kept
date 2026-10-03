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


# ----------------------------------------------------------------- the stewards' verdicts
def _verdicts(*rows: tuple[str, str, str, str, str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["left_system", "left_key", "right_system", "right_key", "verdict"])


def _status(run, system: str, key: str) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    row = run.crosswalk.set_index(["source_system", "source_key"]).loc[(system, key)]
    return row["match_rule"], row["match_review_status"]


def _golden(run, system: str, key: str) -> str:  # type: ignore[no-untyped-def]
    return run.crosswalk.set_index(["source_system", "source_key"]).loc[(system, key), "golden_customer_id"]


def test_different_people_verdict_cuts_a_splink_link(silver: duckdb.DuckDBPyConnection) -> None:
    pytest.importorskip("splink")
    before = run_matching(silver, verdicts=_verdicts())
    assert _golden(before, "crm", "C1") == _golden(before, "loan", "L1")
    after = run_matching(silver, verdicts=_verdicts(("crm", "C1", "loan", "L1", "different_people")))
    assert _golden(after, "crm", "C1") != _golden(after, "loan", "L1")
    assert after.summary["steward_cuts"] == 1


def test_same_person_verdict_links_any_pair_as_steward_approved(silver: duckdb.DuckDBPyConnection) -> None:
    pytest.importorskip("splink")
    run = run_matching(silver, verdicts=_verdicts(("crm", "F3", "crm", "F4", "same_person")))
    assert _golden(run, "crm", "F3") == _golden(run, "crm", "F4")
    assert _status(run, "crm", "F3") == ("steward:same_person", "steward_approved")
    assert run.summary["steward_links"] == 1


def _add_duplicate_chain(conn: duckdb.DuckDBPyConnection, n: int) -> None:
    """n CRM records that CRM's own duplicate pointer joins into one cluster, with distinct names/DOBs."""
    for i in range(n):
        conn.execute(
            "insert into silver.int_identity_records values ('crm', ?, ?, null, ?, ?, ?, null)",
            [f"B{i:02d}", f"big{i} b", f"1970-02-{i + 1:02d}", f"+1905555{2000 + i}", "H0H 0H0"],
        )
        conn.execute(
            "insert into silver.int_identity_evidence values ('crm', ?, null, null, null, null, ?, null)",
            [f"B{i:02d}", None if i == 0 else "B00"],
        )


def test_same_person_verdict_releases_a_member_of_a_too_big_cluster(
    silver: duckdb.DuckDBPyConnection,
) -> None:
    pytest.importorskip("splink")
    _add_duplicate_chain(silver, 13)  # 13 keys: over the limit of 12, held with no national ID involved
    held = run_matching(silver, verdicts=_verdicts())
    assert held.summary["held_reasons"]["too_many_keys"] == 1  # type: ignore[index]
    assert _golden(held, "crm", "B03") != _golden(held, "crm", "B00")
    released = run_matching(silver, verdicts=_verdicts(("crm", "B03", "crm", "B00", "same_person")))
    assert _golden(released, "crm", "B03") == _golden(released, "crm", "B00")
    assert _status(released, "crm", "B03")[1] == "steward_approved"
    assert _golden(released, "crm", "B05") != _golden(released, "crm", "B00")  # the others stay apart


def test_same_person_verdict_cannot_release_a_two_national_id_cluster(
    silver: duckdb.DuckDBPyConnection,
) -> None:
    pytest.importorskip("splink")
    run = run_matching(silver, verdicts=_verdicts(("crm", "T2", "crm", "T1", "same_person")))
    assert _golden(run, "crm", "T1") != _golden(run, "crm", "T2")  # Q3: no cluster holds two national IDs
    assert _status(run, "crm", "T1")[1] == "unlinked"


def test_a_cut_that_other_links_undo_holds_the_cluster(silver: duckdb.DuckDBPyConnection) -> None:
    pytest.importorskip("splink")
    _add_duplicate_chain(silver, 3)  # B00 - B01, B00 - B02: B01 and B02 are joined only through B00
    run = run_matching(silver, verdicts=_verdicts(("crm", "B01", "crm", "B02", "different_people")))
    # no direct link between B01 and B02 to cut, and they are still in one cluster: held
    assert run.summary["held_reasons"]["steward_cannot_link"] == 1  # type: ignore[index]
    assert _golden(run, "crm", "B01") != _golden(run, "crm", "B02")
