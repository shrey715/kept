"""The steward's review sample, and how the gate reads the reviewed file."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from kept.data.gate import review_result
from kept.data.identity.review_sample import review_sample
from kept.data.quality import Status


def _warehouse() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect()
    conn.execute("create schema silver")
    conn.execute(
        """create table silver.int_identity_records as select * from (values
            ('crm', 'C1', 'doe j', 'jane', '1990-04-03', '+14165550123', 'M5V 3L9'),
            ('loan', 'L1', 'doe j', 'jane', '1990-04-03', '+14165550123', 'M5V 3L9'),
            ('deposit', 'D1', 'doe j', null, '1990-04-03', '+14165550123', 'M5V 3L9'),
            ('card', 'K9', 'roe k', null, '1985-01-01', null, 'K1A 0B1'),
            ('bureau', 'B9', 'roe k', 'kim', '1985-01-01', null, 'K1A 0B1'))
            t(source_system, source_key, name_key, first_name_key, dob, phone_e164, postal_code)"""
    )
    return conn


def _crosswalk() -> pd.DataFrame:
    rows = [
        ("G-1", "crm", "C1", None, "exact:case_crm_ref", "auto"),
        ("G-1", "collections", "C1", None, "exact:case_crm_ref", "auto"),  # no attributes: left out
        ("G-1", "loan", "L1", 0.99, "splink", "auto"),
        ("G-1", "deposit", "D1", None, "exact:payment_source_account", "auto"),
        ("G-2", "card", "K9", None, "exact:core_banking_cif", "auto"),  # the anchor: no CRM key, smallest key
        ("G-2", "bureau", "B9", None, "exact:core_banking_cif", "auto"),
        ("G-3", "crm", "ALONE", None, "singleton", "unlinked"),  # not linked: not a predicted link
    ]
    frame = pd.DataFrame(
        rows,
        columns=[
            "golden_customer_id",
            "source_system",
            "source_key",
            "match_score",
            "match_rule",
            "match_review_status",
        ],
    )
    return frame.assign(valid_to=pd.NaT)


def test_sample_pairs_each_linked_key_with_its_cluster_anchor() -> None:
    out = review_sample(_warehouse(), _crosswalk(), n=10)
    pairs = {(r.left_system, r.left_key, r.right_system, r.right_key) for r in out.itertuples()}
    assert pairs == {
        ("loan", "L1", "crm", "C1"),  # the anchor is the CRM key
        ("deposit", "D1", "crm", "C1"),
        ("card", "K9", "bureau", "B9"),  # no CRM key: the smallest (system, key), and bureau sorts first
    }
    assert len(out) == 3 and out["pair_id"].tolist() == ["MP-001", "MP-002", "MP-003"]
    assert out["predicted_link"].all() and (out["is_true_match"] == "").all()  # a person answers these
    shown = out[out["left_key"] == "L1"].iloc[0]
    assert shown["left_dob"] == "1990-04-03" and shown["right_name_key"] == "doe j"


def test_sample_is_reproducible_and_proportional_to_the_kind_of_link() -> None:
    a = review_sample(_warehouse(), _crosswalk(), n=2, seed=1)
    b = review_sample(_warehouse(), _crosswalk(), n=2, seed=1)
    assert a["pair_id"].tolist() == b["pair_id"].tolist() and a["left_key"].tolist() == b["left_key"].tolist()
    assert len(a) == 2
    assert set(review_sample(_warehouse(), _crosswalk(), n=10)["stratum"]) == {"splink", "exact"}


def _file(tmp_path: Path, answers: list[str]) -> Path:
    path = tmp_path / "match_pairs.csv"
    pd.DataFrame({"pair_id": range(len(answers)), "is_true_match": answers}).to_csv(path, index=False)
    return path


def test_gate_counts_only_the_pairs_a_person_has_answered(tmp_path: Path) -> None:
    assert review_result(_file(tmp_path, ["", "", ""])).status is Status.WARN  # nothing reviewed yet
    done = review_result(_file(tmp_path, ["true"] * 49 + ["false"] + [""] * 10))  # 49/50 = 98%
    assert done.status is Status.PASS and "50 of 60 pairs reviewed" in done.detail
    low = review_result(_file(tmp_path, ["yes"] * 9 + ["no"]))
    assert low.status is Status.WARN and "90.0%" in low.detail
    typo = review_result(_file(tmp_path, ["true", "maybe"]))
    assert "1 unreadable" in typo.detail and "1 of 2 pairs reviewed" in typo.detail
