"""The contract must agree with the organisers' data dictionary (docs/*.xlsx).

If the organisers ship a new dictionary, these tests say exactly what changed.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from kept.contracts.feature_registry import FEATURES, OUTCOME_DENY_LIST

DICTIONARY = "CIBC Hackathon - Data Dictionary.xlsx"


@pytest.fixture(scope="module")
def dictionary(repo_root: Path) -> dict[str, Any]:
    openpyxl = pytest.importorskip("openpyxl")
    path = repo_root / "docs" / DICTIONARY
    if not path.exists():
        pytest.skip(f"{DICTIONARY} not in docs/")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = [r for r in wb["Columns"].iter_rows(min_row=2, values_only=True) if r and r[0]]
    tables = [r[0] for r in wb["Tables"].iter_rows(min_row=2, values_only=True) if r and r[0]]
    columns: dict[str, set[str]] = defaultdict(set)
    sensitivity: dict[str, set[str]] = defaultdict(set)
    for table, column, *_rest in rows:
        columns[table].add(column)
        if label := _rest[4] if len(_rest) > 4 else None:
            sensitivity[label].add(f"{table}.{column}")
    return {"tables": tables, "columns": columns, "sensitivity": sensitivity}


def _custom(contract: dict[str, Any], prop: str) -> list[str]:
    return next(p["value"] for p in contract["customProperties"] if p["property"] == prop)


def test_dictionary_has_31_tables(dictionary: dict[str, Any]) -> None:
    assert len(dictionary["tables"]) == 31


def test_protected_attributes_match_dictionary(
    dictionary: dict[str, Any], contract_yaml: dict[str, Any]
) -> None:
    expected = {c.split(".", 1)[1] for c in dictionary["sensitivity"]["Protected attribute"]}
    assert set(_custom(contract_yaml, "protectedAttributes")) == expected


def test_direct_pii_matches_dictionary(dictionary: dict[str, Any], contract_yaml: dict[str, Any]) -> None:
    assert set(_custom(contract_yaml, "directPiiColumns")) == dictionary["sensitivity"]["Direct PII"]


def test_quasi_identifiers_match_dictionary(
    dictionary: dict[str, Any], contract_yaml: dict[str, Any]
) -> None:
    assert (
        set(_custom(contract_yaml, "quasiIdentifierColumns")) == dictionary["sensitivity"]["Quasi-identifier"]
    )


def test_proxies_exist_in_the_data(dictionary: dict[str, Any], contract_yaml: dict[str, Any]) -> None:
    every_column = set().union(*dictionary["columns"].values())
    missing = sorted(set(_custom(contract_yaml, "proxyAttributes")) - every_column)
    assert missing == []


def test_ask_tables_exist(dictionary: dict[str, Any], contract_yaml: dict[str, Any]) -> None:
    source = set(dictionary["tables"])
    for t in _custom(contract_yaml, "askAllowedTables"):
        schema, name = t.split(".", 1)
        if schema == "silver":
            assert name in source, t


def test_feature_sources_exist(dictionary: dict[str, Any]) -> None:
    """Every silver.<table>.<column> a feature reads must exist in the dictionary."""
    cols = dictionary["columns"]
    bad = []
    for f in FEATURES:
        for src in f.source_columns:
            schema, table, column = src.split(".")
            if schema == "silver" and column not in cols.get(table, set()):
                bad.append((f.name, src))
    assert bad == []


def test_deny_list_names_real_columns(dictionary: dict[str, Any]) -> None:
    every_column = set().union(*dictionary["columns"].values())
    derived = {"paid_14d", "roll_forward_30d"}  # labels we compute
    assert sorted(OUTCOME_DENY_LIST - every_column - derived) == []
