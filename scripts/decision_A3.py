# ruff: noqa: E501  (report labels)
"""Decision A3: one feature definition for training and serving (Feast + `kept parity`) against a serving-side rewrite.

    uv run python scripts/decision_A3.py [--warehouse data/warehouse/eval_copy.duckdb] [--data data] [--sample 2000]

Nothing is written to a warehouse. The offline side is features.case_features of the read-only copy; the online side is
the real Feast online store, read through kept.features.parity.run_parity (what `kept parity` runs). Two typical
serving-side rewrites are injected by overriding what the online read returns for the six contact and promise features
(recomputed with the same SQL rules as dbt, scripts/decision_A2.changing_features):
  clock    the rewrite uses the data's snapshot date (2026-09-28) instead of the point-in-time as_of of the nightly;
  timezone the rewrite takes the "after 18h" hour from the UTC timestamp instead of contact_ts_local's hour.
A control (the rewrite with the right as_of) must give 0 mismatches. Cards: the rescored best action under each bug.
Also times a Feast online read per case against a direct DuckDB read.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import duckdb
import pandas as pd
from decision_A2 import CHANGING, changing_features, make_engine
from reportlib import AQUA, KEPT, MUTED, plt, save, style, tidy

from kept.config import DATA_DIR
from kept.contracts.features import FeatureVector
from kept.features.parity import run_parity
from kept.features.store import FeastFeatureProvider
from kept.nba.score import _Buffer, call_capacity, load

SNAPSHOT = datetime(2026, 9, 28, tzinfo=UTC)
UTC_HOUR = "hour(contact_ts_utc)"


class Skewed:
    """The Feast provider, with the six features replaced by a serving-side rewrite's values."""

    reads: ClassVar[dict[str, FeatureVector]] = {}  # the online store's answers, read once for all runs

    def __init__(self, inner: FeastFeatureProvider, values: pd.DataFrame) -> None:
        self.inner, self.values = inner, values

    def get_online(self, case_id: str) -> FeatureVector:
        if case_id not in self.reads:
            self.reads[case_id] = self.inner.get_online(case_id)
        v = self.reads[case_id]
        row = self.values.loc[case_id]
        new = {c: (None if pd.isna(row[c]) else row[c]) for c in CHANGING}
        for c in ("contacts_last_7d", "broken_promises_90d"):
            new[c] = int(new[c])
        return v.model_copy(update=new)


def run(conn: duckdb.DuckDBPyConnection, repo: Path, sample: int, data: Path) -> dict[str, Any]:
    feast = FeastFeatureProvider(repo)
    as_of = conn.sql("select max(as_of) from features.case_features").fetchone()[0].replace(tzinfo=UTC)  # type: ignore[index]
    spine = conn.sql(
        "select c.case_id, c.coll_customer_ref as crm_customer_id from silver.collections_cases c "
        "semi join features.case_features f using (case_id)"
    ).df()
    right = changing_features(conn, spine, as_of).set_index("case_id")
    bugs = {
        "control_right_as_of": right,
        "clock_snapshot_date_instead_of_as_of": changing_features(conn, spine, SNAPSHOT).set_index("case_id"),
        "timezone_utc_hour_instead_of_local": changing_features(conn, spine, as_of, UTC_HOUR).set_index(
            "case_id"
        ),
    }
    out: dict[str, Any] = {"as_of": str(as_of), "snapshot_date": str(SNAPSHOT.date()), "cases": len(spine)}

    bulk = load(conn)
    buffer = _Buffer()
    engine = make_engine(bulk, call_capacity(conn), buffer, data / "exports")
    stored = dict(bulk.vectors)
    now = as_of
    action: dict[tuple[str, tuple[Any, ...]], str] = {}

    def best(case_id: str, vals: pd.Series | None) -> str:
        v = stored[case_id]
        if vals is not None:
            new = {c: (None if pd.isna(vals[c]) else vals[c]) for c in CHANGING}
            for c in ("contacts_last_7d", "broken_promises_90d"):
                new[c] = int(new[c])
            v = v.model_copy(update=new)
        key = (case_id, tuple(v.model_dump().values()))
        if key not in action:
            bulk.vectors[case_id] = v
            card = engine.recommend(case_id, now)
            buffer.events.clear()
            action[key] = card.proposal.action.value if card.proposal else "none"
        return action[key]

    for name, vals in bugs.items():
        t0 = time.perf_counter()
        sampled = run_parity(conn, Skewed(feast, vals), sample=sample, seed=7)
        full = run_parity(conn, Skewed(feast, vals), sample=None)
        # cards: the cases whose six features differ from the stored (right) ones
        diff = ~((vals[CHANGING] == right[CHANGING]) | (vals[CHANGING].isna() & right[CHANGING].isna()))
        differing = diff.any(axis=1)
        changed = sum(best(c, vals.loc[c]) != best(c, None) for c in differing.index[differing])
        out[name] = {
            "parity_sample": {
                "cases": sample,
                "cells": sampled.n_cells,
                "cells_mismatched": sampled.n_mismatched,
                "rate": round(sampled.mismatch_rate, 6),
                "passed": sampled.passed,
                "worst": dict(sampled.worst_features[:6]),
            },
            "parity_all_cases": {
                "cells": full.n_cells,
                "cells_mismatched": full.n_mismatched,
                "rate": round(full.mismatch_rate, 6),
                "passed": full.passed,
                "worst": dict(full.worst_features[:6]),
            },
            "cases_with_a_differing_feature": int(differing.sum()),
            "cards_best_action_changed": int(changed),
            "share_of_cards_changed": round(changed / len(spine), 5),
            "seconds": round(time.perf_counter() - t0, 1),
        }
    out["timing"] = timing(conn, feast, spine.case_id.tolist())
    return out


