import numpy as np
import pandas as pd

from kept.features.drift import DRIFT, WATCH, drift_report, psi, to_markdown


def test_psi_stable_shifted_and_gone_blank() -> None:
    rng = np.random.default_rng(0)
    a = pd.Series(rng.normal(0, 1, 5000))
    assert psi(a, pd.Series(rng.normal(0, 1, 5000))) < WATCH
    assert psi(a, pd.Series(rng.normal(1.5, 1, 5000))) >= DRIFT
    assert psi(pd.Series(["weekly"] * 100), pd.Series(["weekly"] * 50 + [None] * 50)) >= DRIFT  # went blank


def test_report_is_worst_first_and_skips_missing_columns() -> None:
    rng = np.random.default_rng(1)
    train = pd.DataFrame({"x": rng.normal(0, 1, 2000), "y": rng.normal(0, 1, 2000)})
    live = pd.DataFrame({"x": rng.normal(0, 1, 2000), "y": rng.normal(2, 1, 2000)})
    rows = drift_report(train, live, ["x", "y", "absent"])
    assert (
        [r.feature for r in rows] == ["y", "x"] and rows[0].status == "drift" and rows[1].status == "stable"
    )
    md = to_markdown(rows, train_rows=2000, live_rows=2000, live_as_of="2026-10-03")
    assert "Overall: **DRIFT**" in md and "| y |" in md


def test_report_names_features_never_seen_in_training() -> None:
    train = pd.DataFrame({"pay": [None] * 100, "x": range(100)})
    live = pd.DataFrame({"pay": range(100), "x": range(100)})
    md = to_markdown(drift_report(train, live, ["pay", "x"]), train_rows=100, live_rows=100, live_as_of="t")
    assert "**Never seen in training**" in md and "`pay`" in md
