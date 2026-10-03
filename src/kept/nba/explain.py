"""Stage 7: TreeSHAP top 3 reasons mapped to fixed sentences, alternatives, and the
"similar past cases" line. The LLM writes none of it."""

from __future__ import annotations

from collections.abc import Mapping

from kept.contracts.nba import Reason

# feature -> sentence template. Templates may use {value} and {pts}. Filled in by Track D.
REASON_TEMPLATES: Mapping[str, str] = {}


def top_reasons(
    contributions: Mapping[str, float],
    values: Mapping[str, object],
    *,
    templates: Mapping[str, str] = REASON_TEMPLATES,
    k: int = 3,
) -> list[Reason]:
    """Top k features by positive contribution (toward the recommended action), largest
    first; contributions are probabilities, reported as percentage points (0.09 -> 9.0).
    Features without a template, non-model features, or non-positive contributions are
    skipped. Ties broken by feature name."""
    raise NotImplementedError("Track D")


def similar_cases_text(
    *, n: int, kept_rate_payday_plan: float, kept_rate_lump_sum: float, min_group: int = 50
) -> str | None:
    """'812 past cases like this: 64% kept a payday-dated plan vs 39% a lump-sum promise
    (descriptive, not causal).' None if n < min_group."""
    raise NotImplementedError("Track D")
