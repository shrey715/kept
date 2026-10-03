"""Quality gate (Soda checks generated from the data contract) plus Python evaluators.

Each check returns PASS, WARN or BLOCK. Any BLOCK stops the nightly publish.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import pandas as pd
import yaml

from kept.config import (
    AUTO_LINK_THRESHOLD,
    FRESHNESS_BLOCK,
    FRESHNESS_WARN,
    LINKAGE_BLOCK_BELOW,
    LINKAGE_TARGET,
    MATCH_PRECISION_TARGET,
    ROW_COUNT_TOLERANCE,
)
from kept.contracts.data_contract import DataContract
from kept.data.gold import COLLECTIONS_HOLD_STOPS, DO_NOT_CONTACT_FLAGS, HARD_STOP_FLAGS, _on


class Status(StrEnum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class QualityResult:
    rule: str  # Q1-unique-ids ... Q5-freshness, matching the contract ids
    status: Status
    detail: str


_SEVERITY = {Status.PASS: 0, Status.WARN: 1, Status.BLOCK: 2}


def _ids(values: Iterable[object], limit: int = 5) -> str:
    shown = sorted({str(v) for v in values})
    return ", ".join(shown[:limit]) + (f" (+{len(shown) - limit} more)" if len(shown) > limit else "")


def check_unique_ids(c360: pd.DataFrame, crosswalk: pd.DataFrame) -> QualityResult:
    """Q1: golden_customer_id never null or duplicated in c360; each (source_system,
    source_key) with valid_to null maps to exactly one golden ID. Fail: BLOCK."""
    rule = "Q1-unique-ids"
    ids = c360["golden_customer_id"]
    if ids.isna().any():
        return QualityResult(rule, Status.BLOCK, f"{int(ids.isna().sum())} null golden_customer_id")
    if ids.duplicated().any():
        return QualityResult(
            rule, Status.BLOCK, f"duplicated golden_customer_id: {_ids(ids[ids.duplicated()])}"
        )
    active = crosswalk[crosswalk["valid_to"].isna()]
    per_key = active.groupby(["source_system", "source_key"])["golden_customer_id"].nunique()
    if (per_key > 1).any():
        bad = [f"{s}:{k}" for s, k in per_key[per_key > 1].index]
        return QualityResult(rule, Status.BLOCK, f"source keys mapped to several golden IDs: {_ids(bad)}")
    return QualityResult(
        rule, Status.PASS, f"{len(ids):,} golden IDs unique; every active source key maps to one"
    )


def check_linkage(
    open_case_ids: set[str], resolved_case_ids: set[str], account_keys_total: int, account_keys_linked: int
) -> QualityResult:
    """Q2: any unresolved open case -> BLOCK. Linkage >= 0.98 PASS, [0.97, 0.98) WARN,
    < 0.97 BLOCK. account_keys_total == 0 -> BLOCK (nothing loaded)."""
    rule = "Q2-linkage"
    if account_keys_total == 0:
        return QualityResult(rule, Status.BLOCK, "no account keys loaded")
    unresolved = open_case_ids - resolved_case_ids
    if unresolved:
        return QualityResult(
            rule,
            Status.BLOCK,
            f"{len(unresolved)} open cases without a golden ID: {_ids(sorted(unresolved))}",
        )
    ratio = account_keys_linked / account_keys_total
    detail = f"{ratio:.2%} of account keys linked; every open case resolves"
    eps = 1e-9  # 980/1000 must count as 0.98
    if ratio >= LINKAGE_TARGET - eps:
        return QualityResult(rule, Status.PASS, detail)
    status = Status.WARN if ratio >= LINKAGE_BLOCK_BELOW - eps else Status.BLOCK
    return QualityResult(rule, status, detail)


def check_match_safety(crosswalk: pd.DataFrame, national_ids: pd.DataFrame) -> QualityResult:
    """Q3: every match_review_status == 'auto' link with a score has score >= 0.95;
    no golden ID has two distinct non-null national_id_hash values. Fail: BLOCK."""
    rule = "Q3-match-safety"
    weak = crosswalk[
        (crosswalk["match_review_status"] == "auto")
        & crosswalk["match_score"].notna()
        & (crosswalk["match_score"] < AUTO_LINK_THRESHOLD)
    ]
    if len(weak):
        return QualityResult(
            rule,
            Status.BLOCK,
            f"{len(weak)} auto links below {AUTO_LINK_THRESHOLD}: {_ids(weak['golden_customer_id'])}",
        )
    per_id = (
        national_ids.dropna(subset=["national_id_hash"])
        .groupby("golden_customer_id")["national_id_hash"]
        .nunique()
    )
    if (per_id > 1).any():
        return QualityResult(
            rule,
            Status.BLOCK,
            f"{int((per_id > 1).sum())} golden IDs hold two national IDs: {_ids(per_id[per_id > 1].index)}",
        )
    return QualityResult(
        rule, Status.PASS, "every auto link scores >= 0.95; no cluster holds two national IDs"
    )


def check_review_precision(reviewed_pairs: pd.DataFrame) -> QualityResult:
    """Q3 weekly: precision of predicted links on the reviewed sample (columns
    predicted_link, is_true_match). >= 0.98 PASS, else WARN. No predicted links -> WARN."""
    rule = "Q3-review-precision"
    predicted = reviewed_pairs[reviewed_pairs["predicted_link"].astype(bool)]
    if predicted.empty:
        return QualityResult(rule, Status.WARN, "no predicted links in the reviewed sample")
    precision = float(predicted["is_true_match"].astype(bool).mean())
    detail = f"precision {precision:.1%} on {len(predicted)} reviewed predicted links"
    return QualityResult(
        rule, Status.PASS if precision >= MATCH_PRECISION_TARGET - 1e-9 else Status.WARN, detail
    )


def check_contact_safety(c360: pd.DataFrame, source_flags: pd.DataFrame) -> QualityResult:
    """Q4: zero violations. A violation is a golden ID with any source do_not_call/cease
    but do_not_contact false, or any insolvency/bankruptcy/deceased but collections_hold false."""
    rule = "Q4-contact-safety"
    hold_flags = [f for stop in COLLECTIONS_HOLD_STOPS for f in HARD_STOP_FLAGS[stop]]

    def any_flag(columns: tuple[str, ...] | list[str]) -> pd.Series:
        present = [c for c in columns if c in source_flags]
        if not present:
            return pd.Series(dtype=bool)
        on = source_flags[present].map(_on).any(axis=1)
        return on.groupby(source_flags["golden_customer_id"]).any()

    expected_dnc, expected_hold = any_flag(DO_NOT_CONTACT_FLAGS), any_flag(hold_flags)
    gold = c360.set_index("golden_customer_id")
    bad_dnc = [g for g in expected_dnc[expected_dnc].index if not _on(gold["do_not_contact"].get(g))]
    bad_hold = [g for g in expected_hold[expected_hold].index if not _on(gold["collections_hold"].get(g))]
    if bad_dnc or bad_hold:
        return QualityResult(
            rule,
            Status.BLOCK,
            f"{len(bad_dnc)} IDs with a source do-not-call/cease but do_not_contact false: {_ids(bad_dnc)}; "
            f"{len(bad_hold)} IDs with insolvency/bankruptcy/deceased but collections_hold false: "
            f"{_ids(bad_hold)}",
        )
    return QualityResult(rule, Status.PASS, "0 violations")


def check_freshness(source_extracted_at: datetime, published_at: datetime) -> QualityResult:
    """Q5: age <= 26h PASS, (26h, 48h) WARN, >= 48h BLOCK. Naive datetimes -> ValueError.
    published_at before extracted_at -> ValueError."""
    for name, value in (("source_extracted_at", source_extracted_at), ("published_at", published_at)):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware (K7)")
    age = published_at - source_extracted_at
    if age.total_seconds() < 0:
        raise ValueError("published_at is before source_extracted_at")
    detail = f"published {age.total_seconds() / 3600:.1f}h after the source extract"
    if age >= FRESHNESS_BLOCK:
        return QualityResult("Q5-freshness", Status.BLOCK, detail)
    return QualityResult("Q5-freshness", Status.WARN if age > FRESHNESS_WARN else Status.PASS, detail)


def check_row_count(current: int, previous: int | None) -> QualityResult:
    """Q5: within 10% of the last load PASS, else WARN (decided: freshness is what blocks). First load
    (previous None) PASS. previous == 0 and current > 0 -> WARN."""
    rule = "Q5-row-count"
    if previous is None:
        return QualityResult(rule, Status.PASS, f"first load: {current:,} rows")
    if previous == 0:
        status = Status.WARN if current > 0 else Status.PASS
        return QualityResult(rule, status, f"{current:,} rows after an empty load")
    change = (current - previous) / previous
    ok = abs(current - previous) <= previous * ROW_COUNT_TOLERANCE + 1e-9
    return QualityResult(
        rule, Status.PASS if ok else Status.WARN, f"{current:,} rows, {change:+.1%} vs the last load"
    )


def generate_soda_checks(contract: DataContract) -> str:
    """SodaCL YAML for every quality rule in the contract. Deterministic output."""
    gold = "gold.c360_customer"
    required = [c.name for c in contract.table_columns(gold) if c.required and c.name != "golden_customer_id"]
    # Q4 and Q2 compare gold with silver, so they are failed-row checks over two tables
    unresolved_cases = (
        "select c.case_id from silver.collections_cases c left join gold.identity_crosswalk x "
        "on x.source_system = 'collections' and x.source_key = c.coll_customer_ref and x.valid_to is null "
        "where c.outcome is null and x.golden_customer_id is null"
    )
    weak_auto_links = (
        "select golden_customer_id from gold.identity_crosswalk "
        "where match_review_status = 'auto' and match_score is not null "
        f"and match_score < {AUTO_LINK_THRESHOLD}"
    )
    two_national_ids = (
        "select x.golden_customer_id from gold.identity_crosswalk x join silver.int_identity_records r "
        "on r.source_system = x.source_system and r.source_key = x.source_key "
        "where x.valid_to is null and r.national_id_hash is not null "
        "group by x.golden_customer_id having count(distinct r.national_id_hash) > 1"
    )
    contact_violations = (
        "select g.golden_customer_id from gold.c360_customer g join silver.int_source_flags f "
        "using (golden_customer_id) where (f.any_do_not_contact and not g.do_not_contact) "
        "or (f.any_collections_hold and not g.collections_hold)"
    )

    def failed_rows(name: str, query: str) -> dict[str, object]:
        return {"failed rows": {"name": name, "fail query": query}}

    freshness = {
        "freshness(refreshed_at)": {
            "name": "Q5-freshness: gold refreshed within 26h (warn) and 48h (block)",
            "warn": "when > 26h",
            "fail": "when > 48h",
        }
    }
    doc = {
        f"checks for {gold}": [
            {"duplicate_count(golden_customer_id) = 0": {"name": "Q1-unique-ids: no duplicated golden ID"}},
            {"missing_count(golden_customer_id) = 0": {"name": "Q1-unique-ids: no null golden ID"}},
            *(
                {f"missing_count({c}) = 0": {"name": f"required column: {c} is not null (contract)"}}
                for c in required
            ),
            failed_rows(
                "Q4-contact-safety: a source do-not-call, cease or hold reaches the golden record",
                contact_violations,
            ),
            freshness,
            {
                "row_count > 0": {
                    "name": "Q5-freshness: not empty (the 10% row-count tolerance: kept.data.quality)"
                }
            },
        ],
        "checks for gold.identity_crosswalk": [
            {
                "duplicate_count(source_system, source_key) = 0": {
                    "name": "Q1-unique-ids: each active source key maps to one golden ID",
                    "filter": "valid_to is null",
                }
            },
            failed_rows("Q3-match-safety: an auto link scores below the threshold", weak_auto_links),
            failed_rows("Q3-match-safety: a cluster holds two national IDs", two_national_ids),
            failed_rows("Q2-linkage: an open case without a golden ID", unresolved_cases),
        ],
    }
    return yaml.safe_dump(doc, sort_keys=False, width=120)


def quality_report(results: list[QualityResult], *, contract_version: str, as_of: datetime) -> str:
    """The Layer 1 deliverable "a data quality report", as Markdown: a header with the
    contract version and as_of, the gate status, then one table row per result
    (rule, status, detail) in rule order. Deterministic for the same input."""
    ordered = sorted(results, key=lambda r: r.rule)
    lines = [
        "# Data quality report",
        "",
        f"Contract: kept-c360-customer v{contract_version} · as of {as_of.isoformat()}",
        "",
        f"Gate: **{run_gate(results).value.upper()}**",
        "",
        "| Rule | Status | Detail |",
        "|---|---|---|",
        *(f"| {r.rule} | {r.status.value.upper()} | {r.detail.replace('|', '/')} |" for r in ordered),
        "",
    ]
    return "\n".join(lines)


def run_gate(results: list[QualityResult]) -> Status:
    """Worst status wins. Empty list -> BLOCK (no checks ran means not safe)."""
    return max((r.status for r in results), key=_SEVERITY.__getitem__, default=Status.BLOCK)
