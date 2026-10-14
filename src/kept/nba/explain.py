"""Stage 7: TreeSHAP top 3 reasons mapped to fixed sentences, alternatives, and the
"similar past cases" line. The LLM writes none of it."""

from __future__ import annotations

import math
from collections.abc import Mapping

from kept.config import MAX_DRIVERS
from kept.contracts.feature_registry import model_inputs
from kept.contracts.nba import Driver, Reason

# One fixed sentence per model feature. {value} is the case's value (formatted here),
# {pts} the contribution in percentage points. The sentence states the fact; the points say
# how much it pushed toward the recommended action.
REASON_TEMPLATES: Mapping[str, str] = {
    "max_dpd": "{value} days past due on the worst account",
    "times_30plus_dpd_12m": "Reached 30+ days past due {value} times in the last 12 months",
    "days_in_bucket": "{value} days in the current delinquency bucket",
    "broken_promises_90d": "{value} broken promises in the last 90 days",
    "kept_promise_ratio": "Kept {value} of past promises",
    "days_to_next_payroll": "{value}",
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
    if feature == "days_to_next_payroll" and isinstance(v, int):  # negative: the expected pay date has passed
        n = abs(v)
        days = f"{n} day{'' if n == 1 else 's'}"
        if v == 0:
            return "Pay lands today"
        return f"Pay lands in {days}" if v > 0 else f"Expected pay date passed {days} ago"
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


# short labels for the "why" chart; any model input without one shows its name
DRIVER_LABELS: Mapping[str, str] = {
    "max_dpd": "Days past due",
    "times_30plus_dpd_12m": "Times 30+ DPD, 12m",
    "days_in_bucket": "Days in bucket",
    "broken_promises_90d": "Broken promises, 90d",
    "kept_promise_ratio": "Promises kept",
    "days_to_next_payroll": "Days to payday",
    "pay_frequency": "Pay frequency",
    "payroll_delay_days": "Pay delay, days",
    "pay_change_vs_3m_avg": "Pay vs 3-month avg",
    "cash_flow_trend": "Cash-flow trend",
    "card_utilisation_trend": "Card utilisation trend",
    "answer_rate": "Answer rate",
    "answer_rate_after_18h": "Answer rate after 18:00",
    "payment_link_usage": "Payment-link use",
    "cohort_recovery_rate": "Similar cases recovered",
    "cohort_kept_rate": "Similar cases' promises kept",
    "promise_intent": "Said they'd pay",
}


def drivers(
    contributions: Mapping[str, float], values: Mapping[str, object], *, k: int = MAX_DRIVERS
) -> list[Driver]:
    """The k model inputs that move the recommended action most, either way, largest first (ties by name)."""
    allowed = set(model_inputs())
    ranked = sorted(
        (f for f, c in contributions.items() if f in allowed and round(c * 100, 1)),
        key=lambda f: (-abs(contributions[f]), f),
    )
    out = []
    for f in ranked[:k]:
        v = values.get(f)
        missing = v is None or (isinstance(v, float) and math.isnan(v))
        out.append(
            Driver(
                feature=f,
                label=DRIVER_LABELS.get(f, f.replace("_", " ").capitalize()),
                value=None if missing else _fmt(f, v),
                pts=round(contributions[f] * 100, 1),
            )
        )
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
