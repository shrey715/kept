"""LLM drafts source-to-target mappings and schema-drift fixes as pull requests.
An engineer approves them. Lowest priority in Track A; only schemas (never rows)
are sent to the LLM."""

from __future__ import annotations

import json
from dataclasses import dataclass

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
