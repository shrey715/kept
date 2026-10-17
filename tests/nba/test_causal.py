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
