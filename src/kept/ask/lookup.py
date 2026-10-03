"""Step 3b: lookups get three LLM-written SQL candidates; keep the majority result."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from kept.common.llm import Purpose
from kept.contracts.ask import Intent
from kept.contracts.features import RedactedText
from kept.contracts.interfaces import LLMGateway

Rows = tuple[tuple[Any, ...], ...]

_SYSTEM = """You write one DuckDB SELECT query that answers a collections analyst's question.
Rules: SELECT only, one statement. Use only these tables and columns, always schema-qualified
(silver.collections_cases, never collections_cases). Name every column, never SELECT *. For any
aggregate also return count(*) AS n, the size of each group. Do not filter on protected attributes.
Reply with the SQL only, no explanation.

{schema_doc}

Hints from the question parser (may be empty): {hints}"""


def _sql_only(text: str) -> str:
    """Models like to fence their SQL and end it with a semicolon."""
    return re.sub(r"^\s*```(?:sql)?\s*|\s*```\s*$", "", text).strip().rstrip(";").strip()


def generate_candidates(
    intent: Intent, schema_doc: str, llm: LLMGateway, *, n: int, actor_id: str, question: RedactedText
) -> list[str]:
    """n candidate SQL strings: n separate calls with purpose Purpose.ASK_SQL.
    A failed call yields no candidate (the list may be shorter than n).
    `question` is added to the spec: the intent alone doesn't carry what the user asked."""
    hints = intent.model_dump_json(exclude={"kind", "confidence"}, exclude_defaults=True)
    system = _SYSTEM.format(schema_doc=schema_doc, hints=hints)
    out: list[str] = []
    for _ in range(n):
        try:
            # a little temperature so the n drafts can differ: the vote is the check
            reply = llm.complete(
                system=system, user=question, purpose=Purpose.ASK_SQL, actor_id=actor_id, temperature=0.3
            )
        except Exception:
            continue
        if sql := _sql_only(reply.text):
            out.append(sql)
    return out


def _canon(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, int):
        return v
    if isinstance(v, float | Decimal):
        f = float(v)
        return None if f != f else float(f"{f:.6g}")  # NaN has no equal, treat it as NULL
    if isinstance(v, list | tuple):
        return tuple(_canon(x) for x in v)
    return v


def normalize_result(rows: Rows) -> Rows:
    """Canonical form for comparing results: row order ignored, floats rounded to
    6 significant digits, Decimal and float of equal value compare equal."""
    return tuple(sorted((tuple(_canon(c) for c in r) for r in rows), key=repr))


def majority_result(results: Sequence[Rows | None]) -> Rows | None:
    """The result shared by a strict majority of candidates (after normalize_result).
    None entries are failed candidates and count as votes for nothing.
    No strict majority -> None (caller asks a clarifying question)."""
    votes = Counter(normalize_result(r) for r in results if r is not None)
    if not votes:
        return None
    winner, count = votes.most_common(1)[0]
    if count * 2 <= len(results):
        return None
    return next(r for r in results if r is not None and normalize_result(r) == winner)
