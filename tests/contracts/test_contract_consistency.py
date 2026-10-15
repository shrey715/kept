"""The same contract is written in four places: the ODCS YAML, the pydantic models,
the dbt gold schema, and the feature registry. These tests keep them in lockstep."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from kept import config
from kept.contracts import CrosswalkEntry, FeatureVector, GoldenCustomer
from kept.contracts.feature_registry import (
    FEATURES,
    OUTCOME_DENY_LIST,
    STATED_REASON_FIELDS,
    FeatureOrigin,
)


def _schema(contract: dict[str, Any], name: str) -> dict[str, Any]:
    return next(s for s in contract["schema"] if s["name"] == name)


def _custom(contract: dict[str, Any], prop: str) -> list[str]:
    return next(p["value"] for p in contract["customProperties"] if p["property"] == prop)


def _contract_columns(contract: dict[str, Any], name: str) -> list[str]:
    return [p["name"] for p in _schema(contract, name)["properties"]]


def _dbt_columns(repo_root: Path, model: str) -> list[str]:
    with (repo_root / "dbt" / "models" / "gold" / "schema.yml").open() as fh:
        doc = yaml.safe_load(fh)
    m = next(m for m in doc["models"] if m["name"] == model)
    return [c["name"] for c in m["columns"]]


def _sql_columns(repo_root: Path, model: str) -> list[str]:
    sql = (repo_root / "dbt" / "models" / "gold" / f"{model}.sql").read_text()
    return re.findall(r"\bas\s+([a-z_0-9]+)\s*,?\s*$", sql, flags=re.MULTILINE)


# ----------------------------------------------------------------- ODCS shape
def test_contract_has_required_odcs_sections(contract_yaml: dict[str, Any]) -> None:
    for key in (
        "apiVersion",
        "kind",
        "id",
        "version",
        "status",
        "schema",
        "quality",
        "team",
        "customProperties",
    ):
        assert key in contract_yaml, key
    assert contract_yaml["kind"] == "DataContract"
    assert re.fullmatch(r"\d+\.\d+\.\d+", contract_yaml["version"])


def test_contract_quality_rules_are_q1_to_q5(contract_yaml: dict[str, Any]) -> None:
    ids = [q["id"] for q in contract_yaml["quality"]]
    assert [i.split("-")[0] for i in ids] == ["Q1", "Q2", "Q3", "Q4", "Q5"]


def test_contract_classifications_are_known(contract_yaml: dict[str, Any]) -> None:
    allowed = {"internal", "direct_pii", "quasi_identifier", "sensitive", "protected"}
    for s in contract_yaml["schema"]:
        for p in s["properties"]:
            assert p["classification"] in allowed, (s["name"], p["name"])


def test_protected_columns_live_only_in_restricted_table(contract_yaml: dict[str, Any]) -> None:
    for s in contract_yaml["schema"]:
        protected = [p["name"] for p in s["properties"] if p["classification"] == "protected"]
        if s["physicalName"] != "gold.c360_restricted":
            assert protected == [], s["name"]


def test_restricted_table_is_not_askable(contract_yaml: dict[str, Any]) -> None:
    restricted = set(_custom(contract_yaml, "restrictedTables"))
    assert "gold.c360_restricted" in restricted
    assert not restricted & set(_custom(contract_yaml, "askAllowedTables"))


def test_known_protected_and_proxy_attributes_are_listed(contract_yaml: dict[str, Any]) -> None:
    protected = _custom(contract_yaml, "protectedAttributes")
    assert len(protected) == 12 and len(set(protected)) == 12
    assert "gender_code" in protected
    proxies = set(_custom(contract_yaml, "proxyAttributes"))
    # design §9: age, postal code, language, benefit flags, voice; plus salutation (a gender proxy)
    assert {
        "age",
        "date_of_birth",
        "postal_code",
        "fsa",
        "preferred_language",
        "salutation",
        "ei_deposit_flag",
        "cpp_oas_deposit_flag",
        "customer_pitch_mean_hz",
    } <= proxies
    assert not proxies & set(protected)


def test_restricted_table_holds_every_protected_attribute(contract_yaml: dict[str, Any]) -> None:
    cols = _contract_columns(contract_yaml, "c360_restricted")
    assert cols[0] == "golden_customer_id"
    assert set(cols[1:]) == set(_custom(contract_yaml, "protectedAttributes"))


def test_ask_tables_never_include_protected_sources(contract_yaml: dict[str, Any]) -> None:
    allowed = set(_custom(contract_yaml, "askAllowedTables"))
    # text.redacted_notes (Presidio-redacted notes and call transcripts) is the one table outside silver and gold
    assert all(t.startswith(("silver.", "gold.")) or t == "text.redacted_notes" for t in allowed)
    assert "silver.voice_samples" not in allowed and "silver.customers" not in allowed


def test_no_column_is_both_a_c360_column_and_protected(contract_yaml: dict[str, Any]) -> None:
    protected = set(_custom(contract_yaml, "protectedAttributes"))
    assert not protected & set(_contract_columns(contract_yaml, "c360_customer"))


# ----------------------------------------------------------------- YAML == pydantic == dbt
def test_c360_yaml_matches_pydantic(contract_yaml: dict[str, Any]) -> None:
    assert _contract_columns(contract_yaml, "c360_customer") == list(GoldenCustomer.model_fields)


def test_c360_required_flags_match_pydantic(contract_yaml: dict[str, Any]) -> None:
    for p in _schema(contract_yaml, "c360_customer")["properties"]:
        field = GoldenCustomer.model_fields[p["name"]]
        assert field.is_required() == p["required"] or (
            # pydantic gives these a default but they are never null in gold
            p["name"] == "payroll_frequency_detected"
        ), p["name"]


def test_crosswalk_yaml_matches_pydantic(contract_yaml: dict[str, Any]) -> None:
    yaml_cols = _contract_columns(contract_yaml, "identity_crosswalk")
    model_cols = [c for c in CrosswalkEntry.model_fields if c != "source_key"]
    # source_key (a SourceKey) is stored as two columns
    assert set(yaml_cols) == set(model_cols) | {"source_system", "source_key"}


@pytest.mark.parametrize("model", ["c360_customer", "identity_crosswalk", "c360_restricted"])
def test_dbt_schema_matches_contract(contract_yaml: dict[str, Any], repo_root: Path, model: str) -> None:
    assert _dbt_columns(repo_root, model) == _contract_columns(contract_yaml, model)


@pytest.mark.parametrize("model", ["c360_customer", "identity_crosswalk", "c360_restricted"])
def test_dbt_sql_stub_matches_contract(contract_yaml: dict[str, Any], repo_root: Path, model: str) -> None:
    assert _sql_columns(repo_root, model) == _contract_columns(contract_yaml, model)


# ----------------------------------------------------------------- feature registry
def test_registry_names_match_feature_vector() -> None:
    assert [f.name for f in FEATURES] == list(FeatureVector.feature_names())


def test_registry_names_are_unique_snake_case() -> None:
    names = [f.name for f in FEATURES]
    assert len(names) == len(set(names))
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", n) for n in names)


def test_registry_never_registers_outcomes_or_stated_reasons() -> None:
    names = {f.name for f in FEATURES}
    assert not names & OUTCOME_DENY_LIST
    assert not names & STATED_REASON_FIELDS


def test_registry_specs_are_complete() -> None:
    for f in FEATURES:
        assert f.owner in {"A", "B", "C", "D"}, f.name
        assert f.source_columns, f.name
        assert all(
            re.fullmatch(r"(bronze|silver|gold)\.[a-z0-9_]+\.[a-z0-9_]+", c) for c in f.source_columns
        ), f.name
        assert f.description, f.name


def test_no_feature_reads_the_restricted_table() -> None:
    for f in FEATURES:
        assert not any(c.startswith("gold.c360_restricted.") for c in f.source_columns), f.name


def test_text_features_owned_by_track_c() -> None:
    assert all(f.owner == "C" for f in FEATURES if f.origin is FeatureOrigin.TEXT)


def test_hardship_never_feeds_the_model() -> None:
    # "Hardship protects, never scores" (design, governance banner).
    spec = next(f for f in FEATURES if f.name == "hardship_signal")
    assert spec.model_input is False


# ----------------------------------------------------------------- config sanity
def test_threshold_orderings() -> None:
    assert 0 < config.STEWARD_REVIEW_THRESHOLD < config.AUTO_LINK_THRESHOLD <= 1
    assert config.LINKAGE_BLOCK_BELOW < config.LINKAGE_TARGET <= 1
    assert config.FRESHNESS_WARN < config.FRESHNESS_BLOCK
    assert config.CALLING_HOURS_START < config.CALLING_HOURS_END
    assert config.PROMISE_DAYS_AFTER_PAYDAY == (0, 1)
    assert config.HOLDOUT_SHARE == 0.05
    assert config.TOP_REASONS == 3
    assert config.SQL_CANDIDATES % 2 == 1  # majority vote needs an odd count
