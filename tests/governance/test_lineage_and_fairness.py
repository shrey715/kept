"""Protected-attribute lineage CI test and Fairlearn-style recommendation rate checks."""

from __future__ import annotations

import pytest

from kept.contracts import Sensitivity
from kept.contracts.data_contract import ColumnSpec, DataContract
from kept.contracts.feature_registry import FEATURES, FeatureOrigin, FeatureSpec
from kept.governance.fairness import recommendation_rates
from kept.governance.lineage import lineage_violations

pytestmark = pytest.mark.track_b  # governance/ defaults to track_c; this file is Track B's (plan §1)


@pytest.fixture
def contract() -> DataContract:
    """Built by hand so Track C doesn't wait on Track A's loader."""
    return DataContract(
        version="1.0.0",
        columns=(
            ColumnSpec("gold.c360_restricted", "gender_code", "string", Sensitivity.PROTECTED, False, ""),
        ),
        protected_attributes=frozenset(
            {
                "gender_code",
                "marital_status",
                "citizenship_status",
                "household_size",
                "dependants_count",
                "newcomer_program_flag",
                "newcomer_arrival_date",
                "accessibility_needs_flag",
                "accessibility_type",
                "vulnerability_type",
                "ccb_deposit_flag",
                "customer_accent_region",
            }
        ),
        proxy_attributes=frozenset(
            {
                "age",
                "age_band",
                "date_of_birth",
                "postal_code",
                "fsa",
                "salutation",
                "preferred_language",
                "ei_deposit_flag",
                "cpp_oas_deposit_flag",
                "customer_pitch_mean_hz",
            }
        ),
        restricted_tables=frozenset({"gold.c360_restricted"}),
        ask_allowed_tables=frozenset(),
    )


def spec(name: str, *cols: str) -> FeatureSpec:
    return FeatureSpec(name, "float", FeatureOrigin.SQL, cols, "D", "test")


# ----------------------------------------------------------------- THE CI test
def test_registered_features_have_clean_lineage(contract: DataContract) -> None:
    """Fails the build if any registered feature comes from a protected attribute or proxy."""
    assert lineage_violations(FEATURES, contract) == []


def test_registered_features_have_clean_lineage_under_the_real_contract() -> None:
    """The same CI check against the contract A ships, so a contract change can't hide a leak."""
    from kept.contracts.data_contract import load_data_contract

    assert lineage_violations(FEATURES, load_data_contract()) == []


# ----------------------------------------------------------------- detector
@pytest.mark.parametrize(
    "cols,kind",
    [
        (("silver.customers.gender_code",), "protected"),
        (("silver.customers.GENDER_CODE",), "protected"),
        (("silver.customers.marital_status",), "protected"),
        (("silver.deposit_accounts.ccb_deposit_flag",), "protected"),
        (("silver.voice_samples.customer_accent_region",), "protected"),
        (("silver.customers.postal_code",), "proxy"),
        (("silver.customers.salutation",), "proxy"),
        (("silver.customers.date_of_birth",), "proxy"),
        (("silver.deposit_accounts.ei_deposit_flag",), "proxy"),
        (("silver.voice_samples.customer_pitch_mean_hz",), "proxy"),
        (("gold.c360_customer.preferred_language",), "proxy"),
        (("gold.c360_restricted.golden_customer_id",), "restricted_table"),
        (("silver.collections_cases.dpd_at_day_30",), "outcome"),
        (("silver.collections_cases.cure_flag",), "outcome"),
        (("silver.collections_cases.test_cell",), "outcome"),
        (("silver.collections_cases.nba_recommendation_last",), "outcome"),
        (("silver.collections_cases.hardship_reason",), "stated_reason"),
        (("silver.promises_to_pay.broken_reason_agent_coded",), "stated_reason"),
    ],
)
def test_violation_detected(contract: DataContract, cols: tuple[str, ...], kind: str) -> None:
    v = lineage_violations([spec("f", "silver.ok.dpd", *cols)], contract)
    assert [x.kind for x in v] == [kind]
    assert v[0].feature == "f" and v[0].source_column == cols[0]


def test_cohort_features_may_aggregate_past_outcomes(contract: DataContract) -> None:
    cohort = FeatureSpec(
        "cohort_x", "float", FeatureOrigin.COHORT, ("silver.collections_cases.cure_flag",), "D", "t"
    )
    assert lineage_violations([cohort], contract) == []
    leaky = FeatureSpec(
        "cohort_y", "float", FeatureOrigin.COHORT, ("silver.customers.gender_code",), "D", "t"
    )
    assert [v.kind for v in lineage_violations([leaky], contract)] == ["protected"]


