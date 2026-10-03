"""Step 5: grounding. Every number in the narrative must come from the result rows."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any


def extract_numbers(text: str) -> list[Decimal]:
    """Numbers as written: "1,234" -> 1234, "$140.50" -> 140.50, "64%" -> 64, "-3.5" -> -3.5.
    Dates ("2026-10-03", "3 Oct") and ordinals in words are not numbers."""
    raise NotImplementedError("Track B")


def is_grounded(
    narrative: str, rows: Sequence[Sequence[Any]], *, allow: frozenset[Decimal] = frozenset()
) -> bool:
    """True if every number in the narrative equals some numeric cell in rows, where
    a cell matches if it equals the number after rounding the cell to the number's
    written decimal places, or (for percentages) the cell x 100 does. `allow` holds
    numbers that came from the question itself (e.g. "30 days")."""
    raise NotImplementedError("Track B")


def needs_clarification(
    *, router_confidence: float, candidates_agree: bool | None, threshold: float = 0.6
) -> bool:
    """True when confidence < threshold or SQL candidates disagree (False)."""
    raise NotImplementedError("Track B")
