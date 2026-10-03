"""CI test fails the build if a feature comes from a protected attribute or proxy (design §9)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from kept.contracts.data_contract import DataContract
from kept.contracts.feature_registry import FeatureSpec


@dataclass(frozen=True, slots=True)
class LineageViolation:
    feature: str
    source_column: str
    attribute: str
    kind: str  # "protected" | "proxy" | "restricted_table" | "outcome" | "stated_reason"


def lineage_violations(features: Iterable[FeatureSpec], contract: DataContract) -> list[LineageViolation]:
    """A source column "<schema>.<table>.<column>" violates if the column name
    (case-insensitive) is a protected attribute or proxy, its table is a restricted
    table, it is in OUTCOME_DENY_LIST, or it is a stated-reason field.
    Exception: COHORT features may read outcome columns (they aggregate other, closed
    cases before as_of), but never protected, proxy, restricted or stated-reason ones.
    Feature names themselves are checked too (a feature named "age" is a violation)."""
    raise NotImplementedError("Track C")
