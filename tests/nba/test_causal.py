"""kept.nba.causal: weighted Qini equals the gate's, AIPW recovers a known effect under confounded assignment,
and the BLP test separates real heterogeneity from none."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from kept.nba.causal import aipw, blp, case_bootstrap, dr_qini, gate_qini
from kept.nba.uplift import qini_coefficient

pytestmark = pytest.mark.track_d


def _data(n: int = 20_000, seed: int = 0) -> tuple[np.ndarray, ...]:
    rng = np.random.default_rng(seed)
    x = rng.uniform(0, 1, n)
    e = 0.2 + 0.6 * x  # the bank treats high-x cases more often
    t = (rng.uniform(size=n) < e).astype(float)
    tau = 0.2 * (x > 0.5)  # the effect exists only for x > 0.5
    y = (rng.uniform(size=n) < 0.2 + 0.4 * x + tau * t).astype(float)
    return x, e, t, y, tau


def test_weighted_qini_matches_gate() -> None:
    x, _, t, y, _ = _data(2_000)
    assert gate_qini(x, t, y) == pytest.approx(qini_coefficient(x, t.astype(int), y.astype(int)))


def test_aipw_unbiased_under_confounding_and_blp_finds_heterogeneity() -> None:
    x, e, t, y, tau = _data()
    m0, m1 = 0.2 + 0.4 * x, 0.2 + 0.4 * x + tau
    phi = aipw(y, t, m1, m0, e)
    assert phi.mean() == pytest.approx(tau.mean(), abs=0.01)
    assert abs(y[t == 1].mean() - y[t == 0].mean() - tau.mean()) > 0.03  # naive difference is biased
    cases = pd.Series(np.arange(len(x)))
    assert blp(phi, tau, cases)["slope_t"] > 5  # the true CATE carries signal
    assert abs(blp(phi, np.random.default_rng(1).normal(size=len(x)), cases)["slope_t"]) < 4  # noise does not
    assert dr_qini(tau, phi) > 0 > dr_qini(-tau, phi)
    se = case_bootstrap(cases, lambda w: (w * phi).sum() / w.sum(), reps=50).std()
    assert 0.001 < se < 0.01


def test_causal_uplift_ranks_by_the_true_effect() -> None:
    """Confounded assignment, effect only where x > 0.5: the DR- and R-learners rank by x, a plain difference would not."""
    pytest.importorskip("lightgbm")
    from kept.nba.causal import CausalUplift

    rng = np.random.default_rng(0)
    n = 30_000
    x = rng.uniform(0, 1, n)
    act = np.where(rng.uniform(size=n) < 0.2 + 0.6 * x, "call", "wait")
    y = rng.uniform(size=n) < 0.2 + 0.4 * x + 0.25 * (x > 0.5) * (act == "call")
    df = pd.DataFrame({"x": x, "action": act, "paid": y, "case_id": np.arange(n)})
    m = CausalUplift(["x"], ["call"], "paid", k=2).fit(df)
    grid = pd.DataFrame({"x": [0.1, 0.9]})
    for kind in ("dr", "r"):
        lift = m.view(kind).uplift(grid)["call"].to_numpy()
        assert lift[1] - lift[0] > 0.1


def test_study_features_are_clean() -> None:
    """The offline studies' inputs (17 registry inputs + decision context, hour and weekday for the call-hour model) contain no outcome
    column, no protected attribute and no proxy (age, postal code, language, ...)."""
    from kept.contracts.data_contract import load_data_contract
    from kept.contracts.feature_registry import model_inputs
    from kept.features.store import assert_no_denied
    from kept.nba.train import CONTEXT_COLS

    cols = [*model_inputs(), *CONTEXT_COLS, "hour"]
    assert_no_denied(pd.DataFrame(columns=cols))
    c = load_data_contract()
    assert not set(cols) & (c.protected_attributes | c.proxy_attributes)


def test_policy_value_recovers_a_known_policy_and_logged_value() -> None:
    """Two actions, the logged choice confounded with x, the best action flips at x = 0.5: the best policy beats the logged
    actions by about its true margin, and a policy equal to the logged actions has gap zero."""
    pytest.importorskip("lightgbm")
    from kept.nba.causal import policy_value

    rng = np.random.default_rng(0)
    n = 12_000
    x = rng.uniform(0, 1, n)
    a = np.where(rng.uniform(size=n) < 0.15 + 0.7 * x, "b", "a")
    p_y = np.where(a == "b", 0.2 + 0.5 * (x > 0.5), 0.5 - 0.3 * (x > 0.5))
    df = pd.DataFrame({"case_id": np.arange(n), "action": a, "y": (rng.uniform(size=n) < p_y).astype(int), "x": x})
    best = np.where(x > 0.5, "b", "a")
    v = policy_value(df, ["x"], best, "y")
    v = v[(v.e_pi >= 0.05) & (v.e_pi <= 0.95)]
    true_gap = (np.where(best == "b", 0.7, 0.5) - p_y)[v.index].mean()
    assert (v.psi - v.y).mean() == pytest.approx(true_gap, abs=0.03)
    same = policy_value(df, ["x"], a, "y")
    assert (same.psi - same.y).mean() == pytest.approx(0.0, abs=0.01)
