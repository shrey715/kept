"""LLM drafts source-to-target mappings and schema-drift fixes as pull requests.
An engineer approves them. Lowest priority in Track A; only schemas (never rows)
are sent to the LLM."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MappingDraft:
    source_table: str
    target_model: str
    column_map: dict[str, str]
    rationale: str


def draft_mapping(source_schema: dict[str, str], target_columns: list[str]) -> MappingDraft:
    raise NotImplementedError("Track A (stretch)")
