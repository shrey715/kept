"""Step 3b: lookups get three LLM-written SQL candidates; keep the majority result."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from kept.contracts.ask import Intent
from kept.contracts.interfaces import LLMGateway

Rows = tuple[tuple[Any, ...], ...]


def generate_candidates(
    intent: Intent, schema_doc: str, llm: LLMGateway, *, n: int, actor_id: str
) -> list[str]:
    """n candidate SQL strings: n separate calls with purpose Purpose.ASK_SQL.
    A failed call yields no candidate (the list may be shorter than n)."""
    raise NotImplementedError("Track B")


def normalize_result(rows: Rows) -> Rows:
    """Canonical form for comparing results: row order ignored, floats rounded to
    6 significant digits, Decimal and float of equal value compare equal."""
    raise NotImplementedError("Track B")


def majority_result(results: Sequence[Rows | None]) -> Rows | None:
    """The result shared by a strict majority of candidates (after normalize_result).
    None entries are failed candidates and count as votes for nothing.
    No strict majority -> None (caller asks a clarifying question)."""
    raise NotImplementedError("Track B")
