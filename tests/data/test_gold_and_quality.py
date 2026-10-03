"""Gold derivations (consent, contact flags) and the five quality rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from kept.contracts import ContactPermissions, HardStop
from kept.data.gold import derive_contact_flags, hard_stop_flags, merge_contact_permissions
from kept.data.quality import (
    QualityResult,
    Status,
    check_contact_safety,
    check_freshness,
    check_linkage,
    check_match_safety,
    check_review_precision,
    check_row_count,
    check_unique_ids,
    quality_report,
    run_gate,
)

T0 = datetime(2026, 10, 3, 4, 0, tzinfo=UTC)
ALL = ContactPermissions(call=True, sms=True, email=True, push=True)


# ----------------------------------------------------------------- consent
def test_consent_most_restrictive_across_duplicates() -> None:
    a = ContactPermissions(call=True, sms=True, email=False, push=True)
    b = ContactPermissions(call=True, sms=False, email=True, push=True)
    assert merge_contact_permissions([a, b]) == ContactPermissions(
        call=True, sms=False, email=False, push=True
    )


def test_unknown_consent_blocks_everything() -> None:
    assert merge_contact_permissions([ALL, None]) == ContactPermissions()
    assert merge_contact_permissions([]) == ContactPermissions()


perm = st.builds(
    ContactPermissions, call=st.booleans(), sms=st.booleans(), email=st.booleans(), push=st.booleans()
)


@given(st.lists(perm, min_size=1, max_size=6))
def test_merged_consent_never_more_permissive_than_any_record(records: list[ContactPermissions]) -> None:
    merged = merge_contact_permissions(records)
    for ch in ("call", "sms", "email", "push"):
        assert getattr(merged, ch) == all(getattr(r, ch) for r in records)


@given(st.lists(perm, min_size=1, max_size=6))
def test_merged_consent_is_order_independent(records: list[ContactPermissions]) -> None:
    assert merge_contact_permissions(records) == merge_contact_permissions(list(reversed(records)))


# ----------------------------------------------------------------- contact flags
@pytest.mark.parametrize(
    "flags,expected",
    [
        ([{"internal_do_not_call_flag": True}], (True, False)),
        ([{"cease_communication_flag": True}], (True, False)),
        ([{"cease_contact_flag": True}], (True, False)),
        ([{"cease_request_flag": True}], (True, False)),
        ([{"consumer_proposal_flag": True}], (False, True)),
        ([{"insolvency_hold_flag": True}], (False, True)),
        ([{"bankruptcy_flag": True}], (False, True)),
        ([{"bankruptcy_on_file_flag": True}], (False, True)),
        ([{"deceased_flag": True}], (False, True)),
        ([{"deceased_indicator": True}], (False, True)),  # bureau
        ([{"internal_do_not_call_flag": False}, {"cease_contact_flag": True}], (True, False)),
        ([{"internal_do_not_call_flag": None, "deceased_flag": None}], (False, False)),
        ([{}], (False, False)),
        ([], (False, False)),
        ([{"cease_communication_flag": True, "bankruptcy_flag": True}], (True, True)),
    ],
)
def test_derive_contact_flags(flags: list[dict[str, bool | None]], expected: tuple[bool, bool]) -> None:
    assert derive_contact_flags(flags) == expected


def test_national_dncl_never_blocks_collections_contact() -> None:
    # DNCL covers telemarketing, not collections (design §9, dictionary description)
    assert derive_contact_flags([{"national_dncl_flag": True}]) == (False, False)
    assert hard_stop_flags([{"national_dncl_flag": True, "marketing_opt_out_flag": True}]) == frozenset()


def test_hard_stop_flags_collected_across_records() -> None:
    out = hard_stop_flags(
        [
            {"cease_communication_flag": True},
            {"deceased_hold_flag": True, "insolvency_hold_flag": False},
            {"internal_do_not_call_flag": True},  # do-not-call is not a hard stop, only do_not_contact
        ]
    )
    assert out == frozenset({HardStop.CEASE, HardStop.DECEASED})


def test_every_hard_stop_has_source_flags() -> None:
    from kept.data.gold import HARD_STOP_FLAGS

    assert set(HARD_STOP_FLAGS) == set(HardStop)
    assert all(HARD_STOP_FLAGS.values())


# ----------------------------------------------------------------- Q1 unique ids
def _xwalk(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["golden_customer_id", "source_system", "source_key"]).assign(
        valid_to=pd.NaT
    )


def test_q1_passes_on_clean_data() -> None:
    c360 = pd.DataFrame({"golden_customer_id": ["G-000001", "G-000002"]})
    xw = _xwalk([("G-000001", "crm", "1"), ("G-000002", "crm", "2")])
    assert check_unique_ids(c360, xw).status is Status.PASS


@pytest.mark.parametrize("ids", [["G-000001", "G-000001"], ["G-000001", None]])
def test_q1_blocks_duplicate_or_null_ids(ids: list[str | None]) -> None:
    c360 = pd.DataFrame({"golden_customer_id": ids})
    assert check_unique_ids(c360, _xwalk([])).status is Status.BLOCK


def test_q1_blocks_source_key_mapped_twice() -> None:
    c360 = pd.DataFrame({"golden_customer_id": ["G-000001", "G-000002"]})
    xw = _xwalk([("G-000001", "crm", "1"), ("G-000002", "crm", "1")])
    assert check_unique_ids(c360, xw).status is Status.BLOCK


def test_q1_ignores_retired_links() -> None:
    c360 = pd.DataFrame({"golden_customer_id": ["G-000001", "G-000002"]})
    xw = _xwalk([("G-000001", "crm", "1"), ("G-000002", "crm", "1")])
    xw.loc[0, "valid_to"] = pd.Timestamp(T0)
    assert check_unique_ids(c360, xw).status is Status.PASS


# ----------------------------------------------------------------- Q2 linkage
@pytest.mark.parametrize(
    "linked,status",
    [
        (1000, Status.PASS),
        (980, Status.PASS),
        (979, Status.WARN),
        (970, Status.WARN),
        (969, Status.BLOCK),
    ],
)
def test_q2_linkage_thresholds(linked: int, status: Status) -> None:
    assert check_linkage({"C-1"}, {"C-1"}, 1000, linked).status is status


def test_q2_unresolved_open_case_blocks_even_at_full_linkage() -> None:
    assert check_linkage({"C-1", "C-2"}, {"C-1"}, 10, 10).status is Status.BLOCK


def test_q2_nothing_loaded_blocks() -> None:
    assert check_linkage(set(), set(), 0, 0).status is Status.BLOCK


# ----------------------------------------------------------------- Q3 match safety
def test_q3_blocks_low_score_auto_link() -> None:
    xw = pd.DataFrame(
        {"golden_customer_id": ["G-000001"], "match_review_status": ["auto"], "match_score": [0.94]}
    )
    nid = pd.DataFrame({"golden_customer_id": ["G-000001"], "national_id_hash": ["h1"]})
    assert check_match_safety(xw, nid).status is Status.BLOCK


def test_q3_allows_steward_approved_low_score_and_exact_null_score() -> None:
    xw = pd.DataFrame(
        {
            "golden_customer_id": ["G-000001", "G-000002"],
            "match_review_status": ["steward_approved", "auto"],
            "match_score": [0.85, None],
        }
    )
    nid = pd.DataFrame({"golden_customer_id": ["G-000001", "G-000002"], "national_id_hash": ["h1", None]})
    assert check_match_safety(xw, nid).status is Status.PASS


def test_q3_blocks_two_national_ids_in_one_cluster() -> None:
    xw = pd.DataFrame(
        {"golden_customer_id": ["G-000001"], "match_review_status": ["auto"], "match_score": [0.99]}
    )
    nid = pd.DataFrame(
        {"golden_customer_id": ["G-000001", "G-000001", "G-000001"], "national_id_hash": ["h1", "h2", None]}
    )
    assert check_match_safety(xw, nid).status is Status.BLOCK


@pytest.mark.parametrize("tp,fp,status", [(98, 2, Status.PASS), (97, 3, Status.WARN)])
def test_q3_weekly_precision(tp: int, fp: int, status: Status) -> None:
    df = pd.DataFrame({"predicted_link": [True] * (tp + fp), "is_true_match": [True] * tp + [False] * fp})
    assert check_review_precision(df).status is status


# ----------------------------------------------------------------- Q4 contact safety
def test_q4_zero_violations_allowed() -> None:
    c360 = pd.DataFrame(
        {"golden_customer_id": ["G-000001"], "do_not_contact": [False], "collections_hold": [False]}
    )
    flags = pd.DataFrame({"golden_customer_id": ["G-000001"], "cease_contact_flag": [True]})
    r = check_contact_safety(c360, flags)
    assert r.status is Status.BLOCK and "G-000001" in r.detail


def test_q4_passes_when_flags_propagated() -> None:
    c360 = pd.DataFrame(
        {"golden_customer_id": ["G-000001"], "do_not_contact": [True], "collections_hold": [True]}
    )
    flags = pd.DataFrame(
        {
            "golden_customer_id": ["G-000001", "G-000001"],
            "cease_communication_flag": [True, False],
            "deceased_indicator": [None, True],
        }
    )
    assert check_contact_safety(c360, flags).status is Status.PASS


# ----------------------------------------------------------------- Q5 freshness / row count
@pytest.mark.parametrize(
    "age,status",
    [
        (timedelta(hours=0), Status.PASS),
        (timedelta(hours=26), Status.PASS),
        (timedelta(hours=26, seconds=1), Status.WARN),
        (timedelta(hours=47, minutes=59), Status.WARN),
        (timedelta(hours=48), Status.BLOCK),
        (timedelta(days=5), Status.BLOCK),
    ],
)
def test_q5_freshness(age: timedelta, status: Status) -> None:
    assert check_freshness(T0, T0 + age).status is status


def test_q5_freshness_rejects_naive_and_time_travel() -> None:
    with pytest.raises(ValueError):
        check_freshness(datetime(2026, 10, 3), T0)
    with pytest.raises(ValueError):
        check_freshness(T0, T0 - timedelta(seconds=1))


@pytest.mark.parametrize(
    "current,previous,status",
    [
        (100, None, Status.PASS),
        (100, 100, Status.PASS),
        (110, 100, Status.PASS),
        (90, 100, Status.PASS),
        (111, 100, Status.WARN),
        (89, 100, Status.WARN),
        (5, 0, Status.WARN),
    ],
)
def test_q5_row_count(current: int, previous: int | None, status: Status) -> None:
    assert check_row_count(current, previous).status is status


# ----------------------------------------------------------------- gate
def test_q4_ignores_dncl() -> None:
    c360 = pd.DataFrame(
        {"golden_customer_id": ["G-000001"], "do_not_contact": [False], "collections_hold": [False]}
    )
    flags = pd.DataFrame({"golden_customer_id": ["G-000001"], "national_dncl_flag": [True]})
    assert check_contact_safety(c360, flags).status is Status.PASS


def test_quality_report_is_markdown_and_deterministic() -> None:
    results = [
        QualityResult("Q2-linkage", Status.WARN, "97.5% linked"),
        QualityResult("Q1-unique-ids", Status.PASS, "ok"),
    ]
    a = quality_report(results, contract_version="1.0.0", as_of=T0)
    assert a == quality_report(results, contract_version="1.0.0", as_of=T0)
    assert "1.0.0" in a and "warn" in a.lower() and "97.5% linked" in a
    assert a.index("Q1-unique-ids") < a.index("Q2-linkage")  # rule order
    assert "|" in a  # a table


def test_gate_worst_status_wins() -> None:
    p, w, b = (QualityResult("x", s, "") for s in (Status.PASS, Status.WARN, Status.BLOCK))
    assert run_gate([p, p]) is Status.PASS
    assert run_gate([p, w]) is Status.WARN
    assert run_gate([w, b, p]) is Status.BLOCK
    assert run_gate([]) is Status.BLOCK
