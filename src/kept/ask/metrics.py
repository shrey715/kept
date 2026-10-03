"""Step 3a: certified metric definitions -> compiled SQL. The LLM never writes metric SQL.

metric_definitions.formula is pseudo-SQL ("count(worse_bucket_at_end) / count(in_bucket_at_start)"),
so it can't be executed directly. Track B hand-translates each certified metric into a
CertifiedQuery (reviewed by a second person, like any code), and compile_metric only fills
in filters, grouping and dates. Uncertified metrics are never answered as certified.
"""

from __future__ import annotations

from dataclasses import dataclass

from kept.contracts.ask import Intent


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """One row of metric_definitions (data dictionary column names)."""

    metric_id: str
    metric_name: str
    business_definition: str
    formula: str  # pseudo-SQL, for humans
    grain: str  # account / case / customer / promise / contact
    time_basis: str
    default_filters: str  # e.g. "exclude charged_off and insolvency_hold"
    unit: str
    good_direction: str
    synonyms: tuple[str, ...]  # phrases users type; feeds the router
    source_tables: tuple[str, ...]
    example_question: str
    owner: str
    certified_flag: bool


@dataclass(frozen=True, slots=True)
class CertifiedQuery:
    """Our reviewed SQL translation of one certified metric."""

    metric_id: str
    sql_template: str  # SELECT with {group_by_select}, {where} and {group_by} placeholders
    default_where: tuple[str, ...]  # the metric's default_filters as SQL predicates
    allowed_filters: frozenset[str]
    allowed_group_by: frozenset[str]
    date_column: str | None


def load_metric_definitions(rows: list[dict[str, object]]) -> dict[str, MetricDefinition]:
    """Parse metric_definitions rows (synonyms/source_tables arrive as JSON array strings).
    Duplicate metric_id -> ValueError."""
    raise NotImplementedError("Track B")


def compile_metric(
    intent: Intent,
    definitions: dict[str, MetricDefinition],
    queries: dict[str, CertifiedQuery],
) -> tuple[str, list[object]]:
    """(sql, params). Deterministic: the same intent always compiles to the same SQL.
    The metric's default_where predicates are always applied. Filter values become bind
    parameters, never string-interpolated. ValueError when: the metric is unknown, not
    certified_flag, has no CertifiedQuery, or a filter/group_by is not allowed."""
    raise NotImplementedError("Track B")
