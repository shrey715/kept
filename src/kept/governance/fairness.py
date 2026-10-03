"""Fairlearn checks: recommendation rates across groups. Compliance-only inputs
(protected attributes come from gold.c360_restricted, read by compliance)."""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kept.config import COHORT_MIN_GROUP_SIZE

if TYPE_CHECKING:
    import pandas as pd

FOUR_FIFTHS = 0.8  # TBC alarm threshold


@dataclass(frozen=True, slots=True)
class FairnessReport:
    rates: dict[Hashable, float]
    min_ratio: float  # min rate / max rate
    flagged: bool  # min_ratio < threshold
    groups_skipped: tuple[Hashable, ...]  # groups below min_group_size


def recommendation_rates(
    recommended: Sequence[bool], groups: Sequence[Hashable], *, min_group_size: int = 10
) -> FairnessReport:
    """Rate of recommended == True per group; groups smaller than min_group_size are
    skipped (reported). All-zero rates -> min_ratio 1.0. Lengths differ -> ValueError.
    ponytail: plain Python (the same numbers as Fairlearn's selection_rate by group), so it runs without
    the torch-sized `text` extra; the real-data report can cross-check with fairlearn.MetricFrame."""
    if len(recommended) != len(groups):
        raise ValueError("recommended and groups must be the same length")
    counts: dict[Hashable, list[int]] = {}  # group -> [members, recommended]
    for rec, group in zip(recommended, groups, strict=True):
        c = counts.setdefault(group, [0, 0])
        c[0] += 1
        c[1] += bool(rec)
    rates = {g: pos / n for g, (n, pos) in counts.items() if n >= min_group_size}
    best = max(rates.values(), default=0.0)
    ratio = min(rates.values()) / best if best else 1.0
    skipped = tuple(g for g, (n, _) in counts.items() if n < min_group_size)
    return FairnessReport(rates, ratio, ratio < FOUR_FIFTHS, skipped)


# What a recommendation means for each question the report asks. `action` is nba.cards.action:
# null when the case gets no action, otherwise one of the eight Actions.
OUTCOMES: dict[str, str] = {
    "any contact action": "action is neither empty nor 'wait'",
    "call": "action is 'call'",
    "hardship review": "action is 'hardship_review'",
}


def _outcome(actions: pd.Series, name: str) -> list[bool]:
    if name == "any contact action":
        return [isinstance(a, str) and a != "wait" for a in actions]  # a missing action is NaN or None
    return [a == {"call": "call", "hardship review": "hardship_review"}[name] for a in actions]


def fairness_report(
    cards: pd.DataFrame,
    restricted: pd.DataFrame,
    attributes: Sequence[str],
    *,
    min_group_size: int = COHORT_MIN_GROUP_SIZE,
    max_groups: int = 25,
) -> str:
    """Markdown report: for each protected attribute, the share of cases that get each outcome per group,
    and the lowest-to-highest ratio (flagged under four fifths). Cases are joined to the protected
    attributes by golden_customer_id. Groups below min_group_size are listed but not compared; a case
    whose attribute is blank is reported on its own and not compared (missing data is not a group); an
    attribute with more than max_groups distinct values (a free-form field or a date) is skipped.
    A flag is a question to ask, not a verdict: a hardship review is *meant* to reach customers who are
    in hardship, so a gap there can be correct. The report says what the rates are, compliance decides."""
    joined = cards.merge(restricted, on="golden_customer_id", how="left")
    summary = [
        "| attribute | " + " | ".join(OUTCOMES) + " | cases with the attribute blank |",
        "|---|" + "---|" * (len(OUTCOMES) + 1),
    ]
    sections: list[str] = []
    for attr in attributes:
        if attr not in joined.columns or joined[attr].nunique(dropna=True) > max_groups:
            continue
        # A blank attribute is missing data, not a group: show its rates, but compare only real groups.
        blank = joined[attr].isna()
        known = joined[~blank]
        groups = known[attr].astype("string").tolist()
        reports = {
            o: recommendation_rates(_outcome(known["action"], o), groups, min_group_size=min_group_size)
            for o in OUTCOMES
        }
        n_blank = int(blank.sum())
        any_blank = _outcome(joined.loc[blank, "action"], "any contact action") if n_blank else []
        blank_note = f"{n_blank:,} ({sum(any_blank) / n_blank:.0%} get a contact action)" if n_blank else "0"
        summary.append(
            f"| {attr} | "
            + " | ".join(f"{r.min_ratio:.2f}{' FLAG' if r.flagged else ''}" for r in reports.values())
            + f" | {blank_note} |"
        )
        sizes = known.assign(_g=groups).groupby("_g").size()
        lines = [
            f"### {attr}",
            "",
            "| group | cases | " + " | ".join(OUTCOMES) + " |",
            "|---|---|" + "---|" * len(OUTCOMES),
        ]
        for g in sorted(sizes.index, key=str):
            cells = " | ".join(
                "n/a (too few)" if (x := reports[o].rates.get(g)) is None else f"{x:.1%}" for o in OUTCOMES
            )
            lines.append(f"| {g} | {sizes[g]:,} | {cells} |")
        if n_blank:
            cells = " | ".join(
                f"{sum(_outcome(joined.loc[blank, 'action'], o)) / n_blank:.1%}" for o in OUTCOMES
            )
            lines.append(f"| *(blank, not compared)* | {n_blank:,} | {cells} |")
        sections.append("\n".join(lines))
    head = (
        f"Cases scored: {len(cards):,}. Compared by protected attribute from `gold.c360_restricted` "
        f"(compliance only). Four-fifths rule: the lowest group's rate over the highest group's, flagged "
        f"under {FOUR_FIFTHS}. Groups under {min_group_size} cases are not compared.\n\n"
        "Outcomes: " + "; ".join(f"**{o}**: {d}" for o, d in OUTCOMES.items()) + "."
    )
    return (
        head
        + "\n\n## Lowest / highest ratio\n\n"
        + "\n".join(summary)
        + "\n\n## Rates by group\n\n"
        + "\n\n".join(sections)
        + "\n"
    )
