"""Step 5: grounding. Every number in the narrative must come from the result rows."""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATES = re.compile(
    rf"\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}/\d{{1,2}}/\d{{2,4}}"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}(?:,?\s+\d{{4}})?"
    rf"|\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|\b{_MONTH}\s+\d{{4}}",
    re.I,
)
# a leading minus only counts as a sign after a space or bracket ("-3.5"), not inside "31-60"
_NUMBER = re.compile(r"(?:(?<![\w.])-)?\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(%)?")


def _numbers(text: str) -> list[tuple[Decimal, bool]]:
    """(value, is_percent) for every number in the text, dates removed."""
    out = []
    for m in _NUMBER.finditer(_DATES.sub(" ", text)):
        value = Decimal(m[1].replace(",", "") + (m[2] or ""))
        out.append((-value if m[0].startswith("-") else value, m[3] is not None))
    return out


def extract_numbers(text: str) -> list[Decimal]:
    """Numbers as written: "1,234" -> 1234, "$140.50" -> 140.50, "64%" -> 64, "-3.5" -> -3.5.
    Dates ("2026-10-03", "3 Oct") and ordinals in words are not numbers."""
    return [v for v, _ in _numbers(text)]


def _cells(rows: Sequence[Sequence[Any]]) -> list[Decimal]:
    """Numeric cells, plus the numbers inside text cells ("31-60", "C-12"): narratives name buckets."""
    out: list[Decimal] = []
    for row in rows:
        for c in row:
            if isinstance(c, bool):
                continue
            if isinstance(c, int | float | Decimal):
                out.append(Decimal(str(c)))
            elif isinstance(c, str):
                out += [abs(v) for v in extract_numbers(c)]
    return out


def _matches(cell: Decimal, number: Decimal, *, percent: bool) -> bool:
    places = Decimal(1).scaleb(min(int(number.as_tuple().exponent), 0))
    forms = (cell, cell * 100) if percent else (cell,)
    return any(f.quantize(places, rounding=ROUND_HALF_UP) == number for f in forms)


def is_grounded(
    narrative: str, rows: Sequence[Sequence[Any]], *, allow: frozenset[Decimal] = frozenset()
) -> bool:
    """True if every number in the narrative equals some numeric cell in rows, where
    a cell matches if it equals the number after rounding the cell to the number's
    written decimal places, or (for percentages) the cell x 100 does. `allow` holds
    numbers that came from the question itself (e.g. "30 days").
    Numbers inside text cells ("31-60") also count: narratives name buckets and case ids."""
    cells = _cells(rows)
    return all(
        n in allow or any(_matches(c, n, percent=pct) for c in cells) for n, pct in _numbers(narrative)
    )


def needs_clarification(
    *, router_confidence: float, candidates_agree: bool | None, threshold: float = 0.6
) -> bool:
    """True when confidence < threshold or SQL candidates disagree (False)."""
    return router_confidence < threshold or candidates_agree is False