def timing(
    conn: duckdb.DuckDBPyConnection, feast: FeastFeatureProvider, cases: list[str], n: int = 500
) -> dict[str, Any]:
    ids = random.Random(1).sample(cases, n)
    feast.get_online(ids[0])  # warm: registry and store opened
    t0 = time.perf_counter()
    for c in ids:
        feast.get_online(c)
    feast_ms = 1000 * (time.perf_counter() - t0) / n
    t0 = time.perf_counter()
    for c in ids:
        conn.execute("select * from features.case_features where case_id = ?", [c]).fetchone()
    duck_ms = 1000 * (time.perf_counter() - t0) / n
    t0 = time.perf_counter()
    conn.execute("select * from features.case_features where case_id in (select unnest(?))", [ids]).fetchall()
    duck_batch_ms = 1000 * (time.perf_counter() - t0) / n
    return {
        "reads": n,
        "feast_online_ms_per_case": round(feast_ms, 2),
        "duckdb_ms_per_case_one_query_each": round(duck_ms, 2),
        "duckdb_ms_per_case_one_batched_query": round(duck_batch_ms, 3),
        "note": "DuckDB table is read-only, unindexed, 96,000 rows, in the page cache; Feast is the SQLite online store on the same disk",
    }


def figure(out: dict[str, Any]) -> str:
    style()
    names = ["clock_snapshot_date_instead_of_as_of", "timezone_utc_hour_instead_of_local"]
    labels = ["snapshot date\ninstead of as_of", "UTC hour instead of\nlocal hour"]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    for i, (n, colour) in enumerate(zip(names, (KEPT, AQUA), strict=True)):
        r = out[n]["parity_all_cases"]["rate"] * 100
        ax.bar(i, r, color=colour, width=0.5)
        ax.text(
            i,
            r,
            f"{r:.1f}% of cells\n{100 * out[n]['share_of_cards_changed']:.2f}% of cards change",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    ax.axhline(0.1, color=MUTED, lw=1, ls="--")
    ax.text(1.45, 0.1, "parity limit 0.1%", ha="right", va="bottom", fontsize=7, color=MUTED)
    ax.set_xticks([0, 1], labels)
    ax.set_ylabel("Cells that differ (%)")
    ax.set_ylim(0, max(out[n]["parity_all_cases"]["rate"] * 100 for n in names) * 1.35 + 0.2)
    ax.set_title("Two injected skew bugs: both fail `kept parity`", loc="left")
    tidy(ax)
    return save(fig, "dec_A3")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warehouse", default=str(DATA_DIR / "warehouse" / "eval_copy.duckdb"))
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--sample", type=int, default=2000)
    ap.add_argument("--repo", type=Path, default=DATA_DIR.parent / "feature_repo")
    a = ap.parse_args()
    conn = duckdb.connect(a.warehouse, read_only=True)
    conn.execute("SET memory_limit='3GB'; SET threads=4")
    out = {"generated": datetime.now(UTC).isoformat(timespec="minutes"), "warehouse": Path(a.warehouse).name}
    out.update(run(conn, a.repo, a.sample, a.data))
    out["figure"] = figure(out)
    (a.data / "exports" / "reports" / "decision_A3.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
