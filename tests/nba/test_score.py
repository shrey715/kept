"""kept score's batch scorer answers exactly like the model it wraps, and its proposal store
keeps nothing (so the engine's per-card cancel scan stays O(1))."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from kept.contracts.enums import Action
from kept.contracts.features import FeatureVector
from kept.nba.engine import _model_frame
from kept.nba.score import _NoStore, _Precomputed
from kept.nba.train import ACTIONS
from kept.nba.uplift import TLearnerUplift

pytestmark = pytest.mark.track_d


def test_precomputed_scorer_matches_the_model() -> None:
    pytest.importorskip("lightgbm")
    rng = np.random.default_rng(0)
    n = 3_000
    X = pd.DataFrame({"answer_rate": rng.uniform(0, 1, n), "max_dpd": rng.integers(0, 90, n).astype(float)})
    action = pd.Series(rng.choice([a.value for a in ACTIONS], n))
    paid = pd.Series(rng.uniform(0, 1, n) < 0.3 + 0.3 * (X.answer_rate > 0.5) * (action != "wait"))
    model = TLearnerUplift(ACTIONS, params={"min_child_samples": 20}).fit(
        X, action=action, paid_14d=paid, is_random_assignment=pd.Series(True, index=X.index)
    )
    as_of = datetime(2026, 10, 3, 6, tzinfo=UTC)
    vectors = [
        FeatureVector(
            case_id=f"CS-{i}",
            golden_customer_id=f"G-{i}",
            as_of=as_of,
            feature_set_version="fs-0",
            answer_rate=None if i % 7 == 0 else float(rng.uniform(0, 1)),
            max_dpd=int(rng.integers(0, 90)),
        )
        for i in range(200)
    ]
    pre = _Precomputed(model, vectors)
    for v in vectors[:50]:
        row = _model_frame(v)  # exactly what the engine passes per card
        assert pre._find(row) is not None
        pd.testing.assert_frame_equal(pre.predict_proba(row), model.predict_proba(row), check_dtype=False)
        for a in (Action.CALL, Action.EMAIL):
            got, want = pre.contributions(row, a), model.contributions(row, a)
            assert got.keys() == want.keys() and all(abs(got[k] - want[k]) < 1e-12 for k in want)
    unseen = _model_frame(vectors[0].model_copy(update={"max_dpd": 999}))
    assert pre._find(unseen) is None  # falls back to the model
    pd.testing.assert_frame_equal(pre.predict_proba(unseen), model.predict_proba(unseen), check_dtype=False)


def test_batch_proposal_store_keeps_nothing() -> None:
    store = _NoStore()
    store["P-1"] = "proposal"
    assert dict(store) == {} and list(store.values()) == []