def test_feature_named_after_a_proxy_is_a_violation(contract: DataContract) -> None:
    v = lineage_violations([spec("age", "silver.ok.dpd")], contract)
    assert v and v[0].kind == "proxy"


def test_substring_is_not_a_match(contract: DataContract) -> None:
    # "usage" contains "age", "postal_code_valid_flag" is not "postal_code"
    assert (
        lineage_violations([spec("payment_link_usage", "silver.contact_history.link_usage")], contract) == []
    )


def test_every_violation_reported(contract: DataContract) -> None:
    v = lineage_violations([spec("a", "s.t.gender_code"), spec("b", "s.t.age", "s.t.postal_code")], contract)
    assert sorted((x.feature, x.attribute) for x in v) == [
        ("a", "gender_code"),
        ("b", "age"),
        ("b", "postal_code"),
    ]


# ----------------------------------------------------------------- fairness
def test_rates_and_ratio() -> None:
    rec = [True] * 30 + [False] * 70 + [True] * 20 + [False] * 80
    grp = ["a"] * 100 + ["b"] * 100
    r = recommendation_rates(rec, grp)
    assert r.rates == {"a": pytest.approx(0.3), "b": pytest.approx(0.2)}
    assert r.min_ratio == pytest.approx(2 / 3) and r.flagged


def test_close_rates_not_flagged() -> None:
    rec = [True] * 50 + [False] * 50 + [True] * 45 + [False] * 55
    r = recommendation_rates(rec, ["a"] * 100 + ["b"] * 100)
    assert r.min_ratio == pytest.approx(0.9) and not r.flagged


def test_equal_rates() -> None:
    r = recommendation_rates([True, False] * 20 + [True, False] * 20, ["a"] * 40 + ["b"] * 40)
    assert r.min_ratio == pytest.approx(1.0) and not r.flagged


def test_small_groups_skipped() -> None:
    r = recommendation_rates([True] * 20 + [False] * 3, ["a"] * 20 + ["tiny"] * 3)
    assert "tiny" not in r.rates and r.groups_skipped == ("tiny",)


def test_all_zero_rates() -> None:
    r = recommendation_rates([False] * 40, ["a"] * 20 + ["b"] * 20)
    assert r.min_ratio == 1.0 and not r.flagged


def test_length_mismatch() -> None:
    with pytest.raises(ValueError):
        recommendation_rates([True], ["a", "b"])


# ----------------------------------------------------------------- the report on scored cards
def _frames():  # type: ignore[no-untyped-def]
    import pandas as pd

    ids = [f"G-{i}" for i in range(200)]
    # group a: 100 customers, 60 get a call; group b: 100 customers, 30 get a call, 20 wait; 5 have no match
    actions = ["call"] * 60 + ["email"] * 40 + ["call"] * 30 + ["wait"] * 20 + [None] * 50
    cards = pd.DataFrame({"golden_customer_id": ids, "action": actions})
    restricted = pd.DataFrame(
        {
            "golden_customer_id": ids[:195],
            "gender_code": ["a"] * 100 + ["b"] * 95,
            "household_size": range(195),
        }
    )
    return cards, restricted


def test_fairness_report_flags_a_gap_and_names_the_group() -> None:
    from kept.governance.fairness import fairness_report

    cards, restricted = _frames()
    text = fairness_report(
        cards, restricted, ["gender_code", "household_size", "not_a_column"], min_group_size=10
    )
    assert "### gender_code" in text and "FLAG" in text  # b gets a call 30% of the time, a 60%: ratio ~0.5
    assert "| a | 100 | 100.0% | 60.0% |" in text  # any contact action, call, then hardship review
    assert "blank, not compared" in text  # the 5 cases with no protected attributes: reported, not a group
    assert "unknown" not in text
    assert "household_size" not in text.split("## Rates by group")[1]  # 195 distinct values: skipped
    assert "not_a_column" not in text


def test_fairness_report_does_not_compare_tiny_groups() -> None:
    from kept.governance.fairness import fairness_report

    cards, restricted = _frames()
    text = fairness_report(cards, restricted, ["gender_code"], min_group_size=96)
    assert "n/a (too few)" in text  # the 5-case "unknown" group and group b (95) are under 96
