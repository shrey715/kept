# ruff: noqa: E501  (report prose)
"""Fairness report: docs/reports/fairness_report.pdf (LaTeX source alongside). Compliance-only inputs.

    uv run python scripts/fairness_report.py             # needs the warehouse (stop kept serve)
    uv run python scripts/fairness_report.py --render    # re-render from data/exports/reports/fairness_data.json

Uses kept.governance.fairness: for every protected attribute and proxy in
gold.c360_restricted, the share of cases per group that get a contact action, a call and a hardship review, and
the lowest-to-highest ratio (four-fifths rule). Only aggregates leave the warehouse.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from reportlib import AQUA, BLUE, BUILD, KEPT, ORANGE, plt, save, style, tidy

CACHE = BUILD / "fairness_data.json"
SHOW = (
    "gender_code",
    "citizenship_status",
    "marital_status",
    "accessibility_needs_flag",
    "vulnerability_type",
    "household_size",
)


def collect() -> dict[str, object]:
    import duckdb

    from kept.config import COHORT_MIN_GROUP_SIZE, WAREHOUSE_PATH
    from kept.contracts.data_contract import load_data_contract
    from kept.governance.fairness import OUTCOMES, _outcome, recommendation_rates

    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    cards = con.execute("select golden_customer_id, action from nba.cards").df()
    restricted = con.execute("select * from gold.c360_restricted").df()
    contract = load_data_contract()
    attrs = sorted((contract.protected_attributes | contract.proxy_attributes) & set(restricted.columns))
    joined = cards.merge(restricted, on="golden_customer_id", how="left")
    out: dict[str, object] = {
        "written": datetime.now(UTC).strftime("%d %B %Y"),
        "cases": len(cards),
        "attributes": {},
    }
    for a in attrs:
        if joined[a].nunique(dropna=True) > 25:
            continue
        known = joined[joined[a].notna()]
        groups = known[a].astype("string").tolist()
        res = {}
        for o in OUTCOMES:
            r = recommendation_rates(
                _outcome(known["action"], o), groups, min_group_size=COHORT_MIN_GROUP_SIZE
            )
            res[o] = {
                "ratio": r.min_ratio,
                "flagged": r.flagged,
                "rates": {str(k): v for k, v in r.rates.items()},
            }
        sizes = known[a].astype("string").value_counts().to_dict()
        out["attributes"][a] = {
            "outcomes": res,
            "sizes": {str(k): int(v) for k, v in sizes.items()},
            "blank": int(joined[a].isna().sum()),
        }  # type: ignore[index]
    BUILD.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(out, indent=1))
    return out


def render(d: dict) -> None:  # type: ignore[type-arg]
    style()
    attrs = d["attributes"]
    names = sorted(attrs, key=lambda a: attrs[a]["outcomes"]["any contact action"]["ratio"])
    fig, ax = plt.subplots(figsize=(7.2, 0.3 * len(names) + 1.3))
    y = list(range(len(names)))[::-1]
    for o, c, dy in (
        ("any contact action", BLUE, 0.15),
        ("call", ORANGE, 0),
        ("hardship review", AQUA, -0.15),
    ):
        ax.scatter(
            [attrs[a]["outcomes"][o]["ratio"] for a in names],
            [yi + dy for yi in y],
            s=26,
            color=c,
            label=o,
            zorder=3,
        )
    ax.axvline(0.8, color=KEPT, linewidth=1, linestyle="--")
    ax.text(0.8, len(names) - 0.3, " four-fifths line", fontsize=8, color=KEPT)
    ax.set_yticks(y, names)
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("lowest group's rate ÷ highest group's rate (1.0 = everyone treated the same)")
    ax.set_title("Who gets what, by protected attribute", loc="left")
    ax.legend(loc="lower left", frameon=False, fontsize=8)
    tidy(ax)
    save(fig, "f_ratios")

    small = []
    for a in [x for x in SHOW if x in attrs]:
        rates = attrs[a]["outcomes"]["any contact action"]["rates"]
        hr = attrs[a]["outcomes"]["hardship review"]["rates"]
        groups = sorted(rates, key=lambda g: -attrs[a]["sizes"].get(g, 0))[:6]
        fig, ax = plt.subplots(figsize=(3.5, 0.32 * len(groups) + 1.0))
        yy = list(range(len(groups)))[::-1]
        ax.barh(
            [v + 0.17 for v in yy],
            [100 * rates[g] for g in groups],
            height=0.32,
            color=BLUE,
            label="any contact",
        )
        ax.barh(
            [v - 0.17 for v in yy],
            [100 * hr.get(g, 0) for g in groups],
            height=0.32,
            color=AQUA,
            label="hardship review",
        )
        ax.set_yticks(yy, [g[:16] for g in groups], fontsize=7.5)
        ax.set_xlim(0, 100)
        ax.set_xlabel("% of cases", fontsize=7.5)
        ax.set_title(a, loc="left", fontsize=8.5)
        tidy(ax)
        small.append(save(fig, f"f_{a}"))
    print("figures written; compile with: uv run python scripts/reportlib.py")


if __name__ == "__main__":
    render(json.loads(CACHE.read_text()) if "--render" in sys.argv else collect())
