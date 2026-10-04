"""LLM drafts source-to-target mappings and schema-drift fixes as pull requests.
An engineer approves them. Lowest priority in Track A; only schemas (never rows)
are sent to the LLM."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from kept.contracts.interfaces import LLMGateway, Redactor

PURPOSE = "mapping_draft"
SYSTEM = (
    "You map the columns of a source table to the columns of a target model. You see only column "
    "names and types. For each target column give the source column that holds the same thing, or "
    "null if none does. Use only source columns from the list. Do not invent columns. "
    'Reply as JSON: {"column_map": {target: source_or_null}, "rationale": "one short paragraph"}.'
)
JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "column_map": {"type": "object", "additionalProperties": {"type": ["string", "null"]}},
        "rationale": {"type": "string"},
    },
    "required": ["column_map", "rationale"],
}


@dataclass(frozen=True, slots=True)
class MappingDraft:
    source_table: str
    target_model: str
    column_map: dict[str, str]  # target column -> source column, the mapped ones only
    rationale: str
    unmapped: tuple[str, ...] = ()  # target columns the LLM found no source for

    def sql(self) -> str:
        """The draft as a dbt select, for the engineer to review in a pull request."""
        lines = ",\n".join(f'    "{src}" as "{tgt}"' for tgt, src in self.column_map.items())
        return f"select\n{lines}\nfrom {{{{ source('bronze', '{self.source_table}') }}}}\n"


def draft_mapping(
    source_table: str,
    source_schema: dict[str, str],
    target_model: str,
    target_columns: list[str],
    *,
    llm: LLMGateway,
    redactor: Redactor,
    actor_id: str = "system:mapping_assistant",
) -> MappingDraft:
    """Ask the LLM which source column feeds each target column. Only names and types go to it. A
    column it names that is not in `source_schema` is an invention: ValueError, nothing is drafted.
    The prompt goes through `redactor` like any text sent to an LLM (the gateway takes nothing else)."""
    prompt = json.dumps({"source_columns": source_schema, "target_columns": target_columns}, indent=1)
    reply = llm.complete(
        system=SYSTEM,
        user=redactor.redact(prompt),
        purpose=PURPOSE,
        actor_id=actor_id,
        json_schema=JSON_SCHEMA,
    )
    answer = reply.parsed if reply.parsed is not None else json.loads(reply.text)
    chosen = {t: answer["column_map"].get(t) for t in target_columns}
    invented = sorted({s for s in chosen.values() if s is not None and s not in source_schema})
    if invented:
        raise ValueError(f"the draft maps to columns that are not in {source_table}: {invented}")
    return MappingDraft(
        source_table=source_table,
        target_model=target_model,
        column_map={t: s for t, s in chosen.items() if s is not None},
        rationale=str(answer.get("rationale", "")),
        unmapped=tuple(t for t, s in chosen.items() if s is None),
    )


# ---------------------------------------------------------------- schema drift (kept map)
@dataclass(frozen=True, slots=True)
class Drift:
    table: str
    new: dict[str, str]  # columns that arrived but the data dictionary doesn't have -> type
    missing: tuple[str, ...]  # dictionary columns that didn't arrive


def dictionary_columns(xlsx: Path) -> dict[str, list[str]]:
    """table -> columns, in order, from the data dictionary's "Columns" sheet."""
    import openpyxl  # type: ignore[import-untyped]

    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    out: dict[str, list[str]] = {}
    for table, column, *_ in wb["Columns"].iter_rows(min_row=2, values_only=True):
        if table and column:
            out.setdefault(str(table), []).append(str(column))
    return out


def raw_columns(raw_dir: Path, tables: list[str]) -> dict[str, dict[str, str]]:
    """table -> {column: type} as the files arrived: a CSV header (types unknown, VARCHAR) or a Parquet
    folder's schema (hive partition keys like year=2026 left out). Tables with no file are skipped."""
    import duckdb

    out: dict[str, dict[str, str]] = {}
    con = duckdb.connect()
    for t in tables:
        csv_path, folder = raw_dir / f"{t}.csv", raw_dir / t
        if csv_path.exists():
            with csv_path.open(encoding="utf-8", newline="") as f:
                out[t] = dict.fromkeys(next(csv.reader(f)), "VARCHAR")
        elif folder.is_dir():
            files = sorted(folder.rglob("*.parquet"))
            if not files:
                continue
            hive = {p.split("=")[0] for p in files[0].relative_to(folder).parts[:-1] if "=" in p}
            rows = con.execute("describe select * from read_parquet(?)", [str(files[0])]).fetchall()
            out[t] = {str(r[0]): str(r[1]) for r in rows if r[0] not in hive}
    return out


def schema_drift(expected: dict[str, list[str]], actual: dict[str, dict[str, str]]) -> list[Drift]:
    """Tables whose arrived columns differ from the dictionary, by table name."""
    out = []
    for table, cols in sorted(actual.items()):
        want = expected.get(table, [])
        new = {c: typ for c, typ in cols.items() if c not in want}
        missing = tuple(c for c in want if c not in cols)
        if new or missing:
            out.append(Drift(table, new, missing))
    return out
