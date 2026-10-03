"""CI test fails the build if a feature comes from a protected attribute or proxy (design §9)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from kept.contracts.data_contract import DataContract
from kept.contracts.feature_registry import OUTCOME_DENY_LIST, FeatureOrigin, FeatureSpec

# what a customer or agent says caused a hardship: routes to hardship handling, never into a model
STATED_REASON_COLUMNS = frozenset({"hardship_reason", "broken_reason_agent_coded", "stated_reason"})


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
    Feature names themselves are checked too (a feature named "age" is a violation).
    One violation per offending column, the first rule that fires: protected, proxy, restricted
    table, stated reason, outcome."""
    protected = {c.lower() for c in contract.protected_attributes}
    proxy = {c.lower() for c in contract.proxy_attributes}
    restricted = {t.lower() for t in contract.restricted_tables}
    out: list[LineageViolation] = []
    for f in features:
        cohort = f.origin is FeatureOrigin.COHORT
        for source in (f.name, *f.source_columns):
            parts = source.lower().split(".")
            column, table = parts[-1], ".".join(parts[:-1])
            if column in protected:
                kind = "protected"
            elif column in proxy:
                kind = "proxy"
            elif table in restricted:
                kind = "restricted_table"
            elif column in STATED_REASON_COLUMNS:
                kind = "stated_reason"
            elif column in OUTCOME_DENY_LIST and not cohort and source != f.name:
                kind = "outcome"
            else:
                continue
            out.append(
                LineageViolation(f.name, source, column if kind != "restricted_table" else table, kind)
            )
    return out
