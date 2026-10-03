"""Stage 7: TreeSHAP top 3 reasons mapped to fixed sentences, alternatives, and the
"similar past cases" line. The LLM writes none of it."""

from __future__ import annotations

import math
from collections.abc import Mapping

from kept.contracts.feature_registry import model_inputs
from kept.contracts.nba import Reason

# One fixed sentence per model feature. {value} is the case's value (formatted here),
# {pts} the contribution in percentage points. The sentence states the fact; the points say
# how much it pushed toward the recommended action.
REASON_TEMPLATES: Mapping[str, str] = {
    "max_dpd": "{value} days past due on the worst account",
    "times_30plus_dpd_12m": "Reached 30+ days past due {value} times in the last 12 months",
    "days_in_bucket": "{value} days in the current delinquency bucket",
    "broken_promises_90d": "{value} broken promises in the last 90 days",
    "kept_promise_ratio": "Kept {value} of past promises",
    "days_to_next_payroll": "Pay lands in {value} days",
    "pay_frequency": "Paid {value}",
    "payroll_delay_days": "Pay is {value} days late",
    "pay_change_vs_3m_avg": "Latest pay is {value} against the 3-month average",
    "cash_flow_trend": "Monthly cash flow is trending {value}",
    "card_utilisation_trend": "Card utilisation is trending {value}",
    "answer_rate": "Answers {value} of calls",
    "answer_rate_after_18h": "Answers {value} of calls after 18:00",
    "payment_link_usage": "Paid through {value} of past payment links",
    "cohort_recovery_rate": "{value} of similar past cases recovered",
    "cohort_kept_rate": "{value} of promises in similar past cases were kept",
    "promise_intent": "Said they intend to pay",
}
_RATES = {
    "kept_promise_ratio",
    "answer_rate",
    "answer_rate_after_18h",
    "payment_link_usage",
    "cohort_recovery_rate",
    "cohort_kept_rate",
}
_TRENDS = {"cash_flow_trend", "card_utilisation_trend"}


def _fmt(feature: str, v: object) -> str:
    if feature in _RATES and isinstance(v, (int, float)):
        return f"{v:.0%}"
    if feature == "pay_change_vs_3m_avg" and isinstance(v, (int, float)):
        return f"{'down' if v < 0 else 'up'} {abs(v):.0%}"
    if feature in _TRENDS and isinstance(v, (int, float)):
        return "down" if v < 0 else "up" if v > 0 else "flat"
    return str(getattr(v, "value", v))


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
    skipped. Ties broken by feature name. A template that needs {value} is skipped when the
    case has no value for it (we never state a fact we don't have)."""
    allowed = set(model_inputs())
    ranked = sorted(
        (f for f, c in contributions.items() if c > 0 and f in templates and f in allowed),
        key=lambda f: (-contributions[f], f),
    )
    out = []
    for f in ranked:
        v = values.get(f)
        missing = v is None or (isinstance(v, float) and math.isnan(v))
        if "{value" in templates[f] and missing:
            continue
        pts = round(contributions[f] * 100, 1)
        out.append(
            Reason(feature=f, sentence=templates[f].format(value=_fmt(f, v), pts=pts), contribution_pts=pts)
        )
        if len(out) == k:
            break
    return out


def similar_cases_text(
    *, n: int, kept_rate_payday_plan: float, kept_rate_lump_sum: float, min_group: int = 50
) -> str | None:
    """'812 past cases like this: 64% kept a payday-dated plan vs 39% a lump-sum promise
    (descriptive, not causal).' None if n < min_group."""
    if n < min_group:
        return None
    return (
        f"{n} past cases like this: {kept_rate_payday_plan:.0%} kept a payday-dated plan vs "
        f"{kept_rate_lump_sum:.0%} a lump-sum promise (descriptive, not causal)."
    )
