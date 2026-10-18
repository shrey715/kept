# ruff: noqa: E501  (report prose)
"""What `kept score --rank-promises` changes: docs/reports/promise_ranking.md.

    uv run python scripts/promise_ranking_compare.py CARDS_OFF.parquet CARDS_ON.parquet

Both files are nba.cards from `kept score --now <same time>`, without and with the switch, exported to Parquet. Counts only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "docs" / "reports" / "promise_ranking.md"


def main(off_path: str, on_path: str) -> None:
    off, on = pd.read_parquet(off_path), pd.read_parquet(on_path)
    j = off.merge(on, on="case_id", suffixes=("_off", "_on"))
    a_off, a_on = j.action_off.fillna("no action"), j.action_on.fillna("no action")
    changed = a_off != a_on
    asks = {"promise_request", "payment_plan"}
    cross = pd.crosstab(a_off[changed], a_on[changed])
    n_ask_off, n_ask_on = int(a_off.isin(asks).sum()), int(a_on.isin(asks).sum())
    lines = [
        "# Ranking promise asks by their own value\n",
        "Written by `scripts/promise_ranking_compare.py` from two scorings of the same cases at the same time, with and without `kept score --rank-promises`.\n",
        "## What it does\n",
        "Today a call that can carry a sized ask becomes a promise request or a payment plan, which score like the call (they borrow its model). With the switch on, an ask is valued as **P(right party reached at the slot) x P(promise made | reached) x P(kept | promise)**, the three pieces coming from the best-hour model (or the overall reach rate), the observed rate of promises on reached outbound calls over the 60 days before the promise model's cutoff, and the promise model for this sizing. `ranking.score_actions` takes it through `p_kept_given_promise`.\n",
        "## What it changes\n",
        f"{len(j):,} cards. Promise requests and payment plans: {n_ask_off:,} without the switch, {n_ask_on:,} with it. Cards that change action: **{int(changed.sum()):,}** ({100 * changed.mean():.1f}%).\n",
        "| Action without the switch | Action with it | Cards |",
        "|---|---|---:|",
        *[f"| {r.replace('_', ' ')} | {c.replace('_', ' ')} | {int(cross.loc[r, c]):,} |" for r in cross.index for c in cross.columns if cross.loc[r, c]],
        "",
        "## Why it is off\n",
        "Nothing offline can say whether the new values are better. The bank never randomised, or even recorded, a promise ask as an action: its calls are one treatment, and a promise made or kept is an outcome of the call, so conditioning on it (the calls that ended in a promise) would compare customers, not asks. The doubly robust comparison of promise asks against calls on the clean outcome (`causal.policy_value`) needs an ask arm with overlap; there is none. "
        "The chain also counts only the payments that come through a kept promise, while the call it replaces is paid through any route, so it can only rank an ask below the call. Valued that way, asks lose to plain calls wherever they would have been proposed; whether that is right depends on how much an ask adds to a call, which is exactly what is unmeasured. A pilot cell (asks on half of the calls that can carry one) would measure it.\n",
        f"Default: off (`--rank-promises` or `KEPT_RANK_PROMISES=1`). Raw counts: `{json.dumps({'changed': int(changed.sum()), 'cards': len(j)})}`.\n",
    ]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
