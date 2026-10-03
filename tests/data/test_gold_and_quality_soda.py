"""The committed Soda checks are the generated ones (soda/checks/README.md: CI fails if they differ)."""

from __future__ import annotations

from pathlib import Path

import yaml

from kept.contracts.data_contract import load_data_contract
from kept.data.quality import generate_soda_checks

SODA = Path(__file__).resolve().parents[2] / "soda" / "checks" / "c360_customer.yml"


def test_committed_soda_checks_match_the_contract() -> None:
    assert SODA.read_text() == generate_soda_checks(load_data_contract())


def test_soda_checks_name_every_quality_rule_and_parse() -> None:
    doc = yaml.safe_load(SODA.read_text())
    text = SODA.read_text()
    for rule in ("Q1-unique-ids", "Q2-linkage", "Q3-match-safety", "Q4-contact-safety", "Q5-freshness"):
        assert rule in text, rule
    assert set(doc) == {"checks for gold.c360_customer", "checks for gold.identity_crosswalk"}
