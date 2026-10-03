"""Quality gate (Soda checks generated from the data contract) plus Python evaluators.

Each check returns PASS, WARN or BLOCK. Any BLOCK stops the nightly publish.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import pandas as pd

from kept.contracts.data_contract import DataContract


class Status(StrEnum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class QualityResult:
    rule: str  # Q1-unique-ids ... Q5-freshness, matching the contract ids
    status: Status
    detail: str


def check_unique_ids(c360: pd.DataFrame, crosswalk: pd.DataFrame) -> QualityResult:
    """Q1: golden_customer_id never null or duplicated in c360; each (source_system,
    source_key) with valid_to null maps to exactly one golden ID. Fail: BLOCK."""
    raise NotImplementedError("Track A")


def check_linkage(
    open_case_ids: set[str], resolved_case_ids: set[str], account_keys_total: int, account_keys_linked: int
) -> QualityResult:
    """Q2: any unresolved open case -> BLOCK. Linkage >= 0.98 PASS, [0.97, 0.98) WARN,
    < 0.97 BLOCK. account_keys_total == 0 -> BLOCK (nothing loaded)."""
    raise NotImplementedError("Track A")


def check_match_safety(crosswalk: pd.DataFrame, national_ids: pd.DataFrame) -> QualityResult:
    """Q3: every match_review_status == 'auto' link with a score has score >= 0.95;
    no golden ID has two distinct non-null national_id_hash values. Fail: BLOCK."""
    raise NotImplementedError("Track A")


def check_review_precision(reviewed_pairs: pd.DataFrame) -> QualityResult:
    """Q3 weekly: precision of predicted links on the reviewed sample (columns
    predicted_link, is_true_match). >= 0.98 PASS, else WARN. No predicted links -> WARN."""
    raise NotImplementedError("Track A")


def check_contact_safety(c360: pd.DataFrame, source_flags: pd.DataFrame) -> QualityResult:
    """Q4: zero violations. A violation is a golden ID with any source do_not_call/cease
    but do_not_contact false, or any insolvency/bankruptcy/deceased but collections_hold false."""
    raise NotImplementedError("Track A")


def check_freshness(source_extracted_at: datetime, published_at: datetime) -> QualityResult:
    """Q5: age <= 26h PASS, (26h, 48h) WARN, >= 48h BLOCK. Naive datetimes -> ValueError.
    published_at before extracted_at -> ValueError."""
    raise NotImplementedError("Track A")


def check_row_count(current: int, previous: int | None) -> QualityResult:
    """Q5: within 10% of the last load PASS, else WARN (TBC: block?). First load
    (previous None) PASS. previous == 0 and current > 0 -> WARN."""
    raise NotImplementedError("Track A")


def generate_soda_checks(contract: DataContract) -> str:
    """SodaCL YAML for every quality rule in the contract. Deterministic output."""
    raise NotImplementedError("Track A")


def quality_report(results: list[QualityResult], *, contract_version: str, as_of: datetime) -> str:
    """The Layer 1 deliverable "a data quality report", as Markdown: a header with the
    contract version and as_of, the gate status, then one table row per result
    (rule, status, detail) in rule order. Deterministic for the same input."""
    raise NotImplementedError("Track A")


def run_gate(results: list[QualityResult]) -> Status:
    """Worst status wins. Empty list -> BLOCK (no checks ran means not safe)."""
    raise NotImplementedError("Track A")
