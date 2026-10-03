"""Step 3a: certified metric definitions -> compiled SQL. The LLM never writes metric SQL.

metric_definitions.formula is pseudo-SQL ("count(worse_bucket_at_end) / count(in_bucket_at_start)"),
so it can't be executed directly. Track B hand-translates each certified metric into a
CertifiedQuery (reviewed by a second person, like any code), and compile_metric only fills
in filters, grouping and dates. Uncertified metrics are never answered as certified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from kept.contracts.ask import Intent, IntentKind


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
    sql_template: (
        str  # SELECT with {group_by_select}, {where} and {group_by}; own WHERE, {where} adds ' AND ...'
    )
    default_where: tuple[str, ...]  # the metric's default_filters as SQL predicates
    allowed_filters: frozenset[str]
    allowed_group_by: frozenset[str]
    date_column: str | None


def as_bool(v: object) -> bool:
    """CSV/JSON booleans arrive as true/false text."""
    if isinstance(v, bool):
        return v
    t = str(v).strip().lower()
    if t not in ("true", "false"):
        raise ValueError(f"not a boolean: {v!r}")
    return t == "true"


def json_array(v: object) -> tuple[str, ...]:
    """A JSON array string (or an already-parsed list) -> tuple of str; blank -> ()."""
    if isinstance(v, str):
        v = json.loads(v) if v.strip() else []
    return tuple(str(x) for x in v or ())  # type: ignore[attr-defined]


def load_metric_definitions(rows: list[dict[str, object]]) -> dict[str, MetricDefinition]:
    """Parse metric_definitions rows (synonyms/source_tables arrive as JSON array strings).
    Duplicate metric_id -> ValueError."""
    out: dict[str, MetricDefinition] = {}
    for r in rows:
        m = MetricDefinition(
            metric_id=str(r["metric_id"]),
            metric_name=str(r["metric_name"]),
            business_definition=str(r["business_definition"]),
            formula=str(r["formula"]),
            grain=str(r["grain"]),
            time_basis=str(r["time_basis"]),
            default_filters=str(r["default_filters"]),
            unit=str(r["unit"]),
            good_direction=str(r["good_direction"]),
            synonyms=json_array(r["synonyms"]),
            source_tables=json_array(r["source_tables"]),
            example_question=str(r["example_question"]),
            owner=str(r["owner"]),
            certified_flag=as_bool(r["certified_flag"]),
        )
        if m.metric_id in out:
            raise ValueError(f"duplicate metric_id {m.metric_id}")
        out[m.metric_id] = m
    return out


def compile_metric(
    intent: Intent,
    definitions: dict[str, MetricDefinition],
    queries: dict[str, CertifiedQuery],
) -> tuple[str, list[object]]:
    """(sql, params). Deterministic: the same intent always compiles to the same SQL.
    The metric's default_where predicates are always applied. Filter values become bind
    parameters, never string-interpolated. ValueError when: the metric is unknown, not
    certified_flag, has no CertifiedQuery, or a filter/group_by is not allowed."""
    if intent.kind is not IntentKind.METRIC or intent.metric_id not in definitions:
        raise ValueError(f"not a known metric intent: {intent.metric_id}")
    if not definitions[intent.metric_id].certified_flag:
        raise ValueError(f"{intent.metric_id} is not certified")
    q = queries.get(intent.metric_id)
    if q is None:
        raise ValueError(f"no certified query for {intent.metric_id}")
    bad = (set(intent.filters) - q.allowed_filters) | (set(intent.group_by) - q.allowed_group_by)
    if bad:
        raise ValueError(f"not allowed for {intent.metric_id}: {sorted(bad)}")

    where = list(q.default_where)
    params: list[object] = []
    for col in sorted(intent.filters):  # col is in allowed_filters: our identifiers, not user text
        v = intent.filters[col]
        vals = v if isinstance(v, list) else [v]
        if not vals:
            raise ValueError(f"empty filter list for {col}")
        where.append(f"{col} IN ({', '.join('?' * len(vals))})" if isinstance(v, list) else f"{col} = ?")
        params += vals
    for bound, op in ((intent.date_from, ">="), (intent.date_to, "<=")):
        if bound is not None:
            if q.date_column is None:
                raise ValueError(f"{intent.metric_id} has no date column")
            where.append(f"{q.date_column} {op} ?")
            params.append(bound)

    sql = q.sql_template.format(
        group_by_select="".join(f"{c}, " for c in intent.group_by),
        where="".join(f" AND {w}" for w in where),
        group_by=f"GROUP BY {', '.join(intent.group_by)}" if intent.group_by else "",
    )
    return sql, params
